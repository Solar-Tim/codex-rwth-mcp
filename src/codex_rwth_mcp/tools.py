from __future__ import annotations

from typing import Any, Dict

from .config import AppConfig
from .prompts import SYSTEM_PROMPT, diff_prompt, logs_prompt, repo_prompt, screenshot_prompt
from .router import ModelRouter
from .rwth_client import RwthClient


class ToolService:
    def __init__(self, *, config: AppConfig, router: ModelRouter, client: RwthClient):
        self._config = config
        self._router = router
        self._client = client

    async def summarize_logs(self, *, logs: str, context: str = "") -> Dict[str, Any]:
        return await self._complete_text_tool(
            tool_name="summarize_logs",
            payload=logs + context,
            user_prompt=logs_prompt(logs=logs, context=context),
        )

    async def summarize_repo(self, *, files: str, question: str = "") -> Dict[str, Any]:
        return await self._complete_text_tool(
            tool_name="summarize_repo",
            payload=files + question,
            user_prompt=repo_prompt(files=files, question=question),
        )

    async def summarize_diff(self, *, diff: str, context: str = "") -> Dict[str, Any]:
        return await self._complete_text_tool(
            tool_name="summarize_diff",
            payload=diff + context,
            user_prompt=diff_prompt(diff=diff, context=context),
        )

    async def analyze_screenshot(
        self,
        *,
        image_base64: str,
        mime_type: str = "image/png",
        question: str = "",
    ) -> Dict[str, Any]:
        tool_name = "analyze_screenshot"
        decision = self._router.route(
            tool_name=tool_name,
            input_chars=len(image_base64) + len(question),
            needs_vision=True,
        )
        tool_config = self._config.tools[tool_name]
        summary = await self._client.complete_vision(
            model=decision.model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=screenshot_prompt(question=question),
            image_base64=image_base64,
            mime_type=mime_type,
            max_output_tokens=tool_config.max_output_tokens,
            temperature=tool_config.temperature,
        )
        return _tool_result(tool_name=tool_name, model_id=decision.model.id, summary=summary)

    async def _complete_text_tool(
        self, *, tool_name: str, payload: str, user_prompt: str
    ) -> Dict[str, Any]:
        decision = self._router.route(
            tool_name=tool_name,
            input_chars=len(payload),
            needs_vision=False,
        )
        tool_config = self._config.tools[tool_name]
        summary = await self._client.complete_text(
            model=decision.model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=tool_config.max_output_tokens,
            temperature=tool_config.temperature,
        )
        return _tool_result(tool_name=tool_name, model_id=decision.model.id, summary=summary)


def _tool_result(*, tool_name: str, model_id: str, summary: str) -> Dict[str, Any]:
    return {
        "tool": tool_name,
        "model_id": model_id,
        "summary": summary,
    }
