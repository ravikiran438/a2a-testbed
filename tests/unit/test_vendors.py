# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Tests for the vendor/dialect compatibility checker.

The testbed ships exactly one built-in dialect (A2A 1.0 native).
Non-A2A dialects are user-supplied via ``--dialect-file`` JSON.
These tests exercise:
  - the built-in A2A 1.0 native detector / compliance check
  - the user-pluggable dialect loader (``Dialect.from_file``)
  - the auto-detector with extra dialects injected at the API level
  - the markdown report
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from a2a_testbed.vendors import (
    DIALECTS,
    CompatFindingKind,
    Dialect,
    check_compat,
    detect_dialect,
    render_markdown,
)


def _a2a_card() -> dict:
    return {
        "name": "Concierge Agent",
        "description": "Help users plan their day.",
        "url": "https://agent.example.com",
        "version": "1.0.0",
        "supportedInterfaces": [
            {"url": "https://agent.example.com", "protocolBinding": "JSONRPC"}
        ],
        "capabilities": {"streaming": False, "extensions": []},
        "skills": [
            {
                "id": "search_calendar",
                "name": "Search calendar",
                "description": "Search the user's calendar.",
                "tags": ["calendar"],
            }
        ],
    }


# Sample user-authored dialect for a hypothetical non-A2A platform.
# Tests the plug-in mechanism without committing to any specific
# external platform's field map.
_SAMPLE_DIALECT_PAYLOAD = {
    "name": "ExamplePlatform (user-supplied)",
    "identifying_fields": ["display_name", "instructions", "tools"],
    "field_map": {
        "display_name": "name",
        "instructions": "description",
        "tools[].name": "skills[].name",
        "tools[].description": "skills[].description",
        "internal_only_id": None,
    },
    "notes": [
        "Sample dialect for testing the user-pluggable loader."
    ],
}


def _example_card() -> dict:
    return {
        "display_name": "Concierge Agent",
        "instructions": "Help users plan their day.",
        "tools": [
            {"name": "search_calendar", "description": "Search the calendar."}
        ],
        "internal_only_id": "abc",
    }


# --------------------------------------------------------------------------
# Built-in surface
# --------------------------------------------------------------------------


def test_only_a2a_native_built_in():
    """The package ships exactly one built-in dialect (the identity
    dialect); non-A2A dialects are user-supplied via dialect files."""
    assert len(DIALECTS) == 1
    assert "A2A" in DIALECTS[0].name


def test_detect_a2a_native():
    d = detect_dialect(_a2a_card())
    assert d is not None
    assert "A2A" in d.name


def test_detect_returns_none_for_unknown_card():
    """No identifying-field overlap with built-ins → None (not a guess)."""
    assert detect_dialect({"random": "fields"}) is None


def test_a2a_native_card_is_compliant():
    report = check_compat(_a2a_card())
    assert report.a2a_compliant is True
    assert any(f.kind == CompatFindingKind.OK for f in report.findings)


def test_unknown_card_falls_through_to_required_field_check():
    report = check_compat({"foo": "bar"})
    assert report.dialect is None
    assert any(
        f.kind == CompatFindingKind.UNKNOWN_DIALECT for f in report.findings
    )
    missing = [
        f for f in report.findings if f.kind == CompatFindingKind.MISSING_REQUIRED
    ]
    assert len(missing) >= 5
    assert report.a2a_compliant is False


# --------------------------------------------------------------------------
# User-pluggable dialect loader
# --------------------------------------------------------------------------


def test_dialect_from_dict_round_trip():
    d = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    assert d.name == "ExamplePlatform (user-supplied)"
    assert "display_name" in d.identifying_fields
    assert d.field_map["display_name"] == "name"
    assert d.field_map["internal_only_id"] is None


def test_dialect_from_file(tmp_path: Path):
    path = tmp_path / "example.json"
    path.write_text(json.dumps(_SAMPLE_DIALECT_PAYLOAD), encoding="utf-8")
    d = Dialect.from_file(path)
    assert "ExamplePlatform" in d.name


def test_dialect_from_dict_rejects_missing_fields():
    with pytest.raises(ValueError, match="name"):
        Dialect.from_dict({"identifying_fields": []})
    with pytest.raises(ValueError, match="identifying_fields"):
        Dialect.from_dict({"name": "X"})


def test_dialect_from_dict_rejects_non_object():
    with pytest.raises(TypeError):
        Dialect.from_dict("not a dict")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Auto-detection with user-supplied dialects
# --------------------------------------------------------------------------


def test_auto_detect_picks_user_supplied_dialect():
    extra = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    detected = detect_dialect(_example_card(), extra_dialects=(extra,))
    assert detected is extra


def test_auto_detect_a2a_still_wins_when_card_is_a2a():
    extra = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    detected = detect_dialect(_a2a_card(), extra_dialects=(extra,))
    assert detected is not None
    assert "A2A" in detected.name


def test_check_compat_with_extra_dialect():
    extra = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    report = check_compat(_example_card(), extra_dialects=(extra,))
    assert report.dialect is extra
    mapped = [f for f in report.findings if f.kind == CompatFindingKind.MAPPED_FIELD]
    assert any(f.source_path == "display_name" for f in mapped)
    unmapped = [
        f for f in report.findings if f.kind == CompatFindingKind.UNMAPPED_SOURCE_FIELD
    ]
    assert any(f.source_path == "internal_only_id" for f in unmapped)
    missing = [
        f.target_path for f in report.findings
        if f.kind == CompatFindingKind.MISSING_REQUIRED
    ]
    for required in ("version", "capabilities", "skills", "supportedInterfaces"):
        assert required in missing


def test_explicit_dialect_overrides_detection():
    extra = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    report = check_compat(_a2a_card(), dialect=extra)
    assert report.dialect is extra


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def test_markdown_report_for_compliant_a2a_card_says_compliant():
    md = render_markdown(check_compat(_a2a_card()))
    assert "A2A 1.0 compliant" in md


def test_markdown_report_for_user_dialect_card_includes_sections():
    extra = Dialect.from_dict(_SAMPLE_DIALECT_PAYLOAD)
    md = render_markdown(check_compat(_example_card(), extra_dialects=(extra,)))
    assert "ExamplePlatform" in md
    assert "Mapped fields" in md
    assert "Missing required fields" in md
    assert "version" in md
