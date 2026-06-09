#!/usr/bin/env bash
# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.
#
# Dependency-free build (no Maven / no network): compile the single source
# file and package it into a runnable jar. Requires a JDK (javac + jar) on
# PATH. Produces target/agent.jar, the same artifact `mvn package` makes.

set -euo pipefail
cd "$(dirname "$0")"

SRC="src/main/java/com/a2atestbed/template/Main.java"
OUT="target/classes"

rm -rf "$OUT" && mkdir -p "$OUT"
# --release 17 matches pom.xml (maven.compiler.release) so the jar runs on
# any JDK 17+, regardless of which JDK built it.
javac --release 17 -d "$OUT" "$SRC"
jar --create --file target/agent.jar \
    --main-class com.a2atestbed.template.Main \
    -C "$OUT" .
echo "built: $(pwd)/target/agent.jar"
