# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""End-to-end three-party consent scenario over the multi-tenant network."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2a_testbed.scenario import run_scenario_file


REPO_ROOT = Path(__file__).resolve().parents[2]
THREE_PARTY = REPO_ROOT / "examples" / "scenarios" / "three_party_consent.yaml"


@pytest.mark.asyncio
async def test_three_party_passes_end_to_end():
    result = await run_scenario_file(THREE_PARTY, log_level="error")
    assert result.scenario_name.startswith("Three-party")
    assert len(result.steps) == 5, [s.detail for s in result.steps]
    assert result.passed, [
        f"step {s.step_index} ({s.step.action}): {s.detail}"
        for s in result.steps
        if not s.passed
    ]
    assert result.elapsed_ms > 0
