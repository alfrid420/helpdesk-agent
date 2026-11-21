"""Ollama LLM client — uses a ReAct TOOL:/ARGS: protocol because small local models
(mistral, llama3.2) do not reliably use the structured tool-use API."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from .base import LLMResponse, Message, ToolCall, ToolSpec


# ---------------------------------------------------------------------------
# Tool-call prompt helpers
# ---------------------------------------------------------------------------

def _build_tool_system(system: str, tools: list[ToolSpec]) -> str:
    lines = [
        "You have access to these tools.",
        "To call a tool write EXACTLY these two lines and nothing else:",
        "TOOL: tool_name",
        'ARGS: {"param": "value"}',
        "",
        "Available tools:",
    ]
    for t in tools:
        props = list(t.input_schema.get("properties", {}).keys())
        lines.append(f"  {t.name}  params={props}  — {t.description}")
    lines += [
        "",
        "Rules:",
        '  - employee_id must look like E003 and go inside ARGS JSON: {"employee_id": "E003"}',
        "  - If no tool is needed, answer in plain text.",
        "  - Output ONE tool call OR a plain-text answer. Never both.",
        "",
        "Example of a correct tool call:",
        "TOOL: get_leave_balance",
        'ARGS: {"employee_id": "E003"}',
    ]
    return system + "\n\n" + "\n".join(lines)


def _parse_tool_call(text: str, tools: list[ToolSpec]) -> list[ToolCall] | None:
    allowed = {t.name for t in tools}

    # Pattern 1: TOOL: name\nARGS: {...}
    m = re.search(r"TOOL:\s*(\w+)\s*\nARGS:\s*(\{[^}]+\})", text, re.S)
    if m:
        name = m.group(1).strip()
        if name in allowed:
            try:
                args = json.loads(m.group(2))
                return [ToolCall(id=f"call_{name}", name=name, arguments=args)]
            except json.JSONDecodeError:
                pass

    # Pattern 2: {"tool": "name", "args": {...}}  — older prompt format
    m2 = re.search(r'\{"tool":\s*"(\w+)",\s*"args":\s*(\{[^}]+\})\}', text)
    if m2:
        name = m2.group(1).strip()
        if name in allowed:
            try:
                args = json.loads(m2.group(2))
                return [ToolCall(id=f"call_{name}", name=name, arguments=args)]
            except json.JSONDecodeError:
                pass

    # Pattern 3: TOOL: name(E003)  — model puts id in parens instead of JSON
    m3 = re.search(r"TOOL:\s*(\w+)\s*\(([A-Z]\d{3})\)", text)
    if m3:
        name = m3.group(1).strip()
        emp_id = m3.group(2).strip()
        if name in allowed:
            return [ToolCall(id=f"call_{name}", name=name, arguments={"employee_id": emp_id})]

    return None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OllamaClient:
    def __init__(
        self,
        model: str = "mistral",
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._url = base_url

    def _chat(self, system: str, messages: list[dict]) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "system", "content": system}] + messages,
                "stream": False,
                "options": {"temperature": 0.1},
            }
        ).encode()
        req = urllib.request.Request(
            f"{self._url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            return data["message"]["content"]
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._url}. "
                "Make sure Ollama is running (ollama serve)."
            ) from exc

    async def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        # Build the message list Ollama expects
        msgs: list[dict] = []
        for m in messages:
            if m.tool_results:
                for tr in m.tool_results:
                    msgs.append({
                        "role": "user",
                        "content": (
                            f"Tool returned this data:\n{tr.content}\n\n"
                            "Using only this data, answer the user's question "
                            "in plain English. Do not call any more tools."
                        ),
                    })
            elif m.tool_calls:
                for tc in m.tool_calls:
                    msgs.append({
                        "role": "assistant",
                        "content": f"TOOL: {tc.name}\nARGS: {json.dumps(tc.arguments)}",
                    })
            elif m.text:
                msgs.append({"role": m.role, "content": m.text})

        sys_prompt = _build_tool_system(system, tools) if tools else system
        raw = self._chat(sys_prompt, msgs)

        if tools:
            calls = _parse_tool_call(raw, tools)
            if calls:
                return LLMResponse("", calls)

        # Strip any accidental TOOL:/ARGS: lines from plain-text replies
        clean = re.sub(r"TOOL:\s*\w+.*", "", raw, flags=re.S).strip()
        return LLMResponse(clean or raw)
