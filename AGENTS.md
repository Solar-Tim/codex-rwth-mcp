# Codex RWTH MCP Usage

Use the `codex_rwth` MCP server for high-volume preprocessing when available.

- Use `deep_debug_loop` for long logs, CI failures, traces, or repeated debugging evidence.
- Use `deep_diff_review` for large diffs or PR patches before detailed review.
- Use `repo_map_loop` for architecture, ownership, or relevant-file mapping from file trees and selected files.
- Treat deep-loop tools as bounded LangGraph/KiConnect analysis loops, not autonomous coding agents.
- Use one-shot tools only for small summaries: `summarize_logs`, `summarize_repo`, `summarize_diff`, and `analyze_screenshot`.
- If a deep-loop tool returns `status: "needs_codex_input"`, gather the requested files, logs, or command output and call the tool again.
- Keep code edits, shell commands, test execution, architectural decisions, and final reasoning in Codex.
- Do not send secrets, private keys, credentials, personal data, or unrelated private files to RWTH/KiConnect.
