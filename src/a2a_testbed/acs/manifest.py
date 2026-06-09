# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Load and validate ACS manifests locally.

Microsoft's ACS launch references a policy-validation workflow but ships
no hosted/online validator: validation is local, via the
``agent-control-specification`` SDK loading a manifest and the AGT
``agt lint-policy`` CLI. This module is the testbed's local equivalent —
the "online validator" replacement — built the same way the extension
``manifest/validator.py`` is: parse, then emit ordered ``Finding`` rows
a third party can read without prior ACS knowledge.

Two layers of validation:

1. **Structural** — does the YAML parse into a well-formed ``AcsManifest``
   (pydantic). Surfaces field/type errors.
2. **Semantic** — cross-manifest checks pydantic can't express:
   intervention points referencing undeclared policies, ``tool_name_from``
   with no matching declared tool, ``rego`` policies that will need an
   external backend, and use of the two model-call points the testbed
   cannot observe at the wire seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import ValidationError

from a2a_testbed.acs.types import (
    ACS_SPEC_VERSION,
    AcsManifest,
    InterventionPoint,
    PolicyType,
)


class AcsFindingKind(str, Enum):
    """Outcome rows from validating one ACS manifest.

    ``OK`` is the only clean state. ``WARN_*`` rows pass but flag
    something a reviewer should know; ``ERROR_*`` rows mean the manifest
    is unusable as written.
    """

    OK = "ok"
    ERROR_PARSE = "error_parse"
    ERROR_SCHEMA = "error_schema"
    ERROR_POLICY_REF = "error_policy_ref"
    ERROR_NO_INTERVENTION = "error_no_intervention"
    WARN_VERSION_MISMATCH = "warn_version_mismatch"
    WARN_TOOL_REF = "warn_tool_ref"
    WARN_REGO_BACKEND_REQUIRED = "warn_rego_backend_required"
    WARN_NON_OBSERVABLE_POINT = "warn_non_observable_point"


@dataclass(frozen=True)
class AcsFinding:
    """One result row from validating a manifest."""

    kind: AcsFindingKind
    detail: str = ""
    locus: str = ""  # which intervention point / policy / tool, when relevant
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_error(self) -> bool:
        return self.kind.value.startswith("error_")


@dataclass(frozen=True)
class AcsValidationResult:
    """Parsed manifest (when structurally valid) + ordered findings."""

    manifest: Optional[AcsManifest]
    findings: tuple[AcsFinding, ...]

    @property
    def ok(self) -> bool:
        """True when no error-level findings were recorded."""
        return self.manifest is not None and not any(f.is_error for f in self.findings)


def load_manifest_dict(source: Union[str, Path, dict]) -> dict:
    """Read a manifest into a plain dict from a path, YAML string, or dict."""
    if isinstance(source, dict):
        return source
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8")
    elif isinstance(source, str) and "\n" not in source and Path(source).exists():
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = str(source)
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("ACS manifest must be a mapping at the top level")
    return parsed


def _format_pydantic_errors(exc: ValidationError) -> tuple[str, ...]:
    out = []
    for err in exc.errors():
        loc = "/".join(str(p) for p in err["loc"]) or "<root>"
        out.append(f"{loc}: {err['msg']}")
    return tuple(out)


def validate_manifest(source: Union[str, Path, dict]) -> AcsValidationResult:
    """Validate an ACS manifest and return parsed model + findings.

    Never raises for an invalid manifest — every problem becomes a
    Finding so the caller (CLI, contract, report) can render them all at
    once, the same way the extension-manifest validator does.
    """
    findings: list[AcsFinding] = []

    # --- structural ------------------------------------------------
    try:
        raw = load_manifest_dict(source)
    except Exception as exc:  # noqa: BLE001
        return AcsValidationResult(
            manifest=None,
            findings=(AcsFinding(AcsFindingKind.ERROR_PARSE, detail=str(exc)),),
        )

    try:
        manifest = AcsManifest.model_validate(raw)
    except ValidationError as exc:
        return AcsValidationResult(
            manifest=None,
            findings=(
                AcsFinding(
                    AcsFindingKind.ERROR_SCHEMA,
                    detail="manifest failed schema validation",
                    errors=_format_pydantic_errors(exc),
                ),
            ),
        )

    # --- semantic --------------------------------------------------
    declared_version = manifest.agent_control_specification_version
    if declared_version != ACS_SPEC_VERSION:
        findings.append(
            AcsFinding(
                AcsFindingKind.WARN_VERSION_MISMATCH,
                detail=(
                    f"manifest declares ACS {declared_version!r}; testbed pins {ACS_SPEC_VERSION!r}"
                ),
            )
        )

    if not manifest.intervention_points:
        findings.append(
            AcsFinding(
                AcsFindingKind.ERROR_NO_INTERVENTION,
                detail="manifest declares no intervention points; nothing to enforce",
            )
        )

    observable = InterventionPoint.observable_at_wire()
    for point, decl in manifest.intervention_points.items():
        locus = point.value

        if decl.policy_id not in manifest.policies:
            findings.append(
                AcsFinding(
                    AcsFindingKind.ERROR_POLICY_REF,
                    locus=locus,
                    detail=f"references undeclared policy {decl.policy_id!r}",
                )
            )
        else:
            policy = manifest.policies[decl.policy_id]
            if policy.type == PolicyType.REGO:
                findings.append(
                    AcsFinding(
                        AcsFindingKind.WARN_REGO_BACKEND_REQUIRED,
                        locus=locus,
                        detail=(
                            f"policy {decl.policy_id!r} is type 'rego'; needs an "
                            "external OPA / ACS SDK backend registered on the "
                            "evaluator, else it fails closed"
                        ),
                    )
                )

        if point not in observable:
            findings.append(
                AcsFinding(
                    AcsFindingKind.WARN_NON_OBSERVABLE_POINT,
                    locus=locus,
                    detail=(
                        "model-call points aren't observable at the A2A wire "
                        "seam; the agent must emit this snapshot itself"
                    ),
                )
            )

        if decl.tool_name_from and not manifest.tools:
            findings.append(
                AcsFinding(
                    AcsFindingKind.WARN_TOOL_REF,
                    locus=locus,
                    detail=(
                        "declares tool_name_from but the manifest has no tools; "
                        "tool metadata will be absent from the canonical input"
                    ),
                )
            )

    if not findings:
        findings.append(
            AcsFinding(
                AcsFindingKind.OK,
                detail=(
                    f"manifest valid: {len(manifest.intervention_points)} "
                    f"intervention point(s), {len(manifest.policies)} policy(ies)"
                ),
            )
        )

    return AcsValidationResult(manifest=manifest, findings=tuple(findings))
