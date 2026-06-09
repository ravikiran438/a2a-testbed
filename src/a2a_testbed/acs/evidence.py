# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Built-in ACS evidence providers.

ACS evidence providers run *before* a policy and contribute facts
(classifier results, DLP findings, LLM-judge scores) into the canonical
input's ``annotations``, which the policy can then read. The core
evaluator ships no providers — a manifest that declares ``evidence:``
ids must have matching providers registered, or evaluation fails closed.

This module supplies real, dependency-free providers so the evidence
pipeline isn't a no-op stub. The scenario runner auto-registers any of
these whose id a manifest references (see ``scenario.py``); anything else
still falls back to a permissive no-op.

A provider is ``async (canonical: dict) -> dict`` where the return value
is merged into ``annotations``. A policy then reads e.g.
``annotations.dlp.flagged`` via a builtin rule field.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Optional


EvidenceProvider = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


# Default sensitive-keyword list for the keyword DLP provider.
DEFAULT_DLP_KEYWORDS = (
    "confidential",
    "ssn",
    "social security",
    "password",
    "secret",
    "api key",
    "private key",
)

# Structured-secret patterns.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def _collect_text(canonical: dict[str, Any]) -> str:
    """Flatten the policy target + snapshot into a searchable string."""
    target = canonical.get("policy_target", {})
    value = target.get("value") if isinstance(target, dict) else None
    snapshot = canonical.get("snapshot", {})
    return f"{json.dumps(value, default=str)} {json.dumps(snapshot, default=str)}"


def make_keyword_dlp(keywords: Optional[list[str]] = None) -> EvidenceProvider:
    """Build a keyword + pattern DLP evidence provider.

    Returns ``{"dlp": {"flagged": bool, "matches": [...]}}`` so a policy
    can deny on ``annotations.dlp.flagged``.
    """
    kws = [k.lower() for k in (keywords or list(DEFAULT_DLP_KEYWORDS))]

    async def provider(canonical: dict[str, Any]) -> dict[str, Any]:
        text = _collect_text(canonical).lower()
        matches = [k for k in kws if k in text]
        if _SSN_RE.search(text):
            matches.append("ssn_pattern")
        if _CC_RE.search(text):
            matches.append("cc_pattern")
        return {"dlp": {"flagged": bool(matches), "matches": sorted(set(matches))}}

    return provider


# Ready-to-use default instance.
keyword_dlp: EvidenceProvider = make_keyword_dlp()


# Registry the runner consults to turn declared evidence ids into real
# providers. Extend by adding entries here.
BUILTIN_EVIDENCE_PROVIDERS: dict[str, EvidenceProvider] = {
    "keyword_dlp": keyword_dlp,
}
