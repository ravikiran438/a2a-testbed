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


_BUNDLED_PIN = Path(__file__).resolve().parent / "spec_pin.toml"


def _find_pyproject() -> Path:
    """Walk up from this module to this project's own pyproject.toml.

    Only a pyproject whose ``[project].name`` is ``a2a-testbed`` counts:
    an installed wheel lives under some other project's virtualenv, and
    that project's pyproject.toml must not be mistaken for ours. Raises
    ``FileNotFoundError`` when there is none (the wheel case).
    """
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "pyproject.toml"
        if not candidate.exists():
            continue
        try:
            with candidate.open("rb") as f:
                name = tomllib.load(f).get("project", {}).get("name")
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if name == "a2a-testbed":
            return candidate
    raise FileNotFoundError("a2a-testbed pyproject.toml not found above the package")


def _spec_section() -> dict:
    """``[tool.a2a_testbed.spec]`` from the checkout's pyproject.toml, or
    the copy bundled in the package (``spec_pin.toml``) when installed."""
    try:
        path = _find_pyproject()
    except FileNotFoundError:
        try:
            with _BUNDLED_PIN.open("rb") as f:
                return tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data.get("tool", {}).get("a2a_testbed", {}).get("spec", {})


@lru_cache(maxsize=1)
def load_spec_meta() -> SpecMeta:
    """Return the spec pin declared in pyproject.toml.

    A source checkout reads pyproject.toml; an installed wheel reads the
    bundled ``spec_pin.toml``. With neither, fields fall back to a
    sentinel (version ``unknown``) and the CLI surfaces a "spec metadata
    unavailable" hint instead of crashing.
    """
    section = _spec_section()
    return SpecMeta(
        name=section.get("name", "A2A"),
        version=section.get("version", "unknown"),
        commit=section.get("commit", ""),
        last_reviewed=section.get("last_reviewed", ""),
        source_repo=section.get("source_repo", "https://github.com/a2aproject/A2A"),
        specification_path=section.get("specification_path", "docs/specification.md"),
    )
