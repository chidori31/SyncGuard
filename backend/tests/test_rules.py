from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from app.connectors.mock_1c import Mock1C
from app.connectors.mock_bitrix import MockBitrix
from app.rules import RuleSpec, evaluate
from pydantic import ValidationError

ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = ANCHOR + timedelta(minutes=10)


def test_normalization_and_connector_lookup():
    connector = MockBitrix(ANCHOR)
    deal = connector.get_entity("5821")
    assert deal.attributes.amount == Decimal("184000.00")
    assert deal.attributes.customer_id == "1004"
    assert connector.healthcheck()
    assert len(connector.search_entities(status="WON")) == 3
    assert Mock1C(ANCHOR).get_entity("order-5822").attributes.external_reference == "5822"


@pytest.mark.parametrize(
    "index,outcome,risk", [(0, "missing_target", "184000"), (1, "healthy_match", "0"), (2, "wrong_amount", "10000")]
)
def test_required_demo_cases(index, outcome, risk):
    result = evaluate(RuleSpec(), MockBitrix(ANCHOR).entities[index], Mock1C(ANCHOR).entities, NOW)
    assert result.outcome == outcome
    assert result.value_at_risk == Decimal(risk)


@pytest.mark.parametrize("seconds,expected", [(299, "pending"), (300, "missing_target"), (301, "missing_target")])
def test_exact_deadline(seconds, expected):
    assert (
        evaluate(RuleSpec(), MockBitrix(ANCHOR).entities[0], [], ANCHOR + timedelta(seconds=seconds)).outcome
        == expected
    )


def test_duplicate_precedes_amount():
    target = Mock1C(ANCHOR).entities[0]
    duplicate = target.model_copy(update={"external_id": "another"})
    assert evaluate(RuleSpec(), MockBitrix(ANCHOR).entities[1], [target, duplicate], NOW).outcome == "duplicate_target"


@pytest.mark.parametrize("seconds,outcome", [(300, "healthy_match"), (301, "synchronization_delay")])
def test_target_arrival_boundary(seconds, outcome):
    source = MockBitrix(ANCHOR).entities[1]
    arrival = ANCHOR + timedelta(seconds=seconds)
    target = Mock1C(ANCHOR).entities[0].model_copy(update={"created_at": arrival, "updated_at": arrival})
    assert evaluate(RuleSpec(), source, [target], NOW).outcome == outcome


def test_unrelated_update_does_not_reset_deadline():
    source = MockBitrix(ANCHOR).entities[0].model_copy(update={"updated_at": NOW})
    assert evaluate(RuleSpec(), source, [], NOW).outcome == "missing_target"


def test_future_clock_and_missing_event_are_unknown():
    source = MockBitrix(ANCHOR).entities[0]
    assert evaluate(RuleSpec(), source, [], ANCHOR - timedelta(seconds=1)).outcome == "unknown"
    source = source.model_copy(update={"attributes": source.attributes.model_copy(update={"status_changed_at": None})})
    assert evaluate(RuleSpec(), source, [], NOW).outcome == "unknown"


def test_not_won_is_not_applicable():
    source = MockBitrix(ANCHOR).entities[0]
    source = source.model_copy(update={"attributes": source.attributes.model_copy(update={"status": "NEW"})})
    assert evaluate(RuleSpec(), source, [], NOW).outcome == "not_applicable"


def test_currency_mismatch_is_not_healthy():
    source = MockBitrix(ANCHOR).entities[1]
    target = Mock1C(ANCHOR).entities[0]
    target = target.model_copy(update={"attributes": target.attributes.model_copy(update={"currency": "USD"})})
    assert evaluate(RuleSpec(), source, [target], NOW).value_at_risk == Decimal("50000")


def test_reject_naive_timestamp_and_invalid_money():
    source = MockBitrix(ANCHOR).entities[0]
    data = source.model_dump()
    data["created_at"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError):
        type(source).model_validate(data)
    for amount in ("NaN", "-1", "0.001"):
        with pytest.raises(ValidationError):
            type(source.attributes).model_validate({**source.attributes.model_dump(), "amount": amount})
    with pytest.raises(ValueError):
        evaluate(RuleSpec(), source, [], datetime(2026, 1, 1))
