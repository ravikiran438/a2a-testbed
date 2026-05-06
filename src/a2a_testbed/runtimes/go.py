# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Go runtime: spawns `go run <source>/main.go` with the testbed's CLI args."""

from __future__ import annotations

from a2a_testbed.runtimes.subprocess_base import SubprocessRuntimeBase


class GoRuntime(SubprocessRuntimeBase):
    binary_check = ["go", "version"]
    binary_hint = "install Go from https://go.dev/dl/ and ensure `go` is on PATH"
    cmd_template = [
        "go",
        "run",
        "{source}",
        "--agent-card",
        "{card}",
        "--scripts",
        "{scripts}",
        "--port",
        "{port}",
    ]
