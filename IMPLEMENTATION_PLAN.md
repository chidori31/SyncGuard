# Implementation plan and verification log

0. Architecture, working rules, environment template and safe Groq reviewer.
1. FastAPI, configuration, PostgreSQL, Alembic, Docker and health.
2. Relational domain models and constraints.
3. Normalization and mock connector tests.
4. Deterministic rule engine and boundary tests.
5. Transactional incident lifecycle and deduplication.
6. REST endpoints and API tests.
7. Three required demo cases with stable identities.
8. React dashboard, incident details and evidence.
9. Full Docker Compose startup and healthchecks.
10. Complete regression tests including real PostgreSQL constraints/concurrency.
11. Groq review and independently verified decisions.
12. README and polished demo; record actual verification and limitations.

Each milestone must be tested and runnable to the extent available. Verification outcomes and reviewer decisions are recorded in VERIFICATION.md; an unavailable external provider is recorded honestly.

## Final status
v0.1 milestones are complete. Following the user's request, v0.2 adds read-only Bitrix24 REST and 1C OData adapters, seven scenarios, an HTTP contract simulator, atomic CheckRun history, a scenario UI, migration round-trip testing and actual HTTP acceptance testing. Qwen source reviews succeeded after the user's explicit authorization; accepted and rejected advice is recorded in docs/reviews/DECISIONS.md.

GitHub preparation includes a standalone main branch, CI with PostgreSQL and Compose acceptance jobs, a secret scanner, contribution/security docs and a PR template. Runtime and development package constraints record tested versions; platform-specific optional extras may resolve separately. Remote publication/CI and real-installation acceptance remain future work requiring the target repository and installation configuration.

## Project tree
```text
SyncGuard/
  ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, AGENTS.md
  README.md, VERIFICATION.md
  .env.example, .gitignore, compose.yaml, pyproject.toml
  .github/workflows/ci.yml
  docs/INTEGRATION_CONTRACTS.md, acceptance-http.json, reviews/
  backend/
    Dockerfile, requirements.txt, constraints.txt, alembic.ini
    migrations/env.py, versions/ (initial schema + check runs)
    app/
      main.py, api.py, core.py, db.py, models.py
      normalization.py, rules.py, services.py, scenarios.py, simulator.py
      connectors/base.py, mock_bitrix.py, mock_1c.py, http.py
    tests/ (rules, HTTP contracts, PostgreSQL/API, scenarios, migrations)
  frontend/
    Dockerfile, nginx.conf, package.json, package-lock.json
    vite.config.ts, tsconfig.json, index.html
    src/main.tsx, IntegrationLab.tsx, styles.css
  tools/ai_helper.py, check_secrets.py, verify_stack.py, tests/test_ai_helper.py
  requirements-dev.txt
```
