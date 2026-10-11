"""A tiny MCP server (stdio, MCP SDK 2.x) for testing extension checks.

    python tests/oracles/fake_mcp_server.py

Tools:

- ``check``   — answers ``{"ok": <args.ok>}`` (default true): the
  ``ok`` / ``violation`` paths.
- ``reject``  — answers with ``is_error``: the ``rejected`` path.
- ``garbage`` — answers plain text: a malformed response.
- ``echo``    — answers ``{"ok": true, "args": <arguments>}``.
- ``not_a_verdict`` — answers ``{"ok": null}``: malformed.
- ``env``     — answers ``{"ok": true, "value": <os.environ[args.name]>}``.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.lowlevel.server import ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

_SCHEMA = {"type": "object", "additionalProperties": True}
TOOLS = ("check", "reject", "garbage", "echo", "not_a_verdict", "env")


async def _list_tools(
    ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(
        tools=[Tool(name=name, description=name, input_schema=_SCHEMA) for name in TOOLS]
    )


def _text(text: str, *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=error)


async def _call_tool(
    ctx: ServerRequestContext[Any], params: CallToolRequestParams
) -> CallToolResult:
    args = params.arguments or {}
    if params.name == "check":
        return _text(json.dumps({"ok": bool(args.get("ok", True)), "reason": args.get("reason")}))
    if params.name == "reject":
        return _text("invalid contract: missing field", error=True)
    if params.name == "garbage":
        return _text("this is not json")
    if params.name == "not_a_verdict":
        return _text(json.dumps({"ok": None, "error": "internal"}))
    if params.name == "env":
        return _text(json.dumps({"ok": True, "value": os.environ.get(str(args.get("name")))}))
    if params.name == "echo":
        return _text(json.dumps({"ok": True, "args": args}))
    return _text(f"unknown tool {params.name!r}", error=True)


async def _run() -> None:
    server = Server(
        "fake-extension", version="0.0.1", on_list_tools=_list_tools, on_call_tool=_call_tool
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_run())
