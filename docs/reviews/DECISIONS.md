# Independent Qwen reviews — 2026-09-12

Provider: Groq. Model: qwen/qwen3.8-27b. Codex selected synthetic project source, passed it through tools/ai_helper.py sanitizer, inspected the returned advice, implemented bounded changes and verified behavior independently. No environment files, real customer records or private logs were sent.

The user explicitly requested broad Qwen participation after an earlier source-transmission auto-review rejection was explained. Selected-source reviews subsequently succeeded. High reasoning exhausted 16,384 completion tokens without visible text on initial broad reviews; medium effort produced usable responses. Empty/truncated/provider-error output is not treated as a completed review. Raw response files are opinions, not implementation specifications.

## QWEN RECOMMENDATIONS ACCEPTED

| Review | Decision and evidence |
|---|---|
| 01 — final architecture | Clarified the exact pg_advisory_xact_lock variant and that the simulator starts by default in local Compose. Independently checked actual container health, coverage, concurrency and migration tests; model concerns were based on omitted source context. |
| 02 — rule engine | Reject None/bool/empty identifiers rather than converting them to strings. Validate contradictory/future timestamps and supported source conditions. Reject extra normalized attributes. Boundary and normalization tests pass. |
| 03 — HTTP security | Preserve fixed query parameters across nextLink; honor numeric Retry-After; validate resource limits; bound decoded body/pages/entities/time; keep monetary JSON decimals exact. Protocol tests cover retry, redirect refusal, unsafe nextLink and pagination. |
| 04 — test design | Add end-to-end scenario lifecycle, recovery/reopen, deduplication, outage/risk preservation, run history and independent currency totals. Actual endpoints and fields were taken from source, not the suggested pseudo-API. |
| 05 — orchestration | Add an explicit guard for connector metrics reporting an incomplete collection, even though provided HTTP collectors already raise on incompleteness. Regression test verifies UNKNOWN and preservation of prior incidents. |

Migration upgrade/downgrade testing also caught an unnamed generated foreign-key drop; migration now names the constraint explicitly. This was found by Codex verification, not attributed to Qwen.

## QWEN RECOMMENDATIONS REJECTED — AND WHY

- Resolve incidents when a source disappears, even after two runs (05 C1): absence may mean deletion, changed permissions or changed filters. It does not prove business recovery. Added a regression test preserving the incident instead.
- Remove outcome from the fingerprint (05 C2): the product intentionally tracks violation types separately and retains resolved incident history. SLA starts at WON/movedTime, not detected_at; the suggested clock-reset claim is false. Cross-type MTTR aggregation is not implemented or claimed.
- Treat missing amount as a nullable valid NormalizedEntity (05 R1): the schema already rejects it before evaluation. Low-level model_copy can bypass validation in tests; production adapters validate construction.
- Add nonexistent source_entity_type fields to the incident query (05 R3): current rules are restricted to one source and entity type, validated before reconciliation. Broader multi-source identity needs a separately designed schema migration when scope expands.
- Capture the clock only once per run (05 S2): started_at and completed_at intentionally measure different moments; evaluating after I/O uses the current time. Deterministic tests can supply an explicit clock.
- Treat arbitrary target.updated_at after deadline as late sync (02): unrelated edits do not prove late creation. Actual arrival/creation time is used.
- Sum historical delay amounts into current exposure (02/04): historical delay has zero current monetary risk. Deduplicated exposure uses the maximum active risk per source and currency.
- Loosen nextLink path checks by decoding/normalizing arbitrary paths (03): strict refusal is an explicit compatibility boundary; relaxing it needs concrete provider evidence and security tests.
- Claim 14-hour request time despite an existing collection deadline (03): not supported by the code. Synchronous budget caveats are documented accurately.
- Restrict all upstream reads to GET/HEAD (04): Bitrix24 crm.item.list legitimately uses POST for a read method.
- Copy invented API fields/routes or reopen_count/risk_score (04): not present in the project. Tests exercise actual /api/demo/run, checks, observations and timeline.
- Stop adding observations on repeated runs or echo upstream error bodies (04): every run needs audit evidence; raw errors can contain credentials.
- Compare floats with tolerances or silently round malformed input (02/04): deterministic money uses Decimal and exact validation.
- Claim definite CI failures from missing wget, insufficient coverage or untested migrations (01): the running nginx image has a passing wget healthcheck; PostgreSQL concurrency and migration round-trip tests already exist; measured coverage exceeds 90%. These are verification prompts, not confirmed bugs. Incident evidence queries do not join CheckRun, so legacy NULL run_id observations are retained.

Some sanitizer rules redact code fragments resembling secret assignments (for example `key = fingerprint(...)`). This may remove context from model review; source inspection and tests remain authoritative. A successful Qwen response is not proof of correctness, security certification or real-installation compatibility.
