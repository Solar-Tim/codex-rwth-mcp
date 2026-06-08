# Codex RWTH MCP Preprocessor

Local Python MCP server that lets Codex offload high-volume preprocessing to
RWTH's OpenAI-compatible LLM Hosting API while keeping code edits,
architectural decisions, and final reasoning in Codex.

This project is student-maintained. It is not an official RWTH Aachen
University, RWTH IT Center, or WestAI project.

## Official RWTH API Sources

Read these before using the server:

- RWTH IT Center: [Using Large Language Models](https://help.itc.rwth-aachen.de/en/service/5a9d03f1675f4f85ac9b3fd7bb853d44/article/80525f9e55c443af86d2698d0cbed743/)
- RWTH IT Center: [RWTHgpt API access announcement](https://www.itc.rwth-aachen.de/go/id/bndrow?lidx=1#aaaaaaaaabndrpc)
- WestAI: [Large Language Models](https://www.westai.de/services/large-language-models/)
- KiConnect: [Models API reference](https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models)

The RWTH IT Center docs describe an OpenAI-compatible endpoint at
`https://llm.hpc.itc.rwth-aachen.de/`, access tokens from the LLM project page,
model discovery through `/v1/models`, and chat calls through
`/v1/chat/completions`. The KiConnect API reference documents the same
OpenAI-style model discovery shape under
`https://chat.kiconnect.nrw/api/v1/models`.
The RWTHgpt API access announcement lists the student-accessible models used
by `config/routing.kiconnect.yaml`.

## What It Does

The server exposes thirteen MCP tools to Codex:

- `summarize_logs`: cluster logs, identify likely root causes, and produce a compact debugging summary.
- `summarize_repo`: summarize repository excerpts, architecture, flow, and relevant files.
- `analyze_screenshot`: inspect UI, terminal, browser, dashboard, or devtools screenshots.
- `summarize_diff`: summarize large diffs or PR patches, risks, and affected areas.
- `deep_debug_loop`: run bounded KiConnect map/critic/final debugging passes over logs and selected repo files.
- `deep_diff_review`: chunk and review large diffs with merge and critic passes.
- `repo_map_loop`: map relevant files/components from a question, file tree, and guarded repo file reads.
- `deep_repo_review_loop`: perform broad repo review and risk mapping over guarded evidence.
- `deep_test_strategy_loop`: propose focused test strategy from diffs, failures, and selected files.
- `deep_architecture_critic`: critique architecture decisions, coupling risks, and tradeoffs.
- `external_repo_scan_loop`: scan a public GitHub repo read-only for implementation inspiration.
- `coding_task_loop`: return a supervised implementation plan and unified diff patch draft for Codex to inspect.
- `usage_report`: aggregate local redaction-safe KiConnect call, cache, token, and character metadata.

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

### KiConnect Access

For KiConnect API keys, use the KiConnect routing file:

```bash
export KICONNECT_API_KEY="paste-your-token"
export CODEX_RWTH_MCP_CONFIG="$PWD/config/routing.kiconnect.yaml"
```

The KiConnect API reference documents Bearer authentication and OpenAI-style
endpoints under `https://chat.kiconnect.nrw/api/v1`. Use the
[Models API reference](https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models)
as the source of truth for checking model discovery.

Run a live smoke test:

```bash
.venv/bin/python scripts/live_smoke.py
```

The smoke test checks `/models`, verifies the configured model IDs are
available, constructs the MCP server, and calls `summarize_logs` with a small
synthetic log snippet.

## Deep-Loop Tools

The deep-loop tools reduce Codex context usage by letting KiConnect perform
bounded LangGraph-orchestrated analysis before returning a compact handoff.
They support `analysis_depth` values of `fast`, `standard`, `deep`, and
`exhaustive`. The default is `deep`, which spends more KiConnect calls for
better evidence mining, role fanout, synthesis, and critique. Use `fast` or
`standard` when latency matters more than coverage.

Depth budgets are bounded per invocation: `fast` uses up to 4 live calls,
`standard` up to 8, `deep` up to 16, and `exhaustive` up to 32. Deep-loop tools
may return `status: "needs_codex_input"` with concrete evidence requests for
Codex to gather before calling again.

Deep-loop tools can read repo-relative `file_paths` under the current repo root
or under a named `repo_roots` allowlist entry from the routing config. Tool
inputs may select a configured root by name with `repo_root`; arbitrary absolute
paths are rejected. File reads block `.git`, virtual environments, `.env*`, key
material, `config/routing.local.yaml`, binary files, oversized files, and path
traversal.

The specialist tools build on the same bounded LangGraph/KiConnect loop:
`deep_repo_review_loop`, `deep_test_strategy_loop`, and
`deep_architecture_critic` are for larger review and design work. In `deep` and
`exhaustive` modes, the internal graph fans out to mapper, risk finder,
test-strategist, and architecture-critic roles, then runs RWTH synthesizer and
critic passes. `coding_task_loop` is the only tool that also enables a
patch-drafter role.
`external_repo_scan_loop` clones or fetches public GitHub repositories only into
cache storage and reads safe text files; it never executes external code.
`coding_task_loop` may draft a unified diff, but it does not edit the active
checkout. Codex must inspect, apply or rewrite the patch, run tests, and make
the final decision.

Usage metadata is recorded locally in
`~/.cache/codex-rwth-mcp/usage.jsonl` by default. Results expose aggregate
token counts when the API provides them, character estimates otherwise, and
phase/role-level usage metadata without raw prompts or API keys. Deep-loop
results also include additive judged metadata such as `ranked_findings`,
`evidence_references`, `disagreements`, `confidence`, `verification_hints`,
`analysis_depth`, and `roles_used`. Use `usage_report` to inspect recent usage
by tool or model.

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

For KiConnect:

```bash
KICONNECT_API_KEY="$KICONNECT_API_KEY" \
CODEX_RWTH_MCP_CONFIG="$PWD/config/routing.kiconnect.yaml" \
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
