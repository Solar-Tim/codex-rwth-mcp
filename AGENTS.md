# Codex Deep Loop MCP Usage

Use the `codex_deep_loop` MCP server for high-volume preprocessing when
available. Older local configs may still expose the same server as
`codex_rwth`.

- Use `deep_debug_loop` for long logs, CI failures, traces, or repeated debugging evidence.
- Use `deep_diff_review` for large diffs or PR patches before detailed review.
- Use `repo_map_loop` for architecture, ownership, or relevant-file mapping from file trees and selected files.
- Use `deep_repo_review_loop` for broad repo risk scans and ownership/relevance review.
- Use `deep_test_strategy_loop` to turn diffs, failures, and selected files into focused test plans.
- Use `deep_architecture_critic` for design tradeoffs, coupling risks, and architectural objections.
- Use `external_repo_scan_loop` only for read-only inspiration from public GitHub repositories; never execute external code.
- Use `coding_task_loop` only for supervised patch drafts. Codex must inspect, apply or rewrite the patch, run tests, and make the final call.
- Use `usage_report` to inspect local redaction-safe MCP call, cache, and token/character accounting.
- Prefer default `analysis_depth: "deep"` when quality matters. Use `fast` or `standard` only when latency or call budget matters more than coverage; use `exhaustive` for large, high-value investigations.
- Treat deep-loop tools as bounded LangGraph/provider analysis loops, not autonomous coding agents.
- Use one-shot tools only for small summaries: `summarize_logs`, `summarize_repo`, `summarize_diff`, and `analyze_screenshot`.
- If a deep-loop tool returns `status: "needs_codex_input"`, gather the requested files, logs, or command output and call the tool again.
- Keep code edits, shell commands, test execution, architectural decisions, and final reasoning in Codex.
- Do not send secrets, private keys, credentials, personal data, or unrelated private files to the configured provider.
