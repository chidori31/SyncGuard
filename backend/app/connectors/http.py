"""Read-only Bitrix24 REST / 1C OData adapters. Complete-or-error collection boundary."""

import json
import random
import time
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from app.connectors.base import ConnectorError
from app.normalization import Attributes, NormalizedEntity, identifier, normalize_1c


class HTTPConnector:
    def __init__(
        self,
        base_url: str | SecretStr,
        *,
        transport=None,
        params=None,
        auth=None,
        max_pages=100,
        page_size=50,
        max_seconds=20,
        allow_http=False,
    ):
        if (
            type(page_size) is not int
            or not 1 <= page_size <= 1000
            or type(max_pages) is not int
            or not 1 <= max_pages <= 100
            or not 1 <= max_seconds <= 60
        ):
            raise ConnectorError("Invalid connector resource limits")
        url = base_url.get_secret_value() if isinstance(base_url, SecretStr) else base_url
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ConnectorError("Invalid connector URL configuration")
        if parsed.scheme != "https" and not allow_http:
            raise ConnectorError("Connector requires HTTPS")
        self._base_url = url.rstrip("/") + "/"
        self.params = dict(params or {})
        self.max_pages, self.page_size, self.max_seconds = max_pages, page_size, max_seconds
        self.client = httpx.Client(transport=transport, auth=auth, follow_redirects=False, trust_env=False)
        self.metrics = {"requests": 0, "pages": 0, "retries": 0, "complete": False}

    def close(self):
        self.client.close()

    def healthcheck(self):
        # The data request is the authoritative read check; avoid a misleading independent health endpoint.
        return True

    def _request(self, method, url, deadline, **kwargs):
        for attempt in range(3):
            delay = 0.1 * 2**attempt + random.uniform(0, 0.05)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConnectorError("Connector time budget exceeded")
            self.metrics["requests"] += 1
            try:
                # Stream and limit decoded bytes; never log URLs, auth or upstream response bodies.
                with self.client.stream(method, url, timeout=min(5.0, remaining), **kwargs) as response:
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        retry_after = response.headers.get("Retry-After", "")
                        if retry_after.isdigit():
                            delay = max(delay, int(retry_after))
                        if attempt == 2:
                            raise ConnectorError("Connector temporarily unavailable")
                    elif not 200 <= response.status_code < 300:
                        raise ConnectorError("Connector request rejected")
                    else:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 2_000_000 or time.monotonic() > deadline:
                                raise ConnectorError("Connector response limit exceeded")
                        try:
                            payload = json.loads(content, parse_float=Decimal)
                        except (ValueError, UnicodeError):
                            raise ConnectorError("Invalid connector JSON") from None
                        if not isinstance(payload, dict) or "error" in payload:
                            raise ConnectorError("Connector returned an error payload")
                        return payload
            except httpx.HTTPError:
                if attempt == 2:
                    raise ConnectorError("Connector network failure") from None
            self.metrics["retries"] += 1
            remaining = max(0, deadline - time.monotonic())
            if delay >= remaining:
                raise ConnectorError("Retry delay exceeds connector time budget")
            time.sleep(delay)
        raise ConnectorError("Connector unavailable")

    def get_entity(self, external_id):
        # Collection scan: never call in a per-entity orchestration loop.
        return next((e for e in self.fetch_entities() if e.external_id == external_id), None)

    def search_entities(self, **attributes):
        return [
            e for e in self.fetch_entities() if all(getattr(e.attributes, k, None) == v for k, v in attributes.items())
        ]

    @staticmethod
    def _append(result, seen, entity):
        if len(result) >= 10000:
            raise ConnectorError("Connector entity limit exceeded")
        if entity.external_id in seen:
            raise ConnectorError("Snapshot repeats an external entity ID")
        seen.add(entity.external_id)
        result.append(entity)


class Bitrix24Connector(HTTPConnector):
    def fetch_entities(self):
        self.metrics = {"requests": 0, "pages": 0, "retries": 0, "complete": False}
        deadline, result, seen, start = time.monotonic() + self.max_seconds, [], set(), 0
        try:
            for _ in range(self.max_pages):
                payload = self._request(
                    "POST",
                    self._base_url + "crm.item.list",
                    deadline,
                    params=self.params,
                    json={
                        "entityTypeId": 2,
                        "order": {"id": "ASC"},
                        "start": start,
                        "select": [
                            "id",
                            "stageId",
                            "stageSemanticId",
                            "opportunity",
                            "currencyId",
                            "contactId",
                            "createdTime",
                            "updatedTime",
                            "movedTime",
                        ],
                    },
                )
                self.metrics["pages"] += 1
                rows = payload["result"]["items"]
                if not isinstance(rows, list):
                    raise ConnectorError("Invalid Bitrix24 item collection")
                for row in rows:
                    semantic = row["stageSemanticId"]
                    if semantic not in {"S", "P", "F"}:
                        raise ConnectorError("Unknown Bitrix24 stage semantics")
                    entity = NormalizedEntity(
                        source="bitrix24",
                        entity_type="deal",
                        external_id=identifier(row["id"]),
                        created_at=row["createdTime"],
                        updated_at=row["updatedTime"],
                        attributes=Attributes(
                            status={"S": "WON", "P": "IN_PROGRESS", "F": "LOST"}[semantic],
                            amount=row["opportunity"],
                            currency=row["currencyId"],
                            customer_id=identifier(row["contactId"]),
                            status_changed_at=row.get("movedTime"),
                        ),
                    )
                    self._append(result, seen, entity)
                next_offset = payload.get("next")
                if next_offset is None:
                    if type(payload.get("total")) is not int or payload["total"] != len(result):
                        raise ConnectorError("Bitrix24 snapshot count mismatch")
                    self.metrics["complete"] = True
                    return result
                if not rows or type(next_offset) is not int or next_offset <= start:
                    raise ConnectorError("Invalid Bitrix24 pagination cursor")
                start = next_offset
        except (KeyError, TypeError, ValueError):
            raise ConnectorError("Invalid Bitrix24 entity data") from None
        raise ConnectorError("Bitrix24 pagination limit exceeded")


class OneCConnector(HTTPConnector):
    def __init__(self, *args, collection="Document_CustomerOrder", field_map=None, timezone_name="UTC", **kwargs):
        super().__init__(*args, **kwargs)
        if not collection or not all(c.isalnum() or c == "_" for c in collection):
            raise ConnectorError("Invalid 1C collection name")
        self.collection = collection
        self.zone = ZoneInfo(timezone_name)
        # Date must represent actual creation time, not an editable accounting date.
        self.fields = field_map or {
            key: key for key in ("Ref_Key", "Date", "UpdatedAt", "Total", "Currency", "Customer", "CRMDealID")
        }

    def fetch_entities(self):
        self.metrics = {"requests": 0, "pages": 0, "retries": 0, "complete": False}
        deadline, result, seen = time.monotonic() + self.max_seconds, [], set()
        collection_url = self._base_url + self.collection
        current, visited = collection_url, set()
        initial_params = {
            **self.params,
            "$format": "json",
            "$top": self.page_size,
            "$orderby": "Ref_Key",
            "$inlinecount": "allpages",
        }
        params = initial_params
        total = None
        try:
            for _ in range(self.max_pages):
                request_key = str(httpx.URL(current).copy_merge_params(params or {}))
                if request_key in visited:
                    raise ConnectorError("1C pagination loop")
                visited.add(request_key)
                payload = self._request("GET", current, deadline, params=params)
                self.metrics["pages"] += 1
                rows = payload["value"]
                if not isinstance(rows, list):
                    raise ConnectorError("Invalid 1C collection")
                raw_count = payload.get("odata.count", payload.get("@odata.count"))
                if raw_count is not None:
                    if type(raw_count) is not int and not (
                        isinstance(raw_count, str) and raw_count.isascii() and raw_count.isdigit()
                    ):
                        raise ConnectorError("Invalid 1C collection count")
                    count = int(raw_count)
                    if not 0 <= count <= 10000 or (total is not None and total != count):
                        raise ConnectorError("1C snapshot changed while paging")
                    total = count
                for row in rows:
                    normalized = {key: row[field] for key, field in self.fields.items()}
                    for key in ("Date", "UpdatedAt"):
                        stamp = datetime.fromisoformat(normalized[key].replace("Z", "+00:00"))
                        normalized[key] = stamp if stamp.tzinfo else stamp.replace(tzinfo=self.zone)
                    self._append(result, seen, normalize_1c(normalized))
                next_link = payload.get("odata.nextLink", payload.get("@odata.nextLink"))
                if not next_link:
                    if total is not None and len(result) < total and rows:
                        # Some 1C publications implement client-driven paging without nextLink.
                        current, params = collection_url, {**initial_params, "$skip": len(result)}
                        continue
                    if total is None or total != len(result):
                        raise ConnectorError("1C snapshot count missing or inconsistent")
                    self.metrics["complete"] = True
                    return result
                if not isinstance(next_link, str) or not rows:
                    raise ConnectorError("Invalid 1C pagination")
                candidate = urljoin(current, next_link)
                initial, parsed = urlsplit(collection_url), urlsplit(candidate)
                if (parsed.scheme, parsed.netloc, parsed.path) != (
                    initial.scheme,
                    initial.netloc,
                    initial.path,
                ) or parsed.fragment:
                    raise ConnectorError("1C pagination escaped configured collection")
                current, params = str(httpx.URL(candidate).copy_merge_params(self.params)), None
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ConnectorError("Invalid 1C entity data") from None
        raise ConnectorError("1C pagination limit exceeded")
