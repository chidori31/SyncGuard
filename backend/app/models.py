from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.db import Base


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(200), nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    email = Column(String(200), nullable=False)
    __table_args__ = (UniqueConstraint("organization_id", "email"),)


class Connector(Base):
    __tablename__ = "connectors"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(String(40), nullable=False)
    __table_args__ = (UniqueConstraint("organization_id", "id"),)


class Integration(Base):
    __tablename__ = "integrations"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    name = Column(String(200), nullable=False)
    source_connector_id = Column(String(36), nullable=False)
    target_connector_id = Column(String(36), nullable=False)
    status = Column(String(20), nullable=False, default="UNKNOWN")
    last_check = Column(DateTime(timezone=True))
    last_successful_sync = Column(DateTime(timezone=True))
    entities_checked = Column(Integer, nullable=False, default=0)
    demo_anchor = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "source_connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "target_connector_id"], ["connectors.organization_id", "connectors.id"]
        ),
        CheckConstraint("status IN ('UNKNOWN','HEALTHY','DELAYED','BROKEN')"),
    )


class BusinessRule(Base):
    __tablename__ = "business_rules"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    integration_id = Column(String(36), nullable=False)
    name = Column(String(250), nullable=False)
    source_entity_type = Column(String(40), nullable=False, default="deal")
    target_entity_type = Column(String(40), nullable=False, default="customer_order")
    source_condition = Column(JSON, nullable=False, default=lambda: {"status": "WON"})
    match_strategy = Column(String(60), nullable=False, default="external_reference")
    maximum_delay = Column(Integer, nullable=False, default=300)
    severity = Column(String(20), nullable=False, default="CRITICAL")
    enabled = Column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint("organization_id", "integration_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "integration_id"], ["integrations.organization_id", "integrations.id"]
        ),
        CheckConstraint("maximum_delay >= 0"),
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')"),
    )


class ExternalEntity(Base):
    __tablename__ = "external_entities"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    connector_id = Column(String(36), nullable=False)
    entity_type = Column(String(40), nullable=False)
    external_id = Column(String(100), nullable=False)
    normalized_data = Column(JSON, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["organization_id", "connector_id"], ["connectors.organization_id", "connectors.id"]),
        UniqueConstraint("organization_id", "connector_id", "entity_type", "external_id"),
    )


class Observation(Base):
    __tablename__ = "observations"
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(ForeignKey("check_runs.id"), nullable=True, index=True)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    integration_id = Column(String(36), nullable=False)
    source_external_id = Column(String(100), nullable=False)
    outcome = Column(String(40), nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    data = Column(JSON, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "integration_id"], ["integrations.organization_id", "integrations.id"]
        ),
    )


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    integration_id = Column(String(36), nullable=False)
    rule_id = Column(String(36), nullable=False)
    fingerprint = Column(String(64), nullable=False, unique=True)
    source_external_id = Column(String(100), nullable=False)
    type = Column(String(40), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    title = Column(String(300), nullable=False)
    description = Column(String(1000), nullable=False)
    business_value_at_risk = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="RUB")
    detected_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = Column(DateTime(timezone=True))
    details = Column("metadata", JSON, nullable=False, default=dict)
    timeline = Column(JSON, nullable=False, default=list)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "integration_id", "rule_id"],
            ["business_rules.organization_id", "business_rules.integration_id", "business_rules.id"],
        ),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')"),
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')"),
        CheckConstraint("business_value_at_risk >= 0"),
    )


class IncidentEvidence(Base):
    __tablename__ = "incident_evidence"
    id = Column(String(36), primary_key=True, default=uid)
    incident_id = Column(ForeignKey("incidents.id"), nullable=False, index=True)
    observation_id = Column(ForeignKey("observations.id"), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    data = Column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("incident_id", "observation_id"),)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(String(36), primary_key=True, default=uid)
    incident_id = Column(ForeignKey("incidents.id"), nullable=False, index=True)
    channel = Column(String(20), nullable=False, default="in_app")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String(20), nullable=False, default="RECORDED")


class CheckRun(Base):
    __tablename__ = "check_runs"
    id = Column(String(36), primary_key=True, default=uid)
    organization_id = Column(ForeignKey("organizations.id"), nullable=False)
    integration_id = Column(String(36), nullable=False)
    scenario = Column(String(30), nullable=False)
    transport = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    entities_checked = Column(Integer, nullable=False, default=0)
    incidents_created = Column(Integer, nullable=False, default=0)
    diagnostics = Column(JSON, nullable=False, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "integration_id"], ["integrations.organization_id", "integrations.id"]
        ),
        CheckConstraint("status IN ('UNKNOWN','HEALTHY','DELAYED','BROKEN')"),
        CheckConstraint("transport IN ('memory','http')"),
    )
