# Codex Deep Loop MCP

Local Python MCP server that lets Codex offload high-volume deep-loop analysis
to configured OpenAI-compatible worker models while keeping code edits,
architectural decisions, shell commands, and final reasoning in Codex.

The project is provider-configurable. RWTH LLM Hosting and KI:connect.nrw are
documented example providers because they were used for the initial setup, but
the code is not RWTH-specific.

This project is student-maintained and independent. It is not an official RWTH
Aachen University, RWTH IT Center, WestAI, KI:connect.nrw, or NRW university
service.

## Provider Terms

You are responsible for using a provider, endpoint, API key, and submitted data
under terms that permit your use case. Switching API keys does not change the
terms for a provider. For private, commercial, or non-university use, configure
an OpenAI-compatible provider whose terms allow that use.

KI:connect.nrw use is limited by its own terms and institutional eligibility.
The KI:connect terms state that the service may only be used for study,
teaching, research, qualification procedures, university administration, and
tasks for which the university is responsible, and not for private purposes.
See the [KI:connect terms of use](https://chat.kiconnect.nrw/app/terms-of-use).

## Provider API Sources

Read the relevant provider docs before using the server:

- RWTH IT Center: [Using Large Language Models](https://help.itc.rwth-aachen.de/en/service/5a9d03f1675f4f85ac9b3fd7bb853d44/article/80525f9e55c443af86d2698d0cbed743/)
- RWTH IT Center: [RWTHgpt API access announcement](https://www.itc.rwth-aachen.de/go/id/bndrow?lidx=1#aaaaaaaaabndrpc)
- WestAI: [Large Language Models](https://www.westai.de/services/large-language-models/)
- KiConnect: [Models API reference](https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models)
- KiConnect: [Terms of use](https://chat.kiconnect.nrw/app/terms-of-use)

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
- `deep_debug_loop`: run bounded worker-model map/critic/final debugging passes over logs and selected repo files.
- `deep_diff_review`: chunk and review large diffs with merge and critic passes.
- `repo_map_loop`: map relevant files/components from a question, file tree, and guarded repo file reads.
- `deep_repo_review_loop`: perform broad repo review and risk mapping over guarded evidence.
- `deep_test_strategy_loop`: propose focused test strategy from diffs, failures, and selected files.
- `deep_architecture_critic`: critique architecture decisions, coupling risks, and tradeoffs.
- `external_repo_scan_loop`: scan a public GitHub repo read-only for implementation inspiration.
- `coding_task_loop`: return a supervised implementation plan and unified diff patch draft for Codex to inspect.
- `usage_report`: aggregate local redaction-safe provider call, cache, token, and character metadata.

Codex only sees these tool interfaces. Provider model selection stays hidden
behind `config/routing.yaml`.

## Install

```bash
git clone https://github.com/Solar-Tim/codex-deep-loop-mcp.git
cd codex-deep-loop-mcp
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Configure Provider Access

The default routing files use an `rwth` config key for compatibility with the
first implementation. Treat it as the OpenAI-compatible provider config block.

### RWTH Access

Create an RWTH LLM Hosting token using the official RWTH/WestAI process, then:

```bash
export RWTH_OPENAI_API_KEY="paste-your-token"
export CODEX_DEEP_LOOP_MCP_CONFIG="$PWD/config/routing.yaml"
```

Check which model IDs your account can use:

```bash
curl -H "Authorization: Bearer $RWTH_OPENAI_API_KEY" \
  https://llm.hpc.itc.rwth-aachen.de/v1/models
```

If your available model IDs differ from the examples, copy
`config/routing.example.yaml` to `config/routing.local.yaml`, edit the model
IDs, and set `CODEX_DEEP_LOOP_MCP_CONFIG` to that local file.

### KiConnect Access

For KiConnect API keys, use the KiConnect routing file:

```bash
export KICONNECT_API_KEY="paste-your-token"
export CODEX_DEEP_LOOP_MCP_CONFIG="$PWD/config/routing.kiconnect.yaml"
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

The deep-loop tools reduce Codex context usage by letting configured worker
models perform bounded LangGraph-orchestrated analysis before returning a
compact handoff.
They support `analysis_depth` values of `fast`, `standard`, `deep`, and
`exhaustive`. The default is `deep`, which spends more provider calls for
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

The specialist tools build on the same bounded LangGraph/provider loop:
`deep_repo_review_loop`, `deep_test_strategy_loop`, and
`deep_architecture_critic` are for larger review and design work. In `deep` and
`exhaustive` modes, the internal graph fans out to mapper, risk finder,
test-strategist, and architecture-critic roles, then runs worker-model
synthesizer and critic passes. `coding_task_loop` is the only tool that also
enables a patch-drafter role.
`external_repo_scan_loop` clones or fetches public GitHub repositories only into
cache storage and reads safe text files; it never executes external code.
`coding_task_loop` may draft a unified diff, but it does not edit the active
checkout. Codex must inspect, apply or rewrite the patch, run tests, and make
the final decision.

Usage metadata is recorded locally in
`~/.cache/codex-deep-loop-mcp/usage.jsonl` by default. Results expose aggregate
token counts when the API provides them, character estimates otherwise, and
phase/role-level usage metadata without raw prompts or API keys. Deep-loop
results also include additive judged metadata such as `ranked_findings`,
`evidence_references`, `disagreements`, `confidence`, `verification_hints`,
`analysis_depth`, and `roles_used`. Use `usage_report` to inspect recent usage
by tool or model.

## Add To Codex

```bash
codex mcp add codex_deep_loop \
  --env RWTH_OPENAI_API_KEY="$RWTH_OPENAI_API_KEY" \
  --env CODEX_DEEP_LOOP_MCP_CONFIG="$PWD/config/routing.yaml" \
  -- .venv/bin/python -m codex_rwth_mcp
```

Or copy the example from `examples/codex.config.toml` into your
`~/.codex/config.toml`. The Python module is still `codex_rwth_mcp` for
backward compatibility.

Compatibility aliases from the initial provider-specific name are still
accepted: `CODEX_RWTH_MCP_CONFIG`, `CODEX_RWTH_MCP_CACHE_DIR`,
`CODEX_RWTH_MCP_USAGE_LEDGER`, and the `codex-rwth-mcp` console script.

## Run Locally

```bash
RWTH_OPENAI_API_KEY="$RWTH_OPENAI_API_KEY" \
CODEX_DEEP_LOOP_MCP_CONFIG="$PWD/config/routing.yaml" \
.venv/bin/python -m codex_rwth_mcp
```

For KiConnect:

```bash
KICONNECT_API_KEY="$KICONNECT_API_KEY" \
CODEX_DEEP_LOOP_MCP_CONFIG="$PWD/config/routing.kiconnect.yaml" \
.venv/bin/python -m codex_rwth_mcp
```

## Development

```bash
python -m pytest -q
```

The tests use fake provider clients and do not call the network.

## Security

This server sends supplied logs, code excerpts, diffs, and screenshots to the
configured provider endpoint. Do not send secrets, private keys, credentials,
personal data, or material you are not allowed to process through that service.

See `SECURITY.md` for reporting and data-handling expectations.

## Documentation

- `docs/provider-api.md`: provider API source notes, KiConnect terms boundary, and endpoint details.
- `docs/architecture.md`: architecture diagram, project structure, build plan, security notes, and future work.
- `docs/tool-schemas.json`: MCP-facing tool schemas.
- `docs/roadmap.md`: MVP, near-term, and multi-model roadmap.
- `config/routing.example.yaml`: model-routing configuration.
- `examples/codex.config.toml`: Codex MCP configuration example.
