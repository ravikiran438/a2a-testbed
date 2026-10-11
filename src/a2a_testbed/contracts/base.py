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

import asyncio
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

import httpx

# Upper bound on one contract's verify call. Contracts carry their own
# per-request timeouts (5-10s); this catches the ones that chain several
# requests or wait on an SSE stream that never closes.
DEFAULT_CONTRACT_TIMEOUT_S = 45.0


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


class ContractStatus(str, Enum):
    """How one contract run ended.

    ``passed`` stays the single pass/fail bit callers already use; the
    status says *why*, which is what a CI gate needs:

    - ``pass``  — the agent satisfied the rule.
    - ``warn``  — satisfied, with a non-fatal deviation in ``detail``.
    - ``skip``  — the rule does not apply (capability not advertised,
      0.3-only agent, …). Counts as passed.
    - ``fail``  — the agent answered, and the answer violates the rule.
    - ``error`` — the agent could not be reached or did not answer in
      time. Not a conformance verdict; counts as not passed.
    """

    PASS = "pass"
    WARN = "warn"
    SKIP = "skip"
    FAIL = "fail"
    ERROR = "error"


# Exceptions that mean "no answer", not "wrong answer".
_UNREACHABLE = (httpx.TimeoutException, httpx.TransportError, asyncio.TimeoutError)


class Info(str):
    """A passing detail that is information, not a deviation.

    A verify function returns a plain string to mean "passed, with a
    deviation worth reviewing" (``warn``, which ``--strict`` promotes to a
    failure). Return ``Info("...")`` instead to report a plain fact about
    a passing agent — which version it spoke, which response shape it
    chose — without it counting against the agent.
    """


# "skipped — agent does not implement <method> (-32601)": the rule could
# not run because a method the agent advertises (or A2A 1.0 requires) is
# missing. That is a gap in the agent, so it stays a deviation (``warn``,
# a failure under ``--strict``) rather than a "does not apply" skip.
_MISSING_METHOD = re.compile(r"does not implement .*\(-32601\)")


def is_skip_detail(detail: str) -> bool:
    """Contracts report "does not apply" as a passing detail string that
    starts with ``skipped``; recognise that convention."""
    text = detail.lstrip()
    return text.lower().startswith("skipped") and not _MISSING_METHOD.search(text)


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
    # Why the run ended this way; derived from ``passed``/``detail``
    # when not given explicitly (see ``ContractStatus``).
    status: Optional[ContractStatus] = None
    # How many times the contract ran (2 when an unreachable-agent
    # error was retried).
    attempts: int = 1

    def __post_init__(self) -> None:
        if self.status is None:
            if not self.passed:
                self.status = ContractStatus.FAIL
            elif not self.detail:
                self.status = ContractStatus.PASS
            elif is_skip_detail(self.detail):
                self.status = ContractStatus.SKIP
            else:
                self.status = ContractStatus.WARN


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

    async def verify(
        self,
        *args: Any,
        timeout: Optional[float] = DEFAULT_CONTRACT_TIMEOUT_S,
        **kwargs: Any,
    ) -> ContractResult:
        spec_section = extract_spec_section(self.verify_fn)
        try:
            outcome = await asyncio.wait_for(self.verify_fn(*args, **kwargs), timeout=timeout)
            # A contract that passes with a non-fatal deviation can
            # return a string detail instead of raising. Lets us record
            # "agent honored the capability but returned -32601 instead
            # of the spec-mandated -32004" without flipping the result
            # to failed (the capability *was* honored).
            detail = str(outcome) if isinstance(outcome, str) else ""
            return ContractResult(
                self.id,
                passed=True,
                detail=detail,
                spec_section=spec_section,
                category=self.category,
                status=ContractStatus.PASS if isinstance(outcome, Info) else None,
            )
        except AssertionError as exc:
            return ContractResult(
                self.id,
                passed=False,
                detail=str(exc),
                spec_section=spec_section,
                category=self.category,
            )
        except _UNREACHABLE as exc:
            import traceback

            if isinstance(exc, asyncio.TimeoutError) and not isinstance(
                exc, httpx.TimeoutException
            ):
                reason = f"agent did not finish responding within {timeout:g}s"
            else:
                reason = f"agent unreachable or too slow ({type(exc).__name__}: {exc})"
            return ContractResult(
                self.id,
                passed=False,
                detail=reason,
                traceback=traceback.format_exc(),
                spec_section=spec_section,
                category=self.category,
                status=ContractStatus.ERROR,
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
