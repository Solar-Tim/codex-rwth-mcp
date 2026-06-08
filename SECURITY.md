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

Before using this with real projects:

- Confirm you are allowed to send the data to the configured RWTH service.
- Avoid sending secrets, tokens, private keys, credentials, or personal data.
- Use `config/routing.local.yaml` for private routing changes.
- Keep `RWTH_OPENAI_API_KEY` in your environment or secret manager.
- Do not commit `.env`, real config files with secrets, or raw customer data.

The project does not host a shared proxy and does not manage other users' API
keys. Each user runs the server locally with their own credentials.
