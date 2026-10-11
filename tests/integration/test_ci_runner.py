"""The CI-facing conformance runner: statuses, retries, push receiver,
baseline, report formats and the CLI exit codes, end to end against
agents built on the official a2a-sdk."""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from typer.testing import CliRunner

from a2a_testbed.cli.main import app
from a2a_testbed.conformance import (
    AgentUnreachable,
    parse_baseline,
    render,
    run_card_lint,
    run_sweep,
)
from a2a_testbed.contracts.base import Contract, ContractCategory, ContractStatus, Info
from a2a_testbed.contracts.push_receiver import (
    HOSTED_PUSH_RECEIVER,
    PUSH_RECEIVER_ENV,
    is_loopback_agent,
    resolve_push_receiver,
)
from a2a_testbed.contracts.runner import run_contracts
from tests.integration.test_protocol_versions import _drift_agent
from tests.oracles.sdk_agents import CARD_PATH, build_sdk_agent, free_port, serve

REPO_ROOT = Path(__file__).resolve().parents[2]
CARD = REPO_ROOT / "examples" / "agent-cards" / "mixed-versions" / "modern.json"
DRIFT = "transport.advertised_version_served"


@pytest.fixture(autouse=True)
def _no_receiver_env(monkeypatch):
    monkeypatch.delenv(PUSH_RECEIVER_ENV, raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


# --- statuses, timeouts, retries -------------------------------------------


def _contract(fn) -> Contract:
    return Contract(id="t.c", description="d", category=ContractCategory.TRANSPORT, verify_fn=fn)


@pytest.mark.asyncio
async def test_statuses_follow_what_the_contract_did():
    async def ok():
        return None

    async def info():
        return Info("spoke 1.0")

    async def deviation():
        return "refused with the wrong code"

    async def skip():
        return "skipped — not advertised"

    async def wrong():
        raise AssertionError("bad shape")

    async def crashed():
        raise KeyError("result")

    async def unreachable():
        raise httpx.ConnectError("refused")

    expected = {
        ok: ContractStatus.PASS,
        info: ContractStatus.PASS,
        deviation: ContractStatus.WARN,
        skip: ContractStatus.SKIP,
        wrong: ContractStatus.FAIL,
        crashed: ContractStatus.FAIL,
        unreachable: ContractStatus.ERROR,
    }
    for fn, status in expected.items():
        result = await _contract(fn).verify()
        assert result.status is status, fn.__name__
        assert result.passed is (
            status in (ContractStatus.PASS, ContractStatus.WARN, ContractStatus.SKIP)
        )
    assert (await _contract(info).verify()).detail == "spoke 1.0"


@pytest.mark.asyncio
async def test_a_hung_contract_times_out_as_an_error():
    async def hang():
        await asyncio.sleep(30)

    result = await _contract(hang).verify(timeout=0.05)
    assert result.status is ContractStatus.ERROR
    assert "within 0.05s" in result.detail


@pytest.mark.asyncio
async def test_errors_are_retried_once_and_failures_never():
    calls = {"flaky": 0, "wrong": 0}

    async def flaky():
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise TimeoutError
        return None

    async def wrong():
        calls["wrong"] += 1
        raise AssertionError("wrong answer")

    import a2a_testbed.contracts.runner as runner

    runner.RETRY_BACKOFF_S, saved = 0.0, runner.RETRY_BACKOFF_S
    try:
        flaky_r, wrong_r = await run_contracts([_contract(flaky), _contract(wrong)])
    finally:
        runner.RETRY_BACKOFF_S = saved
    assert flaky_r.status is ContractStatus.PASS and flaky_r.attempts == 2
    assert wrong_r.status is ContractStatus.FAIL and wrong_r.attempts == 1
    assert calls == {"flaky": 2, "wrong": 1}


# --- push receiver ----------------------------------------------------------


def test_receiver_resolution(monkeypatch):
    assert is_loopback_agent("http://127.0.0.1:8000")
    assert is_loopback_agent("http://localhost:9999/x")
    assert is_loopback_agent("http://[::1]:8000")
    assert not is_loopback_agent("http://10.0.0.5:8000")
    assert not is_loopback_agent("https://tasks.a2a-testbed.com")
    assert resolve_push_receiver("auto", "http://127.0.0.1:1") == "local"
    assert resolve_push_receiver("auto", "https://agent.example") == HOSTED_PUSH_RECEIVER
    assert resolve_push_receiver("hosted", "http://127.0.0.1:1") == HOSTED_PUSH_RECEIVER
    assert resolve_push_receiver("off", "https://a.example") == "off"
    assert resolve_push_receiver("https://hooks.example", "x") == "https://hooks.example"
    monkeypatch.setenv(PUSH_RECEIVER_ENV, "https://mine.example")
    assert resolve_push_receiver("auto", "http://127.0.0.1:1") == "https://mine.example"
    with pytest.raises(ValueError):
        resolve_push_receiver("sometimes", "x")


@pytest.mark.asyncio
async def test_local_agent_gets_a_local_receiver_and_full_coverage():
    async with serve(lambda base: build_sdk_agent(base, "1.0")) as url:
        report = await run_sweep(url)
    assert report.exit_code == 0, [(r.id, r.result.detail) for r in report.blocking + report.errors]
    assert report.push_receiver.startswith("local (http://127.0.0.1:")
    push = next(r for r in report.rows if r.id == "transport.push_fires_on_completion")
    assert push.outcome == "pass", push.result.detail
    # Informational passes are not deviations: --strict stays green.
    drift = next(r for r in report.rows if r.id == DRIFT)
    assert drift.outcome == "pass" and "A2A 1.0" in drift.result.detail
    report.strict = True
    assert report.exit_code == 0, [(r.id, r.result.detail) for r in report.blocking]


@pytest.mark.asyncio
async def test_unreachable_receiver_skips_push_delivery_instead_of_failing():
    dead = f"http://127.0.0.1:{free_port()}"
    async with serve(lambda base: build_sdk_agent(base, "1.0")) as url:
        report = await run_sweep(
            url, push_receiver=dead, only=("transport.push_fires_on_completion",)
        )
    push = next(r for r in report.rows if r.id == "transport.push_fires_on_completion")
    assert push.outcome == "skip" and "unreachable" in push.result.detail
    assert report.exit_code == 0


@pytest.mark.asyncio
async def test_receiver_off_skips_push_delivery():
    async with serve(lambda base: build_sdk_agent(base, "1.0")) as url:
        report = await run_sweep(
            url, push_receiver="off", only=("transport.push_fires_on_completion",)
        )
    push = next(r for r in report.rows if r.id == "transport.push_fires_on_completion")
    assert push.outcome == "skip" and "disabled" in push.result.detail


@pytest.mark.asyncio
async def test_unknown_only_id_is_rejected():
    with pytest.raises(ValueError, match="unknown contract"):
        await run_sweep("http://127.0.0.1:1", only=["transport.typo"])


@pytest.mark.asyncio
async def test_dead_agent_is_unreachable_not_sixty_failures():
    with pytest.raises(AgentUnreachable):
        await run_sweep(f"http://127.0.0.1:{free_port()}")


# --- baseline + exit codes --------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_turns_a_known_failure_green_and_flags_stale_entries():
    async with serve(_drift_agent) as url:
        plain = await run_sweep(url)
        assert plain.exit_code == 1
        failing = {r.id for r in plain.blocking}
        assert DRIFT in failing
        baseline = parse_baseline(
            {
                "accepted": [{"contract": cid, "reason": "router fix in flight"} for cid in failing]
                + [{"contract": "transport.well_known_card", "reason": "was broken once"}]
            }
        )
        accepted = await run_sweep(url, baseline=baseline)
    assert accepted.exit_code == 0
    row = next(r for r in accepted.rows if r.id == DRIFT)
    assert row.outcome == "accepted" and row.baseline.reason == "router fix in flight"
    assert [e.contract for e in accepted.review.stale] == ["transport.well_known_card"]


@pytest.mark.asyncio
async def test_errors_only_exit_3_and_failures_win():
    async def slow_rpc(request: Request) -> JSONResponse:
        await asyncio.sleep(5)
        return JSONResponse({})

    def slow_agent(base: str) -> Starlette:
        card = json.loads(CARD.read_text())
        card["supportedInterfaces"][0]["url"] = base + "/"

        async def card_route(_r: Request) -> JSONResponse:
            return JSONResponse(card)

        return Starlette(
            routes=[
                Route("/.well-known/agent-card.json", card_route, methods=["GET"]),
                Route("/", slow_rpc, methods=["POST"]),
                Route("/a2a/v1/", slow_rpc, methods=["POST"]),
            ]
        )

    only = ("transport.agent_card_required_fields", "transport.jsonrpc_envelope")
    import a2a_testbed.contracts.runner as runner

    runner.RETRY_BACKOFF_S, saved = 0.0, runner.RETRY_BACKOFF_S
    try:
        async with serve(slow_agent) as url:
            report = await run_sweep(url, timeout=0.3, only=only)
    finally:
        runner.RETRY_BACKOFF_S = saved
    by_id = {r.id: r for r in report.rows}
    assert by_id["transport.agent_card_required_fields"].outcome == "pass"
    env = by_id["transport.jsonrpc_envelope"]
    assert env.outcome == "error" and env.result.attempts == 2
    assert report.exit_code == 3


# --- report formats ---------------------------------------------------------


@pytest.mark.asyncio
async def test_every_format_renders_the_same_verdict():
    async with serve(_drift_agent) as url:
        baseline = parse_baseline({"accepted": [{"contract": DRIFT, "reason": "in flight"}]})
        report = await run_sweep(url, baseline=baseline)

    data = json.loads(render(report, "json", sarif_location="agent-card.json"))
    assert data["exit_code"] == report.exit_code
    assert data["summary"]["accepted"] == 1
    drift = next(r for r in data["results"] if r["id"] == DRIFT)
    assert drift["outcome"] == "accepted" and drift["baseline"]["reason"] == "in flight"

    suite = ET.fromstring(render(report, "junit", sarif_location="x")).find("testsuite")
    assert int(suite.get("tests")) == len(report.results)
    assert int(suite.get("failures")) == len(report.blocking)
    case = next(c for c in suite.iter("testcase") if c.get("name") == DRIFT)
    assert "accepted by baseline" in case.find("skipped").get("message")

    sarif = json.loads(render(report, "sarif", sarif_location="agent-card.json"))
    run = sarif["runs"][0]
    assert sarif["version"] == "2.1.0" and run["tool"]["driver"]["name"] == "a2a-testbed"
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    for res in run["results"]:
        assert res["ruleId"] in rule_ids
        assert (
            res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "agent-card.json"
        )
    suppressed = [r for r in run["results"] if r.get("suppressions")]
    assert [r["ruleId"] for r in suppressed] == [DRIFT]

    md = render(report, "markdown", sarif_location="x")
    assert DRIFT in md and "accepted: in flight" in md


# --- CLI --------------------------------------------------------------------


def _bad_card(tmp_path: Path) -> Path:
    card = json.loads(CARD.read_text())
    card["skills"].append(dict(card["skills"][0]))
    card["supportedInterfaces"][0]["url"] = "http://agent.example.com/a2a/v1"
    path = tmp_path / "agent-card.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


def test_lint_card_good_and_bad(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    good = runner.invoke(app, ["lint-card", str(CARD)])
    assert good.exit_code == 0, good.output

    bad = _bad_card(tmp_path)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    out = runner.invoke(
        app,
        ["lint-card", str(bad), "--format", "json", "-o", "r.sarif", "-o", "r.xml", "-o", "r.md"],
    )
    assert out.exit_code == 1, out.output
    data = json.loads(out.stdout)
    failing = {r["id"] for r in data["results"] if r["outcome"] == "fail"}
    assert {"transport.agent_card_skill_id_unique", "transport.agent_card_https_urls"} <= failing
    sarif = json.loads((tmp_path / "r.sarif").read_text())
    assert sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"][
        "uri"
    ] == str(bad)
    ET.fromstring((tmp_path / "r.xml").read_text())
    assert "AgentCard lint" in (tmp_path / "r.md").read_text()
    assert "AgentCard lint" in summary.read_text()


def test_lint_card_uses_the_default_baseline_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = _bad_card(tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, ["lint-card", str(bad), "--format", "json"])
    failing = [r["id"] for r in json.loads(first.stdout)["results"] if r["outcome"] == "fail"]
    (tmp_path / ".a2a-conformance.yaml").write_text(
        yaml.safe_dump(
            {"version": 1, "accepted": [{"contract": c, "reason": "legacy card"} for c in failing]}
        ),
        encoding="utf-8",
    )
    assert runner.invoke(app, ["lint-card", str(bad)]).exit_code == 0
    assert runner.invoke(app, ["lint-card", str(bad), "--baseline", "none"]).exit_code == 1


def test_cli_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["lint-card", str(CARD), "--format", "yaml"]).exit_code == 2
    assert runner.invoke(app, ["lint-card", str(tmp_path / "missing.json")]).exit_code == 2
    (tmp_path / ".a2a-conformance.yaml").write_text(
        "accepted:\n  - contract: x\n", encoding="utf-8"
    )
    out = runner.invoke(app, ["lint-card", str(CARD)])
    assert out.exit_code == 2 and "reason" in out.output
    assert runner.invoke(app, ["lint-card", str(CARD), "-o", "report.txt"]).exit_code == 2


@pytest.mark.asyncio
async def test_lint_matches_the_live_sweep_for_card_contracts(tmp_path):
    """Same ids and verdicts for the card-only checks, file or live."""
    async with serve(lambda base: build_sdk_agent(base, "1.0")) as url:
        live = await run_sweep(url, push_receiver="off")
        async with httpx.AsyncClient() as client:
            card = (await client.get(url + CARD_PATH)).json()
    path = tmp_path / "card.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    lint = await run_card_lint(path)
    live_outcomes = {r.id: r.outcome for r in live.rows}
    for row in lint.rows:
        assert live_outcomes[row.id] == row.outcome, (row.id, row.result.detail)


# --- review follow-ups --------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_that_goes_silent_is_a_failure_not_an_error():
    """An agent that opens the SSE stream and never closes it answered
    wrongly; that must not be retried and reported as 'unreachable'."""
    from starlette.responses import StreamingResponse

    from a2a_testbed.contracts.transport._task_helpers import stream_sse_events
    from a2a_testbed.transport import A2ATransport

    async def stall(_request: Request) -> StreamingResponse:
        async def body():
            yield b'data: {"jsonrpc": "2.0", "id": "x", "result": {}}\n\n'
            await asyncio.sleep(30)

        return StreamingResponse(body(), media_type="text/event-stream")

    def app_factory(_base: str) -> Starlette:
        return Starlette(
            routes=[Route("/", stall, methods=["POST"]), Route("/a2a/v1/", stall, methods=["POST"])]
        )

    async def verify():
        await stream_sse_events(A2ATransport(), url, "SendStreamingMessage", {}, timeout=0.3)

    async with serve(app_factory) as url:
        result = await _contract(verify).verify()
    assert result.status is ContractStatus.FAIL
    assert "went silent" in result.detail and "1 event(s)" in result.detail


def test_missing_method_is_a_deviation_not_a_skip():
    from a2a_testbed.contracts.base import ContractResult

    missing = ContractResult(
        "c", passed=True, detail="skipped — agent does not implement GetTask (-32601)"
    )
    assert missing.status is ContractStatus.WARN
    na = ContractResult("c", passed=True, detail="skipped — agent does not advertise streaming")
    assert na.status is ContractStatus.SKIP


def test_strict_baseline_accepts_deviations():
    from a2a_testbed.conformance import SweepReport, apply_baseline, render_baseline
    from a2a_testbed.contracts.base import ContractResult

    results = [ContractResult("c.dev", passed=True, detail="wrong error code")]
    baseline = parse_baseline({"accepted": [{"contract": "c.dev", "reason": "tracked"}]})
    lenient = apply_baseline(baseline, results)
    assert not lenient.accepted and [e.contract for e in lenient.stale] == ["c.dev"]
    strict = apply_baseline(baseline, results, strict=True)
    assert "c.dev" in strict.accepted and not strict.stale
    report = SweepReport(target="t", results=results, review=strict, strict=True)
    assert report.exit_code == 0
    assert "c.dev" in render_baseline(results, strict=True)
    assert "c.dev" not in render_baseline(results)


@pytest.mark.asyncio
async def test_sarif_category_and_stable_fingerprints():
    async with serve(_drift_agent) as url:
        report = await run_sweep(url, only=[DRIFT])
    default = json.loads(render(report, "sarif", sarif_location="agent-card.json"))
    assert default["runs"][0]["automationDetails"]["id"] == "a2a-conformance/sweep/"
    named = json.loads(
        render(report, "sarif", sarif_location="agent-card.json", sarif_category="agents/math")
    )
    run = named["runs"][0]
    assert run["automationDetails"]["id"] == "agents/math/"
    # Keyed on contract + file, not the (per-PR) agent URL.
    assert run["results"][0]["partialFingerprints"]["contract"] == f"{DRIFT}@agent-card.json"
