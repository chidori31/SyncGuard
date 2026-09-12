from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from app import models as m
from app import services as svc
from app.connectors.base import MemoryConnector
from app.connectors.http import Bitrix24Connector, OneCConnector
from app.db import get_session
from app.main import app
from app.scenarios import fixture
from app.simulator import app as simulator
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.mark.database
def test_scenario_lifecycle_and_history(database):
    def session_dependency():
        with database() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        with TestClient(app) as client:

            def run(scenario):
                response = client.post("/api/demo/run", json={"scenario": scenario})
                assert response.status_code == 200, response.text
                return response.json()

            first = run("baseline")
            incidents = client.get("/api/incidents").json()
            ids = {row["type"]: row["id"] for row in incidents}
            assert first["status"] == "BROKEN"
            assert run("baseline")["incidents_created"] == 0
            assert run("healthy")["status"] == "HEALTHY"
            assert client.get("/api/dashboard").json()["open_incidents"] == 0
            assert (
                client.patch(f"/api/incidents/{ids['missing_target']}", json={"status": "ACKNOWLEDGED"}).status_code
                == 409
            )
            assert run("baseline")["incidents_created"] == 0
            detail = client.get(f"/api/incidents/{ids['missing_target']}").json()
            assert [item["status"] for item in detail["timeline"]] == ["OPEN", "RESOLVED", "REOPENED"]
            before = client.get("/api/dashboard").json()
            assert run("outage")["status"] == "UNKNOWN"
            after = client.get("/api/dashboard").json()
            assert after["business_value_at_risk"] == before["business_value_at_risk"] == "194000.00"
            assert after["open_incidents"] == 2
            assert run("duplicate")["status"] == "BROKEN"
            assert run("delay")["status"] == "DELAYED"
            assert run("healthy")["status"] == "HEALTHY"
            pending = run("pending")
            assert pending["status"] == "DELAYED" and pending["incidents_created"] == 0
            assert client.get("/api/dashboard").json()["open_incidents"] == 0
            history = client.get(f"/api/integrations/{svc.INTEGRATION_ID}/checks").json()
            assert len(history) == 9 and len({row["id"] for row in history}) == 9
            assert history[0]["id"] == pending["run_id"]
            assert len(history[0]["observations"]) == 3
            assert history[0]["observations"][0]["outcome"] == "pending"
            assert client.post("/api/demo/run", json={"scenario": "invalid"}).status_code == 422
            assert client.post("/api/demo/run", json={"base_url": "https://evil.test/"}).status_code == 422
            assert client.get(f"/api/integrations/{svc.INTEGRATION_ID}/checks?limit=51").status_code == 422
            assert client.get("/api/integrations/unknown/checks").status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.database
@pytest.mark.parametrize(
    "scenario,status",
    [
        ("baseline", "BROKEN"),
        ("healthy", "HEALTHY"),
        ("duplicate", "BROKEN"),
        ("wrong_amount", "DELAYED"),
        ("delay", "DELAYED"),
        ("pending", "DELAYED"),
        ("outage", "UNKNOWN"),
    ],
)
def test_http_contract_to_postgres(database, scenario, status):
    # Exercise real serializers, pagination, normalizers, domain rules and persistence.
    # Only the TCP boundary is replaced here; tools/verify_stack.py covers actual sockets.
    with TestClient(simulator) as server:

        def handle(request):
            return server.request(request.method, str(request.url), content=request.content, headers=request.headers)

        with database() as session:
            svc.run_demo(session, scenario="healthy")
            integration = session.get(m.Integration, svc.INTEGRATION_ID)
            anchor = integration.demo_anchor
            session.rollback()
            params = {"scenario": scenario, "anchor": anchor.isoformat(), "observed_at": m.utcnow().isoformat()}
            source = Bitrix24Connector(
                "http://testserver/bitrix/rest/", transport=httpx.MockTransport(handle), params=params, allow_http=True
            )
            target = OneCConnector(
                "http://testserver/one-c/odata/", transport=httpx.MockTransport(handle), params=params, allow_http=True
            )
            try:
                result = svc.run_demo(
                    session, scenario=scenario, transport="http", source_connector=source, target_connector=target
                )
                assert result["status"] == status
                record = session.get(m.CheckRun, result["run_id"])
                assert record.diagnostics["source"]["pages"] == 2
                assert record.diagnostics["source"]["complete"] is True
                if scenario == "outage":
                    assert record.diagnostics["target"]["retries"] == 2
                    assert record.diagnostics["lookup_complete"] is False
                else:
                    assert record.diagnostics["target"]["complete"] is True
                    assert record.entities_checked == 3
            finally:
                source.close()
                target.close()


@pytest.mark.database
def test_disabled_rule_preserves_existing_incidents(database):
    with database() as session:
        svc.run_demo(session)
        session.get(m.BusinessRule, svc.RULE_ID).enabled = False
        session.commit()
        result = svc.run_demo(session, scenario="healthy")
        assert result["status"] == "UNKNOWN"
        assert session.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status == "OPEN")) == 2
        assert session.get(m.CheckRun, result["run_id"]).diagnostics["failure_phase"] == "rule"


def test_risk_is_deduplicated_and_currencies_never_added_together():
    def row(currency, amount):
        return SimpleNamespace(
            integration_id="i", source_external_id="d", currency=currency, business_value_at_risk=Decimal(amount)
        )

    rows = [row("RUB", "184000"), row("RUB", "10000"), row("USD", "100")]
    assert svc.risk_total(rows) == Decimal("184000")
    assert svc.risk_by_currency(rows) == {"RUB": "184000", "USD": "100"}


@pytest.mark.database
def test_incomplete_metrics_preserve_prior_state(database):
    class Incomplete(MemoryConnector):
        metrics = {"complete": False}

    with database() as session:
        svc.run_demo(session)
        result = svc.run_demo(session, target_connector=Incomplete([]))
        assert result["status"] == "UNKNOWN"
        assert session.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status == "OPEN")) == 2


@pytest.mark.database
def test_source_absence_does_not_prove_recovery(database):
    with database() as session:
        svc.run_demo(session)
        integration = session.get(m.Integration, svc.INTEGRATION_ID)
        sources, targets = fixture("healthy", integration.demo_anchor, m.utcnow())
        session.rollback()
        svc.run_demo(session, source_connector=MemoryConnector(sources.entities[1:]), target_connector=targets)
        missing = session.scalar(select(m.Incident).where(m.Incident.type == "missing_target"))
        assert missing.status == "OPEN"
