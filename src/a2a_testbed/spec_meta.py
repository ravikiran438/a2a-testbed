# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Single read-only handle on the A2A spec metadata declared in
``pyproject.toml`` under ``[tool.a2a_testbed.spec]``.

Every CLI surface that wants to cite the spec — ``run``'s compliance
section, ``coverage``'s header, ``version``'s footer — pulls from
here. The pin lives in pyproject.toml so packaging tooling, IDEs,
and CI can read it without importing Python; this module is the
ergonomic Python view on the same data.

Reads are cached for the process lifetime; the file is small and
spec metadata changes through human review, not at runtime.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class SpecMeta:
    """A2A spec pin currently authoritative for this testbed checkout."""

    name: str
    version: str
    commit: str
    last_reviewed: str
    source_repo: str
    specification_path: str

    @property
    def specification_url(self) -> str:
        """Permalink to the pinned spec text on GitHub."""
        return (
            f"{self.source_repo.rstrip('/')}"
            f"/blob/{self.commit}/{self.specification_path.lstrip('/')}"
        )

    @property
    def short_commit(self) -> str:
        return self.commit[:7]


def _find_pyproject() -> Path:
    """Walk up from this module to find the repo's pyproject.toml.

    Searching upward (rather than hard-coding `Path(__file__).parents[2]`)
    keeps the helper working when the package is installed editable
    from a checkout AND when it's running from a wheel inside
    site-packages — in the wheel case we fall back to bundled
    metadata via the ImportError path in ``load_spec_meta``.
    """
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("pyproject.toml not found above a2a_testbed package")


@lru_cache(maxsize=1)
def load_spec_meta() -> SpecMeta:
    """Return the spec pin declared in pyproject.toml.

    Falls back to a sentinel SpecMeta with empty fields if the
    pyproject.toml can't be located (e.g. wheel install without
    source). The CLI surfaces a "spec metadata unavailable" hint
    instead of crashing.
    """
    try:
        path = _find_pyproject()
    except FileNotFoundError:
        return SpecMeta(
            name="A2A",
            version="unknown",
            commit="",
            last_reviewed="",
            source_repo="https://github.com/a2aproject/A2A",
            specification_path="docs/specification.md",
        )

    with path.open("rb") as f:
        data = tomllib.load(f)

    section = (
        data.get("tool", {})
        .get("a2a_testbed", {})
        .get("spec", {})
    )
    return SpecMeta(
        name=section.get("name", "A2A"),
        version=section.get("version", "unknown"),
        commit=section.get("commit", ""),
        last_reviewed=section.get("last_reviewed", ""),
        source_repo=section.get(
            "source_repo", "https://github.com/a2aproject/A2A"
        ),
        specification_path=section.get(
            "specification_path", "docs/specification.md"
        ),
    )
