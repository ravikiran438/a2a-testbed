# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""AgentRuntime protocol — a runtime is whatever can serve one A2A agent.

Implementations:
- ``python_inproc``: in the orchestrator process (uses a2a-sdk directly)
- ``python_subproc``: spawned `python -m ...` subprocess
- ``go``: spawned `go run ./agents/go-template/`
- ``nodejs``: spawned `node ./agents/nodejs-template/`
- ``java``: spawned `java -jar ...`
- ``external``: already running, just point at url

Every runtime has the same observable surface: a base URL, an
AgentCard (verifiable by the orchestrator), and async start/stop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from a2a.types import AgentCard


class AgentRuntime(ABC):
    """Async lifecycle for a single agent."""

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._started = False

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def started(self) -> bool:
        return self._started

    @property
    @abstractmethod
    def url(self) -> str:
        """Base URL of this agent (without the path-routing prefix in sim mode)."""

    @property
    @abstractmethod
    def agent_card(self) -> AgentCard:
        """The (live) AgentCard, with URLs reflecting the actual bound endpoint."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    async def __aenter__(self) -> "AgentRuntime":
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()


class RuntimeUnavailable(RuntimeError):
    """Raised when a runtime's required toolchain isn't installed."""

    def __init__(self, runtime: str, hint: Optional[str] = None) -> None:
        msg = f"runtime {runtime!r} unavailable on this machine"
        if hint:
            msg += f"; hint: {hint}"
        super().__init__(msg)
