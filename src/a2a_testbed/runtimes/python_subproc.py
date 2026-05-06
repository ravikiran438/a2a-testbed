# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Python subprocess runtime — spawns the reference Python agent template.

Mirrors the Go/Node/Java runtimes for parity. Most scenarios will use
``python_inproc`` instead for speed; this runtime exists so cross-SDK
scenarios can include a Python agent that runs out-of-process exactly
like its peers in other languages.
"""

from __future__ import annotations

import sys

from a2a_testbed.runtimes.subprocess_base import SubprocessRuntimeBase


class PythonSubprocRuntime(SubprocessRuntimeBase):
    binary_check = []  # always present (we are Python)
    cmd_template = [
        sys.executable,
        "{source}/main.py",
        "--agent-card",
        "{card}",
        "--scripts",
        "{scripts}",
        "--port",
        "{port}",
    ]
