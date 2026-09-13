# SyncGuard Acceptance Test Suite — 15 Tests

## Scope & Assumptions

- **Under test:** SyncGuard read-only HTTP service + its persistence layer.
- **Simulators:** Local Bitrix24 REST mock and 1C OData mock, controllable per-scenario via fixture state files.
- **Read-only contract:** SyncGuard issues only `GET`/`HEAD` to sources. No mutation endpoint exists.
- **Snapshot model:** Each CheckRun captures a point-in-time snapshot per source. Cross-source comparison is best-effort; a 2-source read is *not* a distributed transaction.

---

## P0 — Integration / State-Machine (5 tests)

### T-01 · Baseline creates both expected incidents

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24 fixture: order `missing_target184000` absent in 1C, order `wrong_amount10000` present in both but amount differs. 1C fixture matches. |
| **Action** | POST `/api/v1/runs` (triggers one CheckRun). |
| **Assert** | Response `202`. DB contains exactly **2** open incidents: one `type=MISSING`, `target_id=missing_target184000`; one `type=AMOUNT_MISMATCH`, `target_id=wrong_amount10000`. Both `status=OPEN`. No other incidents. |
| **Why P0** | Fails the entire product if the core detection path is broken. |

### T-02 · Healthy scenario resolves both incidents

| Field | Detail |
|---|---|
| **Precondition** | State after T-01 (two OPEN incidents). Fixtures swapped: Bitrix24 now contains `missing_target184000`; amount for `wrong_amount10000` matches 1C. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | Both incidents transition to `status=RESOLVED`. `resolved_at` is set. No new incidents created. Incident IDs unchanged. |
| **Why P0** | Resolution is half the state machine; a stuck-OPEN system is useless. |

### T-03 · Baseline-after-healthy reopens the *same* incident IDs

| Field | Detail |
|---|---|
| **Precondition** | State after T-02 (two RESOLVED incidents, IDs recorded). Fixtures reverted to T-01 baseline. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | The **same** `incident_id` values from T-01 are back to `status=OPEN`. No new incident rows are inserted. `reopen_count` increments by 1. `first_opened_at` is unchanged (preserves original timeline). |
| **Why P0** | Prevents incident-ID proliferation and preserves audit trail. A common bug: creating a new row instead of reopening. |

### T-04 · Duplicate scenario: one `duplicate_target`, old type resolved

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24 fixture has two records mapping to the same 1C target `duplicate_target` (e.g., two CRM deals → one 1C document). No pre-existing incidents. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | Exactly **1** incident: `type=DUPLICATE`, `target_id=duplicate_target`, `status=OPEN`. No `MISSING` or `AMOUNT_MISMATCH` incident for that target. If a prior run had created a `MISSING` for `duplicate_target` (simulated by seeding), that prior incident is `RESOLVED` and the new `DUPLICATE` supersedes it. |
| **Why P0** | Duplicate detection must not coexist with the "missing" interpretation of the same target. |

### T-05 · 1C returns 503 — existing incidents and risk are untouched

| Field | Detail |
|---|---|
| **Precondition** | State after T-01 (two OPEN incidents, aggregate risk > 0). 1C mock configured to return `503 Service Unavailable` for all OData requests. Bitrix24 fixture unchanged. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | Run completes (HTTP 200 or 202, not 5xx from SyncGuard itself). Both existing incidents remain `status=OPEN` with **identical** `risk_score` and `severity`. The run record carries `source_status.1c = "UNKNOWN"` (or `DEGRADED`). No incident is resolved, reopened, or created. `risk_score` on the aggregate is unchanged. |
| **Why P0** | A partial outage must not corrupt the monitoring state. This is the single most dangerous failure mode. |

---

## P1 — Risk Scoring & Business Rules (4 tests)

### T-06 · Delayed order (6 min after WON vs 5 min SLA) → WARNING, risk 0

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24 fixture: order `delayed_order` with `won_at = now - 6 min`, SLA window = 5 min. 1C fixture: matching record present, amounts equal. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | One incident: `type=SLA_BREACH` (or `DELAYED_SYNC`), `severity=WARNING`, `risk_score=0`, `status=OPEN`. It is **not** `ERROR` and does not contribute to aggregate risk. It does not mask or suppress other incidents. |
| **Why P1** | Distinguishes "operational lag" from "data corruption." Conflating them inflates risk and desensitises operators. |

### T-07 · Source modified 2 min ago on fresh DB → no MISSING incident

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24 fixture: record `pending_source` has `updated_at = now - 2 min`. 1C fixture: record absent. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | **Zero** incidents of type `MISSING` for `pending_source`. The observation is recorded (for audit) but the incident engine suppresses it because the source change is within the grace window (e.g., < 5 min). Run still completes successfully. |
| **Why P1** | Prevents false-positive storms during active writes. This is the practical mitigation for the snapshot-consistency gap (see T-15). |

### T-08 · Mixed currencies are never summed under a single RUB label

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24: order A amount `100 RUB`, order B amount `50 EUR`. 1C: matching records with same currencies. No mismatches. |
| **Action** | POST `/api/v1/runs`. Then GET `/api/v1/runs/{run_id}/summary`. |
| **Assert** | Summary reports `total_rub = 100` (or `total_rub = 100 + FX(50 EUR)` **only if** an explicit FX rate is applied and labelled `total_rub_fx_adjusted`). The raw `total_rub` field must **not** equal `150`. Each currency bucket is reported separately: `{RUB: 100, EUR: 50}`. No `AMOUNT_MISMATCH` incident is raised. |
| **Why P1** | A silent currency conflation is a financial-integrity bug. |

### T-09 · Aggregate risk is monotonic per-run and never negative

| Field | Detail |
|---|---|
| **Precondition** | Sequence: T-01 (risk > 0) → T-02 (risk → 0) → T-03 (risk > 0 again). |
| **Action** | Inspect `risk_score` on each run record. |
| **Assert** | `risk_score` is always ≥ 0. It decreases from T-01 to T-02. It increases from T-02 to T-03. No run has a risk higher than the sum of its individual incident risks (no double-counting). |
| **Why P1** | Guards against scoring bugs that make the dashboard meaningless. |

---

## P2 — Database / Persistence (3 tests)

### T-10 · CheckRun row persists with immutable run ID and source status

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. |
| **Action** | POST `/api/v1/runs` → capture `run_id`. POST again → capture `run_id_2`. |
| **Assert** | Two distinct `check_runs` rows. Each has: unique `run_id` (ULID/UUID), `started_at`, `finished_at`, `source_status.bitrix24 = "OK"`, `source_status.1c = "OK"`. `run_id` is not reused. Re-GETting `/api/v1/runs/{run_id}` returns identical data (no drift). |
| **Why P2** | Run IDs are the join key for all observations; a collision or mutation breaks the audit chain. |

### T-11 · Observation rows carry per-run metrics: requests, pages, retries

| Field | Detail |
|---|---|
| **Precondition** | Bitrix24 mock paginates (3 pages, 1 retry on page 2). 1C mock: 1 page, 0 retries. |
| **Action** | POST `/api/v1/runs`. |
| **Assert** | For the run, two `observations` rows (one per source). Bitrix24 row: `requests=4` (3 pages + 1 retry), `pages=3`, `retries=1`. 1C row: `requests=1`, `pages=1`, `retries=0`. Both rows reference the correct `run_id`. |
| **Why P2** | Metrics are the only way to diagnose slow or failing source integrations in production. |

### T-12 · Idempotent re-run of identical baseline does not duplicate incidents

| Field | Detail |
|---|---|
| **Precondition** | State after T-01 (two OPEN incidents). Fixtures unchanged. |
| **Action** | POST `/api/v1/runs` again. |
| **Assert** | Still exactly 2 OPEN incidents (same IDs). No new `observations` rows for already-OPEN incidents (or they are marked `no_change`). `reopen_count` is **not** incremented. Run completes with `new_incidents=0`. |
| **Why P2** | Prevents incident spam on polling. A 30-second poller would otherwise create 120 duplicate rows/hour. |

---

## P3 — API Contract (2 tests)

### T-13 · SyncGuard exposes no mutation endpoints (read-only enforcement)

| Field | Detail |
|---|---|
| **Precondition** | Service running. |
| **Action** | Issue `POST /api/v1/incidents/{id}/resolve`, `PUT /api/v1/incidents/{id}`, `DELETE /api/v1/runs/{id}`. |
| **Assert** | All return `405 Method Not Allowed` (or `404` if the route simply doesn't exist). No state change in DB. The only accepted method on data routes is `GET`; the only accepted method on the trigger route is `POST /api/v1/runs`. |
| **Why P3** | A stray write endpoint is a security and data-integrity risk in a "read-only" system. |

### T-14 · 503 from a source produces a well-formed degraded response, not a crash

| Field | Detail |
|---|---|
| **Precondition** | 1C mock returns `503` with body `{"error":"maintenance"}`. |
| **Action** | POST `/api/v1/runs`. Then GET `/api/v1/runs/{run_id}`. |
| **Assert** | SyncGuard responds `200` (or `202`) — it does **not** propagate 503. Run record: `source_status.1c = "UNKNOWN"`, `source_status.bitrix24 = "OK"`. `error_detail` field contains the 1C error body (truncated to ≤ 512 chars). No stack trace in response. Run `finished_at` is set (it completed, albeit partially). |
| **Why P3** | Operators need a structured degradation signal, not a 500 from the monitoring tool itself. |

---

## P4 — Characterisation / Limitation (1 test)

### T-15 · Snapshot consistency: cross-source race is *documented*, not *fixed*

| Field | Detail |
|---|---|
| **Precondition** | Fresh DB. Bitrix24 mock: record `race_target` present. 1C mock: record `race_target` absent **at the moment SyncGuard reads 1C**, but a background thread in the mock inserts it 50 ms after the 1C read completes (simulating in-flight write). |
| **Action** | POST `/api/v1/runs`. |
| **Assert (characterisation)** | A `MISSING` incident for `race_target` **may** be created. This is the **expected, accepted** behaviour. The test asserts that: (a) the incident is created with `confidence = "LOW"` or a `snapshot_drift = true` flag; (b) the next run (T-02-style healthy fixture) resolves it; (c) the run record logs `snapshot_window_ms` (time between first and last source read) so operators can gauge the race window. **This test does NOT assert the incident is absent** — that would require a distributed transaction, which the read-only architecture does not and should not provide. |
| **Why P4** | Codifies the known limitation. Without this test, a future "fix" that adds a retry loop to suppress the incident will silently change semantics and hide real gaps. The grace window in T-07 is the *only* mitigation; this test documents its boundary. |

---

## Execution Order & Dependencies

```
T-01 → T-02 → T-03     (state-machine chain, sequential)
T-04                     (fresh DB, independent)
T-05                     (depends on T-01 state)
T-06, T-07, T-08        (each fresh DB, independent of each other)
T-09                     (replays T-01→T-02→T-03, read-only assertion)
T-10, T-11, T-12        (T-12 depends on T-01; T-10/T-11 independent)
T-13, T-14              (independent, can run in parallel)
T-15                     (fresh DB, independent)
```

T-01 → T-02 → T-03 must run in a single transactional test fixture (same DB instance, no reset between steps). All other tests reset the DB.

---

## Realistic Limitations Called Out

1. **No true atomic snapshot.** Two HTTP GETs (Bitrix24, then 1C) are not a single transaction. T-15 documents this. The grace window (T-07) reduces false positives but does not eliminate them. If the 1C read is delayed by a network partition, the window widens unpredictably.

2. **503 ≠ 404.** T-05 treats 503 as "source state unknown." A 404 on a specific OData entity would be a *different* signal (entity deleted vs. service down) and is intentionally out of scope for these 15 tests. A follow-up suite should cover 404, 401, and timeout (distinct from 503).

3. **Currency test (T-08) assumes the simulator exposes currency as a field.** If Bitrix24 or 1C omits the currency code on some record types, the "never sum under RUB" guarantee is only as strong as the data. The test asserts on the *output label*, not on upstream data quality.

4. **Metrics (T-11) count HTTP requests, not logical operations.** A single OData `$filter` query that returns 500 records is 1 request, 1 page. A paginated query is N requests, N pages. Retries are counted at the HTTP layer. This is intentional but means "requests" is not a business-meaningful number.

5. **Max 15 tests is a hard cap.** Not covered: concurrent runs (two `POST /runs` in flight), DB migration idempotency, TLS/timeout behaviour, 1C OData `$top`/`$skip` edge at page boundary, Bitrix24 rate-limit (429) handling, and multi-tenant isolation. These need a second suite.

---

## What I Would Push Back On

- **T-03 "reopen same ID" is the highest-risk assertion in this suite.** If the incident store uses an auto-increment PK and the "reopen" is actually a soft-delete + re-insert, the ID *will* change. The test must assert on a **business key** (`source + target_id + type`), not a surrogate PK, or it will be flaky across schema changes. Make the assertion key explicit in the test spec.

- **T-05 "risk intact" needs a tolerance.** If risk is computed as a float, "intact" means `abs(new - old) < 1e-9`. State this in the assertion. Otherwise a floating-point rounding change in the scoring library will fail the test for no reason.

- **T-15 as a "test" is really a documentation artefact.** It will never fail (it asserts the bug exists). I'd mark it as a **characterisation / golden-master test** with a `@known-limitation` tag so CI doesn't treat a future fix as a regression. If someone *does* fix the race (e.g., by adding a 2-second delay before the 1C read), this test should be updated, not deleted, to record the new window.
