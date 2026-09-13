from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text

from app import models as m
from app.connectors.base import ConnectorError
from app.core import event
from app.normalization import NormalizedEntity
from app.rules import RuleSpec, evaluate
from app.scenarios import SCENARIOS, fixture

ORG_ID = str(uuid5(NAMESPACE_URL, "syncguard/demo/organization"))
INTEGRATION_ID = str(uuid5(NAMESPACE_URL, "syncguard/demo/integration"))
RULE_ID = str(uuid5(NAMESPACE_URL, "syncguard/demo/rule"))
LOCK_ID = 71005821
ACTIVE = ("OPEN", "ACKNOWLEDGED")


def lock_demo(session):
    session.execute(text("SET LOCAL lock_timeout = '10s'"))
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_ID})


def seed(session):
    integration = session.get(m.Integration, INTEGRATION_ID)
    if integration:
        return integration, session.get(m.BusinessRule, RULE_ID)
    session.add(m.Organization(id=ORG_ID, name="Демо-компания"))
    session.flush()
    source_id, target_id = (str(uuid5(NAMESPACE_URL, f"syncguard/demo/{kind}")) for kind in ("bitrix", "1c"))
    session.add_all(
        [
            m.Connector(id=source_id, organization_id=ORG_ID, name="Bitrix24", type="mock_bitrix24"),
            m.Connector(id=target_id, organization_id=ORG_ID, name="1С", type="mock_1c"),
        ]
    )
    session.flush()
    integration = m.Integration(
        id=INTEGRATION_ID,
        organization_id=ORG_ID,
        name="1С ↔ Bitrix24",
        source_connector_id=source_id,
        target_connector_id=target_id,
    )
    session.add(integration)
    session.flush()
    rule = m.BusinessRule(
        id=RULE_ID,
        organization_id=ORG_ID,
        integration_id=integration.id,
        name="Завершённая сделка → заказ в 1С за 5 минут",
    )
    session.add(rule)
    session.flush()
    return integration, rule


def fingerprint(rule, source, outcome):
    parts = [
        rule.organization_id,
        rule.integration_id,
        rule.id,
        source.source,
        source.entity_type,
        source.external_id,
        outcome,
    ]
    import json

    return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def title_for(outcome, external_id):
    return {
        "missing_target": f"Сделка #{external_id} не появилась в 1С",
        "wrong_amount": f"Сумма заказа по сделке #{external_id} отличается",
        "duplicate_target": f"Дубли заказов по сделке #{external_id}",
        "synchronization_delay": f"Заказ по сделке #{external_id} создан с опозданием",
    }[outcome]


def timeline(incident, status, now):
    incident.timeline = [*incident.timeline, {"status": status, "at": now.isoformat()}]


def persist_entity(session, integration, connector_id, entity, now):
    row = session.scalar(
        select(m.ExternalEntity).where(
            m.ExternalEntity.organization_id == ORG_ID,
            m.ExternalEntity.connector_id == connector_id,
            m.ExternalEntity.entity_type == entity.entity_type,
            m.ExternalEntity.external_id == entity.external_id,
        )
    )
    if row is None:
        row = m.ExternalEntity(
            organization_id=ORG_ID,
            connector_id=connector_id,
            entity_type=entity.entity_type,
            external_id=entity.external_id,
        )
        session.add(row)
    row.normalized_data = entity.model_dump(mode="json")
    row.observed_at = now


def reconcile(session, integration, rule, source, result, evidence, observation, now):
    incidents = session.scalars(
        select(m.Incident).where(
            m.Incident.organization_id == ORG_ID,
            m.Incident.rule_id == rule.id,
            m.Incident.source_external_id == source.external_id,
        )
    ).all()
    current = None
    created = 0
    if result.violation:
        key = fingerprint(rule, source, result.outcome)
        current = next((i for i in incidents if i.fingerprint == key), None)
        if current is None:
            current = m.Incident(
                organization_id=ORG_ID,
                integration_id=integration.id,
                rule_id=rule.id,
                fingerprint=key,
                source_external_id=source.external_id,
                type=result.outcome,
                status="OPEN",
                detected_at=now,
                timeline=[],
            )
            session.add(current)
            timeline(current, "OPEN", now)
            created = 1
        elif current.status == "RESOLVED":
            current.status = "OPEN"
            current.resolved_at = None
            timeline(current, "REOPENED", now)
        current.severity = result.severity
        current.title = title_for(result.outcome, source.external_id)
        current.description = (
            f"Сделка #{source.external_id} завершена в Bitrix24, но заказ отсутствует в 1С. "
            f"Срок {rule.maximum_delay // 60} минут истёк."
            if result.outcome == "missing_target"
            else result.explanation
        )
        current.business_value_at_risk = result.value_at_risk
        current.currency = source.attributes.currency
        current.last_seen_at = now
        current.details = {
            "expected_target": {"entity_type": rule.target_entity_type, "external_reference": source.external_id},
            "evaluation": result.model_dump(mode="json"),
        }
        session.flush()
        session.add(
            m.IncidentEvidence(incident_id=current.id, observation_id=observation.id, captured_at=now, data=evidence)
        )
        if created:
            session.add(m.Alert(incident_id=current.id))
            event("incident_created", incident_id=current.id, type=result.outcome)
    # Unknown and pending do not prove recovery. Definitive healthy/inapplicable or a changed violation do.
    if result.outcome not in {"unknown", "pending"}:
        for old in incidents:
            if old is not current and old.status in ACTIVE:
                old.status = "RESOLVED"
                old.resolved_at = now
                timeline(old, "RESOLVED", now)
                session.add(
                    m.IncidentEvidence(
                        incident_id=old.id, observation_id=observation.id, captured_at=now, data=evidence
                    )
                )
    return created


def run_demo(
    session,
    *,
    now=None,
    source_connector=None,
    target_connector=None,
    scenario="baseline",
    transport="memory",
    simulator_url=None,
):
    if scenario not in {item["id"] for item in SCENARIOS} or transport not in {"memory", "http"}:
        raise ValueError("Unsupported scenario or transport")
    explicit_now = now
    with session.begin(), ExitStack() as stack:
        lock_demo(session)
        # Capture the production clock after lock acquisition; waiting runs cannot backdate newer state.
        now = explicit_now or m.utcnow()
        integration, rule = seed(session)
        if integration.demo_anchor is None:
            saved = session.scalar(
                select(m.ExternalEntity).where(
                    m.ExternalEntity.connector_id == integration.source_connector_id,
                    m.ExternalEntity.external_id == "5821",
                )
            )
            integration.demo_anchor = (
                (NormalizedEntity.model_validate(saved.normalized_data).created_at + timedelta(hours=1))
                if saved
                else now - timedelta(minutes=10)
            )
        anchor = integration.demo_anchor
        if source_connector is None or target_connector is None:
            if transport == "http":
                from app.connectors.http import Bitrix24Connector, OneCConnector
                from app.core import settings

                base = (simulator_url or settings().simulator_url).rstrip("/")
                params = {"scenario": scenario, "anchor": anchor.isoformat(), "observed_at": now.isoformat()}
                default_source = Bitrix24Connector(base + "/bitrix/rest/", params=params, allow_http=True)
                stack.callback(default_source.close)
                default_target = OneCConnector(base + "/one-c/odata/", params=params, allow_http=True)
                stack.callback(default_target.close)
            else:
                default_source, default_target = fixture(scenario, anchor, now)
            source_connector = source_connector or default_source
            target_connector = target_connector or default_target
        run = m.CheckRun(
            organization_id=ORG_ID,
            integration_id=integration.id,
            scenario=scenario,
            transport=transport,
            status="UNKNOWN",
            started_at=now,
            completed_at=now,
            diagnostics={},
        )
        session.add(run)
        session.flush()
        health = {"source": False, "target": False}
        phase = "rule"
        try:
            if not rule.enabled:
                raise ConnectorError("Rule disabled")
            phase = "source"
            if not source_connector.healthcheck():
                raise ConnectorError("Source unavailable")
            sources = source_connector.fetch_entities()
            require_complete(source_connector)
            validate_snapshot(sources, "bitrix24", rule.source_entity_type)
            health["source"] = True
            if not sources:
                raise ConnectorError("Empty source snapshot cannot prove health")
            phase = "target"
            if not target_connector.healthcheck():
                raise ConnectorError("Target unavailable")
            targets = target_connector.fetch_entities()
            require_complete(target_connector)
            validate_snapshot(targets, "1c", rule.target_entity_type)
            health["target"] = True
        except (ConnectorError, OSError, ValueError, TypeError):
            now = explicit_now or m.utcnow()
            integration.last_check = now
            integration.status = "UNKNOWN"
            integration.entities_checked = 0
            run.completed_at = now
            run.diagnostics = {
                "connector_health": health,
                "lookup_complete": False,
                "failure_phase": phase,
                "source": getattr(source_connector, "metrics", {}),
                "target": getattr(target_connector, "metrics", {}),
            }
            session.add(
                m.Observation(
                    run_id=run.id,
                    organization_id=ORG_ID,
                    integration_id=integration.id,
                    source_external_id="__connector__",
                    outcome="unknown",
                    observed_at=now,
                    data=run.diagnostics,
                )
            )
            event("connector_check", status="unknown", phase=phase, run_id=run.id)
            return {
                "run_id": run.id,
                "integration_id": integration.id,
                "status": "UNKNOWN",
                "entities_checked": 0,
                "incidents_created": 0,
            }
        now = explicit_now or m.utcnow()
        integration.last_check = now
        run.completed_at = now
        event("connector_check", status="healthy", run_id=run.id)
        spec = RuleSpec(
            maximum_delay=rule.maximum_delay,
            source_entity_type=rule.source_entity_type,
            target_entity_type=rule.target_entity_type,
            source_condition=rule.source_condition,
            match_strategy=rule.match_strategy,
            severity=rule.severity,
        )
        outcomes, created = [], 0
        for entity in targets:
            persist_entity(session, integration, integration.target_connector_id, entity, now)
        for source in sources:
            persist_entity(session, integration, integration.source_connector_id, source, now)
            result = evaluate(spec, source, targets, now)
            outcomes.append(result)
            previous = session.scalar(
                select(m.Observation.observed_at)
                .where(
                    m.Observation.integration_id == integration.id,
                    m.Observation.source_external_id == source.external_id,
                    m.Observation.outcome == "healthy_match",
                )
                .order_by(m.Observation.observed_at.desc())
                .limit(1)
            )
            evidence = {
                "source_entity": source.model_dump(mode="json"),
                "target_lookup_result": {
                    "complete": True,
                    "match_count": len(result.matched_ids),
                    "entities": [
                        t.model_dump(mode="json")
                        for t in targets
                        if t.entity_type == rule.target_entity_type and t.external_id in result.matched_ids
                    ],
                },
                "observed_at": now.isoformat(),
                "connector_health": health,
                "rule_evaluation": result.model_dump(mode="json"),
                "last_successful_observation": previous.isoformat() if previous else None,
            }
            observation = m.Observation(
                run_id=run.id,
                organization_id=ORG_ID,
                integration_id=integration.id,
                source_external_id=source.external_id,
                outcome=result.outcome,
                observed_at=now,
                data=evidence,
            )
            session.add(observation)
            session.flush()
            created += reconcile(session, integration, rule, source, result, evidence, observation, now)
            event(
                "rule_evaluation", run_id=run.id, rule_id=rule.id, source_id=source.external_id, outcome=result.outcome
            )
        integration.entities_checked = len(sources)
        session.flush()
        active = session.scalars(
            select(m.Incident).where(m.Incident.integration_id == integration.id, m.Incident.status.in_(ACTIVE))
        ).all()
        if any(r.outcome == "unknown" for r in outcomes):
            integration.status = "UNKNOWN"
        elif any(i.severity == "CRITICAL" for i in active):
            integration.status = "BROKEN"
        elif active or any(r.outcome == "pending" for r in outcomes):
            integration.status = "DELAYED"
        else:
            integration.status = "HEALTHY"
            if any(r.outcome == "healthy_match" for r in outcomes):
                integration.last_successful_sync = now
        run.status, run.entities_checked, run.incidents_created = integration.status, len(sources), created
        run.diagnostics = {
            "connector_health": health,
            "lookup_complete": True,
            "source": getattr(source_connector, "metrics", {}),
            "target": getattr(target_connector, "metrics", {}),
        }
        return {
            "run_id": run.id,
            "integration_id": integration.id,
            "status": integration.status,
            "entities_checked": len(sources),
            "incidents_created": created,
            "outcomes": [r.model_dump(mode="json") for r in outcomes],
        }


def require_complete(connector):
    metrics = getattr(connector, "metrics", None)
    if metrics is not None and metrics.get("complete") is not True:
        raise ConnectorError("Connector reported an incomplete snapshot")


def validate_snapshot(entities, source, entity_type):
    if not isinstance(entities, list):
        raise ConnectorError("Expected a complete snapshot list")
    seen = set()
    for entity in entities:
        if (
            not isinstance(entity, NormalizedEntity)
            or entity.source != source
            or entity.entity_type != entity_type
            or entity.external_id in seen
        ):
            raise ConnectorError("Invalid or duplicate snapshot identity")
        seen.add(entity.external_id)


def risk_total(incidents, currency="RUB"):
    per_source = {}
    for i in incidents:
        if i.currency != currency:
            continue
        key = (i.integration_id, i.source_external_id, i.currency)
        per_source[key] = max(per_source.get(key, Decimal(0)), i.business_value_at_risk)
    return sum(per_source.values(), Decimal(0))


def risk_by_currency(incidents):
    return {currency: str(risk_total(incidents, currency)) for currency in sorted({i.currency for i in incidents})}


def integration_data(session, row):
    active = session.scalars(
        select(m.Incident).where(m.Incident.integration_id == row.id, m.Incident.status.in_(ACTIVE))
    ).all()
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "last_check": row.last_check,
        "last_successful_sync": row.last_successful_sync,
        "entities_checked": row.entities_checked,
        "open_incidents": len(active),
        "business_value_at_risk": str(risk_total(active)),
        "currency": "RUB",
        "risk_by_currency": risk_by_currency(active),
    }
