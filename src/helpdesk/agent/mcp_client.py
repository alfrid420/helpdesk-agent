"""MCP client: the agent talks to the employee-data server over the real MCP protocol (stdio).
It never imports a DB function directly."""
from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from typing import Any, Protocol

from ..config import Settings
from ..llm.base import ToolSpec


class ToolClient(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class McpToolClient:
    def __init__(
        self,
        command: str,
        args: list[str],
        env: dict[str, str],
        cwd: str | None = None,
    ) -> None:
        self._command, self._args, self._env, self._cwd = command, args, env, cwd
        self._stack: AsyncExitStack | None = None
        self._session: Any = None

    @classmethod
    def for_requester(cls, requester_id: str, settings: Settings) -> "McpToolClient":
        """Spawn the real server as a subprocess whose environment fixes the requester identity.
        The subprocess gets ONLY these variables (plus the MCP SDK's minimal safe defaults such as
        PATH), so API keys and other secrets are not inherited."""
        env = {
            "HELPDESK_REQUESTER_ID": requester_id,
            "READONLY_DATABASE_URL": settings.readonly_database_url,
            "AUDIT_LOG_PATH": settings.audit_log_path,
        }
        return cls(sys.executable, ["-m", "helpdesk.mcp_server.server"], env)

    async def __aenter__(self) -> "McpToolClient":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._command, args=self._args, env=self._env, cwd=self._cwd
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack:
            await self._stack.aclose()

    async def list_tools(self) -> list[ToolSpec]:
        result = await self._session.list_tools()
        return [ToolSpec(t.name, t.description or "", t.inputSchema) for t in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(name, arguments)
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.isError:
            return {"ok": False, "error": "tool_error", "message": text[:300]}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"ok": False, "error": "tool_error", "message": "non-JSON tool output"}
        return data if isinstance(data, dict) else {"ok": False, "error": "tool_error", "message": "bad shape"}
