# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for core/time_controller.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from a2a_testbed.core.time_controller import TimeController


def test_initial_now_is_now():
    before = datetime.now(timezone.utc)
    tc = TimeController()
    after = datetime.now(timezone.utc)
    assert before <= tc.now() <= after


def test_advance_moves_clock_forward():
    tc = TimeController(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    tc.advance(60)
    assert tc.now() == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def test_advance_negative_rejected():
    tc = TimeController()
    with pytest.raises(ValueError):
        tc.advance(-1)


def test_advance_chaining():
    tc = TimeController(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    tc.advance(30)
    tc.advance(45)
    assert tc.now() == datetime(2026, 1, 1, 0, 1, 15, tzinfo=timezone.utc)


def test_reset():
    tc = TimeController(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    tc.advance(1000)
    tc.reset(to=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert tc.now() == datetime(2027, 1, 1, tzinfo=timezone.utc)
