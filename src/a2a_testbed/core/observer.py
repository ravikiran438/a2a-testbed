# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Observer agents — passive recorders of inter-agent traffic.

Every step the scenario runner executes is also broadcast to all
registered observers. Observers can declare expectations against
the traffic they see (e.g. behavioral fingerprint accumulation,
audit trail completeness); the hub records every step and lets
downstream semantic validators consume the history.

Observers are first-class scenario citizens: they appear in
``agents:`` with ``role: observer`` and don't participate in the
message flow as ``from``/``to``, but they receive every step's
metadata via the in-process broker.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from a2a_testbed.core.types import Step, StepResult


class TrafficRecord:
    """One observed message as captured by an observer."""

    __slots__ = ("step_index", "step", "result", "extras")

    def __init__(
        self,
        step_index: int,
        step: Step,
        result: StepResult | None,
        extras: Dict[str, Any] | None = None,
    ) -> None:
        self.step_index = step_index
        self.step = step
        self.result = result
        self.extras = extras or {}


@dataclass
class WireExchange:
    """Wire-level request/response pair as seen at the network seam.

    Captured by the multi-tenant or per-process network's traffic tap
    and forwarded to every registered observer agent. Useful for
    audit-style observers that need access to actual wire payloads
    rather than just step records.
    """

    receiver_id: str
    request_body: Dict[str, Any]
    response_body: Dict[str, Any]
    extras: Dict[str, Any] = field(default_factory=dict)


class ObserverHub:
    """In-process broker that fans out traffic records to observers.

    Each observer is identified by its agent id. Observers are passive:
    they don't return responses; the hub just buffers what they have
    seen for later inspection.
    """

    def __init__(self) -> None:
        self._records: Dict[str, List[TrafficRecord]] = defaultdict(list)
        self._registered: set[str] = set()

    def register(self, observer_id: str) -> None:
        self._registered.add(observer_id)

    def observers(self) -> list[str]:
        return sorted(self._registered)

    def record(self, step_index: int, step: Step, result: StepResult | None) -> None:
        if not self._registered:
            return
        record = TrafficRecord(step_index, step, result)
        for obs in self._registered:
            self._records[obs].append(record)

    def history(self, observer_id: str) -> list[TrafficRecord]:
        return [r for r in self._records.get(observer_id, []) if isinstance(r, TrafficRecord)]

    def wire_history(self, observer_id: str) -> list[WireExchange]:
        return [r for r in self._records.get(observer_id, []) if isinstance(r, WireExchange)]

    def record_wire(self, exchange: WireExchange) -> None:
        """Record a wire-level exchange for every registered observer."""
        if not self._registered:
            return
        for observer_id in self._registered:
            self._records[observer_id].append(exchange)

    def clear(self) -> None:
        self._records.clear()
