# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""AgentCard compatibility checker — produces a CompatReport for a card.

Static check (no live agent needed). Given an AgentCard JSON:
  1. Detect which dialect it most closely matches.
  2. Apply the dialect's field map to project source fields onto
     canonical A2A 1.0 paths.
  3. Validate the projected card against ``a2a.types.AgentCard``.
  4. Surface field-level findings (missing required, unmapped source,
     dialect-specific warnings).

The result is a ``CompatReport`` you can render to markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from a2a_testbed.vendors.dialects import Dialect, detect_dialect


class CompatFindingKind(str, Enum):
    OK = "ok"
    MAPPED_FIELD = "mapped_field"
    MISSING_REQUIRED = "missing_required"
    UNMAPPED_SOURCE_FIELD = "unmapped_source_field"
    DIALECT_NOTE = "dialect_note"
    UNKNOWN_DIALECT = "unknown_dialect"


@dataclass(frozen=True)
class CompatFinding:
    kind: CompatFindingKind
    detail: str
    source_path: Optional[str] = None
    target_path: Optional[str] = None


@dataclass
class CompatReport:
    dialect: Optional[Dialect]
    a2a_compliant: bool
    findings: list[CompatFinding] = field(default_factory=list)


# Subset of A2A 1.0 AgentCard fields that the checker treats as required.
# Pulled from the published spec; conservative set.
REQUIRED_A2A_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "url",
    "version",
    "supportedInterfaces",
    "capabilities",
    "skills",
)


def _get_path(obj: Any, path: str) -> Optional[Any]:
    """Get a dotted path from a dict, treating ``[]`` as 'first item'.

    Used only for presence detection; the checker does not deeply
    transform the card. Returns None on any miss.
    """
    cur: Any = obj
    for part in path.split("."):
        if part.endswith("[]"):
            key = part[:-2]
            if not isinstance(cur, dict) or key not in cur:
                return None
            value = cur[key]
            if not isinstance(value, list) or not value:
                return None
            cur = value[0]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
    return cur


def check_compat(
    card: dict[str, Any],
    *,
    dialect: Optional[Dialect] = None,
    extra_dialects: tuple[Dialect, ...] = (),
) -> CompatReport:
    """Produce a ``CompatReport`` for a single AgentCard.

    ``dialect`` may be supplied explicitly (for tests or when the user
    knows the source platform). Otherwise it is auto-detected by
    ``detect_dialect``. ``extra_dialects`` lets callers inject
    user-supplied dialect records (loaded from ``--dialect-file``
    JSON) without mutating module-level state.
    """
    detected = dialect or detect_dialect(card, extra_dialects=extra_dialects)

    findings: list[CompatFinding] = []

    if detected is None:
        findings.append(
            CompatFinding(
                kind=CompatFindingKind.UNKNOWN_DIALECT,
                detail=(
                    "no registered dialect matched any identifying field; "
                    "treating card as opaque and validating only against "
                    "A2A 1.0 required-field presence"
                ),
            )
        )
        a2a_target = card
    else:
        # Project source fields onto canonical A2A paths.
        a2a_target = dict(card)  # shallow copy; field_map only checks presence
        for source_path, target_path in detected.field_map.items():
            value = _get_path(card, source_path)
            if value is None:
                continue
            if target_path is None:
                findings.append(
                    CompatFinding(
                        kind=CompatFindingKind.UNMAPPED_SOURCE_FIELD,
                        detail=(
                            f"{source_path!r} has no A2A 1.0 analogue in "
                            f"the {detected.name} dialect; consider "
                            "exposing it via capabilities.extensions[]"
                        ),
                        source_path=source_path,
                    )
                )
            else:
                findings.append(
                    CompatFinding(
                        kind=CompatFindingKind.MAPPED_FIELD,
                        detail=f"{source_path!r} → {target_path!r}",
                        source_path=source_path,
                        target_path=target_path,
                    )
                )
                # Patch the projected card so the required-field check
                # below accepts the mapping. Top-level only; nested
                # synthesis is out of scope for the static check.
                if "." not in target_path and "[]" not in target_path:
                    a2a_target.setdefault(target_path, value)

        for note in detected.notes:
            findings.append(
                CompatFinding(kind=CompatFindingKind.DIALECT_NOTE, detail=note)
            )

    # Required-field presence check against A2A 1.0.
    missing = [f for f in REQUIRED_A2A_FIELDS if f not in a2a_target]
    for f in missing:
        findings.append(
            CompatFinding(
                kind=CompatFindingKind.MISSING_REQUIRED,
                detail=(
                    f"A2A 1.0 requires top-level field {f!r} which is "
                    "absent (and no dialect map produces it)"
                ),
                target_path=f,
            )
        )

    if not missing:
        findings.append(
            CompatFinding(
                kind=CompatFindingKind.OK,
                detail="all A2A 1.0 required fields present (after dialect mapping)",
            )
        )

    return CompatReport(
        dialect=detected,
        a2a_compliant=(len(missing) == 0),
        findings=findings,
    )
