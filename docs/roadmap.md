# Roadmap

## MVP

- Local stdio MCP server for Codex.
- RWTH OpenAI-compatible chat-completions client.
- Config-driven routing by tool, payload size, priority, and model capability.
- Tools for logs, repository excerpts, screenshots, and diffs.
- Public documentation, license, security policy, and CI.

## Near-Term

- Token-aware chunking for large logs and diffs.
- Secret and PII redaction before sending payloads to RWTH.
- Better live startup diagnostics for missing API keys and invalid model IDs.
- Structured JSON summaries with stable fields for Codex handoff.
- Optional `uvx` and `pipx` install examples after the package layout stabilizes.

## Later

- Multi-model analysis inspired by projects such as `religa/multi_mcp`.
- Parallel consensus tools for expensive, high-value uncertainty:
  - `compare_analysis`
  - `review_with_models`
  - `debate_tradeoff`
- Route telemetry and cost accounting.
- Streamable HTTP deployment for teams that want a managed service.

Multi-model tools should stay disabled by default because they increase cost
and are not part of the core preprocessing path.
