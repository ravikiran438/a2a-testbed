# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""External runtime — agent is already running somewhere; we just point at it."""

from __future__ import annotations

from a2a.types import AgentCard

from a2a_testbed.runtimes.base import AgentRuntime


class ExternalRuntime(AgentRuntime):
    """An agent already running outside the testbed; we never start/stop it."""

    def __init__(self, agent_id: str, agent_card: AgentCard, url: str) -> None:
        super().__init__(agent_id)
        self._card = agent_card
        self._url = url.rstrip("/")

    @property
    def url(self) -> str:
        return self._url

    @property
    def agent_card(self) -> AgentCard:
        return self._card

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
