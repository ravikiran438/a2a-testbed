"""Baseline file: parsing, application, starter generation."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml

from a2a_testbed.conformance.baseline import (
    BaselineError,
    apply_baseline,
    load_baseline,
    parse_baseline,
    render_baseline,
)
from a2a_testbed.contracts.base import ContractResult, ContractStatus


def _r(cid: str, status: ContractStatus, detail: str = "") -> ContractResult:
    passed = status in (ContractStatus.PASS, ContractStatus.WARN, ContractStatus.SKIP)
    return ContractResult(cid, passed=passed, detail=detail, status=status)


def test_reason_is_required():
    with pytest.raises(BaselineError, match="reason"):
        parse_baseline({"version": 1, "accepted": [{"contract": "a"}]})
    with pytest.raises(BaselineError, match="reason"):
        parse_baseline({"version": 1, "accepted": [{"contract": "a", "reason": "  "}]})


@pytest.mark.parametrize(
    "data, match",
    [
        ([], "mapping"),
        ({"version": 2}, "version"),
        ({"accepted": {"contract": "a"}}, "list"),
        ({"accepted": [{"reason": "x"}]}, "contract"),
        ({"accepted": [{"contract": "a", "reason": "x"}] * 2}, "twice"),
        ({"accepted": [{"contract": "a", "reason": "x", "expires": "soon"}]}, "YYYY-MM-DD"),
    ],
)
def test_malformed_baselines_are_rejected(data, match):
    with pytest.raises(BaselineError, match=match):
        parse_baseline(data)


def test_empty_file_is_an_empty_baseline(tmp_path):
    path = tmp_path / "b.yaml"
    path.write_text("", encoding="utf-8")
    assert load_baseline(path).entries == []


def test_apply_accepts_fail_and_error_and_reports_the_rest():
    baseline = parse_baseline(
        {
            "accepted": [
                {"contract": "c.fail", "reason": "known"},
                {"contract": "c.error", "reason": "flaky preview"},
                {"contract": "c.fixed", "reason": "was broken"},
                {"contract": "c.gone", "reason": "renamed"},
                {"contract": "c.old", "reason": "temporary", "expires": "2026-01-01"},
            ]
        }
    )
    results = [
        _r("c.fail", ContractStatus.FAIL, "boom"),
        _r("c.error", ContractStatus.ERROR, "timeout"),
        _r("c.fixed", ContractStatus.PASS),
        _r("c.old", ContractStatus.FAIL, "still broken"),
    ]
    review = apply_baseline(baseline, results, today=dt.date(2026, 10, 11))
    assert set(review.accepted) == {"c.fail", "c.error"}
    assert [e.contract for e in review.stale] == ["c.fixed"]
    assert [e.contract for e in review.unknown] == ["c.gone"]
    assert [e.contract for e in review.expired] == ["c.old"]


def test_entry_applies_through_its_expiry_day():
    baseline = parse_baseline(
        {"accepted": [{"contract": "c", "reason": "r", "expires": dt.date(2026, 10, 11)}]}
    )
    results = [_r("c", ContractStatus.FAIL)]
    assert "c" in apply_baseline(baseline, results, today=dt.date(2026, 10, 11)).accepted
    assert "c" not in apply_baseline(baseline, results, today=dt.date(2026, 10, 12)).accepted


def test_starter_baseline_lists_failures_and_refuses_to_load_until_reasons_exist():
    results = [
        _r("c.ok", ContractStatus.PASS),
        _r("c.bad", ContractStatus.FAIL, "wrong | code\nsecond line"),
        _r("c.down", ContractStatus.ERROR, "timeout"),
        _r("c.skip", ContractStatus.SKIP, "skipped — n/a"),
    ]
    text = render_baseline(results, agent_url="https://agent.example")
    data = yaml.safe_load(text)
    assert [e["contract"] for e in data["accepted"]] == ["c.bad", "c.down"]
    with pytest.raises(BaselineError, match="reason"):
        parse_baseline(data)
    for entry in data["accepted"]:
        entry["reason"] = "tracked in the backlog"
    assert len(parse_baseline(data).entries) == 2


def test_starter_baseline_with_nothing_failing_is_valid():
    text = render_baseline([_r("c.ok", ContractStatus.PASS)])
    assert parse_baseline(yaml.safe_load(text)).entries == []
