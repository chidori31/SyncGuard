# Code Review: Deterministic Integration Rule Engine

## CRITICAL ISSUES

### 1. `str(None)` produces the literal string `"None"` in normalization

Three sites are affected:

```python
# normalize_bitrix
customer_id = str(raw["CONTACT_ID"])  # None → "None"

# normalize_1c
external_reference = str(raw["CRMDealID"])  # None → "None"
customer_id = str(raw["Customer"])  # None → "None"
```

When the upstream system omits or nulls these fields, the result is the four-character string `"None"`, not `None`. Consequences:

- `external_reference="None"` will **never** match a real `source.external_id`, so the target is silently dropped from `matches`. A 1C order with a missing CRM link is invisible to the rule engine—no `missing_target`, no `unknown`, just a false `healthy_match` on the remaining targets or a `pending`/`missing_target` that misattributes the cause.
- `customer_id="None"` pollutes any downstream grouping or reporting.

The fix is to guard with `str(raw["CRMDealID"]) if raw.get("CRMDealID") is not None else None` (or let the model's `str | None` type handle it directly).

---

### 2. No validation that `status_changed_at` is not before `created_at`

```python
started = source.attributes.status_changed_at
if started is None or started > now or source.created_at > now or source.updated_at > now:
    return Evaluation(outcome="unknown", ...)
deadline = started + timedelta(seconds=rule.maximum_delay)
```

If the upstream feed delivers `WON_AT` earlier than `DATE_CREATE` (clock skew, manual edit, data migration), `started < source.created_at`. The code accepts this, computes a deadline that may already be in the past relative to the entity's own creation, and immediately reports `missing_target` or `synchronization_delay` on data that is internally inconsistent. The correct behaviour is to return `unknown` with an explanation that the timestamps are contradictory.

---

### 3. Synchronization-delay check ignores `target.updated_at`

```python
if target.created_at > deadline:
    return Evaluation(outcome="synchronization_delay", ...)
```

Only `created_at` is compared to `deadline`. If the order was created *before* the deadline but the amount/currency was corrected *after* the deadline (i.e., `updated_at > deadline`), the engine reports `healthy_match` even though the correct amount was only in place after the SLA window. The earlier "future timestamp" guard (`t.updated_at > now`) catches only timestamps beyond *now*, not timestamps between `deadline` and `now`.

Whether this is a bug depends on the business definition of "synchronized," but as written the SLA is only enforced on the *creation* event, not on the *final* state of the record.

---

## RISKS

### 4. `now` parameter is untyped

```python
def evaluate(rule: RuleSpec, source: NormalizedEntity, targets: list[NormalizedEntity], now) -> Evaluation:
```

The runtime guard `now.tzinfo is None or now.utcoffset() is None` is a band-aid. A caller can pass a `date`, an `int`, or a naive `datetime` and get a `ValueError` with a misleading message, or (worse) a `date` object that has no `utcoffset` attribute, raising `AttributeError`. Annotate as `now: AwareDatetime` (or `datetime`) and let pydantic / the type checker enforce it.

### 5. Float-to-`str()` in normalization introduces representation risk

```python
amount = str(raw["OPPORTUNITY"])  # e.g. 0.1+0.2 → "0.30000000000000004"
amount = str(raw["Total"])
```

If the upstream API returns JSON numbers (parsed as Python `float`), `str()` captures the full IEEE-754 representation. `Decimal("0.30000000000000004")` is valid but numerically wrong. The normalization layer should either receive strings from the API or use `Decimal(str(raw[...]))` with explicit rounding, or better, parse the JSON with `parse_float=Decimal`.

### 6. Inconsistent payload for `unknown` outcomes

| Scenario | `deadline` | `matched_ids` |
|---|---|---|
| Source timestamp missing/future | `None` (default) | `[]` (default) |
| Target timestamp in future | set (from `**common`) | populated (from `**common`) |

Both return `outcome="unknown"`, but one carries partial evaluation context and the other does not. A consumer that branches on `outcome == "unknown"` cannot rely on the presence of `deadline` or `matched_ids`.

### 7. `value_at_risk` is `0.00` for `synchronization_delay`

`missing_target` sets `value_at_risk=source.attributes.amount`. `synchronization_delay` leaves it at the default `Decimal("0.00")`. If the business concern is "the order arrived late, so the deal amount was at risk during the gap," the risk is the full amount, not zero. If the intent is "no financial loss, just a process warning," the `WARNING` severity is consistent but the field is misleading. Pick one and document it.

### 8. `normalize_1c` never sets `status` or `status_changed_at`

Both default to `""` and `None` respectively. This is harmless today because 1C entities are always targets, but if a future rule uses `source_entity_type="customer_order"` the engine will always return `unknown` (missing `status_changed_at`) with no diagnostic about *why*.

---

## SUGGESTIONS

- **Match-key asymmetry**: the source is matched by `source.external_id` (entity-level field) while the target is matched by `t.attributes.external_reference` (attribute-level field). This works but is fragile. Consider a single `external_id` on both sides and a separate `attributes.crm_deal_id` for the cross-reference, so the match predicate reads `t.external_id == source.external_id` or `t.attributes.crm_deal_id == source.external_id` unambiguously.

- **`RuleSpec.source_condition` is `dict[str, str]`**: the comparison is `getattr(source.attributes, key, None) != value`. If the condition key is `"amount"`, the value is compared as a string (`"1000.00"`) against a `Decimal`, which is always `!=`. The condition dict should be typed or the comparison should coerce. As written, only string-typed attributes (`status`, `currency`) work correctly.

- **`frozen=True` on `Attributes` and `NormalizedEntity`** is good. Consider also adding `model_config = ConfigDict(frozen=True, extra="forbid")` to `Attributes` so a typo in a field name in the normalization layer fails loudly instead of being silently ignored.

- The `violation` property is a simple set membership. Fine. But note it excludes `unknown`, which is correct, and excludes `pending`, which is also correct. No issue here, just confirming.

---

## TESTS

Each test below targets a specific bug or risk above.

```text
1.  str(None) in normalization
    - normalize_1c({"Ref_Key":[REDACTED],"Date":..., "UpdatedAt":...,
                    "Total":"100","Currency":"RUB","Customer":None,
                    "CRMDealID":None})
    → assert entity.attributes.external_reference is None  (not "None")
    → assert entity.attributes.customer_id is None

2.  status_changed_at < created_at
    - Build source with created_at=2024-06-15T10:00Z,
      status_changed_at=2024-06-15T09:00Z (one hour BEFORE creation).
    - now = 2024-06-15T12:00Z, no targets.
    → assert outcome == "unknown"
    → assert "contradictory" in explanation (or similar)

3.  target.updated_at > deadline but target.created_at < deadline
    - deadline = started + 300s = 10:05
    - target.created_at = 10:03 (before deadline)
    - target.updated_at  = 10:08 (after deadline)
    - amounts match.
    → assert outcome is NOT "healthy_match"
      (expected: "synchronization_delay" or a new "late_update" outcome)

4.  Float representation in normalization
    - normalize_bitrix with OPPORTUNITY = 0.30000000000000004 (float)
    → assert entity.attributes.amount == Decimal("0.30")  (after rounding)
      or that the test documents the expected loss of precision.

5.  source_condition with non-string attribute
    - rule.source_condition = {"amount": "1000.00"}
    - source.attributes.amount = Decimal("1000.00")
    → assert outcome != "not_applicable"
      (currently fails: str "1000.00" != Decimal("1000.00"))

6.  unknown outcome payload consistency
    - Case A: source.status_changed_at = None → outcome "unknown"
    - Case B: target.created_at = now + 1h → outcome "unknown"
    → assert both have the same set of populated fields
      (or document the intentional difference)

7.  value_at_risk for synchronization_delay
    - Single match, amount matches, target.created_at > deadline.
    → assert value_at_risk == source.attributes.amount
      (or document that 0.00 is intentional)

8.  Currency mismatch with zero amount
    - source.amount = 0, source.currency = "RUB"
    - target.amount = 0, target.currency = "USD"
    → assert outcome == "wrong_amount"
    → assert value_at_risk == Decimal("0.00")  (no financial risk at zero)

9.  Duplicate targets with differing amounts
    - Two matches: one correct amount, one wrong amount.
    → assert outcome == "duplicate_target"
    → assert value_at_risk == source.attributes.amount
    → (document that the wrong-amount detail is subsumed)

10. now as naive datetime
    - evaluate(rule, source, targets, datetime(2024,1,1,12,0,0))  # no tz
    → assert raises ValueError with clear message
    - evaluate(rule, source, targets, date(2024,1,1))
    → assert raises (not AttributeError)
```

Tests 1, 2, 3, and 5 will fail against the current code and represent the highest-priority fixes. Tests 4, 6, 7, and 10 are lower severity but will cause production confusion.
