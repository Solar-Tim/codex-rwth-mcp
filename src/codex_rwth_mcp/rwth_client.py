from __future__ import annotations

import os
from typing import Any, Optional

from .config import ModelConfig, RwthConfig
from .usage import CompletionResult, CompletionUsage


class RwthClient:
    def __init__(self, config: RwthConfig, async_client: Optional[Any] = None):
        self._config = config
        self._client = async_client or self._create_openai_client(config)

    async def complete_text(
        self,
        *,
        model: ModelConfig,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        response = await self._client.chat.completions.create(
            model=model.id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_output_tokens,
            temperature=temperature,
        )
        content = _extract_message(response)
        return CompletionResult(
            content=content,
            usage=CompletionUsage.from_raw(
                getattr(response, "usage", None),
                estimated_input_chars=len(system_prompt) + len(user_prompt),
                estimated_output_chars=len(content),
            ),
        )

    async def complete_vision(
        self,
        *,
        model: ModelConfig,
        system_prompt: str,
        user_prompt: str,
        image_base64: str,
        mime_type: str,
        max_output_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        if not model.supports_vision:
            raise ValueError(f"model {model.id!r} does not support vision")
        response = await self._client.chat.completions.create(
            model=model.id,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            },
                        },
                    ],
                },
            ],
            max_tokens=max_output_tokens,
            temperature=temperature,
        )
        content = _extract_message(response)
        return CompletionResult(
            content=content,
            usage=CompletionUsage.from_raw(
                getattr(response, "usage", None),
                estimated_input_chars=len(system_prompt) + len(user_prompt),
                estimated_output_chars=len(content),
            ),
        )

    @staticmethod
    def _create_openai_client(config: RwthConfig) -> Any:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"{config.api_key_env} is required")

        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for live RWTH API calls"
            ) from exc

        kwargs = {
            "api_key": api_key,
            "base_url": config.base_url,
            "timeout": config.request_timeout_sec,
        }
        if config.organization:
            kwargs["organization"] = config.organization
        return AsyncOpenAI(**kwargs)


def _extract_message(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise RuntimeError("RWTH response did not include chat message content") from exc
    if not content:
        raise RuntimeError("RWTH response content was empty")
    return str(content)
