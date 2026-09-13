import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from app.connectors.base import ConnectorError
from app.connectors.http import Bitrix24Connector, OneCConnector
from app.connectors.mock_1c import Mock1C
from app.connectors.mock_bitrix import MockBitrix
from app.normalization import identifier, normalize_1c
from app.rules import RuleSpec, evaluate
from pydantic import ValidationError
from test_rules import ANCHOR, NOW


def bitrix_row(id="5821"):
    return {
        "id": id,
        "stageId": "C5:CUSTOM_SUCCESS",
        "stageSemanticId": "S",
        "opportunity": "184000.00",
        "currencyId": "RUB",
        "contactId": 1004,
        "createdTime": (ANCHOR - timedelta(hours=1)).isoformat(),
        "updatedTime": ANCHOR.isoformat(),
        "movedTime": ANCHOR.isoformat(),
    }


def one_c_row(id="order-5821"):
    return {
        "Ref_Key": id,
        "Date": (ANCHOR + timedelta(minutes=2)).isoformat(),
        "UpdatedAt": (ANCHOR + timedelta(minutes=2)).isoformat(),
        "Total": "184000.00",
        "Currency": "RUB",
        "Customer": "1004",
        "CRMDealID": "5821",
    }


def test_bitrix_pages_and_stage_semantics():
    seen = []

    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        data = {"result": {"items": [bitrix_row(str(5821 + body["start"]))]}, "total": 2}
        if body["start"] == 0:
            data["next"] = 1
        return httpx.Response(200, json=data)

    connector = Bitrix24Connector("https://bitrix.test/rest/", transport=httpx.MockTransport(handle))
    try:
        rows = connector.fetch_entities()
        assert len(rows) == 2 and all(row.attributes.status == "WON" for row in rows)
        assert [b["start"] for b in seen] == [0, 1]
        assert all(b["entityTypeId"] == 2 for b in seen)
        assert connector.metrics["complete"] is True
    finally:
        connector.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"result": {"items": []}, "total": 1},
        {"result": {"items": [bitrix_row()]}, "total": 1, "next": 0},
        {"result": {"items": [bitrix_row()]}, "total": 1, "next": "1"},
        {"error": "INVALID_CREDENTIALS", "error_description": "private-upstream-message"},
        {"result": {"items": [{**bitrix_row(), "id": None}]}, "total": 1},
        {"result": {"items": [{**bitrix_row(), "stageSemanticId": "UNKNOWN"}]}, "total": 1},
    ],
)
def test_bitrix_invalid_snapshot_is_unknown_boundary(payload):
    connector = Bitrix24Connector(
        "https://bitrix.test/rest/", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ConnectorError) as error:
            connector.fetch_entities()
        assert "private-upstream-message" not in str(error.value)
        assert connector.metrics["complete"] is False
    finally:
        connector.close()


def test_one_c_paginated_query_preserved_and_decimal_json():
    urls = []

    def handle(request):
        urls.append(str(request.url))
        if request.url.params.get("$skip") == "1":
            return httpx.Response(200, json={"value": [one_c_row("order-b")], "odata.count": "2"})
        return httpx.Response(
            200, json={"value": [one_c_row()], "odata.count": "2", "odata.nextLink": "?%24skip=1&scenario=healthy"}
        )

    connector = OneCConnector("https://one-c.test/odata/", transport=httpx.MockTransport(handle))
    try:
        rows = connector.fetch_entities()
        assert len(rows) == 2 and rows[0].attributes.amount == Decimal("184000.00")
        assert "scenario=healthy" in urls[1]
    finally:
        connector.close()


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.test/collect",
        "http://one-c.test/odata/Document_CustomerOrder",
        "/other/path",
        "https://user:password@one-c.test/odata/Document_CustomerOrder",
        "#fragment",
    ],
)
def test_no_nextlink_exfiltration(link):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"value": [one_c_row()], "odata.count": "2", "odata.nextLink": link})

    connector = OneCConnector(
        "https://one-c.test/odata/",
        auth=("synthetic-user", "synthetic-password"),
        transport=httpx.MockTransport(handle),
    )
    try:
        with pytest.raises(ConnectorError):
            connector.fetch_entities()
        assert len(calls) == 1
    finally:
        connector.close()


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403])
def test_rejected_status_no_redirect_or_retry(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://evil.test/"}, text="private-error")

    connector = Bitrix24Connector("https://bitrix.test/rest/", transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ConnectorError) as error:
            connector.fetch_entities()
        assert len(calls) == 1 and "private-error" not in str(error.value)
    finally:
        connector.close()


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_transient_failures_retry_then_succeed(failure):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) < 3:
            if failure == "timeout":
                raise httpx.ReadTimeout("secret-endpoint-url", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, json={"result": {"items": []}, "total": 0})

    connector = Bitrix24Connector("https://bitrix.test/rest/", transport=httpx.MockTransport(handle))
    try:
        assert connector.fetch_entities() == []
        assert len(calls) == 3 and connector.metrics["retries"] == 2
    finally:
        connector.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"value": []},
        {"value": [one_c_row()], "odata.count": "3"},
        {"value": [one_c_row(), one_c_row()], "odata.count": "2"},
    ],
)
def test_incomplete_or_repeated_one_c_snapshot_rejected(payload):
    connector = OneCConnector(
        "https://one-c.test/odata/", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ConnectorError):
            connector.fetch_entities()
    finally:
        connector.close()


def test_pagination_and_response_limits():
    connector = Bitrix24Connector(
        "https://bitrix.test/rest/",
        max_pages=1,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"result": {"items": [bitrix_row()]}, "total": 2, "next": 1})
        ),
    )
    try:
        with pytest.raises(ConnectorError, match="limit"):
            connector.fetch_entities()
    finally:
        connector.close()
    connector = Bitrix24Connector(
        "https://bitrix.test/rest/",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 2_000_001)),
    )
    try:
        with pytest.raises(ConnectorError, match="limit"):
            connector.fetch_entities()
    finally:
        connector.close()


def test_null_and_invalid_identifiers_not_stringified():
    for value in (None, True, {}, [], ""):
        with pytest.raises(ValueError):
            identifier(value)
    entity = normalize_1c({**one_c_row(), "CRMDealID": None})
    assert entity.attributes.external_reference is None


def test_contradictory_timestamps_and_conditions():
    source = MockBitrix(ANCHOR).entities[0]
    source = source.model_copy(update={"created_at": ANCHOR + timedelta(seconds=1)})
    assert evaluate(RuleSpec(), source, [], NOW).outcome == "unknown"
    with pytest.raises(ValidationError):
        RuleSpec(source_condition={"amount": "1000"})
    with pytest.raises(ValueError):
        evaluate(RuleSpec(), source, [], "not a clock")


def test_unrelated_target_edit_does_not_invent_late_creation():
    source = MockBitrix(ANCHOR).entities[1]
    target = Mock1C(ANCHOR).entities[0].model_copy(update={"updated_at": NOW})
    assert evaluate(RuleSpec(), source, [target], NOW).outcome == "healthy_match"


def test_one_c_client_driven_paging_and_fixed_params():
    offsets = []

    def handle(request):
        assert request.url.params["scenario"] == "healthy"
        offset = int(request.url.params.get("$skip", 0))
        offsets.append(offset)
        return httpx.Response(200, json={"value": [one_c_row(f"order-{offset}")], "odata.count": "3"})

    connector = OneCConnector(
        "https://one-c.test/odata/", page_size=1, params={"scenario": "healthy"}, transport=httpx.MockTransport(handle)
    )
    try:
        assert len(connector.fetch_entities()) == 3
        assert offsets == [0, 1, 2]
        assert connector.metrics["complete"] is True
    finally:
        connector.close()


@pytest.mark.parametrize("count", [True, 1.5, "1.5", -1, 10001])
def test_invalid_odata_count(count):
    connector = OneCConnector(
        "https://one-c.test/odata/",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"value": [one_c_row()], "odata.count": count})
        ),
    )
    try:
        with pytest.raises(ConnectorError):
            connector.fetch_entities()
    finally:
        connector.close()
