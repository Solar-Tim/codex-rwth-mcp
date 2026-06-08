# Provider API Sources

This project is designed for OpenAI-compatible chat-completions providers.
RWTH LLM Hosting and KI:connect.nrw are documented here as example providers
used for the initial setup.

## Official Sources

- RWTH IT Center: [Using Large Language Models](https://help.itc.rwth-aachen.de/en/service/5a9d03f1675f4f85ac9b3fd7bb853d44/article/80525f9e55c443af86d2698d0cbed743/)
- RWTH IT Center: [RWTHgpt API access announcement](https://www.itc.rwth-aachen.de/go/id/bndrow?lidx=1#aaaaaaaaabndrpc)
- WestAI: [Large Language Models](https://www.westai.de/services/large-language-models/)
- KiConnect: [Models API reference](https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models)

## What The RWTH Docs State

The RWTH IT Center page documents:

- Access is requested through WestAI.
- API access uses access tokens from the LLM project page.
- The OpenAI-compatible endpoint is available at `https://llm.hpc.itc.rwth-aachen.de/`.
- Port `443` must be reachable.
- API discovery uses `GET /v1/models`.
- Chat usage uses `POST /v1/chat/completions`.
- The OpenAI Python SDK can be configured with `base_url="https://llm.hpc.itc.rwth-aachen.de/"`.

The examples in this repository therefore default to:

```yaml
rwth:
  base_url: https://llm.hpc.itc.rwth-aachen.de
  api_key_env: RWTH_OPENAI_API_KEY
```

## Model IDs

RWTH's available models can change. Do not rely on this repository as the
source of truth for model availability. Query your account's model list:

```bash
curl -H "Authorization: Bearer $RWTH_OPENAI_API_KEY" \
  https://llm.hpc.itc.rwth-aachen.de/v1/models
```

Then copy the exact model IDs into `config/routing.local.yaml` or
`config/routing.yaml`.

For KiConnect API keys, the documented model discovery endpoint is:

```bash
curl -H "Authorization: Bearer $KICONNECT_API_KEY" \
  https://chat.kiconnect.nrw/api/v1/models
```

This is grounded in the KiConnect
[Models API reference](https://chat.kiconnect.nrw/app/api-docs/#tag/models/get/v1models),
which documents Bearer authentication and `GET /v1/models` under the
`https://chat.kiconnect.nrw/api` server. The checked-in
`config/routing.kiconnect.yaml` uses the full OpenAI-compatible base URL
`https://chat.kiconnect.nrw/api/v1`, so the OpenAI SDK appends
`/chat/completions` and the smoke script appends `/models`.

The RWTH IT Center
[RWTHgpt API access announcement](https://www.itc.rwth-aachen.de/go/id/bndrow?lidx=1#aaaaaaaaabndrpc)
states that student API access is available for `gpt-oss-120b`,
`e5-mistral-7b-instruct`, `qwen3-embedding-8b`, and
`mistralai-mistral-small-4-119b`. Those IDs match the KiConnect model list
observed during the live smoke test.

The checked-in routing examples use documented model IDs from RWTH's public
examples where possible. If a model is unavailable for your account, replace it
with one returned by `/v1/models`.

## Important Boundary

This repository is not affiliated with RWTH Aachen University, RWTH IT Center,
WestAI, KI:connect.nrw, or NRW university institutions. It is a
student-maintained MCP server that can connect to OpenAI-compatible providers
when the user already has authorized access and a permitted use case.

KI:connect use is governed by the
[KI:connect terms of use](https://chat.kiconnect.nrw/app/terms-of-use), which
limit use to university-related purposes such as study, teaching, research,
qualification procedures, university administration, and tasks for which the
university is responsible. Configure another compliant provider for private,
commercial, or otherwise non-covered use cases.
