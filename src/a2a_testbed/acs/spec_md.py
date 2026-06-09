# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Render an ACS manifest into a human-readable governance summary, and
scaffold a starter manifest.

ACS's selling point is *auditable, inspectable* controls — but a YAML
manifest still takes a moment to read. ``render_spec_md`` turns a manifest
into plain-English Markdown ("at pre_tool_call, deny when the receiver is
external; evidence keyword_dlp runs first; fails closed"), the ACS analog
of the extension-manifest ``spec`` renderer. ``starter_manifest_yaml``
emits a commented skeleton to kill the blank-page problem.

There is deliberately no "generate from a model" command: an ACS manifest
is authored governance intent, not a mechanical projection of a type
(unlike an extension manifest's JSON Schema).
"""

from __future__ import annotations

from a2a_testbed.acs.types import (
    ACS_SPEC_VERSION,
    AcsManifest,
    BuiltinRule,
    InterventionPoint,
    PolicyDecl,
    PolicyType,
)


# Plain-English phrasing for each builtin operator.
_OP_PHRASE = {
    "equals": "equals",
    "not_equals": "does not equal",
    "in": "is one of",
    "not_in": "is not one of",
    "contains": "contains",
    "not_contains": "does not contain",
    "endswith": "ends with",
    "startswith": "starts with",
    "exists": "is present",
    "absent": "is absent",
}


def _phrase_rule(rule: BuiltinRule) -> str:
    phrase = _OP_PHRASE.get(rule.op, rule.op)
    head = f"**{rule.decision.value}** when `{rule.field}` {phrase}"
    if rule.op not in ("exists", "absent"):
        head += f" `{rule.value!r}`"
    if rule.description:
        head += f" — {rule.description}"
    return head


def _describe_policy(policy_id: str, policy: PolicyDecl) -> list[str]:
    lines: list[str] = []
    if policy.type == PolicyType.REGO:
        lines.append(
            f"- Policy `{policy_id}` (**rego**): evaluated by OPA — "
            f"bundle `{policy.bundle}`, query `{policy.query}`. "
            "Requires a registered Rego backend, else fails closed."
        )
        return lines
    lines.append(
        f"- Policy `{policy_id}` (**builtin**), default **{policy.default_decision.value}**:"
    )
    if not policy.rules:
        lines.append("    - (no rules — always applies the default decision)")
    for rule in policy.rules:
        lines.append(f"    - {_phrase_rule(rule)}")
    return lines


def render_spec_md(manifest: AcsManifest) -> str:
    """Render a manifest into a Markdown governance summary."""
    meta = manifest.metadata or {}
    name = meta.get("name", "(unnamed)")
    observable = InterventionPoint.observable_at_wire()

    lines: list[str] = [
        f"# ACS governance summary: {name}",
        "",
        f"**ACS version:** {manifest.agent_control_specification_version}",
    ]
    if meta.get("description"):
        lines.append(f"**Description:** {meta['description']}")
    lines += [
        f"**Intervention points:** {len(manifest.intervention_points)}  ·  "
        f"**Policies:** {len(manifest.policies)}  ·  "
        f"**Tools:** {len(manifest.tools)}",
        "",
        "_Verdicts are deterministic; any evidence/policy failure resolves "
        "to **deny** (fail-closed)._",
        "",
        "## Intervention points",
        "",
    ]

    for point, decl in manifest.intervention_points.items():
        wire = (
            ""
            if point in observable
            else (" _(not observable at the A2A wire seam — the agent must emit it)_")
        )
        lines.append(f"### `{point.value}`{wire}")
        lines.append("")
        lines.append(f"- Evaluates `{decl.policy_target}` (`{decl.policy_target_kind}`)")
        if decl.tool_name_from:
            lines.append(f"- Tool resolved from `{decl.tool_name_from}`")
        if decl.evidence:
            lines.append("- Evidence first: " + ", ".join(f"`{e}`" for e in decl.evidence))
        policy = manifest.policies.get(decl.policy_id)
        if policy is None:
            lines.append(f"- ⚠ references undeclared policy `{decl.policy_id}`")
        else:
            lines += _describe_policy(decl.policy_id, policy)
        lines.append("")

    if manifest.tools:
        lines += ["## Tools", "", "| Tool | Clearance | Security labels |", "|---|---|---|"]
        for tid, tool in manifest.tools.items():
            labels = ", ".join(tool.security_labels) or "—"
            lines.append(f"| `{tool.id}` | {tool.clearance or '—'} | {labels} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def starter_manifest_yaml(name: str = "my-agent") -> str:
    """Emit a commented starter ACS manifest for the user to edit."""
    return f"""# ACS manifest scaffold — edit to express your governance intent.
# Validate:  a2a-testbed acs validate <this-file>
# Summarize: a2a-testbed acs spec <this-file>
#
# Docs: https://github.com/ravikiran438/a2a-testbed/blob/main/docs/ACS.md

agent_control_specification_version: "{ACS_SPEC_VERSION}"

metadata:
  name: "{name}"
  description: "Describe what this manifest governs."

policies:
  example_policy:
    type: builtin              # 'builtin' (deps-free) or 'rego' (needs OPA)
    default_decision: allow
    rules:
      # First match wins. Ops: equals, not_equals, in, not_in, contains,
      # not_contains, endswith, startswith, exists, absent.
      - name: deny-external-receiver
        field: "tool.security_labels"
        op: contains
        value: "external"
        decision: deny          # allow | warn | deny | escalate
        description: "deny handoffs to externally-labelled tools"

intervention_points:
  # Wire-observable points: agent_startup, input, pre_tool_call,
  # post_tool_call, output, agent_shutdown. (Model-call points run
  # inside the agent and aren't visible at the A2A wire seam.)
  pre_tool_call:
    policy_target: "$.tool_call.args"
    policy_target_kind: tool_args
    tool_name_from: "$.tool_call.name"
    policy: example_policy
    # evidence:               # optional; e.g. the built-in DLP classifier
    #   - keyword_dlp

tools:
  example_tool:
    type: Tool
    id: example_tool
    clearance: internal
    security_labels: [internal]
"""
