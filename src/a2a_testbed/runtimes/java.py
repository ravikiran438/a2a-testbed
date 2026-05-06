# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Java runtime: spawns `java -jar <source>/agent.jar` with the testbed's CLI args.

The reference Java agent ships as a single fat JAR for the simplest
subprocess story. Build it once with Maven before running scenarios
that declare java agents; the testbed only spawns the prebuilt jar.
"""

from __future__ import annotations

from a2a_testbed.runtimes.subprocess_base import SubprocessRuntimeBase


class JavaRuntime(SubprocessRuntimeBase):
    binary_check = ["java", "--version"]
    binary_hint = "install JDK 21+ from https://adoptium.net and ensure `java` is on PATH"
    cmd_template = [
        "java",
        "-jar",
        "{source}",
        "--agent-card",
        "{card}",
        "--scripts",
        "{scripts}",
        "--port",
        "{port}",
    ]
