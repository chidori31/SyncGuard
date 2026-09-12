## Review: Synthetic-Data Integration MVP Orchestration

### CRITICAL ISSUES

**C1 – Stale incidents from deleted source entities permanently block HEALTHY status**

`reconcile` is only invoked for entities present in the current `sources` list (line: `for source in sources:`). If a deal is deleted in Bitrix24 between runs, no evaluation executes for it, so its incident is never resolved. The integration stays `BROKEN`/`DELAYED` indefinitely.

This is the *opposite* of false-healthy (stuck-not-healthy), but it is a data-integrity bug: the dashboard will report a phantom incident forever, and `risk_total` will include a deal that no longer exists.

*Evidence:* `run_demo` iterates `for source in sources:` and calls `reconcile` inside that loop. There is no sweep of active incidents whose `source_external_id` is absent from the current snapshot.

*Bounded fix:* After the per-entity loop, run a second pass:
```python
seen_ids = {s.external_id for s in sources}
stale = [i for i in active if i.source_external_id not in seen_ids]
for old in stale:
    old.status = "RESOLVED"
    old.resolved_at = now
    timeline(old, "RESOLVED", now)
```
Gate this behind a configurable grace period (e.g., only resolve if the entity was absent for ≥ 2 consecutive runs) to avoid flapping on transient connector gaps.

---

**C2 – Fingerprint includes `outcome`, silently resetting the SLA clock on violation-type transition**

`fingerprint(rule, source, outcome)` hashes the outcome string. When a violation changes type (e.g. `missing_target` → `wrong_amount` because the target appeared with a wrong amount), the new fingerprint matches no existing incident. A **new** incident is created with a fresh `detected_at`, and the old one is resolved by the sweep. The original detection time is lost.

*Evidence:*
```python
key = [REDACTED], source, result.outcome)   # includes outcome
current = next((i for i in incidents if i.fingerprint == key), None)
if current is None:
    current = m.Incident(..., detected_at=now, ...)  # new clock
```
A deal missing for 2 h that then appears with a wrong amount becomes a brand-new WARNING incident with `detected_at = now`. The 2-hour gap is invisible to any SLA or MTTR metric.

*Bounded fix:* Remove `outcome` from the fingerprint (key on `org + integration + rule + source + entity_type + external_id`). On type change, update `current.type`, `current.severity`, and append a `TYPE_CHANGED` timeline entry instead of creating a new row. This preserves `detected_at` and the full history.

---

### RISKS

**R1 – `source.attributes.amount` may be `None`; unhandled in `evaluate`**

`value_at_risk=source.attributes.amount` passes the raw attribute into a `Decimal`-typed Pydantic field. If the connector omits `amount`, Pydantic v2 raises `ValidationError`. Whether this is caught depends on the inheritance chain (`pydantic.ValidationError` → `ValueError` in v2, so it *is* caught by the `except` clause in `run_demo`). However, the error message will be opaque ("field required" / "value is not a valid decimal") and the entire run aborts with `UNKNOWN` status, masking the real cause.

*Fix:* Guard in `evaluate` before constructing the `Evaluation`:
```python
amount = source.attributes.amount
if amount is None:
    return Evaluation(outcome="unknown", explanation="Source entity has no amount")
```

**R2 – No snapshot-completeness verification**

`validate_snapshot` checks type, source tag, entity type, and duplicate IDs, but not that the connector actually returned a *complete* page set. A pagination bug that silently drops the last page would shrink `sources`, skip evaluations, and produce no incidents for the missing entities. The `lookup_complete` flag in diagnostics is hardcoded to `True` after the try-block succeeds.

*Fix:* Have the connector expose a `complete: bool` in its metrics (the test already asserts `record.diagnostics["source"]["complete"] is True`). In `run_demo`, if `complete` is `False`, treat the run as `UNKNOWN` rather than proceeding with a partial snapshot.

**R3 – `reconcile` incident query is scoped by `source_external_id` only, not by entity type or source connector**

Two different source entities (different `entity_type` or `source`) sharing the same `external_id` string would collide in the `incidents` list. The resolution sweep would resolve the "other" entity's incident. Not exploitable in the current single-source demo, but a latent bug if a second source connector is added.

*Fix:* Add `m.Incident.source_entity_type == source.entity_type` (or include the source connector ID) to the `WHERE` clause.

---

### SUGGESTIONS

**S1 – `import json` inside `fingerprint`**

Move to module level. It works, but it's a 30-byte import that runs on every call and obscures the dependency.

**S2 – `now` is re-captured three times in `run_demo`**

```python
now = explicit_now or m.utcnow()  # after lock
...
now = explicit_now or m.utcnow()  # in except
...
now = explicit_now or m.utcnow()  # after try
```
Capture once after the lock. If `explicit_now` is `None`, the three calls can return different timestamps, making `CheckRun.started_at` ≠ `Observation.observed_at` ≠ `CheckRun.completed_at` by milliseconds. Harmless for the demo, but it makes log correlation and audit trails harder.

**S3 – `LOCK_ID` is a module-level constant shared by all integrations**

Fine for a single-integration demo. If a second integration is added, all runs serialize on the same advisory lock. Derive the key from the integration ID: `uuid5(NAMESPACE_URL, f"lock/{integration_id}")`.

---

### TESTS TO ADD (regression)

**T1 – Source entity deletion → stale incident resolution (guards C1)**
```python
def test_deleted_source_resolves_stale_incident(database):
    with database() as s:
        svc.run_demo(s, scenario="baseline")  # creates missing_target incident
        assert s.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status == "OPEN")) == 2
        # Simulate: entity "5821" no longer in source snapshot
        # (use a custom scenario or monkey-patch the connector to drop it)
        svc.run_demo(s, scenario="entity_deleted")  # new scenario: 2 of 3 entities
        assert (
            s.scalar(select(func.count()).select_from(m.Incident).where(m.Incident.status == "OPEN")) == 1
        )  # one resolved
```

**T2 – Violation type transition preserves `detected_at` (guards C2)**
```python
def test_violation_type_change_preserves_detection_time(database):
    with database() as s:
        svc.run_demo(s, scenario="baseline")  # missing_target, detected_at = T0
        inc = s.scalar(select(m.Incident).where(m.Incident.type == "missing_target"))
        original_detected = inc.detected_at
        svc.run_demo(s, scenario="wrong_amount")  # same entity, now wrong_amount
        # After fix (C2): same incident row, type updated, detected_at unchanged
        inc = s.scalar(select(m.Incident).where(m.Incident.source_external_id == "5821"))
        assert inc.detected_at == original_detected
        assert inc.type == "wrong_amount"
        assert any(e["status"] == "TYPE_CHANGED" for e in inc.timeline)
```

**T3 – `amount=None` produces `unknown`, not a crash (guards R1)**
```python
def test_missing_amount_yields_unknown(database):
    # Build a NormalizedEntity with attributes.amount = None
    # Call evaluate(); assert outcome == "unknown"
    # Call run_demo with a connector returning that entity; assert status == "UNKNOWN"
```

**T4 – Incomplete snapshot does not produce HEALTHY (guards R2)**
```python
def test_incomplete_snapshot_is_unknown(database):
    # Monkey-patch connector.metrics to return {"complete": False}
    # Call run_demo; assert result["status"] == "UNKNOWN"
    # Assert no incidents were created or resolved
```

---

### FALSE POSITIVES TO REJECT

- **"The `session.begin()` + `ExitStack` pattern is over-engineered."** It is the correct way to guarantee that the advisory lock, connector cleanup, and DB transaction all share a single scope. Removing either `ExitStack` or `session.begin()` would leak a lock or leave a dangling transaction on the error path.

- **"The `fingerprint` should not include `organization_id` and `integration_id` because they're constant."** They are constant *in this demo*, but the function is a general-purpose dedup key. Removing them would break correctness if the code is ever reused across orgs. Keep them.

- **"The `risk_total` `max` per source is wrong; it should sum."** It is correct. Two active incidents for the same deal (e.g., a stale `missing_target` and a new `wrong_amount` during a transition) represent the *same* at-risk amount, not additive risk. Summing would double-count.

- **"The 409 on PATCH to a RESOLVED incident is a bug."** It is the correct HTTP semantics: a RESOLVED incident is in a terminal state; re-opening it is an explicit REOPENED action (which the code does internally), not a generic status patch. The API correctly rejects the ambiguous request.
