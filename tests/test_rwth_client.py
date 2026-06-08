import pytest

from codex_rwth_mcp.config import ModelConfig, RwthConfig
from codex_rwth_mcp.rwth_client import RwthClient


class FakeChoice:
    def __init__(self, content: str):
        self.message = type("Message", (), {"content": content})


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse("summary text")


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


@pytest.mark.asyncio
async def test_text_completion_uses_openai_compatible_chat_payload():
    fake = FakeClient()
    client = RwthClient(RwthConfig(base_url="https://api.rwth.example/v1"), async_client=fake)

    result = await client.complete_text(
        model=ModelConfig(id="rwth-small"),
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=500,
        temperature=0.1,
    )

    call = fake.chat.completions.calls[0]
    assert result == "summary text"
    assert call["model"] == "rwth-small"
    assert call["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert call["max_tokens"] == 500
    assert call["temperature"] == 0.1


@pytest.mark.asyncio
async def test_vision_completion_sends_data_url_image_content():
    fake = FakeClient()
    client = RwthClient(RwthConfig(base_url="https://api.rwth.example/v1"), async_client=fake)

    await client.complete_vision(
        model=ModelConfig(id="rwth-vision", supports_vision=True),
        system_prompt="system",
        user_prompt="inspect this",
        image_base64="abc123",
        mime_type="image/png",
        max_output_tokens=700,
        temperature=0.0,
    )

    call = fake.chat.completions.calls[0]
    content = call["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "inspect this"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,abc123"
