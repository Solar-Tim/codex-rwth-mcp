# Security Policy

## Supported Versions

Security fixes are handled on the `main` branch until the project starts
publishing tagged releases.

## Reporting a Vulnerability

Please do not open a public issue for secrets exposure, credential handling
bugs, prompt-injection bypasses, or data-leakage reports.

Report security issues privately through GitHub Security Advisories for this
repository. If that is unavailable, contact the repository maintainer directly.

## Data Handling Expectations

This MCP server sends the content you pass into its tools to the configured
OpenAI-compatible RWTH endpoint. That may include logs, code excerpts, diffs,
screenshots, terminal output, or other sensitive debugging material.

The deep-loop tools can also read explicitly supplied repo-relative file paths.
Those reads are constrained to the server working directory or to named
allowlist entries configured through `repo_roots`. Tool input may select a
configured root by name, but arbitrary absolute paths are rejected. The
implementation blocks path traversal, `.git`, virtual environments, `.env*`,
key material, `config/routing.local.yaml`, binary files, and oversized files.
Skipped files are reported in `safety_notes`.

`coding_task_loop` returns supervised patch drafts for Codex to inspect. It must
not mutate the active checkout, run shell commands, or access live
infrastructure. External repository scans are read-only inspiration paths for
public GitHub repositories; external code must not be executed.

Usage metadata is appended locally to
`~/.cache/codex-rwth-mcp/usage.jsonl` by default. The ledger stores
redaction-safe event metadata such as tool name, model id, cache status, token
counts when available, role, analysis depth, and character estimates. It must
not store prompts, API keys, or raw evidence.

Before using this with real projects:

- Confirm you are allowed to send the data to the configured RWTH service.
- Avoid sending secrets, tokens, private keys, credentials, or personal data.
- Review `file_paths` before passing them to deep-loop tools.
- Review configured `repo_roots` before using multi-repo evidence.
- Use `config/routing.local.yaml` for private routing changes.
- Keep `RWTH_OPENAI_API_KEY` in your environment or secret manager.
- Do not commit `.env`, real config files with secrets, or raw customer data.

The project does not host a shared proxy and does not manage other users' API
keys. Each user runs the server locally with their own credentials.
