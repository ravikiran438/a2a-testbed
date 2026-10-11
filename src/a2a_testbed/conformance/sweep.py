# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Run a conformance sweep (live agent) or a card lint (file) and return a
``SweepReport``. The CLI and the GitHub Action are thin wrappers over this.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a_testbed.conformance.baseline import Baseline, apply_baseline
from a2a_testbed.conformance.report import SweepReport
from a2a_testbed.contracts.base import DEFAULT_CONTRACT_TIMEOUT_S
from a2a_testbed.contracts.push_receiver import push_receiver_for, resolve_push_receiver
from a2a_testbed.contracts.runner import run_transport_contracts, transport_contracts
from a2a_testbed.transport import A2ATransport

# Contracts that read only the AgentCard — no RPC. ``lint-card`` runs
# these against a card file; well_known_card is left out because it is
# about the HTTP endpoint, which a file does not have.
CARD_CONTRACT_IDS: tuple[str, ...] = (
    "transport.agent_card_required_fields",
    "transport.agent_card_skill_attributes",
    "transport.agent_card_skill_id_unique",
    "transport.agent_card_capabilities_object",
    "transport.agent_card_supported_interfaces",
    "transport.agent_card_preferred_interface",
    "transport.agent_card_url_well_formed",
    "transport.provider_well_formed",
    "transport.default_modes_distinct",
    "transport.extensions_uri_absolute",
    "transport.extensions_uri_unique",
    "transport.signatures_well_formed",
    "transport.agent_card_protocol_version_format",
    "transport.agent_card_https_urls",
    "transport.agent_card_security_schemes",
)

# Card-fetch attempts before declaring the agent unreachable.
_PREFLIGHT_ATTEMPTS = 3


class AgentUnreachable(RuntimeError):
    """The AgentCard endpoint could not be reached at all."""


def _descriptions(transport: A2ATransport, agent_url: str) -> dict[str, str]:
    return {c.id: c.description for c in transport_contracts(transport, agent_url)}


async def preflight(transport: A2ATransport, agent_url: str, *, timeout: float = 10.0) -> None:
    """Make sure *something* answers at the card URL before sweeping.

    A dead URL would otherwise turn into 60-odd identical failures. Any
    HTTP answer (even a 404) counts as reachable: a missing card is a
    real conformance failure the contracts should report.
    """
    url = agent_url.rstrip("/") + transport.card_endpoint_path()
    last: Optional[Exception] = None
    for attempt in range(_PREFLIGHT_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                await client.get(url)
            return
        except httpx.HTTPError as exc:
            last = exc
            if attempt + 1 < _PREFLIGHT_ATTEMPTS:
                await asyncio.sleep(1.0 * (attempt + 1))
    raise AgentUnreachable(f"{url} did not answer after {_PREFLIGHT_ATTEMPTS} attempts ({last!r})")


async def run_sweep(
    agent_url: str,
    *,
    protocol_version: Optional[str] = None,
    baseline: Optional[Baseline] = None,
    strict: bool = False,
    timeout: Optional[float] = DEFAULT_CONTRACT_TIMEOUT_S,
    retries: int = 1,
    push_receiver: str = "auto",
    only: Optional[Iterable[str]] = None,
) -> SweepReport:
    """Sweep a live agent. Raises ``AgentUnreachable`` / ``ValueError``.

    ``only`` restricts the sweep to those contract ids; unknown ids are a
    ``ValueError`` so a typo cannot turn into an empty, passing run.
    """
    transport = A2ATransport(protocol_version=protocol_version)
    resolved = resolve_push_receiver(push_receiver, agent_url)
    descriptions = _descriptions(transport, agent_url)
    if only is not None:
        only = list(only)
        unknown = sorted(set(only) - set(descriptions))
        if unknown:
            raise ValueError(f"unknown contract id(s): {', '.join(unknown)}")
    await preflight(transport, agent_url)

    from a2a_testbed.contracts.transport._task_helpers import AgentProbe

    probe = await AgentProbe.create(transport, agent_url)
    async with push_receiver_for(resolved) as receiver_label:
        results = await run_transport_contracts(
            transport, agent_url, timeout=timeout, retries=retries, only=only
        )
    return SweepReport(
        target=agent_url,
        results=results,
        descriptions=descriptions,
        review=apply_baseline(baseline or Baseline(), results, strict=strict),
        kind="sweep",
        protocol_version=probe.dialect.value,
        push_receiver=receiver_label,
        strict=strict,
    )


@contextlib.asynccontextmanager
async def _serve_card(card: dict[str, Any]) -> AsyncIterator[str]:
    async def handler(_request: Request) -> JSONResponse:
        return JSONResponse(card)

    paths = ("/.well-known/agent-card.json", "/.well-known/agent.json")
    app = Starlette(routes=[Route(p, handler, methods=["GET"]) for p in paths])
    from a2a_testbed.contracts.push_receiver import _free_port

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started or task.done():
            break
        await asyncio.sleep(0.025)
    if not server.started:
        server.should_exit = True
        with contextlib.suppress(BaseException):
            await task
        raise RuntimeError("could not start the loopback server for the card")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await task


def read_card_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: an AgentCard must be a JSON object")
    return data


async def run_card_lint(
    card_path: Path,
    *,
    protocol_version: Optional[str] = None,
    baseline: Optional[Baseline] = None,
    strict: bool = False,
) -> SweepReport:
    """Run the card-only contracts against an AgentCard file.

    The card is served from an ephemeral loopback server so the exact
    contract code of the live sweep runs; nothing leaves the machine.
    """
    card = read_card_file(card_path)
    transport = A2ATransport(protocol_version=protocol_version)
    from a2a_testbed.contracts.transport._task_helpers import AgentProbe

    async with _serve_card(card) as url:
        probe = await AgentProbe.create(transport, url)
        results = await run_transport_contracts(
            transport, url, only=CARD_CONTRACT_IDS, timeout=15.0, retries=0
        )
        descriptions = _descriptions(transport, url)
    return SweepReport(
        target=str(card_path),
        results=results,
        descriptions=descriptions,
        review=apply_baseline(baseline or Baseline(), results, strict=strict),
        kind="lint",
        protocol_version=probe.dialect.value,
        strict=strict,
    )
