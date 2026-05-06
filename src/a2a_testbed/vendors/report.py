# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Markdown rendering for ``CompatReport``."""

from __future__ import annotations

from a2a_testbed.vendors.checker import (
    CompatFindingKind,
    CompatReport,
)


_KIND_HEADERS = {
    CompatFindingKind.OK: "✓ A2A 1.0 compliance",
    CompatFindingKind.MAPPED_FIELD: "Mapped fields",
    CompatFindingKind.MISSING_REQUIRED: "Missing required fields",
    CompatFindingKind.UNMAPPED_SOURCE_FIELD: "Unmapped source fields",
    CompatFindingKind.DIALECT_NOTE: "Dialect notes",
    CompatFindingKind.UNKNOWN_DIALECT: "Unknown dialect",
}


def render_markdown(report: CompatReport) -> str:
    """Render a ``CompatReport`` as a markdown report.

    Sections are organized by finding kind so a reviewer can skim and
    focus on the actionable parts (missing required fields,
    unmappable source fields).
    """
    lines: list[str] = []
    lines.append("# AgentCard Compatibility Report")
    lines.append("")

    if report.dialect is not None:
        lines.append(f"**Detected dialect:** {report.dialect.name}")
    else:
        lines.append("**Detected dialect:** _unrecognized_")
    lines.append("")

    if report.a2a_compliant:
        lines.append("**Status:** ✓ A2A 1.0 compliant (after dialect mapping).")
    else:
        lines.append(
            "**Status:** ✗ Not A2A 1.0 compliant — required fields missing."
        )
    lines.append("")

    by_kind: dict[CompatFindingKind, list] = {}
    for f in report.findings:
        by_kind.setdefault(f.kind, []).append(f)

    # Stable section order: status first, then mapped, then missing, then unmapped, then notes.
    section_order = [
        CompatFindingKind.OK,
        CompatFindingKind.MAPPED_FIELD,
        CompatFindingKind.MISSING_REQUIRED,
        CompatFindingKind.UNMAPPED_SOURCE_FIELD,
        CompatFindingKind.DIALECT_NOTE,
        CompatFindingKind.UNKNOWN_DIALECT,
    ]
    for kind in section_order:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.append(f"## {_KIND_HEADERS[kind]}")
        lines.append("")
        for f in items:
            if (
                kind in {CompatFindingKind.MAPPED_FIELD}
                and f.source_path is not None
                and f.target_path is not None
            ):
                lines.append(f"- `{f.source_path}` → `{f.target_path}`")
            elif (
                kind == CompatFindingKind.MISSING_REQUIRED
                and f.target_path is not None
            ):
                lines.append(f"- `{f.target_path}` — {f.detail}")
            elif (
                kind == CompatFindingKind.UNMAPPED_SOURCE_FIELD
                and f.source_path is not None
            ):
                lines.append(f"- `{f.source_path}` — {f.detail}")
            else:
                lines.append(f"- {f.detail}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
