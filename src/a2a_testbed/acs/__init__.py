# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Agent Control Specification (ACS) support for a2a-testbed.

ACS is an open, vendor-neutral runtime-governance standard: deterministic
controls placed at fixed checkpoints (intervention points) in an agent's
lifecycle, expressed as a portable YAML manifest. This package lets the
testbed load an ACS manifest, validate it locally, shape A2A wire
exchanges into ACS canonical policy input, and evaluate verdicts with
fail-closed semantics.

Public surface:

- ``AcsManifest`` and friends — the manifest model (``types``)
- ``validate_manifest`` — the local validator (``manifest``)
- ``AcsEvaluator`` — the fail-closed intervention-point evaluator (``evaluator``)
- ``snapshot_for`` / ``build_canonical_input`` — the wire seam (``canonical``)

The eight ACS intervention points and the canonical input shape follow:
  https://commandline.microsoft.com/agent-control-specification-runtime-governance/
"""

from a2a_testbed.acs.canonical import (
    build_canonical_input,
    resolve_path,
    snapshot_for,
    tool_metadata,
)
from a2a_testbed.acs.evaluator import (
    AcsEvaluationError,
    AcsEvaluator,
    EvidenceProvider,
    PolicyBackend,
)
from a2a_testbed.acs.evidence import (
    BUILTIN_EVIDENCE_PROVIDERS,
    keyword_dlp,
    make_keyword_dlp,
)
from a2a_testbed.acs.manifest import (
    AcsFinding,
    AcsFindingKind,
    AcsValidationResult,
    load_manifest_dict,
    validate_manifest,
)
from a2a_testbed.acs.rego import (
    RegoBackend,
    register_rego_backend,
    verdict_from_opa_value,
)
from a2a_testbed.acs.spec_md import (
    render_spec_md,
    starter_manifest_yaml,
)
from a2a_testbed.acs.types import (
    ACS_SPEC_VERSION,
    AcsManifest,
    BuiltinRule,
    CanonicalInput,
    Decision,
    InterventionPoint,
    InterventionPointDecl,
    PolicyDecl,
    PolicyType,
    ToolDecl,
    Verdict,
)


__all__ = [
    "ACS_SPEC_VERSION",
    "BUILTIN_EVIDENCE_PROVIDERS",
    "AcsEvaluationError",
    "AcsEvaluator",
    "AcsFinding",
    "AcsFindingKind",
    "AcsManifest",
    "AcsValidationResult",
    "BuiltinRule",
    "CanonicalInput",
    "Decision",
    "EvidenceProvider",
    "InterventionPoint",
    "InterventionPointDecl",
    "PolicyBackend",
    "PolicyDecl",
    "PolicyType",
    "RegoBackend",
    "ToolDecl",
    "Verdict",
    "register_rego_backend",
    "verdict_from_opa_value",
    "build_canonical_input",
    "keyword_dlp",
    "load_manifest_dict",
    "make_keyword_dlp",
    "render_spec_md",
    "resolve_path",
    "starter_manifest_yaml",
    "snapshot_for",
    "tool_metadata",
    "validate_manifest",
]
