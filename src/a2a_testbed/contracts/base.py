# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Base types for conformance contracts.

A *contract* is a verifiable statement about an A2A network's
behavior.

## Sourcing principle

Every contract in this suite is derived from the published A2A
specification rather than from any single implementation. The spec
is treated as the authority; each contract's docstring cites the
relevant section.

Each contract file's docstring carries:

  Spec:    A2A 1.0 §<section>
  URL:     https://github.com/a2aproject/A2A/blob/<rev>/<path>
  Clause:  <one-sentence paraphrase of what the spec mandates>

The pinned spec commit lives in ``pyproject.toml`` under
``[tool.a2a_testbed.spec]`` and is read at runtime by
``a2a_testbed.spec_meta``. When the A2A specification revises,
the CONTRIBUTING.md checklist ("Tracking the upstream A2A spec")
spells out the bump-and-resweep procedure.

## Layout

- ``contracts/transport/``  — wire-level invariants any A2A server
  must satisfy (well-known card endpoint reachable, JSON-RPC
  envelope shape correct, required-extension enforcement, error
  codes, etc.).
- ``contracts/network/``    — multi-agent flow invariants
  (observer completeness, consent-chain audit, fault recovery,
  etc.). These are testbed-defined; A2A itself is a per-agent
  protocol and does not specify multi-agent flow invariants.
- ``contracts/extensions/`` — semantic invariants tied to specific
  protocol extensions, exercised by delegating to each protocol's
  MCP server.

Each contract is a small dataclass + async run callable, registered
under one of the categories above.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


# A2A-preferred citation: report rows benefit from showing the A2A
# section (which is what the testbed conforms against) even when a
# contract also cites JSON-RPC 2.0 or another upstream spec. This
# regex matches anywhere in the docstring (Spec: line OR Source:
# line) so contracts that cite JSON-RPC first but mention A2A
# second still surface the A2A §.
_A2A_SECTION = re.compile(
    r"A2A\s+\d+(?:\.\d+)*\s+§\s*(?P<section>[\w.\-]+)",
    re.IGNORECASE,
)
# Generic fallback: any "Spec: <name> §<n>" line. Char class
# allows hyphens / slashes so JSON-RPC, RFC-XXXX, Schema.org etc.
# parse cleanly when no A2A section is cited.
_SPEC_LINE = re.compile(
    r"Spec:\s*(?P<spec>[\w./\- ]+?)\s+§\s*(?P<section>[\w.\-]+)",
    re.IGNORECASE,
)


def extract_spec_section(verify_fn: Callable[..., Any]) -> Optional[str]:
    """Pull the ``§<section>`` citation from a contract module's docstring.

    Prefers A2A citations over upstream specs (JSON-RPC, RFC, etc.)
    so the report's "Spec §" column tracks the protocol the testbed
    actually claims conformance against. Returns ``None`` for
    contracts whose module has no docstring or no spec line — typically
    network contracts that are original to the testbed (those carry
    ``Spec:    Original to a2a-testbed``).
    """
    module_name = getattr(verify_fn, "__module__", None)
    if not module_name:
        return None
    module = sys.modules.get(module_name)
    if module is None:
        return None
    doc = getattr(module, "__doc__", None) or ""

    a2a_match = _A2A_SECTION.search(doc)
    if a2a_match is not None:
        return f"§{a2a_match.group('section')}"

    spec_match = _SPEC_LINE.search(doc)
    if spec_match is not None:
        return f"§{spec_match.group('section')}"

    return None


class ContractCategory(str, Enum):
    TRANSPORT = "transport"  # wire-level invariants
    NETWORK = "network"  # multi-agent flow invariants
    EXTENSION = "extension"  # protocol-extension semantic invariants
    POLICY = "policy"  # ACS runtime-governance invariants


@dataclass
class ContractResult:
    contract_id: str
    passed: bool
    detail: str = ""
    traceback: Optional[str] = None
    # Spec section pulled from the contract module's docstring at
    # verify time. ``None`` for testbed-original contracts (which
    # have no spec section to cite).
    spec_section: Optional[str] = None
    category: Optional[ContractCategory] = None


@dataclass
class Contract:
    """One verifiable statement.

    Each contract owns:
      - id: stable identifier across releases
      - description: one-line human-readable summary
      - category: where it slots in the contract taxonomy
      - verify_fn: async callable that raises on failure or returns
        nothing on success. The runner translates exceptions into
        ``ContractResult(passed=False)``.
    """

    id: str
    description: str
    category: ContractCategory
    verify_fn: Callable[..., Awaitable[None]] = field(repr=False)

    async def verify(self, *args: Any, **kwargs: Any) -> ContractResult:
        spec_section = extract_spec_section(self.verify_fn)
        try:
            outcome = await self.verify_fn(*args, **kwargs)
            # A contract that passes with a non-fatal deviation can
            # return a string detail instead of raising. Lets us record
            # "agent honored the capability but returned -32601 instead
            # of the spec-mandated -32004" without flipping the result
            # to failed (the capability *was* honored).
            detail = outcome if isinstance(outcome, str) else ""
            return ContractResult(
                self.id,
                passed=True,
                detail=detail,
                spec_section=spec_section,
                category=self.category,
            )
        except AssertionError as exc:
            return ContractResult(
                self.id,
                passed=False,
                detail=str(exc),
                spec_section=spec_section,
                category=self.category,
            )
        except Exception as exc:
            import traceback

            return ContractResult(
                self.id,
                passed=False,
                detail=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
                spec_section=spec_section,
                category=self.category,
            )
