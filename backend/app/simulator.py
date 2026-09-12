"""Local HTTP contract simulator. No real Bitrix24 or 1C installation is implied."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import Body, FastAPI, HTTPException, Query, Request
from pydantic import AwareDatetime

from app.scenarios import Scenario, fixture

app = FastAPI(title="SyncGuard HTTP contract simulator")


@app.get("/health")
def health():
    return {"status": "ok", "mode": "synthetic"}


def entities(scenario, anchor, observed_at):
    now = observed_at or datetime.now(timezone.utc)
    return fixture(scenario, anchor or now - timedelta(minutes=10), now)


@app.post("/bitrix/rest/crm.item.list")
def bitrix(
    body: dict = Body(...),
    scenario: Scenario = "baseline",
    anchor: AwareDatetime | None = None,
    observed_at: AwareDatetime | None = None,
):
    if body.get("entityTypeId") != 2:
        raise HTTPException(400, "Simulator supports deals only")
    source, _ = entities(scenario, anchor, observed_at)
    start = body.get("start", 0)
    if type(start) is not int or start < 0:
        raise HTTPException(400, "Invalid pagination offset")
    rows = [
        {
            "id": e.external_id,
            "stageId": "C1:WON",
            "stageSemanticId": "S",
            "opportunity": str(e.attributes.amount),
            "currencyId": e.attributes.currency,
            "contactId": e.attributes.customer_id,
            "createdTime": e.created_at.isoformat(),
            "updatedTime": e.updated_at.isoformat(),
            "movedTime": e.attributes.status_changed_at.isoformat(),
        }
        for e in source.entities
    ]
    # Deliberately small pages exercise actual multi-request traversal in the demo.
    response = {"result": {"items": rows[start : start + 2]}, "total": len(rows)}
    if start + 2 < len(rows):
        response["next"] = start + 2
    return response


@app.get("/one-c/odata/Document_CustomerOrder")
def one_c(
    request: Request,
    scenario: Scenario = "baseline",
    anchor: AwareDatetime | None = None,
    observed_at: AwareDatetime | None = None,
    skip: int = Query(0, alias="$skip", ge=0),
):
    if scenario == "outage":
        raise HTTPException(503, "Synthetic 1C outage")
    _, target = entities(scenario, anchor, observed_at)
    rows = [
        {
            "Ref_Key": e.external_id,
            "Date": e.created_at.isoformat(),
            "UpdatedAt": e.updated_at.isoformat(),
            "Total": str(e.attributes.amount),
            "Currency": e.attributes.currency,
            "Customer": e.attributes.customer_id,
            "CRMDealID": e.attributes.external_reference,
        }
        for e in sorted(target.entities, key=lambda e: e.external_id)
    ]
    response = {"value": rows[skip : skip + 2], "odata.count": str(len(rows))}
    if skip + 2 < len(rows):
        query = dict(request.query_params)
        query["$skip"] = skip + 2
        response["odata.nextLink"] = str(request.url.replace(query=urlencode(query)))
    return response
