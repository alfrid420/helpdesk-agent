"""Anthropic implementation of LLMClient. The SDK is imported lazily so the rest of the
codebase (and the unit tests) work without it installed."""
from __future__ import annotations

from typing import Any

from .base import LLMResponse, Message, ToolCall, ToolSpec


def _to_api(msg: Message) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for result in msg.tool_results:
        blocks.append(
            {
                "type": "tool_result",
                "tool_use_id": result.tool_call_id,
                "content": result.content,
                "is_error": result.is_error,
            }
        )
    if msg.text:
        blocks.append({"type": "text", "text": msg.text})
    for call in msg.tool_calls:
        blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
    if len(blocks) == 1 and blocks[0]["type"] == "text":
        return {"role": msg.role, "content": blocks[0]["text"]}
    return {"role": msg.role, "content": blocks}


class AnthropicClient:
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic  # lazy

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [_to_api(m) for m in messages],
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        resp = await self._client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        return LLMResponse(text=text, tool_calls=calls)
