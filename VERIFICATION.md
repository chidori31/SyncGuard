# Verification and review decisions

## Current release — v0.3, 2026-09-12

- Full local Python suite with PostgreSQL: **168 passed**, no database skips, **94.83% backend statement coverage** (90% gate). Two existing dependency deprecation warnings remain.
- Frontend: **10 actual-HTTP tests passed**, TypeScript/Vite production build passed. Errors are localized; the 60-second deadline includes JSON body reads and mutations are not automatically retried.
- Ruff check/format and staged Git-blob credential scan passed.
- Qwen delivered three implementation drafts with tests. Accepted code and corrections are recorded in [docs/delegation/README.md](docs/delegation/README.md). An independent local reviewer confirmed both review fixes; its recheck passed 67 helper/archive tests.
- GitHub CI includes Python/PostgreSQL, frontend tests/build, Compose HTTP acceptance, and a source ZIP artifact job gated on the checks. Remote CI has not run.
- Fresh source ZIP from implementation commit `96cddbae8c8ec25c9b11b7769074eb4dbdc58eb8` was SHA-256/manifest verified and extracted without `.git`, `.env` or installed dependencies. It started a separate Compose project on ports 3300/18000/18100/65432 and a newly created PostgreSQL volume. The API incident list was verified empty before seeding.
- **11 actual-HTTP scenario runs passed from that archive**, through nginx → FastAPI → Bitrix24/1C simulators → fresh PostgreSQL. Recorded evidence: [acceptance-release-http.json](docs/acceptance-release-http.json). Alembic reports no schema drift. Groq SDK is absent from the running backend.
- First archive build hit `spawnSync esbuild ETXTBSY` during npm install in Docker. Repeating the unchanged frontend build succeeded; npm reported 0 vulnerabilities and TypeScript/Vite passed. The subsequent full Compose run reached four healthy services. A similar upstream failure is documented in [esbuild issue 3156](https://github.com/evanw/esbuild/issues/3156); no application change was made on the basis of that report.
- Local history audit at the implementation commit checked 95 reachable Git blobs for Groq/GitHub credential patterns: zero findings. This is a bounded pattern check, not a complete secret or security audit.
- Browser release check: clicking Run completed an HTTP check with three entities and no duplicate incidents. Stopping only the test backend displayed a localized unavailable-service error; starting it and clicking Retry cleared the error. The main localhost:3000 Compose project was rebuilt successfully with its existing database preserved; all four services are healthy and UI shows v0.3.
- The final documentation commit adds this acceptance record only. Runtime and release-tool source are unchanged from the boot-tested implementation commit; final archive manifests are compared during packaging.


## Historical v0.2 verification, 2026-09-12

The records below this section describe the historical v0.1 implementation. They are superseded by this v0.2 verification and [Qwen decision log](docs/reviews/DECISIONS.md).

- Added Bitrix24 crm.item.list and 1C OData read adapters, complete collection checks, bounded retry and strict nextLink handling. Seven synthetic scenarios share memory and HTTP semantics.
- Added CheckRun and nullable run_id on observations; migration 4b9a05587d84 applied to the existing demo PostgreSQL. Initial and new migration upgrade/downgrade/re-upgrade and model consistency pass in a separate schema.
- Full local pytest run with real PostgreSQL: **92 passed**, no database skips, **95% backend statement coverage**. CI gate is 90%. Two dependency deprecation warnings remain in Starlette/AnyIO test tooling.
- Actual-socket acceptance: **11 scenario runs passed**, through nginx → API → Bitrix24/1C HTTP simulators → PostgreSQL. Repeat creates no duplicate incidents; healthy resolves; baseline reopens the same IDs; outage retains two incidents and RUB 194000 exposure. Recorded diagnostics show actual requests, pages and retries in [acceptance-http.json](docs/acceptance-http.json).
- Final v0.2 container rebuild with package constraints passed; all four services are healthy. `alembic check` reports no new upgrade operations. TypeScript/Vite production build and npm install audit pass (0 reported vulnerabilities). The running backend has no Groq SDK installed.
- Browser verification: HTTP scenario controls work; healthy shows all three matched orders, zero open incidents and zero risk; baseline restores the two original incidents. The table displays per-deal outcomes and network page/request metrics.
- Final browser outage check shows UNKNOWN, two retries, incomplete target lookup and the explicit message that previous incidents/risk are preserved. Returned the UI to baseline with two active incidents and RUB 194000 risk. A temporary fetch error during container replacement cleared after reload.
- Five Qwen review responses completed: architecture, rules, HTTP security, test design and orchestration. High-effort empty responses and initial rejection are described in the decision log; no advice was accepted without source/test verification.
- GitHub workflow prepared with PostgreSQL/unit/build and Compose acceptance jobs. Remote CI has not run, because no repository has been pushed yet. A tracked-source secret scan excludes the supplied key and environment files.
- Docker Desktop initially failed on stale Windows runtime sockets. Stopped the failed backend, backed up only the runtime socket directories, and restarted successfully; containers, volumes and existing incident IDs were preserved. Four local services are used: PostgreSQL, backend, frontend, simulator.

Scope: verified against synthetic HTTP contracts, not real 1C/Bitrix24 installations. The actual 1C schema, timezone, reference dictionaries, credential provisioning and production onboarding are still required for installation-specific acceptance. No external business objects are created or updated. This is a working local integration-monitoring MVP, not a production SaaS release.

## Historical v0.1 record

## Milestone 0
Created architecture, plan, working rules, environment template and development-only Groq CLI.
Groq qwen/qwen3.8-27b architecture request succeeded using the supplied key in a process environment (not persisted).

QWEN RECOMMENDATIONS ACCEPTED:
- Transaction-scoped PostgreSQL advisory lock, inside the same transaction as writes.
- Unknown connector results must never become absent or resolve existing incidents.
- Stable external entity identity belongs in the incident fingerprint.

QWEN RECOMMENDATIONS REJECTED:
- No separate occurrence table for the MVP.

WHY: A fingerprint includes tenant, integration, rule, source type, external ID and violation. Reopening updates a durable incident timeline. The single demo tenant is serialized; more granular per-integration locks can follow real connectors.

Environment: Python 3.12 available by explicit path. Docker Desktop started. Port 5432 was already allocated; project PostgreSQL uses loopback port 55432.

## Milestones 1–2: backend and database
- FastAPI launched locally and subsequently in Docker.
- Alembic initial migration applied to real PostgreSQL 17.
- Ten domain tables, foreign keys, tenant-consistent composite references, unique fingerprints and CHECK constraints.
- `/health` reports actual DB readiness; database failure returns sanitized HTTP 503.

## Milestones 3–7: deterministic vertical slice
- Initial normalization/engine suite: 15 tests passed.
- Initial backend, API, lifecycle, concurrency and helper suite: 40 tests passed.
- Live API first run: 3 entities, 2 incidents, BROKEN.
- #5821: CRITICAL missing_target, RUB 184000.
- #5822: healthy_match.
- #5823: WARNING wrong_amount, RUB 10000 difference at risk.
- Second and later live API runs: zero newly created incidents.
- Database tests cover four simultaneous first runs, rollback, resolved→reopened lifecycle, unknown connector data, invalid statuses/negative risk and cross-tenant foreign keys.

## Milestones 8–10: UI, Docker and regression
- `npm run build`: TypeScript check and Vite production build passed on Windows and inside Docker.
- `docker compose up -d --build`: PostgreSQL, FastAPI and nginx/React running and healthy. Loopback ports 55432, 8000 and 3000.
- Backend and frontend containers recreated successfully; existing incident IDs and evidence persisted in PostgreSQL.
- Frontend proxy checks: `/health` returns ready, `/openapi.json` returns 200, `/api/demo/run` returns BROKEN / 3 entities / 0 duplicates.
- Real browser: dashboard, demo button, #5821 evidence, acknowledgement and timeline, incident search/status filter; no captured JavaScript warnings/errors.
- Verified final build after reload. A search in Incidents does not filter the dashboard's recent incidents.
- UI acknowledgement test leaves #5821 ACKNOWLEDGED; active incident count remains 2 and risk remains RUB 194000.
- Final pytest run with TEST_DATABASE_URL: **45 passed**, no skipped database tests. **97% total statement coverage** across backend and helper; rule engine 98%, service orchestration 99%, API 97%.
- Two dependency deprecation warnings from Starlette TestClient/httpx and AnyIO; no failed assertions.
- `alembic check`: no new upgrade operations detected.
- Ruff check/format completed; TypeScript/CSS formatted with Prettier.
- `npm audit` (including development dependencies): 0 reported vulnerabilities at verification time.

## Milestone 11: independent review boundary and self-review
Groq architecture review succeeded (see accepted recommendations above).
Automatic approval review rejected the later attempt to send the explicitly selected rules.py/services.py source files to Groq, citing lack of recognized authorization for this particular private source payload and external destination. That source-review request was not executed and was not retried by another route. Consequently, **external source/security review is not claimed complete**.

Codex completed local source/security review and verified corrections:
- Serialize API money as decimal strings instead of float conversion.
- Missing/future timestamps yield unknown; a pending result never resolves an active incident.
- Fully inapplicable observations do not invent a successful synchronization timestamp.
- Mock anchor fallback tolerates a previously stored missing event timestamp.
- Health endpoint and provider error responses do not return private exception bodies.
- Sanitizer also removes HTTP URLs containing credentials and handles Groq response-validation failures.
- Dashboard's recent incident table is independent of the incident search filter.

No Qwen recommendations were invented for the blocked source review. Local tests and source inspection supplied the second-stage verification.

## Milestone 12: delivery
Russian README documents startup, demo, API, tests, architecture, Groq CLI, configuration and explicit MVP limits. Archive excludes .env, credentials, caches, node_modules, dist and local environments. The supplied Groq key was used only in the environment of the authorized architecture request and was not saved in project files.

Scope limits: localhost single demo tenant, no authentication or automatic scheduler, no real connectors, RUB risk aggregation, last 100 incidents in UI / last 50 evidence in details, no retention job. This is a functioning mock MVP, not a production SaaS release.
