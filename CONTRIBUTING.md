# Contributing

Contributions are welcome when they keep the project focused: a local MCP
deep-loop companion for Codex that can use configured OpenAI-compatible worker
models.

## Development Setup

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

## Contribution Guidelines

- Keep tool behavior deterministic and testable without live provider calls.
- Do not commit API keys, screenshots containing secrets, raw logs, or private
  code from third-party projects.
- Add or update tests for routing, config validation, client payloads, and tool
  service behavior.
- Keep new tools behind explicit MCP interfaces. Codex should not need to know
  route or model-selection details.
- Prefer config additions over hard-coded model choices.
- Document any new provider or model capability with a source link.

## Pull Request Checklist

- [ ] Tests pass with `python -m pytest -q`.
- [ ] Public examples contain no secrets.
- [ ] Documentation explains new user-facing behavior.
- [ ] New models or endpoints point to official documentation.
