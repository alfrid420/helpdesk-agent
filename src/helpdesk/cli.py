"""Chat CLI.

  python -m helpdesk.cli --as E003            interactive
  python -m helpdesk.cli --as E003 --ask "..."  one-shot

On Windows, asyncio defaults to ProactorEventLoop which breaks the MCP stdio
subprocess transport.  We switch to SelectorEventLoop before anything starts.
This restores the real MCP server over stdio — no bypass.

How MCP works here (3 lines):
  The agent spawns helpdesk.mcp_server.server as a subprocess.
  It talks to it over stdin/stdout using the MCP JSON-RPC protocol.
  The server enforces authorization and talks to Postgres; the agent never touches the DB directly.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

# --- Windows: switch to SelectorEventLoop so subprocess stdio works with MCP ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg  # noqa: E402  (import after policy is set)

from .agent.agent import AgentReply  # noqa: E402
from .agent.builder import build_agent  # noqa: E402
from .agent.mcp_client import McpToolClient  # noqa: E402
from .config import ConfigError, load_settings  # noqa: E402
from .llm import create_llm  # noqa: E402

_ID = re.compile(r"E\d{3}")


def _print_reply(reply: AgentReply) -> None:
    print(f"\n{reply.text}\n")
    notes = [f"outcome={reply.outcome}", f"route={reply.route}"]
    if reply.block_category:
        notes.append(f"blocked:{reply.block_category}")
    if reply.tools:
        notes.append("tools=" + ",".join(f"{t.name}({t.outcome})" for t in reply.tools))
    if reply.redactions:
        notes.append("redactions=" + ",".join(f"{k}x{v}" for k, v in reply.redactions.items()))
    print("  [" + " | ".join(notes) + "]\n")


async def _run(requester: str, question: str | None) -> int:
    settings = load_settings()
    try:
        llm = create_llm(settings)
    except ConfigError as exc:
        print(f"\nConfiguration error:\n{exc}\n", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(settings.readonly_database_url, connect_timeout=3):
            pass
    except psycopg.OperationalError:
        print(
            "\nCannot reach Postgres.\n"
            "  Run:  docker compose up -d --wait\n"
            "  Then: python -m helpdesk.db.seed\n",
            file=sys.stderr,
        )
        return 2

    async with McpToolClient.for_requester(requester, settings) as tools:
        agent = build_agent(settings, requester, llm, tools)
        if question:
            _print_reply(await agent.ask(question))
            return 0
        print(f"Helpdesk Agent: signed in as {requester}. Type /quit to exit.")
        while True:
            try:
                line = await asyncio.to_thread(input, f"{requester}> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if line.strip() in {"/quit", "/exit"}:
                return 0
            if line.strip():
                _print_reply(await agent.ask(line.strip()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Helpdesk Agent")
    parser.add_argument(
        "--as", dest="requester", default="E003",
        help="authenticated employee id (default E003)",
    )
    parser.add_argument("--ask", help="ask a single question and exit")
    args = parser.parse_args()
    if not _ID.fullmatch(args.requester):
        sys.exit("--as must look like E003")
    sys.exit(asyncio.run(_run(args.requester, args.ask)))


if __name__ == "__main__":
    main()
