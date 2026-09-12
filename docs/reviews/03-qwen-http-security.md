# Security & Correctness Review — HTTP Connector (Local Synthetic Demo)

Overall the code is well-structured for its stated scope. `follow_redirects=False`, `trust_env=False`, strict URL validation, 2 MB body cap, and the `nextLink` host/path pin are all correct. The findings below are ordered by actionability for this codebase.

---

## CRITICAL ISSUES

### 1. 1C: `self.params` (auth, tokens) silently dropped after page 1

```python
# first page
params = {**self.params, "$format": "json", "$top": self.page_size, ...}
payload = self._request("GET", current, deadline, params=params)
...
# subsequent pages
current, params = candidate, None          # ← self.params is gone
```

If `self.params` carries an `access_token`, `api_key`, or any server-required query credential, **every page after the first is sent without it**. The request will either 401 (correct failure) or, worse, the OData server may fall back to a session/anonymous path and return data the caller is not entitled to read.

**Fix:** preserve the operator-supplied params and merge them with whatever the `nextLink` already encodes:

```python
# keep a frozen copy at init
self._static_params = dict(params or {})

# in fetch_entities, after resolving candidate:
from urllib.parse import parse_qs, urlencode

link_query = parse_qs(urlsplit(candidate).query)
merged = {k: v[-1] for k, v in link_query.items()}  # nextLink wins
merged.update(self._static_params)  # operator params always present
current = urlunsplit((*urlsplit(candidate)[:3], urlencode(merged), ""))
params = None
```

This guarantees the token is present on every hop regardless of what the server echoes in `nextLink`.

---

## RISKS

### 2. 1C `nextLink` path check is byte-exact; trailing-slash or percent-encoding drift causes silent rejection or (if "fixed" naively) bypass

```python
if (parsed.scheme, parsed.netloc, parsed.path) != (initial.scheme, initial.netloc, initial.path) or parsed.fragment:
```

`urlsplit` does **not** normalise paths. Two realistic mismatches:

| Server returns `nextLink` | `urlsplit().path` | `initial.path` | Result |
|---|---|---|---|
| `/Document_CustomerOrder/` (trailing `/`) | `/Document_CustomerOrder/` | `/Document_CustomerOrder` | **rejected** (false positive) |
| `/Document%5FCustomerOrder` | `/Document%5FCustomerOrder` | `/Document_CustomerOrder` | **rejected** (false positive) |

A "fix" that percent-decodes or strips trailing slashes before comparing would be fine, but doing it *after* `urljoin` without re-validating the netloc could reintroduce a bypass if the decode changes the effective host (e.g. `host%2Fevil.com`).

**Fix:** compare on a normalised, percent-decoded path *and* re-assert netloc equality after normalisation:

```python
from urllib.parse import unquote


def _norm_path(p: str) -> str:
    p = unquote(p)
    return p.rstrip("/") or "/"


if (
    (parsed.scheme, parsed.netloc) != (initial.scheme, initial.netloc)
    or _norm_path(parsed.path) != _norm_path(initial.path)
    or parsed.fragment
):
    raise ConnectorError("1C pagination escaped configured collection")
```

### 3. Retry loop ignores `Retry-After` and uses fixed exponential backoff without jitter

```python
time.sleep(min(0.1 * 2**attempt, max(0, deadline - time.monotonic())))
```

* A 429 with `Retry-After: 5` will be retried after 0.1 s, 0.2 s — hammering the rate limiter.
* Deterministic backoff from multiple connector instances (if the demo ever runs more than one) causes thundering-herd.

For a single local simulator this is low-impact, but the fix is cheap:

```python
retry_after = response.headers.get("Retry-After")
if retry_after and retry_after.isdigit():
    delay = min(float(retry_after), max(0, deadline - time.monotonic()))
else:
    delay = min(0.1 * (2**attempt) + random.uniform(0, 0.05), max(0, deadline - time.monotonic()))
time.sleep(delay)
```

### 4. No upper bound on `page_size` / `max_pages`; 2 MB cap is the only backstop

`page_size` and `max_pages` are constructor arguments with no validation. A misconfigured `page_size=1_000_000` makes the server attempt to serialise a huge page; the 2 MB body cap will abort it, but the server-side cost is real. Similarly `max_pages=10_000` × 5 s per-request timeout = up to 14 h of a single thread blocked.

```python
if not (1 <= page_size <= 10_000):
    raise ConnectorError("page_size out of range")
if not (1 <= max_pages <= 1_000):
    raise ConnectorError("max_pages out of range")
```

### 5. `get_entity` / `search_entities` trigger a full-collection fetch per call

```python
def get_entity(self, external_id):
    return next((e for e in self.fetch_entities() if e.external_id == external_id), None)
```

Each call downloads up to `max_pages × page_size` entities over the wire, parses JSON, and discards everything except one row. In the local demo this is tolerable, but if the connector is ever reused for a lookup-heavy code path it becomes an O(n) network cost per call.

**Suggestion:** document the cost explicitly (docstring or a `# WARNING` comment) so a future refactorer doesn't call this in a loop. If the upstream API supports `?$filter=Ref_Key eq '...'` or `crm.item.get`, prefer that.

---

## SUGGESTIONS (non-blocking)

* **`self.params` is a mutable dict shared across requests.** Store a `tuple(self.params.items())` or `frozenset` at init so a concurrent mutation can't corrupt a mid-flight fetch.
* **`healthcheck` always returns `True`.** The comment justifies this, but consider returning a small dict `{"ok": True, "note": "use fetch_entities for real check"}` so callers can't accidentally treat it as a liveness signal.
* **`SecretStr` value is extracted to a plain `str` at `__init__` time.** Fine for a local demo; in a long-lived service the plaintext URL (possibly containing a token in the path) lives in `self._base_url` for the object's lifetime. Keep it as `SecretStr` and call `.get_secret_value()` at request time if this pattern ever leaves the demo.

---

## TESTS

```python
import httpx
from unittest.mock import patch
from app.connectors.base import ConnectorError
from app.connectors.http_connector import OneCConnector, Bitrix24Connector

# --- helper: build a mock transport that returns canned responses ---
def _mock_transport(responses: list[httpx.Response]):
    it = iter(responses)
    def handler(request: httpx.Request) -> httpx.Response:
        return next(it)
    return httpx.MockTransport(handler)

def _resp(body: dict, status=200):
    return httpx.Response(status, json=body)

# 1. 1C: auth param must survive to page 2+
def test_1c_params_preserved_on_subsequent_pages():
    page1 = {"value": [{"Ref_Key": [REDACTED], "Date": "2025-01-01T00:00:00Z",
                         "UpdatedAt": "2025-01-01T00:00:00Z", "Total": 100,
                         "Currency": "USD", "Customer": "C1", "CRMDealID": "D1"}],
             "odata.count": 2,
             "odata.nextLink": "http://localhost:8080/Document_CustomerOrder?$skip=1"}
    page2 = {"value": [{"Ref_Key": [REDACTED], "Date": "2025-01-02T00:00:00Z",
                         "UpdatedAt": "2025-01-02T00:00:00Z", "Total": 200,
                         "Currency": "USD", "Customer": "C2", "CRMDealID": "D2"}],
             "odata.count": 2}
    # Capture what the client actually sends
    sent_queries = []
    def handler(request: httpx.Request) -> httpx.Response:
        sent_queries.append(request.url.query.decode())
        return next(it)
    it = iter([_resp(page1), _resp(page2)])
    c = OneCConnector("http://localhost:8080", allow_http=True,
                      transport=httpx.MockTransport(handler),
                      params={"access_token": [REDACTED]})
    c.fetch_entities()
    # Every request must carry the token
    assert all("access_token=[REDACTED] in q for q in sent_queries), \
        f"token missing on page 2+: {sent_queries}"

# 2. 1C: nextLink to a different host is rejected
def test_1c_nextlink_cross_host_rejected():
    page1 = {"value": [{"Ref_Key": [REDACTED], "Date": "2025-01-01T00:00:00Z",
                         "UpdatedAt": "2025-01-01T00:00:00Z", "Total": 1,
                         "Currency": "USD", "Customer": "C", "CRMDealID": "D"}],
             "odata.count": 1,
             "odata.nextLink": "http://evil.example/Document_CustomerOrder?$skip=1"}
    it = iter([_resp(page1)])
    c = OneCConnector("http://localhost:8080", allow_http=True,
                      transport=httpx.MockTransport(lambda r: next(it)))
    with pytest.raises(ConnectorError, match="escaped"):
        c.fetch_entities()

# 3. 1C: nextLink to a different path is rejected
def test_1c_nextlink_cross_path_rejected():
    page1 = {"value": [{"Ref_Key": [REDACTED], "Date": "2025-01-01T00:00:00Z",
                         "UpdatedAt": "2025-01-01T00:00:00Z", "Total": 1,
                         "Currency": "USD", "Customer": "C", "CRMDealID": "D"}],
             "odata.count": 1,
             "odata.nextLink": "http://localhost:8080/Other_Collection?$skip=1"}
    it = iter([_resp(page1)])
    c = OneCConnector("http://localhost:8080", allow_http=True,
                      transport=httpx.MockTransport(lambda r: next(it)))
    with pytest.raises(ConnectorError, match="escaped"):
        c.fetch_entities()

# 4. Bitrix24: looping cursor (next ≤ start) is rejected
def test_bitrix24_looping_cursor():
    page1 = {"result": {"items": [{"id": 1, "stageSemanticId": "P", "opportunity": 10,
                                   "currencyId": "USD", "contactId": 1,
                                   "createdTime": "2025-01-01T00:00:00Z",
                                   "updatedTime": "2025-01-01T00:00:00Z"}],
                         "total": 2},
             "next": 0}          # goes backwards
    it = iter([_resp(page1)])
    c = Bitrix24Connector("http://localhost:8080", allow_http=True,
                          transport=httpx.MockTransport(lambda r: next(it)))
    with pytest.raises(ConnectorError, match="cursor"):
        c.fetch_entities()

# 5. Response body > 2 MB is aborted
def test_oversized_response_rejected():
    big = b"x" * 2_000_001
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big,
                              headers={"content-type": "application/json"})
    c = Bitrix24Connector("http://localhost:8080", allow_http=True,
                          transport=httpx.MockTransport(handler))
    with pytest.raises(ConnectorError, match="limit exceeded"):
        c.fetch_entities()

# 6. 429 → retried → still 429 → raises after 3 attempts
def test_429_exhausts_retries():
    c = Bitrix24Connector("http://localhost:8080", allow_http=True,
                          transport=httpx.MockTransport(
                              lambda r: httpx.Response(429)),
                          max_seconds=30)
    with pytest.raises(ConnectorError, match="temporarily unavailable"):
        c.fetch_entities()
    assert c.metrics["retries"] == 2      # 3 attempts, 2 retries
    assert c.metrics["requests"] == 3

# 7. Malformed JSON (valid HTTP 200, body not JSON)
def test_malformed_json():
    c = Bitrix24Connector("http://localhost:8080", allow_http=True,
                          transport=httpx.MockTransport(
                              lambda r: httpx.Response(200, content=b"not json",
                                                       headers={"content-type": "application/json"})))
    with pytest.raises(ConnectorError, match="Invalid connector JSON"):
        c.fetch_entities()

# 8. JSON payload is a list, not a dict
def test_json_array_rejected():
    c = Bitrix24Connector("http://localhost:8080", allow_http=True,
                          transport=httpx.MockTransport(
                              lambda r: httpx.Response(200, json=[1, 2, 3])))
    with pytest.raises(ConnectorError, match="error payload"):
        c.fetch_entities()
```

---

**Summary:** The SSRF surface is well-contained for a local demo (`follow_redirects=False`, `trust_env=False`, host+path pin on `nextLink`). The one finding that would bite in a real deployment is **#1** (auth params vanishing after page 1 in the 1C connector). Everything else is hardening that is cheap to add now and expensive to retrofit later.
