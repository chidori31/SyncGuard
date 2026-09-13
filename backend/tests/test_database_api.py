from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from app import models as m
from app import services as svc
from app.connectors.base import ConnectorError, MemoryConnector
from app.connectors.mock_1c import Mock1C
from app.connectors.mock_bitrix import MockBitrix
from app.db import get_session
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.database


def test_fully_healthy_integration(database):
    now = m.utcnow()
    anchor = now - timedelta(minutes=10)
    source = MockBitrix(anchor).entities[1]
    with database() as session:
        result = svc.run_demo(
            session, now=now, source_connector=MemoryConnector([source]), target_connector=Mock1C(anchor)
        )
        assert result["status"] == "HEALTHY"
        integration = session.get(m.Integration, svc.INTEGRATION_ID)
        assert integration.last_successful_sync == now
        assert session.scalar(select(func.count()).select_from(m.Incident)) == 0


def test_empty_source_is_unknown(database):
    with database() as session:
        assert svc.run_demo(session, source_connector=MemoryConnector([]))["status"] == "UNKNOWN"


def test_pending_observation_preserves_active_incident(database):
    now = m.utcnow()
    anchor = now - timedelta(minutes=10)
    source = MockBitrix(anchor)
    with database() as session:
        svc.run_demo(session, now=now, source_connector=source)
        source.entities[0] = source.entities[0].model_copy(
            update={"attributes": source.entities[0].attributes.model_copy(update={"status_changed_at": now})}
        )
        svc.run_demo(session, now=now, source_connector=source)
        assert session.scalar(select(m.Incident).where(m.Incident.type == "missing_target")).status == "OPEN"


def test_creation_dedup_and_evidence(database):
    with database() as session:
        assert svc.run_demo(session)["incidents_created"] == 2
        assert svc.run_demo(session)["incidents_created"] == 0
        rows = session.scalars(select(m.Incident)).all()
        assert len(rows) == 2
        assert svc.risk_total(rows) == Decimal("194000")
        evidence = session.scalars(select(m.IncidentEvidence)).all()
        assert len(evidence) == 4
        assert evidence[0].data["target_lookup_result"]["complete"] is True
        assert session.scalar(select(func.count()).select_from(m.ExternalEntity)) == 5


def test_parallel_first_runs_deduplicate(database):
    def run(_):
        with database() as session:
            return svc.run_demo(session)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert sum(r["incidents_created"] for r in results) == 2
    with database() as session:
        assert session.scalar(select(func.count()).select_from(m.Incident)) == 2
        assert session.scalar(select(func.count()).select_from(m.Organization)) == 1


def test_recovery_and_reopen(database):
    now = m.utcnow()
    anchor = now - timedelta(minutes=10)
    sources = MockBitrix(anchor)
    targets = Mock1C(anchor)
    recovered = targets.entities + [
        targets.entities[0].model_copy(
            update={
                "external_id": "recovered-5821",
                "attributes": targets.entities[0].attributes.model_copy(
                    update={"external_reference": "5821", "amount": Decimal("184000")}
                ),
            }
        )
    ]
    with database() as session:
        svc.run_demo(session, now=now, source_connector=sources, target_connector=targets)
        svc.run_demo(
            session,
            now=now + timedelta(seconds=1),
            source_connector=sources,
            target_connector=MemoryConnector(recovered),
        )
        incident = session.scalar(select(m.Incident).where(m.Incident.type == "missing_target"))
        assert incident.status == "RESOLVED"
        assert incident.resolved_at is not None
        session.rollback()
        svc.run_demo(session, now=now + timedelta(seconds=2), source_connector=sources, target_connector=targets)
        session.refresh(incident)
        assert incident.status == "OPEN"
        assert incident.resolved_at is None
        assert [e["status"] for e in incident.timeline] == ["OPEN", "RESOLVED", "REOPENED"]


def test_connector_failure_preserves_incidents(database):
    class Broken(MemoryConnector):
        def fetch_entities(self):
            raise ConnectorError("No complete snapshot")

    with database() as session:
        svc.run_demo(session)
        result = svc.run_demo(session, target_connector=Broken([]))
        assert result["status"] == "UNKNOWN"
        assert session.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status == "OPEN")) == 2
        assert (
            session.scalar(select(m.Observation).where(m.Observation.outcome == "unknown")).data["lookup_complete"]
            is False
        )


def test_unknown_entity_timestamp_does_not_resolve(database):
    anchor = m.utcnow() - timedelta(minutes=10)
    source = MockBitrix(anchor)
    with database() as session:
        svc.run_demo(session, source_connector=source)
        source.entities[0] = source.entities[0].model_copy(
            update={"attributes": source.entities[0].attributes.model_copy(update={"status_changed_at": None})}
        )
        assert svc.run_demo(session, source_connector=source)["status"] == "UNKNOWN"
        assert session.scalar(select(m.Incident).where(m.Incident.type == "missing_target")).status == "OPEN"


def test_transaction_rollback(database, monkeypatch):
    def fail(*args):
        raise RuntimeError("Synthetic failure")

    monkeypatch.setattr(svc, "reconcile", fail)
    with database() as session:
        with pytest.raises(RuntimeError):
            svc.run_demo(session)
        assert session.scalar(select(func.count()).select_from(m.Organization)) == 0
        assert session.scalar(select(func.count()).select_from(m.Observation)) == 0


def test_database_constraints_and_tenant_foreign_keys(database):
    with database() as session:
        svc.run_demo(session)
        existing = session.scalar(select(m.Incident))
        copy = {
            column.key: getattr(existing, column.key)
            for column in m.Incident.__table__.columns
            if column.key not in {"id", "metadata"}
        }
        session.add(m.Incident(**copy))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(m.Organization(id="other", name="Other"))
        session.commit()
        session.add(m.BusinessRule(organization_id="other", integration_id=svc.INTEGRATION_ID, name="Invalid tenant"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        existing = session.scalar(select(m.Incident))
        existing.business_value_at_risk = Decimal("-1")
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        existing = session.scalar(select(m.Incident))
        existing.status = "INVALID"
        with pytest.raises(IntegrityError):
            session.commit()


def test_rest_api_and_acknowledgement(database):
    def session_dependency():
        with database() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        with TestClient(app) as client:
            assert client.get("/api/integrations").json() == []
            assert client.post("/api/demo/run").status_code == 200
            assert client.post("/api/demo/run").json()["incidents_created"] == 0
            assert client.get("/api/dashboard").json()["business_value_at_risk"] == "194000.00"
            integrations = client.get("/api/integrations").json()
            assert integrations[0]["status"] == "BROKEN"
            assert client.get(f"/api/integrations/{svc.INTEGRATION_ID}").status_code == 200
            assert client.get("/api/rules").json()[0]["maximum_delay"] == 300
            rows = client.get("/api/incidents").json()
            missing = next(row for row in rows if row["type"] == "missing_target")
            detail = client.get(f"/api/incidents/{missing['id']}").json()
            assert detail["evidence"][0]["source_entity"]["external_id"] == "5821"
            assert detail["evidence"][0]["target_lookup_result"]["match_count"] == 0
            path = f"/api/incidents/{missing['id']}"
            assert client.patch(path, json={"status": "ACKNOWLEDGED"}).json()["status"] == "ACKNOWLEDGED"
            assert client.patch(path, json={"status": "ACKNOWLEDGED"}).status_code == 200
            assert len(client.get(path).json()["timeline"]) == 2
            assert len(client.get("/api/incidents?status=ACKNOWLEDGED").json()) == 1
            assert client.patch(path, json={"status": "RESOLVED"}).status_code == 422
            assert client.get("/api/incidents?limit=500").status_code == 422
            assert client.get("/api/incidents/not-found").status_code == 404
            assert client.get("/api/integrations/not-found").status_code == 404
    finally:
        app.dependency_overrides.clear()
