"""Deterministic business decisions. No database, HTTP, connector or LLM imports."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.normalization import NormalizedEntity


class RuleSpec(BaseModel):
    maximum_delay: int = Field(default=300, ge=0)
    source_entity_type: str = "deal"
    target_entity_type: str = "customer_order"
    source_condition: dict[str, str] = Field(default_factory=lambda: {"status": "WON"})
    match_strategy: Literal["external_reference"] = "external_reference"
    severity: Literal["INFO", "WARNING", "CRITICAL"] = "CRITICAL"
    model_config = ConfigDict(frozen=True)

    @field_validator("source_condition")
    @classmethod
    def supported_conditions(cls, value):
        if not value or set(value) - {"status", "currency", "customer_id", "external_reference"}:
            raise ValueError("Only explicit string-attribute conditions are supported")
        return value


class Evaluation(BaseModel):
    outcome: str
    severity: str = "INFO"
    value_at_risk: Decimal = Decimal("0.00")
    explanation: str
    deadline: AwareDatetime | None = None
    matched_ids: list[str] = Field(default_factory=list)

    @property
    def violation(self):
        return self.outcome in {"missing_target", "duplicate_target", "wrong_amount", "synchronization_delay"}


def evaluate(rule: RuleSpec, source: NormalizedEntity, targets: list[NormalizedEntity], now: datetime) -> Evaluation:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware UTC clock is required")
    if source.updated_at < source.created_at or source.created_at > now or source.updated_at > now:
        return Evaluation(outcome="unknown", explanation="Contradictory or future source timestamps")
    if source.entity_type != rule.source_entity_type or any(
        getattr(source.attributes, key, None) != value for key, value in rule.source_condition.items()
    ):
        return Evaluation(outcome="not_applicable", explanation="Source does not match the rule")
    started = source.attributes.status_changed_at
    if started is None or started < source.created_at or started > source.updated_at or started > now:
        return Evaluation(outcome="unknown", explanation="Missing or future source event timestamp")
    deadline = started + timedelta(seconds=rule.maximum_delay)
    matches = [
        t
        for t in targets
        if t.entity_type == rule.target_entity_type and t.attributes.external_reference == source.external_id
    ]
    common = {"deadline": deadline, "matched_ids": [t.external_id for t in matches]}
    if any(t.created_at > now or t.updated_at > now or t.updated_at < t.created_at for t in matches):
        return Evaluation(outcome="unknown", explanation="Target timestamp lies in the future", **common)
    if not matches:
        if now < deadline:
            return Evaluation(outcome="pending", explanation="Synchronization deadline has not elapsed", **common)
        return Evaluation(
            outcome="missing_target",
            severity=rule.severity,
            value_at_risk=source.attributes.amount,
            explanation="Complete target lookup returned no matching order after deadline",
            **common,
        )
    if len(matches) > 1:
        return Evaluation(
            outcome="duplicate_target",
            severity=rule.severity,
            value_at_risk=source.attributes.amount,
            explanation="Multiple orders reference the same source deal",
            **common,
        )
    target = matches[0]
    if target.attributes.currency != source.attributes.currency or target.attributes.amount != source.attributes.amount:
        risk = (
            source.attributes.amount
            if target.attributes.currency != source.attributes.currency
            else abs(source.attributes.amount - target.attributes.amount)
        )
        return Evaluation(
            outcome="wrong_amount",
            severity="WARNING",
            value_at_risk=risk,
            explanation="Source and target amounts or currencies differ",
            **common,
        )
    if target.created_at > deadline:
        return Evaluation(
            outcome="synchronization_delay",
            severity="WARNING",
            explanation="Matching order was created after the synchronization deadline",
            **common,
        )
    return Evaluation(
        outcome="healthy_match", explanation="Exactly one timely order matches amount and currency", **common
    )
