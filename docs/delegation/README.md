# Qwen implementation delegation — 2026-09-12

The user requested actual implementation work delegated to Qwen, with a generous token budget. `tools/ai_helper.py` called Groq's `qwen/qwen3.8-27b`; three successful responses supplied Python code and tests. Codex integrated and corrected those drafts. Qwen did not execute tests or access the repository.

## Transmission boundary

Automatic approval review rejected the initial attempt to transmit an existing scanner source file. That request did not execute. Explicit confirmation for source transmission is still pending. The approved alternative sent newly written, generic standalone task specifications only: no project files, environment, customer data or logs. The credential was used for API authentication in the process environment, never in the prompt or repository.

## QWEN RECOMMENDATIONS ACCEPTED

| Delegated deliverable | Integrated source | Independent validation |
|---|---|---|
| NUL-delimited Git index/tree scanner, blob reads, safe diagnostics, temporary Git tests | `tools/check_secrets.py` | Staged credential remains detected after the working copy is cleaned; commit selection, conflicts, symlinks and environment paths checked |
| Deterministic in-memory ZIP with sorted entries and SHA-256 manifest | `tools/release_archive.py` | ZIP is opened independently; hashes, deterministic bytes and unsafe path rejection checked |
| Git-ref release CLI, exclusive output creation, checksum sidecar, ZIP inspection tests | `tools/build_release.py` | Exact committed content, full tree from subdirectory, environment exclusion, output preservation and injected disk-write failures checked |

The corresponding `*-draft.md` files preserve sanitized model responses as provenance. They are untrusted historical drafts and can contain invalid examples; use the tested source modules. Sanitization damaged some expressions in the returned code. Those expressions were restored from the task contract, and synthetic PEM headers in the archived prose were removed to avoid false positives in the source scanner.

## QWEN RECOMMENDATIONS REJECTED / CORRECTED

- The scanner draft silently skipped forbidden files, symlinks and unmerged stages. Its test draft incorrectly asserted clean results for some of them. Codex changed these to findings, and rejected empty snapshots and partial scans from subdirectories. Six independent assertions failed before the corrections; the final scanner suite passed 15 tests.
- The ZIP draft accepted NUL, Windows-reserved/case-variant paths, file/directory collisions and a commit ID ending in a newline. Eight added cases failed before correction; the resulting archive suite passed 40 tests.
- The CLI draft wrote a string to a binary checksum file. Its first executable test run failed three tests. It also registered created files too late for cleanup after a partial write, and read a partial tree when called from a subdirectory. Codex corrected these, preserved existing outputs, and tested injected write failures; the builder suite passed 11 tests.
- Several test examples expected unprefixed ZIP members, despite the agreed `SyncGuard/` prefix. They were corrected against the actual artifact contract, with manifest content checked independently.

WHY: Model output is a candidate implementation, not evidence that the behavior works. Each accepted module was checked against its requirements with real Git repositories or real ZIP files. The frontend boundary was implemented by Codex and verified against a real local HTTP server.

## Provider failures and helper changes

A broad release-builder prompt exhausted an 8192-token completion budget without useful output. The work was split into archive and CLI tasks using budgets up to 16384 and low reasoning effort; both returned actual code. One medium-effort corrective request returned HTTP 429. These failures are not counted as completed delegation.

The helper now has an `implement` mode asking for code and tests. Empty or length-truncated completions fail without printing a partial artifact. Sanitizer regressions cover quoted replacements and code identifiers such as `sort_keys`; sanitization remains heuristic. Drafts are never executed automatically, and Groq remains absent from application runtime.

## Independent local review

A separate Codex reviewer inspected the changes locally, without external source transmission. It found a sanitizer regression for suffixed credential identifiers and platform-dependent ZIP metadata. Five added sanitizer cases failed before the narrow fix; the helper suite now passes 26 tests. ZIP metadata is explicitly fixed for source entries and manifest; its suite now passes 41 tests. The reviewer independently reran both suites (67 passed) and confirmed identical Windows/Linux platform-switch archive bytes. No remaining findings were reported in that recheck.
