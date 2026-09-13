# SyncGuard architecture

Modular monolith: React → same-origin /api → FastAPI services → SQLAlchemy → PostgreSQL.
Connectors normalize external data into immutable Pydantic entities. A pure rule engine accepts a rule, normalized source/targets and an explicit UTC clock. It never calls an LLM, HTTP or a database.

## Business semantics
- A WON event starts the deadline; unrelated updates do not reset it.
- Before the five-minute deadline, missing targets are pending (no incident).
- At the deadline, a missing target is CRITICAL; duplicate targets take precedence over amount/delay. Amounts use Decimal, currency must match.
- A matched target created after the deadline is a synchronization_delay WARNING. Healthy means one timely target with the same amount and currency.
- Failed connector reads are unknown observations, never evidence of an absent order. Existing incidents remain open.
- Value at risk is full deal value for missing/duplicate targets, absolute difference for wrong_amount, zero for historical delays. Aggregate metrics count each affected source once (maximum active exposure) per currency. API returns separate currency buckets; demo cards display RUB. No exchange-rate conversion.

## Persistence and concurrency
Organization, User, Connector, Integration, BusinessRule, ExternalEntity, Observation, Incident, IncidentEvidence, Alert and CheckRun are relational tables. Tenant consistency uses composite foreign keys for the integration/rule hierarchy. No authentication or SaaS isolation is claimed: the MVP is a localhost demo for one seeded organization. CheckRun, observations and evidence commit atomically; old v0.1 observations may have no run_id.
Each run obtains a PostgreSQL transaction advisory lock (pg_advisory_xact_lock) before fixture initialization and evaluation. Unique incident fingerprint (organization, rule, source identity, violation) prevents repeated incidents. A resolved fingerprint can reopen with a new timeline entry; history and evidence stay attached. The integration lock serializes runs. Incidents disappear from active risk only after a successful observation proves recovery or rule inapplicability. Changes, observations and evidence commit atomically.

## Boundaries
API handles HTTP; services orchestrate transactions; domain rules contain business decisions. Memory fixtures and read-only HTTP adapters implement the same connector contract. Bitrix24 uses crm.item.list with entityTypeId=2 and semantic success S. 1C reads a configured OData collection with explicit field mapping. HTTP contract simulators run in an auxiliary test container, enabled by default in the local Compose stack; it is not a separately deployed production service. No background scheduler in MVP: each POST /api/demo/run performs a fresh check. No writes to external systems.

Collectors either return a validated complete collection or raise ConnectorError. Explicit incomplete metrics are also rejected at orchestration. Pagination counts, unique external IDs, resource bounds and same-collection nextLink checks prevent accepting known partial results. These checks cannot create a distributed consistent snapshot: data changing during reads can require a later retry. Disappearing source entities do not automatically resolve incidents. A violation-type change creates/reopens a separate fingerprint while retaining the prior incident history; detected_at is an incident timestamp, not the WON/SLA start.

The demo route constructs adapters only for a server-configured simulator URL. Connecting real installations requires a separate configuration/onboarding path, agreed field semantics and credentials; those are not accepted from the public demo body. The HTTP client defaults to HTTPS, disables ambient proxies/redirects, caps pages/bytes/entities/time, retries only transient read failures, and emits safe diagnostics without raw URLs or response bodies.
Alembic owns schema. Production database is PostgreSQL; tests use real PostgreSQL for persistence and pure unit tests for the engine.
Docker exposes frontend and API only on loopback. Groq SDK is installed only in development and tools/ai_helper.py cannot be imported by the backend.

## AI helper
Only explicit synthetic prompts are sent to Groq. No automatic file collection, .env reads or logs. Sanitization redacts recognizable credentials; it cannot identify arbitrary confidential business prose. Never supply real customer data. Bounded SDK retries, timeout and safe errors; unavailability never blocks deterministic application behavior.
