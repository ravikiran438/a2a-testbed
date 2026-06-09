# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Shared subprocess runtime machinery for Go / Node.js / Java agents.

Each subprocess agent must accept these CLI flags:

  --agent-card <path-to-json>    AgentCard JSON file
  --port <int>                   bind port (0 = random, recommended)
  --scripts <path-to-json>       scripts mapping: {"action": "response", ...}

And on startup must:

1. Bind an HTTP server on 127.0.0.1:<port>
2. Print exactly one line to stdout: "A2A_TESTBED_READY: <base_url>"
3. Serve the AgentCard at /.well-known/agent-card.json
4. Accept JSON-RPC at /a2a/v1/ (or whatever DEFAULT_RPC_URL the SDK uses)
5. Respond to message/send by matching the message text against the
   scripts map; fallback to "[<agent_id>] handled action: <text>"

The orchestrator uses the printed URL to discover the bound port (which
may differ from the requested one when port=0).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from a2a.types import AgentCard
from google.protobuf.json_format import MessageToJson

from a2a_testbed.runtimes.base import AgentRuntime, RuntimeUnavailable


logger = logging.getLogger(__name__)

_READY_LINE = re.compile(r"A2A_TESTBED_READY:\s*(\S+)")


class SubprocessRuntimeBase(AgentRuntime):
    """Spawn an external process that hosts the agent over HTTP."""

    binary_check: list[str] = []  # subclass: command to verify toolchain (e.g. ['go','version'])
    binary_hint: str = ""  # subclass: install-hint message
    cmd_template: list[str] = []  # subclass: command template; gets formatted at start

    def __init__(
        self,
        agent_id: str,
        agent_card: AgentCard,
        source: str,
        scripts: dict[str, str] | None = None,
        port: int = 0,
        log_level: str = "warning",
    ) -> None:
        super().__init__(agent_id)
        self._original_card = agent_card
        self._live_card: Optional[AgentCard] = None
        self._source = Path(source).expanduser().resolve()
        self._scripts = dict(scripts or {})
        self._port = port
        self._log_level = log_level

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._url: Optional[str] = None
        self._tempdir: Optional[tempfile.TemporaryDirectory] = None

    @property
    def url(self) -> str:
        if self._url is None:
            raise RuntimeError(f"{self._agent_id} subprocess has not started")
        return self._url

    @property
    def agent_card(self) -> AgentCard:
        return self._live_card if self._live_card is not None else self._original_card

    async def start(self) -> None:
        self._verify_toolchain()
        self._tempdir = tempfile.TemporaryDirectory(prefix=f"a2a-testbed-{self._agent_id}-")
        td = Path(self._tempdir.name)
        card_path = td / "agent-card.json"
        scripts_path = td / "scripts.json"
        card_path.write_text(MessageToJson(self._original_card), encoding="utf-8")
        scripts_path.write_text(json.dumps(self._scripts), encoding="utf-8")

        cmd = [
            arg.format(
                source=str(self._source),
                card=str(card_path),
                scripts=str(scripts_path),
                port=str(self._port),
                log_level=self._log_level,
            )
            for arg in self.cmd_template
        ]

        logger.info("[%s] spawning %s", self._agent_id, cmd)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._source) if self._source.is_dir() else None,
        )
        self._url = await self._wait_for_ready_line()
        self._started = True

    async def stop(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
                await self._proc.wait()
            self._proc = None
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None
        self._started = False

    # ------------------------------------------------------------------

    def _verify_toolchain(self) -> None:
        if not self.binary_check:
            return
        binary = self.binary_check[0]
        if shutil.which(binary) is None:
            raise RuntimeUnavailable(self.__class__.__name__, hint=self.binary_hint)

    async def _wait_for_ready_line(self) -> str:
        assert self._proc is not None and self._proc.stdout is not None
        timeout = 30.0
        try:
            while True:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=timeout)
                if not line:
                    raise RuntimeError(f"{self._agent_id} subprocess closed stdout before ready")
                decoded = line.decode("utf-8", errors="replace").strip()
                logger.debug("[%s] %s", self._agent_id, decoded)
                m = _READY_LINE.search(decoded)
                if m:
                    return m.group(1)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"{self._agent_id} subprocess did not print A2A_TESTBED_READY within {timeout}s"
            ) from exc
