# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Machine-readable conformance reports: JSON, JUnit XML, SARIF, Markdown.

One ``SweepReport`` (results + baseline review + exit policy) renders to
every format, so the terminal table, the CI job summary, the code-scanning
upload and the test-report widget never disagree.

Exit codes (``SweepReport.exit_code``):

- ``0`` — every contract passed, skipped, or is accepted by the baseline.
- ``1`` — at least one contract failed (the agent answered and broke a
  rule). With ``--strict``, soft-pass deviations count too.
- ``3`` — no failures, but at least one contract could not reach the
  agent or timed out even after a retry. Lets a workflow tolerate an
  unreachable preview while still failing on wrong answers.
- ``2`` — usage error, or the agent could not be reached at all (set by
  the CLI, not here).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional

from a2a_testbed.conformance.baseline import BaselineEntry, BaselineReview
from a2a_testbed.contracts.base import ContractResult, ContractStatus
from a2a_testbed.spec_meta import load_spec_meta

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_ERRORS_ONLY = 3

TOOL_NAME = "a2a-testbed"
TOOL_URI = "https://github.com/ravikiran438/a2a-testbed"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"

# Effective outcome of a row once the baseline is applied.
ACCEPTED = "accepted"

_SYMBOL = {
    "pass": "✓",
    "warn": "~",
    "skip": "–",
    "fail": "✗",
    "error": "!",
    ACCEPTED: "○",
}


def tool_version() -> str:
    try:
        from importlib.metadata import version

        return version("a2a-testbed")
    except Exception:  # pragma: no cover - not installed
        return "0+unknown"


@dataclass
class Row:
    result: ContractResult
    description: str
    baseline: Optional[BaselineEntry]

    @property
    def id(self) -> str:
        return self.result.contract_id

    @property
    def status(self) -> ContractStatus:
        assert self.result.status is not None
        return self.result.status

    @property
    def outcome(self) -> str:
        return ACCEPTED if self.baseline is not None else self.status.value

    @property
    def symbol(self) -> str:
        return _SYMBOL[self.outcome]


@dataclass
class SweepReport:
    """One conformance run, ready to render."""

    target: str
    results: list[ContractResult]
    descriptions: dict[str, str] = field(default_factory=dict)
    review: BaselineReview = field(default_factory=BaselineReview)
    kind: str = "sweep"  # "sweep" (live agent) or "lint" (card file)
    protocol_version: Optional[str] = None
    push_receiver: Optional[str] = None
    strict: bool = False

    @property
    def rows(self) -> list[Row]:
        return [
            Row(
                r, self.descriptions.get(r.contract_id, ""), self.review.accepted.get(r.contract_id)
            )
            for r in self.results
        ]

    def count(self, outcome: str) -> int:
        return sum(1 for row in self.rows if row.outcome == outcome)

    @property
    def blocking(self) -> list[Row]:
        bad = {"fail", "warn"} if self.strict else {"fail"}
        return [row for row in self.rows if row.outcome in bad]

    @property
    def errors(self) -> list[Row]:
        return [row for row in self.rows if row.outcome == "error"]

    @property
    def exit_code(self) -> int:
        if self.blocking:
            return EXIT_FAILED
        if self.errors:
            return EXIT_ERRORS_ONLY
        return EXIT_OK

    @property
    def verdict(self) -> str:
        return {EXIT_OK: "pass", EXIT_FAILED: "fail", EXIT_ERRORS_ONLY: "error"}[self.exit_code]

    def summary(self) -> dict[str, int]:
        counts = {o: self.count(o) for o in ("pass", "warn", "skip", "fail", "error", ACCEPTED)}
        counts["total"] = len(self.results)
        return counts


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def _entry_json(entry: BaselineEntry) -> dict[str, Any]:
    out: dict[str, Any] = {"contract": entry.contract, "reason": entry.reason}
    if entry.owner:
        out["owner"] = entry.owner
    if entry.expires:
        out["expires"] = entry.expires.isoformat()
    return out


def to_json(report: SweepReport) -> str:
    meta = load_spec_meta()
    payload = {
        "tool": {"name": TOOL_NAME, "version": tool_version()},
        "kind": report.kind,
        "target": report.target,
        "protocol_version": report.protocol_version,
        "push_receiver": report.push_receiver,
        "spec": {
            "name": meta.name,
            "version": meta.version,
            "commit": meta.commit,
            "specification_url": meta.specification_url if meta.commit else "",
        },
        "verdict": report.verdict,
        "exit_code": report.exit_code,
        "strict": report.strict,
        "summary": report.summary(),
        "results": [
            {
                "id": row.id,
                "outcome": row.outcome,
                "status": row.status.value,
                "description": row.description,
                "spec_section": row.result.spec_section,
                "category": row.result.category.value if row.result.category else None,
                "detail": row.result.detail,
                "attempts": row.result.attempts,
                "baseline": _entry_json(row.baseline) if row.baseline else None,
            }
            for row in report.rows
        ],
        "baseline": {
            "stale": [_entry_json(e) for e in report.review.stale],
            "expired": [_entry_json(e) for e in report.review.expired],
            "unknown": [_entry_json(e) for e in report.review.unknown],
        },
    }
    return json.dumps(payload, indent=2) + "\n"


# --------------------------------------------------------------------------
# JUnit XML
# --------------------------------------------------------------------------


def to_junit(report: SweepReport) -> str:
    s = report.summary()
    suite = ET.Element(
        "testsuite",
        {
            "name": f"a2a-conformance {report.target}",
            "tests": str(s["total"]),
            "failures": str(len(report.blocking)),
            "errors": str(s["error"]),
            "skipped": str(s["skip"] + s[ACCEPTED]),
        },
    )
    for row in report.rows:
        classname = f"a2a.{row.result.category.value}" if row.result.category else "a2a"
        case = ET.SubElement(suite, "testcase", {"classname": classname, "name": row.id})
        detail = row.result.detail or ""
        section = f" ({row.result.spec_section})" if row.result.spec_section else ""
        if row.outcome == ACCEPTED:
            assert row.baseline is not None
            ET.SubElement(
                case,
                "skipped",
                {"message": f"accepted by baseline: {row.baseline.reason}"},
            ).text = detail
        elif row.outcome == "skip":
            ET.SubElement(case, "skipped", {"message": detail})
        elif row.outcome == "fail" or (row.outcome == "warn" and report.strict):
            ET.SubElement(case, "failure", {"message": f"{row.description}{section}"}).text = detail
        elif row.outcome == "error":
            ET.SubElement(case, "error", {"message": "agent unreachable or too slow"}).text = detail
        elif row.outcome == "warn":
            ET.SubElement(case, "system-out").text = f"deviation: {detail}"
    root = ET.Element("testsuites")
    root.append(suite)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# --------------------------------------------------------------------------
# SARIF 2.1.0 (GitHub code scanning)
# --------------------------------------------------------------------------


def to_sarif(report: SweepReport, *, location: str, category: Optional[str] = None) -> str:
    """SARIF log with one result per non-passing row.

    Code scanning anchors every result to a file in the repository;
    ``location`` is that file (the AgentCard, by default). Accepted
    rows carry an external suppression with the baseline reason, so
    they show as dismissed rather than disappearing.

    ``category`` names the analysis (``automationDetails.id``). Code
    scanning keeps one set of alerts per category, so give each agent
    its own when one workflow checks several; the default is one
    category per kind of check (``sweep`` / ``lint``). Fingerprints use
    the contract and the file, not the agent URL, so per-PR preview URLs
    do not reopen the same alert.
    """
    meta = load_spec_meta()
    help_uri = meta.specification_url if meta.commit else TOOL_URI
    rows = report.rows
    rules = [
        {
            "id": row.id,
            "name": row.id.split(".")[-1],
            "shortDescription": {"text": row.description or row.id},
            "helpUri": help_uri,
            "properties": {
                "tags": ["a2a", "conformance"],
                **({"spec_section": row.result.spec_section} if row.result.spec_section else {}),
            },
        }
        for row in rows
    ]
    rule_index = {row.id: i for i, row in enumerate(rows)}
    results = []
    for row in rows:
        if row.outcome in ("pass", "skip"):
            continue
        if row.outcome == "warn" and not report.strict:
            level = "note"
        elif row.outcome in ("fail", "warn"):
            level = "error"
        elif row.outcome == "error":
            level = "warning"
        else:  # accepted
            level = "error" if row.status is ContractStatus.FAIL else "warning"
        section = f" ({row.result.spec_section})" if row.result.spec_section else ""
        prefix = "Could not verify" if row.status is ContractStatus.ERROR else "Violation"
        text = f"{prefix}{section} on {report.target}: {row.result.detail or row.description}"
        result: dict[str, Any] = {
            "ruleId": row.id,
            "ruleIndex": rule_index[row.id],
            "level": level,
            "message": {"text": text},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": location},
                        "region": {"startLine": 1},
                    }
                }
            ],
            "partialFingerprints": {"contract": f"{row.id}@{location}"},
        }
        if row.baseline is not None:
            result["suppressions"] = [{"kind": "external", "justification": row.baseline.reason}]
        results.append(result)
    log = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": tool_version(),
                        "informationUri": TOOL_URI,
                        "rules": rules,
                    }
                },
                "automationDetails": {
                    "id": f"{(category or f'a2a-conformance/{report.kind}').rstrip('/')}/"
                },
                "results": results,
            }
        ],
    }
    return json.dumps(log, indent=2) + "\n"


# --------------------------------------------------------------------------
# Markdown (GitHub job summary)
# --------------------------------------------------------------------------


def _md(text: str) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def to_markdown(report: SweepReport) -> str:
    meta = load_spec_meta()
    s = report.summary()
    headline = {
        "pass": "✅ Conformant",
        "fail": "❌ Not conformant",
        "error": "⚠️ Could not verify (agent unreachable or too slow)",
    }[report.verdict]
    what = "AgentCard lint" if report.kind == "lint" else "A2A conformance"
    spec = f"{meta.name} {meta.version}" + (
        f" (`{meta.short_commit}`)" if meta.short_commit else ""
    )
    lines = [
        f"### {what}: {headline}",
        "",
        f"`{report.target}` vs. {spec}"
        + (f", probed as A2A {report.protocol_version}" if report.protocol_version else ""),
        "",
        f"**{s['pass']}** passed · **{s['warn']}** deviations · **{s['skip']}** skipped · "
        f"**{s['fail']}** failed · **{s['error']}** errors · **{s[ACCEPTED]}** accepted "
        f"(baseline) · {s['total']} total",
        "",
    ]
    attention = [r for r in report.rows if r.outcome in ("fail", "error", ACCEPTED)] + [
        r for r in report.rows if r.outcome == "warn"
    ]
    if attention:
        lines += ["| | Contract | Spec § | Detail |", "|---|---|---|---|"]
        for row in attention:
            detail = row.result.detail
            if row.baseline is not None:
                detail = f"accepted: {row.baseline.reason} — {detail}"
            lines.append(
                f"| {row.symbol} {row.outcome} | `{row.id}` | {row.result.spec_section or '—'} "
                f"| {_md(detail)} |"
            )
        lines.append("")
    notes = []
    for entry in report.review.stale:
        notes.append(f"- `{entry.contract}` now passes; delete it from the baseline.")
    for entry in report.review.expired:
        assert entry.expires is not None
        notes.append(
            f"- `{entry.contract}` baseline entry expired on {entry.expires.isoformat()}; "
            "it is enforced again."
        )
    for entry in report.review.unknown:
        notes.append(f"- `{entry.contract}` is in the baseline but was not run.")
    if notes:
        lines += ["**Baseline**", "", *notes, ""]
    lines += [
        "<details><summary>All contracts</summary>",
        "",
        "| | Contract | Spec § | Detail |",
        "|---|---|---|---|",
    ]
    for row in report.rows:
        lines.append(
            f"| {row.symbol} | `{row.id}` | {row.result.spec_section or '—'} "
            f"| {_md(row.result.detail) or '—'} |"
        )
    lines += ["", "</details>", ""]
    return "\n".join(lines)


FORMATS = {
    "json": to_json,
    "junit": to_junit,
    "markdown": to_markdown,
}
# File extensions recognised by ``--report PATH``.
EXTENSIONS = {
    ".json": "json",
    ".xml": "junit",
    ".sarif": "sarif",
    ".md": "markdown",
    ".markdown": "markdown",
}


def render(
    report: SweepReport,
    fmt: str,
    *,
    sarif_location: str,
    sarif_category: Optional[str] = None,
) -> str:
    if fmt == "sarif":
        return to_sarif(report, location=sarif_location, category=sarif_category)
    try:
        return FORMATS[fmt](report)
    except KeyError:
        raise ValueError(f"unknown report format {fmt!r}") from None
