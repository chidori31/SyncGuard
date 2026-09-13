# MVP release readiness

**Goal:** Finish the existing localhost MVP and make its committed source independently testable and packageable for GitHub.

**Spec:** Existing README and ARCHITECTURE; original MVP requires deterministic detection, evidence, PostgreSQL, React, Compose and passing tests. This continues the user's authorized milestone work. Real-installation onboarding is a separate optional scope question, not silently added here.

**Architecture:** Keep the modular monolith and single synthetic tenant. Add a shared frontend HTTP boundary and release tooling. Qwen receives bounded implementation tasks; Codex checks the actual code and runs tests before integration. Provider responses are untrusted drafts and never executed automatically.

**Global constraints:** Python 3.12; Node 22.18+; Decimal money; timezone-aware timestamps; no customer data, secrets or .env in prompts/Git; no LLM in runtime business logic; no public deployment or push without the destination repository.

## Tasks

- [x] Frontend HTTP boundary. Create `frontend/tests/api.test.mjs` and `frontend/src/api.ts`; migrate the two existing fetch consumers. Exercise real local HTTP responses: valid JSON, 404/409/503, malformed JSON, delayed headers/body, caller cancellation and dropped connection. Use a 60-second default timeout, no mutation retry, safe Russian messages. Run `node --test tests/api.test.mjs`, then TypeScript/Vite build. Verify that the old behavior fails the timeout/error assertions before applying the fix.
- [x] Qwen implementation: staged-source secret scanner. Replace working-file reads in `tools/check_secrets.py` with index/committed blob inspection; reusable `scan_repository(root, ref=None)` returns safe findings. Tests use temporary Git repositories and reproduce a staged credential hidden by a later working-copy edit. Reject forbidden environment files, symlinks and unmerged entries. Source transmission was rejected and remains pending; generic task-only delegation was approved and produced the integrated implementation.
- [x] Qwen implementation: release builder. Add `tools/build_release.py`, using a committed Git ref, the scanner and Python stdlib ZIP/hash primitives. Package only committed blobs into a source ZIP with SHA-256 manifest, refuse existing outputs, and exclude Git metadata/untracked environment files. Tests independently inspect ZIP contents and reproduce secret/unsafe-path refusal. Preserve the user-facing project outside the build output.
- [x] Acceptance and delivery. Run all Python tests with PostgreSQL, frontend HTTP tests/build, Ruff, migrations and actual HTTP acceptance. Build a source release and start a fresh Compose project from that extracted release, on separate local ports/volume. Record observed results, update README/CI, commit and keep the project ready for the user's GitHub destination.

Fresh verification is required before any completion claim. Never turn an unavailable real installation or a refused Groq request into a claimed test success.
