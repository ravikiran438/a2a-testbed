# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for core/observer.py."""

from __future__ import annotations

from a2a_testbed.core.observer import ObserverHub
from a2a_testbed.core.types import Step


def _step(**overrides):
    base = {"from": "a", "to": "b", "action": "ping"}
    base.update(overrides)
    return Step.model_validate(base)


def test_no_observers_no_records():
    hub = ObserverHub()
    hub.record(0, _step(), None)
    # Without registration, nothing accumulates anywhere
    assert hub.observers() == []


def test_one_observer_accumulates_history():
    hub = ObserverHub()
    hub.register("watch")
    hub.record(0, _step(), None)
    hub.record(1, _step(action="ack"), None)
    history = hub.history("watch")
    assert len(history) == 2
    assert history[0].step.action == "ping"
    assert history[1].step.action == "ack"


def test_two_observers_each_see_everything():
    hub = ObserverHub()
    hub.register("o1")
    hub.register("o2")
    hub.record(0, _step(), None)
    assert len(hub.history("o1")) == 1
    assert len(hub.history("o2")) == 1


def test_observers_listed_alphabetically():
    hub = ObserverHub()
    hub.register("zeta")
    hub.register("alpha")
    assert hub.observers() == ["alpha", "zeta"]


def test_clear_resets_history():
    hub = ObserverHub()
    hub.register("o")
    hub.record(0, _step(), None)
    assert hub.history("o")
    hub.clear()
    assert hub.history("o") == []
