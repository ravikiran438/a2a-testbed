# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the Agent Control Specification (ACS) support.

Covers the four foundational guarantees:
  1. The local validator parses + cross-checks a manifest into Findings.
  2. The builtin policy engine enforces allow/deny verdicts.
  3. The evaluator fails closed when evidence or the policy backend errors.
  4. The wire seam shapes a WireExchange into the right canonical input,
     version-agnostically.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2a_testbed.acs import (
    ACS_SPEC_VERSION,
    AcsEvaluator,
    AcsFindingKind,
    AcsManifest,
    BuiltinRule,
    Decision,
    InterventionPoint,
    InterventionPointDecl,
    PolicyDecl,
    PolicyType,
    snapshot_for,
    validate_manifest,
)
from a2a_testbed.contracts.policy import (
    make_acs_enforcement_contract,
    make_acs_fail_closed_contract,
)
from a2a_testbed.core.observer import WireExchange


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "examples" / "acs" / "email-agent.acs.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _deny_external_manifest() -> AcsManifest:
    """A minimal manifest: deny pre_tool_call when recipient is external."""
    return AcsManifest(
        metadata={"name": "test-email-agent"},
        policies={
            "email_policy": PolicyDecl(
                type=PolicyType.BUILTIN,
                default_decision=Decision.ALLOW,
                rules=[
                    BuiltinRule(
                        name="deny-external-domain",
                        field="policy_target.value.message.to",
                        op="endswith",
                        value="@external.example",
                        decision=Decision.DENY,
                        description="recipient outside the org",
                    )
                ],
            )
        },
        intervention_points={
            InterventionPoint.PRE_TOOL_CALL: InterventionPointDecl(
                policy_target="$.tool_call.args",
                policy_target_kind="tool_args",
                tool_name_from="$.tool_call.name",
                policy="email_policy",
                evidence=["recipient_classifier"],
            )
        },
    )


def _exchange(to: str) -> WireExchange:
    return WireExchange(
        receiver_id="send_email",
        request_body={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {"message": {"to": to, "text": "hi"}},
        },
        response_body={"jsonrpc": "2.0", "id": "1", "result": {"ok": True}},
    )


# ---------------------------------------------------------------------------
# 1. Local validator
# ---------------------------------------------------------------------------


def test_render_spec_md():
    from a2a_testbed.acs import render_spec_md

    manifest = validate_manifest(
        REPO_ROOT / "examples" / "acs" / "three-party-governance.acs.yaml"
    ).manifest
    md = render_spec_md(manifest)
    assert "# ACS governance summary: three-party-governance" in md
    assert "`pre_tool_call`" in md
    # Rules render in plain English.
    assert "**deny** when `tool.security_labels` contains" in md
    assert "fail-closed" in md
    # Tools table present.
    assert "| `carol` | external |" in md


def test_starter_manifest_scaffold_validates():
    from a2a_testbed.acs import starter_manifest_yaml

    text = starter_manifest_yaml("scaffold-test")
    result = validate_manifest(text)
    assert result.ok, [f"{f.kind.value}: {f.detail}" for f in result.findings]
    assert result.manifest.metadata["name"] == "scaffold-test"


def test_validate_example_manifest_ok():
    result = validate_manifest(EXAMPLE)
    assert result.manifest is not None
    assert result.ok, [f"{f.kind.value}: {f.detail}" for f in result.findings]
    assert result.manifest.agent_control_specification_version == ACS_SPEC_VERSION


def test_validator_flags_undeclared_policy():
    bad = {
        "agent_control_specification_version": ACS_SPEC_VERSION,
        "intervention_points": {"input": {"policy": "missing_policy"}},
    }
    result = validate_manifest(bad)
    kinds = {f.kind for f in result.findings}
    assert AcsFindingKind.ERROR_POLICY_REF in kinds
    assert not result.ok


def test_validator_flags_non_observable_model_point():
    m = {
        "agent_control_specification_version": ACS_SPEC_VERSION,
        "policies": {"p": {"type": "builtin"}},
        "intervention_points": {"pre_model_call": {"policy": "p"}},
    }
    result = validate_manifest(m)
    kinds = {f.kind for f in result.findings}
    assert AcsFindingKind.WARN_NON_OBSERVABLE_POINT in kinds
    # Warning only — still usable.
    assert result.ok


def test_validator_reports_parse_error():
    result = validate_manifest("this: : : not valid yaml: [")
    assert result.manifest is None
    assert result.findings[0].kind == AcsFindingKind.ERROR_PARSE


# ---------------------------------------------------------------------------
# 2. Builtin enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builtin_denies_external_recipient():
    manifest = _deny_external_manifest()
    evaluator = AcsEvaluator(fail_closed=True)
    evaluator.register_evidence("recipient_classifier", _noop_evidence)
    snapshot = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@external.example"))
    verdict = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, snapshot)
    assert verdict.decision == Decision.DENY
    assert verdict.rule_name == "deny-external-domain"
    assert not verdict.failed_closed


@pytest.mark.asyncio
async def test_builtin_allows_internal_recipient():
    manifest = _deny_external_manifest()
    evaluator = AcsEvaluator(fail_closed=True)
    evaluator.register_evidence("recipient_classifier", _noop_evidence)
    snapshot = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@internal.example"))
    verdict = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, snapshot)
    assert verdict.decision == Decision.ALLOW


async def _noop_evidence(_canonical: dict) -> dict:
    return {"recipient_classifier": "ok"}


# ---------------------------------------------------------------------------
# 3. Fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_failure_denies_closed():
    manifest = _deny_external_manifest()

    async def boom(_c):
        raise RuntimeError("evidence down")

    evaluator = AcsEvaluator(fail_closed=True)
    evaluator.register_evidence("recipient_classifier", boom)
    snapshot = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@internal.example"))
    verdict = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, snapshot)
    # Internal recipient would normally ALLOW; evidence failure forces deny.
    assert verdict.decision == Decision.DENY
    assert verdict.failed_closed


@pytest.mark.asyncio
async def test_missing_evidence_provider_denies_closed():
    manifest = _deny_external_manifest()
    evaluator = AcsEvaluator(fail_closed=True)  # no provider registered
    snapshot = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@internal.example"))
    verdict = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, snapshot)
    assert verdict.decision == Decision.DENY
    assert verdict.failed_closed


@pytest.mark.asyncio
async def test_rego_without_backend_denies_closed():
    manifest = AcsManifest(
        policies={"p": PolicyDecl(type=PolicyType.REGO, bundle="./p", query="data.x")},
        intervention_points={InterventionPoint.OUTPUT: InterventionPointDecl(policy="p")},
    )
    evaluator = AcsEvaluator(fail_closed=True)
    verdict = await evaluator.evaluate(manifest, InterventionPoint.OUTPUT, {"output": {}})
    assert verdict.decision == Decision.DENY
    assert verdict.failed_closed


# ---------------------------------------------------------------------------
# 4. Wire seam + contracts
# ---------------------------------------------------------------------------


def test_snapshot_is_version_agnostic():
    # Same logical handoff, different A2A-ish envelopes -> same tool_call shape.
    v1 = _exchange("x@internal.example")
    v0 = WireExchange(
        receiver_id="send_email",
        request_body={
            "method": "message/send",
            "params": {"message": {"to": "x@internal.example"}},
        },
        response_body={"result": {"ok": True}},
    )
    s1 = snapshot_for(InterventionPoint.PRE_TOOL_CALL, v1)
    s0 = snapshot_for(InterventionPoint.PRE_TOOL_CALL, v0)
    assert s1["tool_call"]["name"] == s0["tool_call"]["name"] == "send_email"
    assert s1["tool_call"]["args"]["message"]["to"] == s0["tool_call"]["args"]["message"]["to"]


@pytest.mark.asyncio
async def test_fail_closed_contract_passes():
    manifest = _deny_external_manifest()
    snapshot = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@internal.example"))
    contract = make_acs_fail_closed_contract(
        manifest,
        InterventionPoint.PRE_TOOL_CALL,
        snapshot,
        evidence_provider_id="recipient_classifier",
    )
    result = await contract.verify()
    assert result.passed, result.detail
    assert result.category.value == "policy"


@pytest.mark.asyncio
async def test_keyword_dlp_provider():
    from a2a_testbed.acs import keyword_dlp

    flagged = await keyword_dlp(
        {"policy_target": {"value": {"text": "send the CONFIDENTIAL report"}}, "snapshot": {}}
    )
    assert flagged["dlp"]["flagged"] is True
    assert "confidential" in flagged["dlp"]["matches"]

    clean = await keyword_dlp({"policy_target": {"value": {"text": "hello there"}}, "snapshot": {}})
    assert clean["dlp"]["flagged"] is False

    # Structured secret (SSN pattern) is detected too.
    ssn = await keyword_dlp(
        {"policy_target": {"value": {"text": "id 123-45-6789"}}, "snapshot": {}}
    )
    assert "ssn_pattern" in ssn["dlp"]["matches"]


@pytest.mark.asyncio
async def test_evidence_feeds_policy_deny():
    """A real evidence provider's annotation drives a policy deny."""
    from a2a_testbed.acs import keyword_dlp

    manifest = validate_manifest(REPO_ROOT / "examples" / "acs" / "dlp-evidence.acs.yaml").manifest
    assert manifest is not None
    evaluator = AcsEvaluator(fail_closed=True)
    evaluator.register_evidence("keyword_dlp", keyword_dlp)

    def exchange(text: str) -> WireExchange:
        return WireExchange(
            receiver_id="send",
            request_body={
                "method": "message/send",
                "params": {"message": {"parts": [{"kind": "text", "text": text}]}},
            },
            response_body={},
        )

    sensitive = snapshot_for(InterventionPoint.PRE_TOOL_CALL, exchange("the password is hunter2"))
    v = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, sensitive)
    assert v.decision == Decision.DENY and not v.failed_closed

    clean = snapshot_for(InterventionPoint.PRE_TOOL_CALL, exchange("schedule a meeting"))
    v2 = await evaluator.evaluate(manifest, InterventionPoint.PRE_TOOL_CALL, clean)
    assert v2.decision == Decision.ALLOW


def test_verdict_from_opa_value_mapping():
    from a2a_testbed.acs import verdict_from_opa_value

    p = InterventionPoint.PRE_TOOL_CALL
    assert verdict_from_opa_value("deny", p).decision == Decision.DENY
    assert verdict_from_opa_value("allow", p).decision == Decision.ALLOW
    # object form with reasons
    v = verdict_from_opa_value({"decision": "warn", "reasons": ["x"], "rule": "r"}, p)
    assert v.decision == Decision.WARN and v.rule_name == "r" and "x" in v.reasons
    # unknown / missing / null all fail closed
    assert verdict_from_opa_value("bogus", p).failed_closed
    assert verdict_from_opa_value({}, p).failed_closed
    assert verdict_from_opa_value(None, p).decision == Decision.DENY


@pytest.mark.asyncio
async def test_rego_backend_end_to_end():
    """Gated: runs only when the OPA binary is available."""
    from a2a_testbed.acs import (
        RegoBackend,
        PolicyDecl,
        PolicyType,
        build_canonical_input,
    )

    if not RegoBackend.is_available():
        pytest.skip("opa binary not on PATH")

    bundle = str(REPO_ROOT / "examples" / "acs" / "rego")
    policy = PolicyDecl(type=PolicyType.REGO, bundle=bundle, query="data.email_agent.verdict")
    backend = RegoBackend()

    def canonical_for(to: str):
        snap = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange(to))
        return build_canonical_input(
            InterventionPoint.PRE_TOOL_CALL,
            snap,
            policy_target_path="$.tool_call.args",
            policy_target_kind="tool_args",
        )

    deny = await backend(policy, canonical_for("x@external.example"))
    assert deny.decision == Decision.DENY
    allow = await backend(policy, canonical_for("x@internal.example"))
    assert allow.decision == Decision.ALLOW


@pytest.mark.asyncio
async def test_rego_backend_parses_opa_output(monkeypatch):
    """Verify the OPA subprocess parse path without needing the binary."""
    import json as _json

    from a2a_testbed.acs import (
        PolicyDecl,
        PolicyType,
        RegoBackend,
        build_canonical_input,
    )
    from a2a_testbed.acs import rego as rego_mod

    opa_out = _json.dumps({"result": [{"expressions": [{"value": "deny"}]}]}).encode()

    class _FakeProc:
        returncode = 0

        async def communicate(self, input=None):
            return (opa_out, b"")

    async def _fake_exec(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(rego_mod.asyncio, "create_subprocess_exec", _fake_exec)

    backend = RegoBackend()
    policy = PolicyDecl(type=PolicyType.REGO, bundle="x", query="data.x.verdict")
    canonical = build_canonical_input(InterventionPoint.OUTPUT, {"output": {}})
    verdict = await backend(policy, canonical)
    assert verdict.decision == Decision.DENY


@pytest.mark.asyncio
async def test_runner_evaluates_acs_per_step():
    """ScenarioRunner._evaluate_acs applies a manifest to a step's exchange."""
    import json
    from types import SimpleNamespace

    from a2a_testbed.core.types import Step
    from a2a_testbed.scenario import ScenarioRunner

    manifest_path = REPO_ROOT / "examples" / "acs" / "three-party-governance.acs.yaml"
    runner = ScenarioRunner(acs_manifest_path=str(manifest_path))
    # _load_acs only reads scenario.acs (None here) + the override path.
    runner._acs = runner._load_acs(SimpleNamespace(acs=None), manifest_path.parent)
    assert runner._acs is not None

    def payload(text: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {"message": {"parts": [{"kind": "text", "text": text}]}},
        }

    resp = SimpleNamespace(text=json.dumps({"result": {}}))

    # Handoff to carol (external label) -> deny.
    deny_step = Step.model_validate(
        {"from": "bob", "to": "carol", "action": "grant_consent", "message": "grant_consent"}
    )
    # pre_tool_call is the demo manifest's only point -> evaluate "pre".
    deny_verdicts = await runner._evaluate_acs(
        deny_step, payload("grant_consent"), resp, phase="pre"
    )
    assert any(v["decision"] == "deny" for v in deny_verdicts)

    # Handoff to bob (internal), no regulated content -> allow.
    allow_step = Step.model_validate(
        {"from": "alice", "to": "bob", "action": "forward", "message": "forward request"}
    )
    allow_verdicts = await runner._evaluate_acs(
        allow_step, payload("forward request"), resp, phase="pre"
    )
    assert allow_verdicts and all(v["decision"] == "allow" for v in allow_verdicts)


def test_runner_enforce_mode_resolves_from_flag_and_field():
    """Enforce flag overrides the scenario field; field is the fallback."""
    from types import SimpleNamespace

    from a2a_testbed.scenario import ScenarioRunner

    # Flag wins when set.
    r = ScenarioRunner(acs_enforce=True)
    r._acs_enforce = (
        r._acs_enforce_override
        if r._acs_enforce_override is not None
        else bool(SimpleNamespace(acs_enforce=False).acs_enforce)
    )
    assert r._acs_enforce is True

    # Falls back to the scenario field when the flag is unset.
    r2 = ScenarioRunner()
    r2._acs_enforce = (
        r2._acs_enforce_override
        if r2._acs_enforce_override is not None
        else bool(SimpleNamespace(acs_enforce=True).acs_enforce)
    )
    assert r2._acs_enforce is True


def test_blocking_helpers():
    from a2a_testbed.scenario import ScenarioRunner

    allow = [{"decision": "allow", "intervention_point": "input"}]
    deny = [
        {
            "decision": "deny",
            "intervention_point": "pre_tool_call",
            "reasons": ["external"],
            "rule_name": "deny-external",
        }
    ]
    assert not ScenarioRunner._has_block(allow)
    assert ScenarioRunner._has_block(deny)
    assert ScenarioRunner._has_block([{"decision": "escalate"}])
    assert "pre_tool_call=deny" in ScenarioRunner._block_reason(deny)


@pytest.mark.asyncio
async def test_enforcement_contract_positive_and_negative():
    manifest = _deny_external_manifest()
    evaluator = AcsEvaluator(fail_closed=True)
    evaluator.register_evidence("recipient_classifier", _noop_evidence)

    deny_snap = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@external.example"))
    allow_snap = snapshot_for(InterventionPoint.PRE_TOOL_CALL, _exchange("x@internal.example"))

    deny_contract = make_acs_enforcement_contract(
        manifest,
        InterventionPoint.PRE_TOOL_CALL,
        deny_snap,
        Decision.DENY,
        label="external",
        evaluator=evaluator,
    )
    allow_contract = make_acs_enforcement_contract(
        manifest,
        InterventionPoint.PRE_TOOL_CALL,
        allow_snap,
        Decision.ALLOW,
        label="internal",
        evaluator=evaluator,
    )
    assert (await deny_contract.verify()).passed
    assert (await allow_contract.verify()).passed
