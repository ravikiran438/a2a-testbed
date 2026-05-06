# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Node.js runtime: spawns `node <source>/index.js` with the testbed's CLI args."""

from __future__ import annotations

from a2a_testbed.runtimes.subprocess_base import SubprocessRuntimeBase


class NodejsRuntime(SubprocessRuntimeBase):
    binary_check = ["node", "--version"]
    binary_hint = "install Node 20+ from https://nodejs.org and ensure `node` is on PATH"
    cmd_template = [
        "node",
        "{source}/index.js",
        "--agent-card",
        "{card}",
        "--scripts",
        "{scripts}",
        "--port",
        "{port}",
    ]
