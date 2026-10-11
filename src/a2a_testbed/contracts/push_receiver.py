# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Webhook receiver for the push-notification contracts.

``transport.push_fires_on_completion`` registers a push config pointing
at a receiver we control, drives a task to completion, then reads the
receiver to see whether the webhook arrived. The receiver speaks a tiny
protocol shared with the hosted one at ``push.a2a-testbed.com``:

- ``POST /webhook/<token>`` — record one delivery
- ``GET  /received/<token>`` — ``{"hooks": [{"body": ..., "headers": ...}]}``

Which receiver a sweep uses (``resolve_push_receiver``):

- ``local``  — start this receiver in-process on 127.0.0.1. Right for an
  agent running on the same machine (a CI job that starts the agent and
  then sweeps it): no external service, no internet access needed.
- ``hosted`` — the public receiver at ``push.a2a-testbed.com``. Needed
  for a remote agent, which cannot reach a loopback address.
- ``off``    — skip push delivery.
- any URL   — a receiver you run yourself (same two routes).
- ``auto``   — ``local`` when the agent is on this machine (a loopback
  host), ``hosted`` otherwise.

The ``A2A_TESTBED_PUSH_RECEIVER`` environment variable is what the
contracts read; ``local_push_receiver`` and the CLI set it for the
duration of a sweep.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import socket
from collections.abc import AsyncIterator, Iterator
from typing import Any, Optional
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

PUSH_RECEIVER_ENV = "A2A_TESTBED_PUSH_RECEIVER"
HOSTED_PUSH_RECEIVER = "https://push.a2a-testbed.com"
# Sentinel value of ``PUSH_RECEIVER_ENV`` that disables push delivery.
PUSH_RECEIVER_OFF = "off"

RECEIVER_MODES = ("auto", "local", "hosted", "off")


def build_push_receiver() -> Starlette:
    """An in-memory receiver app: captures webhooks per token."""
    received: dict[str, list[dict[str, Any]]] = {}

    async def webhook(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        body = (await request.body()).decode("utf-8", "replace")
        received.setdefault(token, []).append({"body": body, "headers": dict(request.headers)})
        return JSONResponse({"ok": True})

    async def read(request: Request) -> JSONResponse:
        token = request.path_params["token"]
        return JSONResponse({"token": token, "hooks": received.get(token, [])})

    return Starlette(
        routes=[
            Route("/webhook/{token}", webhook, methods=["POST"]),
            Route("/received/{token}", read, methods=["GET"]),
        ]
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def serve_push_receiver(host: str = "127.0.0.1") -> AsyncIterator[str]:
    """Run a receiver on an ephemeral port; yield its base URL."""
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(build_push_receiver(), host=host, port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.025)
    if not server.started:  # pragma: no cover - defensive
        server.should_exit = True
        raise RuntimeError("local push receiver failed to start")
    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await task


@contextlib.contextmanager
def push_receiver_env(value: Optional[str]) -> Iterator[None]:
    """Point the contracts at ``value`` for the duration of the block."""
    previous = os.environ.get(PUSH_RECEIVER_ENV)
    if value is None:
        os.environ.pop(PUSH_RECEIVER_ENV, None)
    else:
        os.environ[PUSH_RECEIVER_ENV] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(PUSH_RECEIVER_ENV, None)
        else:
            os.environ[PUSH_RECEIVER_ENV] = previous


def is_loopback_agent(agent_url: str) -> bool:
    """True when the agent runs on this machine, so it can reach a
    receiver bound to 127.0.0.1. A private-network address on another
    host could not, so only loopback counts."""
    host = (urlparse(agent_url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_push_receiver(choice: str, agent_url: str) -> str:
    """Map a ``--push-receiver`` choice to ``local`` / ``off`` / a URL.

    ``auto`` defers to ``A2A_TESTBED_PUSH_RECEIVER`` when it is set, so
    an explicit environment keeps working unchanged.
    """
    choice = choice.strip()
    lowered = choice.lower()
    if lowered == "auto":
        env = os.environ.get(PUSH_RECEIVER_ENV)
        if env:
            return PUSH_RECEIVER_OFF if env.strip().lower() == PUSH_RECEIVER_OFF else env
        return "local" if is_loopback_agent(agent_url) else HOSTED_PUSH_RECEIVER
    if lowered == "hosted":
        return HOSTED_PUSH_RECEIVER
    if lowered in ("local", PUSH_RECEIVER_OFF):
        return lowered
    parsed = urlparse(choice)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return choice
    raise ValueError(
        f"--push-receiver must be one of {', '.join(RECEIVER_MODES)} or an http(s) URL; "
        f"got {choice!r}"
    )


@contextlib.asynccontextmanager
async def push_receiver_for(resolved: str) -> AsyncIterator[str]:
    """Activate a resolved receiver for a sweep; yield a display label."""
    if resolved == "local":
        async with serve_push_receiver() as url:
            with push_receiver_env(url):
                yield f"local ({url})"
        return
    with push_receiver_env(resolved):
        yield "off" if resolved == PUSH_RECEIVER_OFF else resolved
