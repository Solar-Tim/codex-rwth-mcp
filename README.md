# Codex RWTH MCP Preprocessor

Local Python MCP server that lets Codex offload high-volume preprocessing to
RWTH's OpenAI-compatible LLM Hosting API while keeping code edits,
architectural decisions, and final reasoning in Codex.

This project is student-maintained. It is not an official RWTH Aachen
University, RWTH IT Center, or WestAI project.

## Official RWTH API Sources

Read these before using the server:

- RWTH IT Center: [Using Large Language Models](https://help.itc.rwth-aachen.de/en/service/5a9d03f1675f4f85ac9b3fd7bb853d44/article/80525f9e55c443af86d2698d0cbed743/)
- WestAI: [Large Language Models](https://www.westai.de/services/large-language-models/)

The RWTH IT Center docs describe an OpenAI-compatible endpoint at
`https://llm.hpc.itc.rwth-aachen.de/`, access tokens from the LLM project page,
model discovery through `/v1/models`, and chat calls through
`/v1/chat/completions`.

## What It Does

The server exposes four MCP tools to Codex:

- `summarize_logs`: cluster logs, identify likely root causes, and produce a compact debugging summary.
- `summarize_repo`: summarize repository excerpts, architecture, flow, and relevant files.
- `analyze_screenshot`: inspect UI, terminal, browser, dashboard, or devtools screenshots.
- `summarize_diff`: summarize large diffs or PR patches, risks, and affected areas.

Codex only sees these tool interfaces. RWTH model selection stays hidden behind
`config/routing.yaml`.

## Install

```bash
git clone https://github.com/Solar-Tim/codex-rwth-mcp.git
cd codex-rwth-mcp
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Configure RWTH Access

Create an RWTH LLM Hosting token using the official RWTH/WestAI process, then:

```bash
export RWTH_OPENAI_API_KEY="paste-your-token"
export CODEX_RWTH_MCP_CONFIG="$PWD/config/routing.yaml"
```

Check which model IDs your account can use:

```bash
curl -H "Authorization: Bearer $RWTH_OPENAI_API_KEY" \
  https://llm.hpc.itc.rwth-aachen.de/v1/models
```

If your available model IDs differ from the examples, copy
`config/routing.example.yaml` to `config/routing.local.yaml`, edit the model
IDs, and set `CODEX_RWTH_MCP_CONFIG` to that local file.

## Add To Codex

```bash
codex mcp add codex-rwth \
  --env RWTH_OPENAI_API_KEY="$RWTH_OPENAI_API_KEY" \
  --env CODEX_RWTH_MCP_CONFIG="$PWD/config/routing.yaml" \
  -- .venv/bin/python -m codex_rwth_mcp
```

Or copy the example from `examples/codex.config.toml` into your
`~/.codex/config.toml`.

## Run Locally

```bash
RWTH_OPENAI_API_KEY="$RWTH_OPENAI_API_KEY" \
CODEX_RWTH_MCP_CONFIG="$PWD/config/routing.yaml" \
.venv/bin/python -m codex_rwth_mcp
```

## Development

```bash
python -m pytest -q
```

The tests use fake RWTH clients and do not call the network.

## Security

This server sends supplied logs, code excerpts, diffs, and screenshots to the
configured RWTH endpoint. Do not send secrets, private keys, credentials,
personal data, or material you are not allowed to process through that service.

See `SECURITY.md` for reporting and data-handling expectations.

## Documentation

- `docs/rwth-api.md`: RWTH API source notes and endpoint details.
- `docs/architecture.md`: architecture diagram, project structure, build plan, security notes, and future work.
- `docs/tool-schemas.json`: MCP-facing tool schemas.
- `docs/roadmap.md`: MVP, near-term, and multi-model roadmap.
- `config/routing.example.yaml`: model-routing configuration.
- `examples/codex.config.toml`: Codex MCP configuration example.
