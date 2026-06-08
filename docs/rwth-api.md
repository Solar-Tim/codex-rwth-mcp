# RWTH API Sources

This project is designed for RWTH's OpenAI-compatible LLM Hosting API.

## Official Sources

- RWTH IT Center: [Using Large Language Models](https://help.itc.rwth-aachen.de/en/service/5a9d03f1675f4f85ac9b3fd7bb853d44/article/80525f9e55c443af86d2698d0cbed743/)
- WestAI: [Large Language Models](https://www.westai.de/services/large-language-models/)

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

The checked-in routing examples use documented model IDs from RWTH's public
examples where possible. If a model is unavailable for your account, replace it
with one returned by `/v1/models`.

## Important Boundary

This repository is not affiliated with RWTH Aachen University, RWTH IT Center,
or WestAI. It is a student-maintained MCP server that can connect to RWTH's
OpenAI-compatible API when the user already has authorized access.
