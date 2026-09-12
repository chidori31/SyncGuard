# Working rules

Codex is the primary developer. Qwen/Groq AI Helper is a second-opinion reviewer.
Use tools/ai_helper.py for significant architecture, complex modules, difficult debugging, security, important tests and milestone reviews. Do not call it for tiny edits. Never blindly copy suggestions or redesign working components without evidence. Validate all advice against source, tests and requirements. Record QWEN RECOMMENDATIONS ACCEPTED, QWEN RECOMMENDATIONS REJECTED and WHY.

The user explicitly requested broad Qwen participation on 2026-09-12 after the initial code-transmission rejection was explained. Use Qwen throughout substantial development stages with a generous completion budget. Select only project source files needed for a review; sanitize before transmission. This authorization does not include secrets, environment files, private customer data or real logs. Record actual reviews and independent decisions under docs/reviews. Codex remains responsible for implementation and verification.

Work milestone by milestone. Run relevant tests, launch what is available, fix issues and report concise progress. Keep domain code independent of API and connectors. Decimal money, UTC timestamps, database constraints and atomic transactions are mandatory. No secrets, customer data, private logs or environment files in prompts or version control. Groq failure cannot break SyncGuard. Use only synthetic context in reviews. Do not add infrastructure beyond this MVP.
