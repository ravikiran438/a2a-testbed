# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""In-process Python runtime — fastest path, used as scenario default.

This runtime does not spin up its own HTTP server. Instead it registers
the agent's AgentCard + a scripted handler with the multi-tenant
network, which routes incoming requests to the right handler by URL
path. That makes scenario setup ~instant and removes the need for a
port-per-agent.

For the per-process realistic mode there is a separate
``python_perproc`` runtime that does spin up a uvicorn server.
"""

from __future__ import annotations

from typing import Mapping, Optional

from a2a.types import AgentCard

from a2a_testbed.runtimes.base import AgentRuntime


class PythonInProcRuntime(AgentRuntime):
    """An in-process agent. Registered with the multitenant network on start."""

    def __init__(
        self,
        agent_id: str,
        agent_card: AgentCard,
        scripts: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(agent_id)
        self._original_card = agent_card
        self._live_card: Optional[AgentCard] = None
        self._scripts: dict[str, str] = dict(scripts or {})
        self._url: Optional[str] = None

    @property
    def url(self) -> str:
        if self._url is None:
            raise RuntimeError(f"{self._agent_id} not yet attached to a network")
        return self._url

    @property
    def agent_card(self) -> AgentCard:
        return self._live_card if self._live_card is not None else self._original_card

    @property
    def scripts(self) -> Mapping[str, str]:
        return dict(self._scripts)

    def attach(self, base_url: str, live_card: AgentCard) -> None:
        """Called by the multi-tenant network once the agent's URL is known."""
        self._url = base_url
        self._live_card = live_card

    async def start(self) -> None:
        # Lifecycle is owned by the multi-tenant network, not this runtime.
        # We mark started for symmetry with subprocess runtimes.
        self._started = True

    async def stop(self) -> None:
        self._started = False

    def script_for(self, action_label: str) -> str:
        """Resolve a scripted response for an action label, with substring match."""
        if not action_label:
            return f"[{self._agent_id}] acknowledged"
        for key, value in self._scripts.items():
            if key.lower() in action_label.lower():
                return value
        return f"[{self._agent_id}] handled action: {action_label}"
