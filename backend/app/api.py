from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import services as svc
from app.db import get_session
from app.scenarios import SCENARIOS, Scenario

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_session)]


def incident_data(row):
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "organization_id",
            "integration_id",
            "rule_id",
            "source_external_id",
            "type",
            "severity",
            "status",
            "title",
            "description",
            "currency",
            "detected_at",
            "last_seen_at",
            "resolved_at",
            "timeline",
        )
    } | {"metadata": row.details, "business_value_at_risk": str(row.business_value_at_risk)}


def rule_data(row, integration):
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "integration_id",
            "name",
            "source_entity_type",
            "target_entity_type",
            "source_condition",
            "match_strategy",
            "maximum_delay",
            "severity",
        )
    } | {"source_connector": integration.source_connector_id, "target_connector": integration.target_connector_id}


@router.get("/integrations")
def integrations(db: DB):
    return [
        svc.integration_data(db, row)
        for row in db.scalars(select(m.Integration).where(m.Integration.organization_id == svc.ORG_ID))
    ]


@router.get("/integrations/{integration_id}")
def integration(integration_id: str, db: DB):
    row = db.scalar(
        select(m.Integration).where(m.Integration.id == integration_id, m.Integration.organization_id == svc.ORG_ID)
    )
    if row is None:
        raise HTTPException(404, "Integration not found")
    return svc.integration_data(db, row)


@router.get("/incidents")
def incidents(
    db: DB,
    status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = select(m.Incident).where(m.Incident.organization_id == svc.ORG_ID)
    if status:
        query = query.where(m.Incident.status == status)
    return [
        incident_data(row)
        for row in db.scalars(query.order_by(m.Incident.detected_at.desc(), m.Incident.id).limit(limit).offset(offset))
    ]


@router.get("/incidents/{incident_id}")
def incident(incident_id: str, db: DB):
    row = db.scalar(select(m.Incident).where(m.Incident.id == incident_id, m.Incident.organization_id == svc.ORG_ID))
    if row is None:
        raise HTTPException(404, "Incident not found")
    data = incident_data(row)
    integration = db.get(m.Integration, row.integration_id)
    data["integration"] = svc.integration_data(db, integration)
    data["business_rule"] = rule_data(db.get(m.BusinessRule, row.rule_id), integration)
    evidence = db.scalars(
        select(m.IncidentEvidence)
        .where(m.IncidentEvidence.incident_id == row.id)
        .order_by(m.IncidentEvidence.captured_at.desc(), m.IncidentEvidence.id)
        .limit(50)
    ).all()
    data["evidence"] = [{"id": e.id, "captured_at": e.captured_at, **e.data} for e in evidence]
    return data


class StatusUpdate(BaseModel):
    status: Literal["ACKNOWLEDGED"]


@router.patch("/incidents/{incident_id}")
def acknowledge(incident_id: str, body: StatusUpdate, db: DB):
    with db.begin():
        svc.lock_demo(db)
        row = db.scalar(
            select(m.Incident).where(m.Incident.id == incident_id, m.Incident.organization_id == svc.ORG_ID)
        )
        if row is None:
            raise HTTPException(404, "Incident not found")
        if row.status == "RESOLVED":
            raise HTTPException(409, "Resolved incident cannot be acknowledged")
        if row.status != body.status:
            row.status = body.status
            svc.timeline(row, body.status, m.utcnow())
    return incident_data(row)


@router.get("/rules")
def rules(db: DB):
    return [
        rule_data(row, db.get(m.Integration, row.integration_id))
        for row in db.scalars(select(m.BusinessRule).where(m.BusinessRule.organization_id == svc.ORG_ID))
    ]


class DemoRequest(BaseModel):
    scenario: Scenario = "baseline"
    transport: Literal["memory", "http"] = "memory"
    model_config = {"extra": "forbid"}


@router.get("/demo/scenarios")
def demo_scenarios():
    return SCENARIOS


@router.post("/demo/run")
def run_demo(db: DB, body: DemoRequest = Body(default_factory=DemoRequest)):
    return svc.run_demo(db, scenario=body.scenario, transport=body.transport)


@router.get("/integrations/{integration_id}/checks")
def checks(integration_id: str, db: DB, limit: int = Query(10, ge=1, le=50)):
    integration(integration_id, db)
    rows = db.scalars(
        select(m.CheckRun)
        .where(m.CheckRun.organization_id == svc.ORG_ID, m.CheckRun.integration_id == integration_id)
        .order_by(m.CheckRun.completed_at.desc(), m.CheckRun.id)
        .limit(limit)
    ).all()
    result = []
    for row in rows:
        observations = db.scalars(
            select(m.Observation).where(m.Observation.run_id == row.id).order_by(m.Observation.source_external_id)
        ).all()
        result.append(
            {
                name: getattr(row, name)
                for name in (
                    "id",
                    "scenario",
                    "transport",
                    "status",
                    "started_at",
                    "completed_at",
                    "entities_checked",
                    "incidents_created",
                    "diagnostics",
                )
            }
            | {
                "observations": [
                    {
                        "id": obs.id,
                        "source_external_id": obs.source_external_id,
                        "outcome": obs.outcome,
                        "data": obs.data,
                    }
                    for obs in observations
                ]
            }
        )
    return result


@router.get("/dashboard")
def dashboard(db: DB):
    integrations = db.scalars(select(m.Integration).where(m.Integration.organization_id == svc.ORG_ID)).all()
    incidents = db.scalars(
        select(m.Incident).where(m.Incident.organization_id == svc.ORG_ID, m.Incident.status.in_(svc.ACTIVE))
    ).all()
    return {
        "integrations": len(integrations),
        "healthy": sum(i.status == "HEALTHY" for i in integrations),
        "delayed": sum(i.status == "DELAYED" for i in integrations),
        "broken": sum(i.status == "BROKEN" for i in integrations),
        "unknown": sum(i.status == "UNKNOWN" for i in integrations),
        "open_incidents": len(incidents),
        "business_value_at_risk": str(svc.risk_total(incidents)),
        "currency": "RUB",
        "risk_by_currency": svc.risk_by_currency(incidents),
    }
