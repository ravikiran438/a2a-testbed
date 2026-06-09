# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Reporter: serialize ScenarioResult to JSON, Markdown, and SVG badge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Union

from a2a_testbed.core.types import ReportSink, ScenarioResult


_BADGE_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="200" height="20" role="img" aria-label="a2a-testbed: {label}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="200" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="120" height="20" fill="#555"/>
    <rect x="120" width="80" height="20" fill="{color}"/>
    <rect width="200" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="60" y="14">a2a-testbed</text>
    <text x="160" y="14">{label}</text>
  </g>
</svg>"""


def write_reports(
    result: ScenarioResult,
    sinks: Iterable[ReportSink],
    *,
    base_dir: Union[str, Path] = ".",
) -> list[Path]:
    base = Path(base_dir)
    written: list[Path] = []
    for sink in sinks:
        path = base / sink.path
        path.parent.mkdir(parents=True, exist_ok=True)
        if sink.format == "json":
            path.write_text(_to_json(result), encoding="utf-8")
        elif sink.format == "markdown":
            path.write_text(_to_markdown(result), encoding="utf-8")
        elif sink.format == "svg-badge":
            path.write_text(_to_badge(result), encoding="utf-8")
        else:
            raise ValueError(f"unknown report format {sink.format!r}")
        written.append(path)
    return written


def _to_json(result: ScenarioResult) -> str:
    payload = json.loads(result.model_dump_json())
    payload["passed"] = result.passed
    payload["pass_count"] = result.pass_count
    payload["fail_count"] = result.fail_count
    payload["contracts_pass_count"] = result.contracts_pass_count
    payload["contracts_fail_count"] = result.contracts_fail_count
    # Stamp the spec the contracts were derived against. Lets a CI
    # report archive prove "this run was conformance-tested against
    # commit X of the A2A spec on date Y."
    from a2a_testbed.spec_meta import load_spec_meta

    meta = load_spec_meta()
    payload["spec"] = {
        "name": meta.name,
        "version": meta.version,
        "commit": meta.commit,
        "specification_url": meta.specification_url if meta.commit else "",
        "last_reviewed": meta.last_reviewed,
    }
    return json.dumps(payload, indent=2, default=str)


def _to_markdown(result: ScenarioResult) -> str:
    from a2a_testbed.spec_meta import load_spec_meta

    meta = load_spec_meta()
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"# Scenario report: {result.scenario_name}",
        "",
        f"**Status:** {status}",
        f"**Mode:** {result.mode.value}",
        f"**Steps:** {result.pass_count} passed / {result.fail_count} failed",
    ]
    if result.contracts:
        lines.append(
            f"**Contracts:** {result.contracts_pass_count} passed / "
            f"{result.contracts_fail_count} failed against "
            f"{meta.name} {meta.version}"
            + (f" (commit `{meta.short_commit}`)" if meta.short_commit else "")
        )
    if result.acs_verdicts:
        blocked_steps = sum(1 for s in result.steps if s.acs_blocked)
        lines.append(
            f"**ACS:** {len(result.acs_verdicts)} verdicts, "
            f"{result.acs_blocked_count} blocking"
            + (f" · {blocked_steps} step(s) blocked" if blocked_steps else "")
        )
    lines.extend(
        [
            f"**Started:** {result.started_at.isoformat()}",
            f"**Finished:** {result.finished_at.isoformat()}",
            f"**Elapsed:** {result.elapsed_ms:.1f} ms",
            "",
            "## Steps",
            "",
            "| # | Kind | From → To | Action | Status | Detail |",
            "|---|---|---|---|---|---|",
        ]
    )
    for r in result.steps:
        s = r.step
        check = "✓" if r.passed else "✗"
        detail = r.detail.replace("|", "\\|")
        from_to = f"{s.from_ or '—'} → {s.to or '—'}"
        action = f"`{s.action}`" if s.action else "—"
        lines.append(
            f"| {r.step_index} | {s.kind.value} | {from_to} | {action} | {check} | {detail} |"
        )

    if result.contracts:
        spec_url = meta.specification_url if meta.commit else meta.source_repo
        lines.extend(
            [
                "",
                "## Conformance contracts",
                "",
                f"Each row below maps to a clause in the A2A "
                f"specification. Source: [{meta.name} {meta.version}]"
                f"({spec_url}).",
                "",
                "| Spec § | Contract | Agent | Status | Detail |",
                "|---|---|---|---|---|",
            ]
        )
        for c in result.contracts:
            check = "✓" if c.passed else "✗"
            detail = c.detail.replace("|", "\\|") or "—"
            lines.append(
                f"| {c.spec_section or '—'} | `{c.contract_id}` | "
                f"{c.agent_id or '—'} | {check} | {detail} |"
            )

    acs_verdicts = result.acs_verdicts
    if acs_verdicts:
        decision_icon = {
            "allow": "🟢 allow",
            "warn": "🟡 warn",
            "deny": "🔴 deny",
            "escalate": "🟣 escalate",
        }
        lines.extend(
            [
                "",
                "## ACS runtime governance",
                "",
                "Per-step verdicts from the applied Agent Control "
                "Specification (ACS) manifest. See "
                "[docs/ACS.md](../../docs/ACS.md).",
                "",
                "| Step | Intervention point | Decision | Policy | Why |",
                "|---|---|---|---|---|",
            ]
        )
        for v in acs_verdicts:
            why = "; ".join(v.get("reasons") or []).replace("|", "\\|") or "—"
            fc = " (fail-closed)" if v.get("failed_closed") else ""
            decision = decision_icon.get(v.get("decision", ""), v.get("decision", "—"))
            lines.append(
                f"| {v.get('step_index', '—')} | "
                f"`{v.get('intervention_point', '—')}` | {decision}{fc} | "
                f"{v.get('policy_id') or '—'} | {why} |"
            )

    return "\n".join(lines) + "\n"


def _to_badge(result: ScenarioResult) -> str:
    total = result.pass_count + result.fail_count
    acs_blocking = result.acs_blocked_count
    if result.passed and acs_blocking == 0:
        label = f"{result.pass_count}/{result.pass_count} ✓"
        color = "#4c1"
    elif result.passed and acs_blocking > 0:
        # Steps passed but ACS flagged blocking verdicts (record mode):
        # amber so a reviewer notices the governance signal.
        label = f"{result.pass_count}/{result.pass_count} ⚠ ACS"
        color = "#dfb317"
    else:
        label = f"{result.pass_count}/{total} ✗"
        color = "#e05d44"
    return _BADGE_TEMPLATE.format(label=label, color=color)
