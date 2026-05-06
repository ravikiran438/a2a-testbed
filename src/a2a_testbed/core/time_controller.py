# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Abstract time controller for scenario testing.

Real-world A2A protocols use TTLs, refresh cadences, and prediction
horizons measured in seconds-to-days. We can't (and shouldn't) sleep
through those in tests. The TimeController exposes a clock that the
orchestrator and all in-process agents read instead of `datetime.now()`,
and a single ``advance(seconds)`` operation that simulates time passing.

Subprocess-runtime agents can't easily be wired to a virtual clock; for
those, scenarios that need time control should set
``TimeController.real_clock_for_subprocess=False`` (default) and accept
that subprocess agents see real wall time. Most TTL/refresh tests can
still be exercised in sim mode using only in-process agents.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


class TimeController:
    """Virtual clock with explicit ``advance``."""

    def __init__(
        self,
        *,
        start: datetime | None = None,
        real_clock_for_subprocess: bool = False,
    ) -> None:
        self._now = start or datetime.now(timezone.utc)
        self.real_clock_for_subprocess = real_clock_for_subprocess

    def now(self) -> datetime:
        """Return the current virtual time."""
        return self._now

    def advance(self, seconds: int) -> datetime:
        """Move the virtual clock forward and return the new time."""
        if seconds < 0:
            raise ValueError("cannot advance time backwards")
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def reset(self, to: datetime | None = None) -> None:
        self._now = to or datetime.now(timezone.utc)
