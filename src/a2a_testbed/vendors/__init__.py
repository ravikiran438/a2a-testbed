# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Static AgentCard compatibility checker.

Takes an AgentCard JSON from any source — A2A 1.0 native, or any
non-A2A dialect declared via a user-supplied ``--dialect-file`` —
and reports what would need to change for it to be A2A 1.0
compliant.

The checker has three layers:
  1. ``Dialect`` declarations describe how to detect a non-A2A
     platform's card shape and how to map its fields onto canonical
     A2A paths. The package ships only the A2A 1.0 native dialect;
     authoritative platform mappings are user-supplied via JSON
     dialect files.
  2. ``check_compat`` runs detection, applies the field map, and
     compares the result against A2A 1.0 required fields.
  3. ``render_markdown`` formats findings as a markdown report
     suitable for CI output or PR comments.
"""

from a2a_testbed.vendors.checker import (
    CompatFinding,
    CompatFindingKind,
    CompatReport,
    check_compat,
)
from a2a_testbed.vendors.dialects import (
    DIALECTS,
    Dialect,
    detect_dialect,
)
from a2a_testbed.vendors.report import render_markdown


__all__ = [
    "CompatFinding",
    "CompatFindingKind",
    "CompatReport",
    "DIALECTS",
    "Dialect",
    "check_compat",
    "detect_dialect",
    "render_markdown",
]
