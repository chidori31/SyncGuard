# Development

Use Python 3.12, Node 22+, Docker Compose v2 and PostgreSQL 17. See README for setup.

Before committing, run `python -m ruff check .`, `python -m ruff format --check .`, the full pytest suite with TEST_DATABASE_URL, and `npm ci && npm run build` inside frontend. Run `python tools/verify_stack.py` after changing connector contracts or orchestration; this changes local demo incidents and restores the baseline scenario at the end.

Database tests create isolated random schemas, including migration upgrade/downgrade tests. Never point tests at a customer database. Schema changes require an Alembic migration and meaningful PostgreSQL verification.

Keep monetary values as Decimal and timestamps timezone-aware. Missing or incomplete upstream reads must remain UNKNOWN; they must not close existing incidents. Do not move AI calls into runtime business logic.

CI uses the documented v7 actions: [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python), [setup-node](https://github.com/actions/setup-node). Package constraints in backend/constraints.txt record the tested environment; update them deliberately and validate on both host and container. Optional platform-specific dependencies may resolve separately.

Qwen reviews selected synthetic source through tools/ai_helper.py. Read AGENTS.md, independently verify suggestions, and record accepted/rejected decisions under docs/reviews. Credentials belong in process environment, never source, prompts, fixtures or Git history.
