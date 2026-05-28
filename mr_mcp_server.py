"""Massive Rocket MCP server (v1.0.0dj).

Exposes the MR data tools defined in ``mr_tools`` over the Model Context
Protocol (stdio transport), so any MCP client — Claude Desktop, the
Claude CLI, an IDE — can read the pipeline, partner contacts,
stakeholder coverage, quarterly targets and proof-point catalog, and
draft outreach, using the SAME tool definitions the in-app agent uses.

Run it
------
    pip install mcp            # not in requirements.txt — see note below
    python mr_mcp_server.py    # speaks MCP over stdin/stdout

Claude Desktop config (claude_desktop_config.json):
    {
      "mcpServers": {
        "massive-rocket": {
          "command": "python",
          "args": ["/abs/path/to/mr_mcp_server.py"],
          "env": {
            "NOTION_API_KEY": "...",
            "NOTION_DATA_SOURCE_ID": "...",
            "ANTHROPIC_API_KEY": "...",
            "DATABASE_URL_USECASES": "...",
            "MR_MCP_READONLY": "1"
          }
        }
      }
    }

Read-only mode
--------------
Set ``MR_MCP_READONLY=1`` to hide write tools (currently ``log_call``).
Useful when pointing a desktop client at production data — the agent
can read everything but can't mutate the activity store.

Why ``mcp`` isn't in requirements.txt
-------------------------------------
The Flask web service on Railway doesn't need it — only this standalone
process does. Keeping it out of requirements.txt avoids bloating every
web deploy with the MCP SDK + its transitive deps. Install it wherever
you actually run the server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import mr_tools

log = logging.getLogger("mr_mcp_server")


def _readonly() -> bool:
    return os.environ.get("MR_MCP_READONLY", "").strip().lower() in (
        "1", "true", "yes", "on")


def _exposed_tools():
    return mr_tools.all_tools(include_writes=not _readonly())


async def _serve() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError:
        sys.stderr.write(
            "The 'mcp' package is not installed.\n"
            "Install it where you run this server:\n\n"
            "    pip install mcp\n\n"
            "(It is intentionally not in requirements.txt — the Flask web "
            "service doesn't need it.)\n"
        )
        raise SystemExit(2)

    server = Server("massive-rocket")

    @server.list_tools()
    async def list_tools() -> list:  # noqa: ANN001
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in _exposed_tools()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list:  # noqa: ANN001
        # Honour read-only mode at call time too, not just in the list.
        if _readonly():
            t = mr_tools.get_tool(name)
            if t is not None and t.writes:
                payload = {"error": f"{name} is a write tool and this MCP "
                                    f"server is running read-only"}
                return [types.TextContent(
                    type="text", text=json.dumps(payload))]
        result = mr_tools.call_tool(name, arguments or {})
        return [types.TextContent(
            type="text", text=json.dumps(result, default=str, indent=2))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    n_tools = len(_exposed_tools())
    log.info("Massive Rocket MCP server starting — %d tools exposed%s",
             n_tools, " (read-only)" if _readonly() else "")
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
