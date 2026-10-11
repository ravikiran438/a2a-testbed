"""Scenario `expect.extensions`: checked on the extension's MCP server,
failing closed.

Uses a fake MCP server (tests/oracles/fake_mcp_server.py, MCP SDK 2.x
over stdio) so every path runs without any protocol installed; one test
runs the shipped example against the real PACE server when it is
installed.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from a2a_testbed.scenario import ScenarioLoadError, load_scenario, run_scenario_file

REPO_ROOT = Path(__file__).resolve().parents[2]
CARDS = REPO_ROOT / "examples" / "agent-cards" / "three-party"
FAKE_SERVER = REPO_ROOT / "tests" / "oracles" / "fake_mcp_server.py"
URI = "https://example.org/fake-extension/v1"
FAKE_DELEGATE = {"uri": URI, "command": ["{python}", str(FAKE_SERVER)]}


def _scenario(tmp_path: Path, expect: dict, **top) -> Path:
    doc = {
        "name": "extension expectations",
        "mode": "sim",
        "agents": [
            {"id": "alice", "card": str(CARDS / "alice.json"), "runtime": "python_inproc"},
            {"id": "carol", "card": str(CARDS / "carol.json"), "runtime": "python_inproc"},
        ],
        "flow": [
            {
                "from": "carol",
                "to": "alice",
                "action": "deliver",
                "message": "deliver: groceries",
                "expect": {"response_status": "2xx", **expect},
            }
        ],
        **top,
    }
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


async def _step(tmp_path: Path, checks, *, delegates=None, cli_delegates=None):
    top = {"mcp_delegates": [FAKE_DELEGATE] if delegates is None else delegates}
    path = _scenario(tmp_path, {"extensions": {URI: checks}}, **top)
    result = await run_scenario_file(path, log_level="error", mcp_delegates=cli_delegates)
    return result.steps[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "check",
    [
        {"tool": "check", "args": {"ok": True}, "verdict": "ok"},
        {"tool": "check", "args": {"ok": True}},  # verdict defaults to ok
        {"tool": "check", "args": {"ok": False}, "verdict": "violation"},
        {"tool": "reject", "verdict": "rejected"},
    ],
)
async def test_matching_verdict_passes(tmp_path, check):
    step = await _step(tmp_path, check)
    assert step.passed, step.detail
    assert "extension checks passed" in step.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "check, expected, got",
    [
        ({"tool": "check", "args": {"ok": False}, "verdict": "ok"}, "ok", "violation"),
        ({"tool": "check", "args": {"ok": True}, "verdict": "violation"}, "violation", "ok"),
        # A server-flagged error is not a violation: a malformed call must
        # not satisfy an expected "violation".
        ({"tool": "reject", "verdict": "violation"}, "violation", "rejected"),
    ],
)
async def test_mismatched_verdict_fails(tmp_path, check, expected, got):
    step = await _step(tmp_path, check)
    assert not step.passed
    assert f"expected {expected}, got {got}" in step.detail
    assert URI in step.detail and check["tool"] in step.detail


@pytest.mark.asyncio
async def test_every_check_in_a_list_must_hold(tmp_path):
    ok = {"tool": "check", "args": {"ok": True}}
    bad = {"tool": "check", "args": {"ok": False}, "verdict": "ok"}
    assert (await _step(tmp_path, [ok, ok])).passed
    step = await _step(tmp_path, [ok, bad])
    assert not step.passed and "expected ok, got violation" in step.detail


@pytest.mark.asyncio
async def test_unconfigured_uri_fails(tmp_path):
    step = await _step(tmp_path, {"tool": "check"}, delegates=[])
    assert not step.passed
    assert f"no MCP delegate configured for {URI}" in step.detail


@pytest.mark.asyncio
async def test_missing_server_command_fails(tmp_path):
    delegates = [{"uri": URI, "command": ["no-such-mcp-server-binary"]}]
    step = await _step(tmp_path, {"tool": "check"}, delegates=delegates)
    assert not step.passed and "command not found" in step.detail


@pytest.mark.asyncio
async def test_dead_server_fails(tmp_path):
    delegates = [{"uri": URI, "command": [sys.executable, "-c", "import sys; sys.exit(3)"]}]
    step = await _step(tmp_path, {"tool": "check"}, delegates=delegates)
    assert not step.passed and "MCP server unavailable" in step.detail


@pytest.mark.asyncio
async def test_unknown_tool_fails_even_when_rejected_is_expected(tmp_path):
    step = await _step(tmp_path, {"tool": "no_such_tool", "verdict": "rejected"})
    assert not step.passed
    assert "not offered by the server" in step.detail and "check" in step.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["ok", "violation"])
async def test_malformed_answer_fails(tmp_path, verdict):
    for tool in ("garbage", "not_a_verdict"):
        step = await _step(tmp_path, {"tool": tool, "verdict": verdict})
        assert not step.passed and "unexpected payload" in step.detail, (tool, step.detail)


@pytest.mark.asyncio
async def test_http_failure_is_reported_before_extension_checks(tmp_path):
    path = _scenario(
        tmp_path,
        {"response_status": "5xx", "extensions": {URI: {"tool": "check"}}},
        mcp_delegates=[FAKE_DELEGATE],
    )
    result = await run_scenario_file(path, log_level="error")
    assert not result.steps[0].passed and "expected 5xx" in result.steps[0].detail


@pytest.mark.asyncio
async def test_delegates_file_relative_to_scenario_and_cli_override(tmp_path):
    (tmp_path / "delegates.yaml").write_text(
        yaml.safe_dump({"delegates": [{"uri": URI, "command": ["no-such-binary"]}]}),
        encoding="utf-8",
    )
    path = _scenario(
        tmp_path, {"extensions": {URI: {"tool": "check"}}}, mcp_delegates="delegates.yaml"
    )
    broken = await run_scenario_file(path, log_level="error")
    assert not broken.steps[0].passed and "command not found" in broken.steps[0].detail

    override = tmp_path / "override.yaml"
    override.write_text(yaml.safe_dump({"delegates": [FAKE_DELEGATE]}), encoding="utf-8")
    fixed = await run_scenario_file(path, log_level="error", mcp_delegates=override)
    assert fixed.steps[0].passed, fixed.steps[0].detail


@pytest.mark.parametrize("legacy", ["acap", "phala", "nerve", "pace"])
def test_old_field_names_are_a_clear_load_error(tmp_path, legacy):
    path = _scenario(tmp_path, {legacy: {"language": "te"}})
    with pytest.raises(ScenarioLoadError, match=f"expect.{legacy} is no longer supported"):
        load_scenario(path)


def test_unknown_expectation_keys_are_rejected(tmp_path):
    path = _scenario(tmp_path, {"respones_status": "2xx"})
    with pytest.raises(ScenarioLoadError, match="respones_status"):
        load_scenario(path)


def test_malformed_checks_are_rejected(tmp_path):
    for bad in ({"args": {}}, {"tool": "t", "verdict": "maybe"}, {"tool": "t", "extra": 1}, []):
        path = _scenario(tmp_path, {"extensions": {URI: bad}})
        with pytest.raises(ScenarioLoadError):
            load_scenario(path)
    path = _scenario(tmp_path, {"extensions": {}})
    with pytest.raises(ScenarioLoadError):
        load_scenario(path)


@pytest.mark.parametrize("key", ["extensions", "expext", "pace"])
def test_misplaced_step_keys_are_rejected(tmp_path, key):
    """A check indented beside `expect:` (or a misspelt `expect:`) must
    fail the load instead of being dropped."""
    path = _scenario(tmp_path, {})
    doc = yaml.safe_load(path.read_text())
    doc["flow"][0][key] = {URI: {"tool": "check"}}
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match=key):
        load_scenario(path)


def test_misspelt_scenario_keys_are_rejected(tmp_path):
    path = _scenario(tmp_path, {}, mcp_delegate="x.yaml")
    with pytest.raises(ScenarioLoadError, match="mcp_delegate"):
        load_scenario(path)


def test_extension_checks_only_on_send_steps(tmp_path):
    path = _scenario(tmp_path, {})
    doc = yaml.safe_load(path.read_text())
    doc["flow"].append(
        {"kind": "observe", "from": "alice", "expect": {"extensions": {URI: {"tool": "check"}}}}
    )
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="only evaluated on send steps"):
        load_scenario(path)


@pytest.mark.asyncio
async def test_relative_server_path_resolves_against_the_delegates_file(tmp_path, monkeypatch):
    servers = tmp_path / "servers"
    servers.mkdir()
    (servers / "fake.py").write_text(FAKE_SERVER.read_text(), encoding="utf-8")
    (tmp_path / "delegates.yaml").write_text(
        yaml.safe_dump({"delegates": [{"uri": URI, "command": ["{python}", "servers/fake.py"]}]}),
        encoding="utf-8",
    )
    path = _scenario(
        tmp_path, {"extensions": {URI: {"tool": "check"}}}, mcp_delegates="delegates.yaml"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = await run_scenario_file(path, log_level="error")
    assert result.steps[0].passed, result.steps[0].detail


@pytest.mark.asyncio
async def test_inline_delegates_mapping_form(tmp_path):
    step = await _step(tmp_path, {"tool": "check"}, delegates={"delegates": [FAKE_DELEGATE]})
    assert step.passed, step.detail


@pytest.mark.asyncio
async def test_malformed_delegates_block_is_a_load_error(tmp_path):
    path = _scenario(
        tmp_path,
        {"extensions": {URI: {"tool": "check"}}},
        mcp_delegates=[{"uri": URI}],
    )
    with pytest.raises(ScenarioLoadError, match="command"):
        await run_scenario_file(path, log_level="error")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("A2A_TESTBED_REAL_MCP") != "1" or shutil.which("uvx") is None,
    reason="set A2A_TESTBED_REAL_MCP=1 (needs uvx and network) to run against the pinned PACE",
)
async def test_shipped_example_against_the_real_pace_server():
    example = REPO_ROOT / "examples" / "scenarios" / "extension_checks.yaml"
    result = await run_scenario_file(example, log_level="error")
    assert result.passed, [s.detail for s in result.steps if not s.passed]
    details = " ".join(s.detail for s in result.steps)
    assert "validate_time_window=violation" in details
    assert "validate_language_match=violation" in details
