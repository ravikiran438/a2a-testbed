# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Baseline file: known, accepted contract failures.

A team adopting the conformance gate rarely starts fully green. The
baseline (``.a2a-conformance.yaml`` by default) lists the contracts whose
failure is accepted for now, each with a reason, so CI can gate on
everything else without the exceptions disappearing from view::

    version: 1
    accepted:
      - contract: transport.push_fires_on_completion
        reason: Push delivery ships with the queue migration.
        owner: "@platform-team"      # optional
        expires: 2026-12-31          # optional; the entry stops applying after it

Rules:

- ``reason`` is required. An accepted failure nobody can explain is just
  a hidden failure.
- An entry applies to a ``fail`` or ``error`` result (and, under
  ``--strict``, to a ``warn`` deviation). The row still shows in every
  report, marked accepted, with its reason.
- An entry whose contract now passes is reported as *stale* so it gets
  deleted; it never fails the run.
- An expired entry no longer applies; the run fails on that contract
  again and the report says the entry expired.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from a2a_testbed.contracts.base import ContractResult, ContractStatus

DEFAULT_BASELINE_PATH = ".a2a-conformance.yaml"
BASELINE_VERSION = 1


class BaselineError(ValueError):
    """The baseline file is malformed."""


@dataclass(frozen=True)
class BaselineEntry:
    contract: str
    reason: str
    owner: Optional[str] = None
    expires: Optional[dt.date] = None

    def expired(self, today: dt.date) -> bool:
        return self.expires is not None and today > self.expires


@dataclass
class Baseline:
    path: Optional[Path] = None
    entries: list[BaselineEntry] = field(default_factory=list)

    def entry_for(self, contract_id: str) -> Optional[BaselineEntry]:
        for entry in self.entries:
            if entry.contract == contract_id:
                return entry
        return None


@dataclass
class BaselineReview:
    """What the baseline did to one sweep's results."""

    accepted: dict[str, BaselineEntry] = field(default_factory=dict)
    # Entries whose contract passed (or skipped) this run.
    stale: list[BaselineEntry] = field(default_factory=list)
    # Entries past their expiry date (they no longer apply).
    expired: list[BaselineEntry] = field(default_factory=list)
    # Entries naming a contract this sweep did not run.
    unknown: list[BaselineEntry] = field(default_factory=list)


def _parse_date(value: Any, where: str) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise BaselineError(f"{where}: expires must be a YYYY-MM-DD date, got {value!r}") from exc


def parse_baseline(data: Any, path: Optional[Path] = None) -> Baseline:
    label = str(path) if path else "baseline"
    if data is None:
        return Baseline(path=path)
    if not isinstance(data, dict):
        raise BaselineError(f"{label}: top level must be a mapping")
    version = data.get("version", BASELINE_VERSION)
    if version != BASELINE_VERSION:
        raise BaselineError(f"{label}: unsupported version {version!r} (expected 1)")
    raw = data.get("accepted") or []
    if not isinstance(raw, list):
        raise BaselineError(f"{label}: 'accepted' must be a list")
    entries: list[BaselineEntry] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        where = f"{label}: accepted[{i}]"
        if not isinstance(item, dict):
            raise BaselineError(f"{where} must be a mapping")
        contract = str(item.get("contract") or "").strip()
        if not contract:
            raise BaselineError(f"{where}: 'contract' is required")
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise BaselineError(
                f"{where} ({contract}): 'reason' is required — say why this failure is accepted"
            )
        if contract in seen:
            raise BaselineError(f"{where}: {contract} is listed twice")
        seen.add(contract)
        owner = item.get("owner")
        entries.append(
            BaselineEntry(
                contract=contract,
                reason=reason,
                owner=str(owner).strip() if owner else None,
                expires=_parse_date(item.get("expires"), where),
            )
        )
    return Baseline(path=path, entries=entries)


def load_baseline(path: Path) -> Baseline:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BaselineError(f"{path}: invalid YAML: {exc}") from exc
    return parse_baseline(data, path)


def _acceptable(strict: bool) -> tuple[ContractStatus, ...]:
    """Statuses that fail the run, and so can be accepted by a baseline."""
    base = (ContractStatus.FAIL, ContractStatus.ERROR)
    return (*base, ContractStatus.WARN) if strict else base


def apply_baseline(
    baseline: Baseline,
    results: Iterable[ContractResult],
    *,
    today: Optional[dt.date] = None,
    strict: bool = False,
) -> BaselineReview:
    today = today or dt.date.today()
    acceptable = _acceptable(strict)
    review = BaselineReview()
    by_id = {r.contract_id: r for r in results}
    for entry in baseline.entries:
        result = by_id.get(entry.contract)
        if result is None:
            review.unknown.append(entry)
            continue
        if entry.expired(today):
            review.expired.append(entry)
            continue
        if result.status in acceptable:
            review.accepted[entry.contract] = entry
        else:
            review.stale.append(entry)
    return review


def render_baseline(
    results: Iterable[ContractResult], *, agent_url: str = "", strict: bool = False
) -> str:
    """A starter baseline accepting every current fail/error.

    Reasons are left empty on purpose: the file will not load until
    someone writes down why each failure is acceptable.
    """
    failing = [r for r in results if r.status in _acceptable(strict)]
    lines = [
        "# a2a-testbed conformance baseline: accepted failures.",
        "# Fill in a reason for every entry (the file is rejected while any",
        "# reason is empty). Optional per entry: owner, expires (YYYY-MM-DD).",
        "# Delete entries once their contract passes; the report flags them.",
    ]
    if agent_url:
        lines.append(f"# Generated from a sweep of {agent_url}")
    lines.append(f"version: {BASELINE_VERSION}")
    if not failing:
        lines.append("accepted: []")
        return "\n".join(lines) + "\n"
    lines.append("accepted:")
    for r in failing:
        detail = " ".join((r.detail or "").split())
        if len(detail) > 100:
            detail = detail[:97] + "..."
        lines.append(f"  - contract: {r.contract_id}")
        if detail:
            lines.append(f"    # {r.status.value}: {detail}")
        lines.append('    reason: ""')
    return "\n".join(lines) + "\n"
