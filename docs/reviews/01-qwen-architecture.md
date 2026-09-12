## Verdict: Sound MVP architecture with two contradictions and one atomicity gap

The modular-monolith split (React → FastAPI → SQLAlchemy → PG) is clean, the pure rule engine is correctly isolated from I/O, and the deployment claims are honest about localhost scope. The main problems are a lock-scoping ambiguity, a healthcheck portability risk, and a doc/compose framing mismatch on the simulator.

---

### CRITICAL ISSUES

**1. Advisory-lock scope is underspecified.**
"Each run obtains a PostgreSQL transaction advisory lock before fixture initialization and evaluation." If this is `pg_advisory_xact_lock`, it releases at COMMIT—fine. If it is `pg_advisory_lock` (session-scoped), the lock must be explicitly released *before* the connection returns to the pool; otherwise the next run on the same pooled connection deadlocks waiting on itself. The docs never state which variant. **Action:** confirm the code uses `pg_advisory_xact_lock` (or an explicit `pg_advisory_unlock` in a `finally`). If it's session-scoped, this is a production-blocking bug the moment the pool reuses a connection.

**2. Frontend healthcheck may not have `wget`.**
The compose healthcheck runs `wget -q --spider http://127.0.0.1/`. If the frontend image is `node:alpine` or a slim nginx build without `wget`, every healthcheck fails, `depends_on: condition: service_healthy` never resolves, and `docker compose up --wait` times out. The `verify` CI job builds the frontend but doesn't run the compose stack, so this would only surface in `http-acceptance`—which hasn't run remotely yet. **Action:** verify the frontend image includes `wget`, or switch to `curl -f` / a TCP check.

---

### RISKS

**3. Simulator framing contradiction.**
Docs: "HTTP contract simulators run in an auxiliary test container, **not a new production service**." Compose: `simulator` is a first-class service with its own healthcheck, built from `./backend`, started by default in `docker compose up`. It is not behind a Docker Compose `profiles` gate. For a localhost MVP this is operationally fine, but the doc language implies it's invisible to the deployment. A reviewer reading the compose file will see a second uvicorn process bound to 8100. **Action:** either add `profiles: ["dev"]` to the simulator service (and to the backend's `depends_on`), or soften the doc to "not a separately deployed production service; it co-locates in the local stack."

**4. Coverage gate at 90 % is fragile for the simulator.**
`--cov=app` includes `app.simulator`. The simulator implements Bitrix24 `crm.item.list` (entityTypeId=2, semantic S), 1C OData with field mapping, pagination, error paths, and the "explicit incomplete metrics rejected" logic. Hitting 90 % on that surface requires substantial simulator tests. The 90 passing tests may already cover this, but the two new regressions could push coverage below the gate if they add uncovered branches. **Action:** run `pytest --cov=app --cov-report=term-missing` locally before pushing; consider `--cov-branch` exclusion for the simulator's error-response factories if they're thin wrappers.

**5. `run_id` NULL on v0.1 observations.**
"Old v0.1 observations may have no run_id." Any query that JOINs `observations → check_runs` to build a timeline or compute "observations since last run" will silently drop legacy rows. The atomicity guarantee ("CheckRun, observations and evidence commit atomically") applies only to new writes. Not a bug, but a query-correctness trap if a future feature aggregates across runs. **Action:** add a comment or a `COALESCE` convention in the repository layer; add a unit test asserting the JOIN handles NULL `run_id`.

**6. No explicit Alembic step in CI.**
CI runs `pytest` but never `alembic upgrade head`. If the test fixture creates the schema via `Base.metadata.create_all` rather than migrations, the CI validates the ORM model but not the migration chain. A migration bug (e.g., a missing `run_id` column added in v0.2) would pass CI and fail on a fresh `docker compose up`. **Action:** add `alembic upgrade head` against the CI Postgres before pytest, or add a dedicated migration test that runs `alembic upgrade base` → `head` on a scratch database.

---

### SUGGESTIONS

**7. HTTP-acceptance job is redundant with `verify` for the frontend build.**
`verify` does `npm ci && npm run build`. `http-acceptance` rebuilds via Docker. If the Dockerfile is correct, both pass; if it's wrong, only `http-acceptance` catches it. This is acceptable, but the two jobs don't share a cache, so a full CI run is ~2× the build time. For an MVP this is fine; just be aware the 15-minute timeout on each job is tight if the Docker build is slow on a cold runner.

**8. `tools/check_secrets.py` vs. compose defaults.**
The compose file uses `${POSTGRES_PASSWORD:[REDACTED]}`. If the literal string `syncguard` appears in the repo, `check_secrets` may flag it depending on its rules. For localhost this is a false positive. **Action:** whitelist localhost-default credentials in the checker or document the exception.

**9. "Disappearing source entities do not automatically resolve incidents."**
This is the correct conservative choice and is stated clearly. No change needed. Just confirm the rule engine's "recovery" path requires a *positive* observation (entity present, amount matches), not the *absence* of an entity. The docs imply this; a one-line test would lock it in.

---

### TESTS TO ADD (before remote CI)

| # | What | Why |
|---|------|-----|
| 1 | Two concurrent `POST /api/demo/run` on the same integration; assert the second blocks (or 409s) and both succeed sequentially. | Validates advisory-lock behaviour end-to-end. |
| 2 | Frontend container: `docker compose run --rm frontend which wget` (or equivalent). | Catches the healthcheck portability issue before remote CI. |
| 3 | Alembic `upgrade base` → `head` on a scratch DB, then `downgrade -1` → `upgrade head`. | Proves migration chain is reversible and matches ORM. |
| 4 | Query the incident timeline with a v0.1 observation (NULL `run_id`) mixed with v0.2 rows. | Confirms no silent data loss in JOINs. |
| 5 | Run `pytest --cov=app --cov-fail-under=90` locally with the two new regression tests. | Catches coverage regression before the 15-min CI window. |

---

**Bottom line:** The architecture is appropriately scoped for a localhost single-org demo. The module boundaries are clean, the atomicity story is correct *if* the advisory lock is transaction-scoped, and the deployment claims are honest. The two items that will actually break remote CI are the `wget` healthcheck and the coverage gate. Fix those, confirm the lock variant, and the stack is ready for its first remote run.
