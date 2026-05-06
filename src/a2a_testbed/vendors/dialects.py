# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Dialects describe how a non-A2A platform's AgentCard maps onto A2A 1.0.

A ``Dialect`` is a small declarative record that lets the
compatibility checker translate a foreign card's fields onto
canonical A2A 1.0 paths. The package ships exactly one built-in
dialect — A2A 1.0 native (the identity dialect) — and exposes a
loader so users can plug in their own dialects for any other
platform via:

  ``a2a-testbed compat <card.json> --dialect-file <my-dialect.json>``

The dialect file is a JSON serialization of the ``Dialect`` record
below. Authoritative platform mappings are out of scope for the
testbed itself; consumers with first-hand platform documentation
supply them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class Dialect:
    """One platform's AgentCard shape + mapping to canonical A2A 1.0.

    The record is JSON-friendly so users can author dialects in a
    config file rather than editing Python code.
    """

    name: str
    identifying_fields: frozenset[str]
    # source-field-path -> target A2A path or None when no analogue
    field_map: dict[str, Optional[str]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Dialect":
        if not isinstance(payload, dict):
            raise TypeError("dialect file must be a JSON object")
        for required in ("name", "identifying_fields"):
            if required not in payload:
                raise ValueError(f"dialect missing required field: {required!r}")
        return cls(
            name=str(payload["name"]),
            identifying_fields=frozenset(payload["identifying_fields"]),
            field_map=dict(payload.get("field_map") or {}),
            notes=tuple(payload.get("notes") or ()),
        )

    @classmethod
    def from_file(cls, path: Path) -> "Dialect":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# A2A 1.0 native: no mapping needed. The "identity" dialect.
A2A_NATIVE = Dialect(
    name="A2A 1.0 (native)",
    identifying_fields=frozenset({"capabilities", "supportedInterfaces"}),
    field_map={},
    notes=(
        "Native A2A 1.0 AgentCard — no field translation required. "
        "Validation falls through to A2A 1.0 required-field presence check.",
    ),
)


# Built-in dialects: the identity dialect only. Non-A2A dialects are
# user-supplied via ``--dialect-file``.
DIALECTS: tuple[Dialect, ...] = (A2A_NATIVE,)


def detect_dialect(
    card: dict[str, Any],
    *,
    extra_dialects: tuple[Dialect, ...] = (),
) -> Optional[Dialect]:
    """Return the dialect whose ``identifying_fields`` best match the card.

    ``extra_dialects`` lets the caller (CLI / library) inject
    user-supplied dialects without mutating the global ``DIALECTS``
    tuple. The match score is the count of identifying fields present
    at the top level of the card. The dialect with the highest
    non-zero score wins; ties broken by registration order. Returns
    None when no dialect has any identifying field present.
    """
    if not isinstance(card, dict):
        return None

    best: Optional[Dialect] = None
    best_score = 0
    for dialect in (*DIALECTS, *extra_dialects):
        score = sum(1 for f in dialect.identifying_fields if f in card)
        if score > best_score:
            best = dialect
            best_score = score
    return best
