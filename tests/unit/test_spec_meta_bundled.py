"""The spec pin bundled in the package matches pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from a2a_testbed import spec_meta

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_bundled_pin_matches_pyproject():
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        authoritative = tomllib.load(f)["tool"]["a2a_testbed"]["spec"]
    with spec_meta._BUNDLED_PIN.open("rb") as f:
        bundled = tomllib.load(f)
    assert bundled == authoritative, (
        "src/a2a_testbed/spec_pin.toml is out of sync with "
        "[tool.a2a_testbed.spec] in pyproject.toml; update both together"
    )


def test_installed_layout_uses_bundled_pin(monkeypatch):
    """Without our pyproject above the package (a wheel install), the
    bundled pin is used instead of an unrelated project's pyproject."""

    def no_checkout():
        raise FileNotFoundError

    monkeypatch.setattr(spec_meta, "_find_pyproject", no_checkout)
    spec_meta.load_spec_meta.cache_clear()
    try:
        meta = spec_meta.load_spec_meta()
        assert meta.version != "unknown" and meta.commit
    finally:
        spec_meta.load_spec_meta.cache_clear()
