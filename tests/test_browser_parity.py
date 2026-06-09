# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Browser ↔ Python parity guard.

The testbed maintains several behaviours in two languages — the Python
source of truth and a TypeScript port that runs in the playground:

  - conformance contracts  (contracts/*  ↔  playground/src/conformance/)
  - the ACS validator      (acs/manifest.py  ↔  playground/src/acsValidator.ts)
  - the ACS evaluator      (acs/evaluator.py ↔  playground/src/acsEvaluator.ts)

These can silently drift if a kind / op / intervention point / contract is
added on one side but not the other. This module fingerprints both
registries from source (no JS execution required, so it runs in any CI)
and fails on any divergence — the automated successor to the "same id
strings + eyeball diff" discipline.

Behavioural parity (same verdicts on shared fixtures) was validated with
cross-language harnesses when these ports were written; this guard keeps
the *surfaces* from diverging thereafter.
"""

from __future__ import annotations

import re
from pathlib import Path

from a2a_testbed.acs.evaluator import _OPS
from a2a_testbed.acs.manifest import AcsFindingKind
from a2a_testbed.acs.types import Decision, InterventionPoint


REPO = Path(__file__).resolve().parents[1]
PG = REPO / "playground" / "src"
PY_TRANSPORT = REPO / "src" / "a2a_testbed" / "contracts" / "transport"
TS_CONFORMANCE = PG / "conformance" / "contracts"


def _read(rel: str) -> str:
    return (PG / rel).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


# ---------------------------------------------------------------------------
# ACS surface parity
# ---------------------------------------------------------------------------


def test_acs_finding_kinds_parity():
    block = _between(_read("acsValidator.ts"), "export type AcsFindingKind =", ";")
    ts = set(re.findall(r"'([a-z_]+)'", block))
    py = {k.value for k in AcsFindingKind}
    assert ts == py, f"ACS finding-kind drift: TS-only={ts - py}, PY-only={py - ts}"


def test_acs_decisions_parity():
    line = next(ln for ln in _read("acsEvaluator.ts").splitlines() if "export type Decision" in ln)
    ts = set(re.findall(r"'([a-z]+)'", line))
    py = {d.value for d in Decision}
    assert ts == py, f"ACS decision drift: TS-only={ts - py}, PY-only={py - ts}"


def test_acs_intervention_points_parity():
    val = _read("acsValidator.ts")
    all_block = _between(val, "const ALL_POINTS", "]")
    ts_all = set(re.findall(r"'([a-z_]+)'", all_block))
    py_all = {p.value for p in InterventionPoint}
    assert ts_all == py_all, (
        f"intervention-point drift: TS-only={ts_all - py_all}, PY-only={py_all - ts_all}"
    )

    obs_block = _between(val, "OBSERVABLE_AT_WIRE", "]")
    ts_obs = set(re.findall(r"'([a-z_]+)'", obs_block))
    py_obs = {p.value for p in InterventionPoint.observable_at_wire()}
    assert ts_obs == py_obs, (
        f"observable-point drift: TS-only={ts_obs - py_obs}, PY-only={py_obs - ts_obs}"
    )


def test_acs_builtin_ops_parity():
    py_ops = set(_OPS)
    # acsEvaluator.ts OPS map
    ev_block = _between(_read("acsEvaluator.ts"), "const OPS: Record", "};")
    ts_ops = set(re.findall(r"^\s*([a-z_]+):", ev_block, re.MULTILINE))
    # acsValidator.ts BUILTIN_OPS set (used for structural validation)
    val_block = _between(_read("acsValidator.ts"), "const BUILTIN_OPS", "]")
    ts_validator_ops = set(re.findall(r"'([a-z_]+)'", val_block))
    assert ts_ops == py_ops, (
        f"evaluator op drift: TS-only={ts_ops - py_ops}, PY-only={py_ops - ts_ops}"
    )
    assert ts_validator_ops == py_ops, (
        f"validator op drift: TS-only={ts_validator_ops - py_ops}, PY-only={py_ops - ts_validator_ops}"
    )


def test_acs_spec_version_parity():
    ts = re.search(r"ACS_SPEC_VERSION\s*=\s*'([^']+)'", _read("acsValidator.ts"))
    ts_eval = re.search(r"ACS_SPEC_VERSION\s*=\s*'([^']+)'", _read("acsEvaluator.ts"))
    from a2a_testbed.acs.types import ACS_SPEC_VERSION

    assert ts is not None and ts.group(1) == ACS_SPEC_VERSION
    # acsEvaluator may not redeclare it; only assert when present.
    if ts_eval is not None:
        assert ts_eval.group(1) == ACS_SPEC_VERSION


# ---------------------------------------------------------------------------
# Conformance contract parity (the original drift concern)
# ---------------------------------------------------------------------------


def _ids(paths, pattern: str) -> set[str]:
    out: set[str] = set()
    for p in paths:
        out |= set(re.findall(pattern, p.read_text(encoding="utf-8")))
    return out


def test_transport_contract_ids_parity():
    py_ids = _ids(sorted(PY_TRANSPORT.glob("*.py")), r'id="(transport\.[a-z0-9_]+)"')
    ts_ids = _ids(sorted(TS_CONFORMANCE.glob("*.ts")), r"id: '(transport\.[a-z0-9_]+)'")
    assert py_ids, "no Python transport contract ids found — test wiring broke"
    assert ts_ids == py_ids, (
        f"transport-contract drift: TS-only={ts_ids - py_ids}, PY-only={py_ids - ts_ids}"
    )
