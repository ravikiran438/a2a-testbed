# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""a2a-testbed CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from a2a_testbed.reporter import write_reports
from a2a_testbed.scenario import run_scenario_file


app = typer.Typer(
    name="a2a-testbed",
    no_args_is_help=True,
    help="Polyglot multi-agent A2A network simulator and conformance runner.",
)
console = Console()


@app.command()
def run(
    scenario: Path = typer.Argument(
        ...,
        help="Path to scenario YAML file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    log_level: str = typer.Option(
        "warning",
        "--log-level",
        "-l",
        help="Underlying uvicorn/log level: error, warning, info, debug.",
    ),
    write_reports_to: Path | None = typer.Option(
        None,
        "--reports-dir",
        "-r",
        help="If set, write declared reports under this directory.",
    ),
    probe_external: bool = typer.Option(
        False,
        "--probe-external",
        help=(
            "Run the spec-derived contract suite against agents declared "
            "`runtime: external` too. Off by default — sends ~23 HTTP "
            "probes to the live URL, which is impolite without consent. "
            "Turn on for your own deployed agents (Cloudflare/Lambda/etc.) "
            "to verify A2A 1.0 conformance end-to-end."
        ),
    ),
    acs: Path | None = typer.Option(
        None,
        "--acs",
        help=(
            "Path to an Agent Control Specification (ACS) manifest. "
            "Evaluates each step's wire exchange against the manifest's "
            "intervention points and reports verdicts. Overrides any "
            "`acs:` field declared in the scenario. See docs/ACS.md."
        ),
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    acs_enforce: bool = typer.Option(
        False,
        "--acs-enforce",
        help=(
            "Enforce ACS verdicts instead of just recording them: a "
            "deny/escalate blocks the handoff before dispatch and halts "
            "the flow. Overrides the scenario's `acs_enforce:` field."
        ),
    ),
) -> None:
    """Run a scenario and print a colored summary."""
    result = asyncio.run(
        run_scenario_file(
            scenario,
            log_level=log_level,
            probe_external=probe_external,
            acs=acs,
            # Pass True only when the flag is set; None defers to the
            # scenario's `acs_enforce:` field.
            acs_enforce=True if acs_enforce else None,
        )
    )

    table = Table(
        title=f"{result.scenario_name}  ({result.mode.value})",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("Kind", style="cyan")
    table.add_column("From → To")
    table.add_column("Action")
    table.add_column("Pass", justify="center")
    table.add_column("Detail", style="dim")
    for r in result.steps:
        s = r.step
        from_to = f"{s.from_ or '—'} → {s.to or '—'}"
        action = s.action or "—"
        check = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
        table.add_row(
            str(r.step_index),
            s.kind.value,
            from_to,
            action,
            check,
            r.detail,
        )
    console.print(table)

    # Conformance contract section. Always rendered when contracts
    # were evaluated — turns the scenario result from "step X passed"
    # into "step X passed AND these N spec clauses held."
    if result.contracts:
        from a2a_testbed.spec_meta import load_spec_meta

        meta = load_spec_meta()
        spec_label = (
            f"{meta.name} {meta.version}"
            f"{f' (commit {meta.short_commit})' if meta.short_commit else ''}"
        )
        contracts_table = Table(
            title=f"Conformance contracts vs. {spec_label}",
            show_lines=False,
        )
        contracts_table.add_column("Spec §", style="dim", no_wrap=True)
        contracts_table.add_column("Contract", style="cyan")
        contracts_table.add_column("Agent", style="dim")
        contracts_table.add_column("Pass", justify="center")
        contracts_table.add_column("Detail", style="dim")
        for c in result.contracts:
            check = "[green]✓[/green]" if c.passed else "[red]✗[/red]"
            contracts_table.add_row(
                c.spec_section or "—",
                c.contract_id,
                c.agent_id or "—",
                check,
                c.detail or "—",
            )
        console.print(contracts_table)

    # ACS verdict section. Rendered when the scenario ran with an ACS
    # manifest. Each row is one intervention-point evaluation against a
    # step's wire exchange, colored by decision.
    acs_verdicts = result.acs_verdicts
    if acs_verdicts:
        decision_style = {
            "allow": "green",
            "warn": "yellow",
            "deny": "red",
            "escalate": "magenta",
        }
        acs_table = Table(
            title="ACS runtime governance (per-step verdicts)",
            show_lines=False,
        )
        acs_table.add_column("Step", justify="right", style="dim")
        acs_table.add_column("Intervention point", style="cyan")
        acs_table.add_column("Decision", justify="center")
        acs_table.add_column("Policy", style="dim")
        acs_table.add_column("Why", style="dim")
        for v in acs_verdicts:
            decision = v.get("decision", "?")
            style = decision_style.get(decision, "white")
            fc = " [red](fail-closed)[/red]" if v.get("failed_closed") else ""
            acs_table.add_row(
                str(v.get("step_index", "—")),
                str(v.get("intervention_point", "—")),
                f"[{style}]{decision}[/{style}]{fc}",
                v.get("policy_id") or "—",
                "; ".join(v.get("reasons") or []) or "—",
            )
        console.print(acs_table)

    summary = (
        f"[bold]{result.pass_count}/{result.pass_count + result.fail_count}[/bold] steps passed"
    )
    if result.contracts:
        c_total = result.contracts_pass_count + result.contracts_fail_count
        summary += f" · [bold]{result.contracts_pass_count}/{c_total}[/bold] contracts passed"
    if acs_verdicts:
        summary += (
            f" · [bold]{len(acs_verdicts)}[/bold] ACS verdicts "
            f"({result.acs_blocked_count} blocking)"
        )
        blocked_steps = sum(1 for s in result.steps if s.acs_blocked)
        if blocked_steps:
            summary += f" · [red]{blocked_steps} step(s) blocked[/red]"
    summary += f" in {result.elapsed_ms:.0f} ms"
    if result.passed:
        console.print(f"[green]✓ {summary}[/green]")
    else:
        console.print(f"[red]✗ {summary}[/red]")

    # Write declared reports if requested
    getattr(result, "_reports", None)  # populated in scenario module if present
    # We re-load scenario to pick up the declared sinks
    from a2a_testbed.scenario import load_scenario

    sc = load_scenario(scenario)
    if sc.reports:
        base = write_reports_to or scenario.parent
        paths = write_reports(result, sc.reports, base_dir=base)
        for p in paths:
            console.print(f"  → wrote [cyan]{p}[/cyan]")

    raise typer.Exit(code=0 if result.passed else 1)


@app.command(name="version")
def version_cmd() -> None:
    """Print the testbed version."""
    from a2a_testbed import __version__

    console.print(f"a2a-testbed {__version__}")


@app.command(name="compat")
def compat_cmd(
    card_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to an AgentCard JSON file (any dialect).",
    ),
    dialect: str | None = typer.Option(
        None,
        "--dialect",
        "-d",
        help=(
            "Force a specific built-in dialect by name (currently only "
            "'a2a'). Omit to auto-detect; combine with --dialect-file "
            "to load user-supplied dialects."
        ),
    ),
    dialect_file: list[Path] = typer.Option(
        None,
        "--dialect-file",
        "-f",
        help=(
            "Path to a user-supplied dialect JSON file (repeatable). "
            "Each file declares one foreign-platform dialect: name, "
            "identifying_fields, field_map, notes. The auto-detector "
            "considers user-supplied dialects alongside the built-in "
            "A2A 1.0 dialect."
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="If set, write the markdown report here. Otherwise prints to stdout.",
        resolve_path=True,
    ),
) -> None:
    """Static AgentCard compatibility check against A2A 1.0.

    Detects the source dialect (built-in A2A native, or user-supplied
    via ``--dialect-file``), applies field mappings, and reports what's
    missing or unmapped. Output is markdown.

    The testbed deliberately ships only the A2A native dialect built-in.
    For non-A2A platforms (Foundry / ADK / Bedrock / etc.) supply a
    dialect file with authoritative field mappings; we don't ship
    heuristic guesses.
    """
    import json
    from a2a_testbed.vendors import (
        DIALECTS,
        Dialect,
        check_compat,
        render_markdown,
    )

    raw = json.loads(card_path.read_text(encoding="utf-8"))

    extras: list[Dialect] = []
    for path in dialect_file or []:
        try:
            extras.append(Dialect.from_file(path))
        except Exception as exc:
            console.print(f"[red]✗ failed to load dialect file {path}:[/red] {exc}")
            raise typer.Exit(code=2)

    forced = None
    if dialect is not None:
        match = dialect.lower()
        for d in (*DIALECTS, *extras):
            if match in d.name.lower():
                forced = d
                break
        if forced is None:
            available = ", ".join(d.name for d in (*DIALECTS, *extras))
            console.print(f"[red]✗ unknown dialect {dialect!r}[/red]; available: {available}")
            raise typer.Exit(code=2)

    report = check_compat(
        raw,
        dialect=forced,
        extra_dialects=tuple(extras),
    )
    md = render_markdown(report)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        status = "[green]✓[/green]" if report.a2a_compliant else "[yellow]⚠[/yellow]"
        console.print(f"{status} wrote compat report → [cyan]{output}[/cyan]")
    else:
        console.print(md)

    raise typer.Exit(code=0 if report.a2a_compliant else 1)


@app.command(name="validate")
def validate_cmd(
    card_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to an AgentCard JSON file.",
    ),
    manifest_dir: Path | None = typer.Option(
        None,
        "--manifest-dir",
        "-m",
        help=(
            "Directory of ExtensionManifest files keyed by URI. Layout: "
            "<manifest-dir>/<host>/<uri-path>/manifest.json. When the "
            "card declares 'https://example.org/foo/v1', the validator "
            "looks for <manifest-dir>/example.org/foo/v1/manifest.json. "
            "Required for any extension to be deeply validated; "
            "extensions whose manifest isn't found report MANIFEST_NOT_FOUND."
        ),
        resolve_path=True,
    ),
    manifest_file: list[Path] = typer.Option(
        None,
        "--manifest-file",
        "-f",
        help=(
            "Path to an individual ExtensionManifest JSON file (repeatable). "
            "Each manifest's ``extension.uri`` is read from the file itself "
            "and used as the lookup key. Combine with --manifest-dir or "
            "use alone for one-off validations."
        ),
    ),
    allow_fetch: bool = typer.Option(
        False,
        "--allow-fetch",
        help=(
            "If set, fall through to HTTPS fetching when a manifest "
            "isn't found locally. Off by default for offline-first dev."
        ),
    ),
    via_mcp: bool = typer.Option(
        False,
        "--via-mcp",
        help=(
            "Additionally delegate semantic validation to each protocol's "
            "registered MCP server (deeper than the manifest's JSON Schema "
            "check). Spawns each server as a subprocess; requires the "
            "protocol package to be installed. Default registry covers "
            "Phala, NERVE, and PACE."
        ),
    ),
) -> None:
    """Offline AgentCard validation against local manifests.

    Pure local. Useful for protocol authors developing a new card +
    manifest before deploying anything. No network calls unless
    --allow-fetch is set explicitly.

    Layered manifest resolution (in order):
      1. Manifests pre-loaded via --manifest-file (in-memory)
      2. Local directory tree --manifest-dir (filesystem cache)
      3. HTTPS fetch (only if --allow-fetch)

    With --via-mcp, additionally calls each protocol's MCP validator
    tool for semantic validation (cross-field invariants the manifest
    schema can't capture).
    """
    import asyncio
    import json as _json

    from a2a_testbed.manifest import (
        CompositeManifestStore,
        ExtensionManifest,
        FindingKind,
        HttpManifestStore,
        InMemoryManifestStore,
        LocalManifestStore,
        validate_agent_card,
    )

    card = _json.loads(card_path.read_text(encoding="utf-8"))

    inline_store = InMemoryManifestStore()
    for path in manifest_file or []:
        try:
            manifest = ExtensionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            console.print(f"[red]✗ failed to load manifest file {path}:[/red] {exc}")
            raise typer.Exit(code=2)
        inline_store.add(manifest)

    stores: list = [inline_store]
    if manifest_dir is not None:
        stores.append(LocalManifestStore(manifest_dir))
    if allow_fetch:
        stores.append(HttpManifestStore())

    store = CompositeManifestStore(stores)

    findings = asyncio.run(validate_agent_card(card, store=store))

    mcp_findings = []
    if via_mcp:
        from a2a_testbed.extensions import (
            delegate_validate_card,
            make_default_registry,
        )

        try:
            mcp_findings = asyncio.run(
                delegate_validate_card(card, registry=make_default_registry())
            )
        except Exception as exc:
            console.print(f"[yellow]! MCP delegation skipped:[/yellow] {type(exc).__name__}: {exc}")

    if not findings:
        console.print(
            "[dim]no capabilities.extensions[] declared on this card "
            "(transport-only A2A agent — no extension validation needed).[/dim]"
        )
        raise typer.Exit(code=0)

    ok_count = 0
    hard_failures = 0
    for f in findings:
        if f.kind == FindingKind.DECLARED_OK:
            color = "green"
            marker = "✓"
            ok_count += 1
        elif f.kind == FindingKind.MANIFEST_NOT_FOUND:
            color = "yellow"
            marker = "?"
        elif f.kind in {FindingKind.DECLARED_INVALID, FindingKind.PAYLOAD_MISSING}:
            color = "red"
            marker = "✗"
            hard_failures += 1
        else:
            color = "yellow"
            marker = "!"
        console.print(
            f"  [{color}]{marker} {f.kind.value:30s}[/{color}] [cyan]{f.extension_uri}[/cyan]"
        )
        if f.detail:
            console.print(f"      [dim]{f.detail}[/dim]")
        for err in f.schema_errors:
            console.print(f"      [red]↳ {err}[/red]")

    total = len(findings)

    if mcp_findings:
        console.print("\n[bold]MCP delegation results:[/bold]")
        from a2a_testbed.extensions import MCPFindingKind as _MK

        for mf in mcp_findings:
            if mf.kind == _MK.PASSED:
                color = "green"
                marker = "✓"
            elif mf.kind == _MK.SERVER_UNAVAILABLE:
                color = "yellow"
                marker = "!"
            else:
                color = "red"
                marker = "✗"
                hard_failures += 1
            console.print(
                f"  [{color}]{marker} {mf.kind.value:25s}[/{color}] [cyan]{mf.extension_uri}[/cyan]"
            )
            if mf.detail:
                console.print(f"      [dim]{mf.detail}[/dim]")

    if hard_failures > 0:
        console.print(f"[red]✗ {hard_failures} broken finding(s); see above[/red]")
        raise typer.Exit(code=1)
    if ok_count < total:
        console.print(
            f"[yellow]{ok_count}/{total} validated; "
            f"{total - ok_count} unresolved (manifest missing or unknown URI)[/yellow]"
        )
        # MANIFEST_NOT_FOUND is informational — exit 0
        raise typer.Exit(code=0)
    console.print(f"[green]✓ {ok_count}/{total} extensions validated[/green]")
    raise typer.Exit(code=0)


@app.command(name="card")
def card_cmd(
    agent_url: str = typer.Argument(
        ..., help="HTTPS URL of the agent (its base, not the card path)."
    ),
    manifest_root: Path | None = typer.Option(
        None,
        "--manifest-root",
        help=(
            "Optional local directory holding cached manifests laid out as "
            "<root>/<host>/<path>/manifest.json. When set, fetched first; "
            "remote HTTP fallback follows."
        ),
        resolve_path=True,
    ),
) -> None:
    """Fetch an agent's AgentCard and validate every declared extension.

    For each entry in ``capabilities.extensions[]`` the validator
    fetches the matching ExtensionManifest (local cache first, then
    HTTP) and validates the entry's payload against the manifest's
    JSON Schema. No protocol-specific code in the testbed; any agent
    that publishes a manifest gets validated for free.
    """
    import asyncio
    import json as _json

    import httpx

    from a2a_testbed.manifest import (
        CompositeManifestStore,
        FindingKind,
        HttpManifestStore,
        InMemoryManifestStore,
        LocalManifestStore,
        validate_agent_card,
    )
    from a2a_testbed.transport import A2ATransport

    transport = A2ATransport()

    async def _run() -> int:
        card_url = agent_url.rstrip("/") + transport.card_endpoint_path()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(card_url)
        if resp.status_code != 200:
            console.print(
                f"[red]✗ failed to fetch AgentCard ({resp.status_code})[/red] "
                f"from [cyan]{card_url}[/cyan]"
            )
            return 1
        card = _json.loads(resp.text)

        stores: list = [InMemoryManifestStore()]
        if manifest_root is not None:
            stores.append(LocalManifestStore(manifest_root))
        stores.append(HttpManifestStore())
        store = CompositeManifestStore(stores)

        findings = await validate_agent_card(card, store=store)

        if not findings:
            console.print(
                "[dim]no capabilities.extensions[] declared on this card "
                "(transport-only A2A agent — no extension validation needed).[/dim]"
            )
            return 0

        ok_count = sum(1 for f in findings if f.kind == FindingKind.DECLARED_OK)
        for f in findings:
            tag = f.kind.value
            if f.kind == FindingKind.DECLARED_OK:
                color = "green"
                marker = "✓"
            elif f.kind == FindingKind.MANIFEST_NOT_FOUND:
                color = "yellow"
                marker = "?"
            else:
                color = "red"
                marker = "✗"
            console.print(f"  [{color}]{marker} {tag:30s}[/{color}] [cyan]{f.extension_uri}[/cyan]")
            if f.detail:
                console.print(f"      [dim]{f.detail}[/dim]")
            for err in f.schema_errors:
                console.print(f"      [red]↳ {err}[/red]")

        total = len(findings)
        if ok_count == total:
            console.print(f"[green]✓ {ok_count}/{total} extensions validated[/green]")
            return 0
        console.print(
            f"[yellow]{ok_count}/{total} extensions validated, "
            f"{total - ok_count} reported above[/yellow]"
        )
        # Exit non-zero only on hard failures (DECLARED_INVALID, PAYLOAD_MISSING).
        # MANIFEST_NOT_FOUND and UNKNOWN_URI are informational.
        hard_failures = sum(
            1
            for f in findings
            if f.kind in {FindingKind.DECLARED_INVALID, FindingKind.PAYLOAD_MISSING}
        )
        return 1 if hard_failures > 0 else 0

    raise typer.Exit(code=asyncio.run(_run()))


manifest_app = typer.Typer(
    name="manifest",
    help="Generate and validate ExtensionManifest documents.",
    no_args_is_help=True,
)
app.add_typer(manifest_app, name="manifest")


@manifest_app.command(name="generate")
def manifest_generate_cmd(
    extension_uri: str = typer.Option(
        ...,
        "--extension-uri",
        "-u",
        help="Stable URI used in capabilities.extensions[].uri.",
    ),
    name: str = typer.Option(..., "--name", "-n", help="Human-readable protocol name."),
    version: str = typer.Option(..., "--version", "-v", help="Protocol semver (e.g. '1.0.0')."),
    ref_class: str | None = typer.Option(
        None,
        "--ref-class",
        "-c",
        help=(
            "Dotted path to the pydantic *Ref class describing the "
            "AgentCard payload. Form: 'module.path:ClassName'. Omit for "
            "extensions that augment runtime behavior without adding "
            "card fields; the manifest will carry a permissive "
            "OpaquePayload schema."
        ),
    ),
    description: str | None = typer.Option(default=None, help="One-line description."),
    publisher: str | None = typer.Option(default=None),
    human_readable_spec: str | None = typer.Option(default=None),
    machine_readable_spec: str | None = typer.Option(default=None),
    invariant: list[str] = typer.Option(
        default=None,
        help=(
            "Repeatable. Add a human-readable invariant string. "
            "Example: --invariant 'OE-1: every terminal task ...'"
        ),
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Path to write the manifest JSON file.",
        resolve_path=True,
    ),
) -> None:
    """Generate an ExtensionManifest from a pydantic *Ref class.

    The pydantic class's ``model_json_schema()`` becomes the
    ``agent_card_payload_schema`` field — no hand-writing required.
    Any user with their own protocol pydantic model can run this
    against their model to publish a manifest at their extension URI.
    """
    from a2a_testbed.manifest import generate_manifest

    manifest = generate_manifest(
        extension_uri=extension_uri,
        name=name,
        version=version,
        ref_class=ref_class,
        description=description,
        publisher=publisher,
        human_readable_spec=human_readable_spec,
        machine_readable_spec=machine_readable_spec,
        invariants=invariant or [],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        manifest.model_dump_json(by_alias=True, indent=2, exclude_none=True),
        encoding="utf-8",
    )
    console.print(f"[green]wrote manifest[/green] [cyan]{output}[/cyan]")
    console.print(f"  uri:     [dim]{extension_uri}[/dim]")
    console.print(f"  ref:     [dim]{ref_class}[/dim]")
    console.print(f"  version: [dim]{version}[/dim]")


@manifest_app.command(name="spec")
def manifest_spec_cmd(
    manifest_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to the manifest JSON to render as SPEC.md.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="If set, write SPEC.md here. Otherwise prints to stdout.",
        resolve_path=True,
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "If set, compare the freshly-rendered SPEC.md against the "
            "file at --output and exit non-zero on drift. Useful in CI to "
            "flag when the committed SPEC.md is out of date with the "
            "manifest. Implies --output."
        ),
    ),
) -> None:
    """Render an ExtensionManifest as a developer-facing SPEC.md.

    Closes the paper-code drift gap: every protocol's repo can ship a
    SPEC.md that's auto-generated from its manifest. The preprint can
    be edited manually but the wire-format table is always sourced
    from code.
    """
    import json
    from a2a_testbed.manifest import ExtensionManifest, render_spec_md

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = ExtensionManifest.model_validate(raw)
    rendered = render_spec_md(manifest)

    if check:
        if output is None:
            console.print(
                "[red]✗ --check requires --output to point at the committed SPEC.md[/red]"
            )
            raise typer.Exit(code=2)
        if not output.exists():
            console.print(f"[red]✗ --check target does not exist: {output}[/red]")
            raise typer.Exit(code=1)
        existing = output.read_text(encoding="utf-8")
        if existing != rendered:
            console.print(f"[red]✗ SPEC.md drift detected at {output}[/red]")
            console.print("[dim]Re-run without --check to regenerate.[/dim]")
            raise typer.Exit(code=1)
        console.print(f"[green]✓ {output} is up to date[/green]")
        raise typer.Exit(code=0)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[green]wrote SPEC.md → [/green][cyan]{output}[/cyan]")
    else:
        console.print(rendered)


@manifest_app.command(name="validate")
def manifest_validate_cmd(
    manifest_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to a manifest JSON file to load and validate.",
    ),
) -> None:
    """Validate that a manifest file conforms to the manifest envelope.

    Useful for CI checks on protocol repos that publish their own
    manifests; catches drift between the JSON and the envelope shape.
    """
    import json
    from a2a_testbed.manifest import ExtensionManifest

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        ExtensionManifest.model_validate(raw)
    except Exception as exc:  # pragma: no cover - reported via CLI
        console.print(f"[red]✗ manifest invalid:[/red] {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ manifest valid[/green] [cyan]{manifest_path}[/cyan]")


@app.command(name="contracts")
def contracts_cmd(
    scenario: Path = typer.Argument(
        ...,
        help="Path to a scenario YAML; runs the scenario, then evaluates "
        "transport contracts against every in-process agent + network "
        "contracts against the run result.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    log_level: str = typer.Option("error", "--log-level", "-l"),
) -> None:
    """Run a scenario, then evaluate the spec-derived contract suite."""
    from a2a_testbed.contracts.runner import (
        run_transport_contracts,
    )
    from a2a_testbed.transport import A2ATransport

    async def _run() -> int:
        await run_scenario_file(scenario, log_level=log_level)
        # Probe each in-process agent via its multitenant URL using
        # the same transport the scenario ran with. The scenario is
        # re-loaded to surface the network instance that already
        # booted the agents.
        from a2a_testbed.scenario import load_scenario

        scenario_obj = load_scenario(scenario)
        scenario_dir = scenario.parent
        from a2a_testbed.network.multitenant import MultiTenantNetwork
        from a2a_testbed.runtimes.python_inproc import PythonInProcRuntime
        from a2a_testbed.core.loader import load_agent_card_from_path
        from a2a_testbed.scenario import scripts_from_steps

        scripts = scripts_from_steps(scenario_obj.flow)
        transport = A2ATransport()

        # Spin up a fresh multi-tenant network just for contract probing.
        net = MultiTenantNetwork(log_level=log_level, transport=transport)
        for decl in scenario_obj.agents:
            card_path = (
                scenario_dir / decl.card if not Path(decl.card).is_absolute() else Path(decl.card)
            )
            card = load_agent_card_from_path(card_path)
            runtime = PythonInProcRuntime(decl.id, card, scripts=dict(scripts.get(decl.id, {})))
            net.register(runtime)

        async with net:
            agent_table = Table(title="Transport contracts (per agent)", show_lines=False)
            agent_table.add_column("Agent", style="cyan")
            agent_table.add_column("Contract", style="dim")
            agent_table.add_column("Pass", justify="center")
            agent_table.add_column("Detail")

            all_results: list = []
            for agent_id in sorted(net._runtimes.keys()):
                url = net.url_of(agent_id)
                results = await run_transport_contracts(transport, url)
                for r in results:
                    all_results.append((agent_id, r))
                    check = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
                    agent_table.add_row(agent_id, r.contract_id, check, r.detail or "—")

            console.print(agent_table)

            summary = {
                "total": len(all_results),
                "passed": sum(1 for _, r in all_results if r.passed),
                "failed": sum(1 for _, r in all_results if not r.passed),
            }

        if summary["failed"] == 0:
            console.print(
                f"[green]✓ {summary['passed']}/{summary['total']} "
                f"transport contracts passed[/green]"
            )
            return 0

        console.print(f"[red]✗ {summary['failed']} of {summary['total']} contracts failed[/red]")
        return 1

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


@app.command(name="conformance")
def conformance_cmd(
    agent_url: str = typer.Argument(
        ...,
        help=(
            "HTTPS URL of the agent to test (its base, not the card path). "
            "Example: https://my-agent.example.com"
        ),
    ),
    fail_on_deviation: bool = typer.Option(
        False,
        "--strict",
        help=(
            "Treat capability-consistency deviations (agent refused but "
            "with the wrong error code) as failures. Off by default — "
            "those soft passes still surface in the detail column."
        ),
    ),
) -> None:
    """Run the full A2A 1.0 transport-contract sweep against a deployed agent.

    Standalone counterpart to ``run``: takes a URL, fetches the
    AgentCard, and exercises every spec-derived transport contract
    (~23 probes) against the live deployment. Prints a per-row table
    with the spec section each contract enforces and exits non-zero
    if any contract fails.

    Use this for your own deployed agents — Cloudflare Workers,
    AWS Lambda, GKE, anywhere — to confirm conformance before
    onboarding a third party. The ``run --probe-external`` flag
    does the same checks inside a multi-agent scenario when you'd
    rather drive realistic flow at the same time.
    """
    from a2a_testbed.contracts.runner import run_transport_contracts
    from a2a_testbed.spec_meta import load_spec_meta
    from a2a_testbed.transport import A2ATransport

    transport = A2ATransport()

    async def _run() -> int:
        try:
            results = await run_transport_contracts(transport, agent_url)
        except Exception as exc:  # pragma: no cover - defensive
            console.print(f"[red]✗ contract sweep failed before completing: {exc}[/red]")
            return 2

        meta = load_spec_meta()
        spec_label = (
            f"{meta.name} {meta.version}"
            f"{f' (commit {meta.short_commit})' if meta.short_commit else ''}"
        )
        table = Table(
            title=f"Conformance: {agent_url} vs. {spec_label}",
            show_lines=False,
        )
        table.add_column("Spec §", style="dim", no_wrap=True)
        table.add_column("Contract", style="cyan")
        table.add_column("Pass", justify="center")
        table.add_column("Detail", style="dim")

        passed = 0
        failed = 0
        deviations = 0
        for r in results:
            check = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
            # Contracts that returned a soft-pass detail string are
            # still passed=True but their detail starts with
            # "capability honored —" or similar. Surface them as
            # warnings so the operator can decide whether to act.
            if r.passed and r.detail:
                check = "[yellow]~[/yellow]"
                deviations += 1
            if r.passed:
                passed += 1
            else:
                failed += 1
            table.add_row(
                r.spec_section or "—",
                r.contract_id,
                check,
                r.detail or "—",
            )
        console.print(table)
        console.print()

        # Decide exit code. Strict mode promotes deviations to failures
        # so CI can gate on "perfect conformance"; default lets them
        # through (the agent honored the capability).
        effective_failures = failed + (deviations if fail_on_deviation else 0)
        if effective_failures == 0:
            console.print(
                f"[green]✓ {passed}/{len(results)} contracts passed[/green]"
                + (
                    f"  [yellow]({deviations} soft-pass deviation"
                    f"{'s' if deviations != 1 else ''})[/yellow]"
                    if deviations
                    else ""
                )
            )
            return 0

        if failed:
            console.print(f"[red]✗ {failed} of {len(results)} contracts failed[/red]")
        if fail_on_deviation and deviations:
            console.print(
                f"[red]✗ --strict: {deviations} deviation"
                f"{'s' if deviations != 1 else ''} treated as failures[/red]"
            )
        return 1

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


@app.command(name="coverage")
def coverage_cmd() -> None:
    """Report contract coverage of the A2A spec.

    Walks ``src/a2a_testbed/contracts/`` to count implemented
    contracts per category and prints them alongside the roadmap
    categories declared in ``contracts/CATALOG.md``. Header carries
    the spec pin from ``pyproject.toml`` so the reader knows which
    version of the spec the coverage claim is against.
    """
    from datetime import date, datetime, timedelta

    from a2a_testbed.spec_meta import load_spec_meta

    meta = load_spec_meta()
    contracts_root = Path(__file__).resolve().parents[1] / "contracts"

    # Filesystem walk: every non-helper .py under contracts/<category>/
    # is one implemented contract. Files starting with `_` are
    # internal helpers (e.g. `_task_helpers.py`), not contracts.
    excluded = {"__init__.py", "base.py", "runner.py"}
    impl_files: dict[str, set[str]] = {}
    for category_dir in sorted(p for p in contracts_root.iterdir() if p.is_dir()):
        files = {
            f.stem
            for f in category_dir.glob("*.py")
            if f.name not in excluded and not f.name.startswith("_")
        }
        impl_files[category_dir.name] = files

    # Map each implemented contract module to the roadmap category it
    # actually fulfills (the on-disk directory groups by file-tree
    # convenience, not by spec section). Update this map when adding
    # new contracts; the quarterly review checklist references it.
    CONTRACT_CATEGORY: dict[str, str] = {
        # Transport: AgentCard structural / discovery
        "well_known_card": "agentcard structural",
        "agent_card_required_fields": "agentcard structural",
        "agent_card_has_skills": "agentcard structural",
        "agent_card_skill_id_unique": "agentcard structural",
        "agent_card_capabilities_object": "agentcard structural",
        "agent_card_supported_interfaces": "agentcard structural",
        "agent_card_preferred_interface": "agentcard structural",
        "agent_card_url_well_formed": "agentcard structural",
        "provider_well_formed": "agentcard structural",
        "default_modes_distinct": "agentcard structural",
        # Extension declarations
        "extensions_uri_absolute": "extensions (spec-section)",
        "extensions_uri_unique": "extensions (spec-section)",
        # Versioning
        "agent_card_protocol_version_format": "versioning",
        # Transport-level security / authorization
        "agent_card_https_urls": "authorization / security",
        "agent_card_security_schemes": "authorization / security",
        "signatures_well_formed": "authorization / security",
        # JSON serialization
        "json_camel_case": "json serialization",
        "iso8601_timestamps": "json serialization",
        # JSON-RPC envelope + error semantics
        "jsonrpc_envelope": "jsonrpc envelope/errors",
        "jsonrpc_version_field": "jsonrpc envelope/errors",
        "jsonrpc_id_echo": "jsonrpc envelope/errors",
        "jsonrpc_result_xor_error": "jsonrpc envelope/errors",
        "jsonrpc_error_code_range": "jsonrpc envelope/errors",
        "method_not_found": "jsonrpc envelope/errors",
        "send_message_required_fields": "jsonrpc envelope/errors",
        "error_data_atype": "jsonrpc envelope/errors",
        # Capability ↔ method consistency
        "streaming_capability_consistency": "capability validation",
        "push_notifications_capability_consistency": "capability validation",
        "extended_card_capability_consistency": "capability validation",
        # Task lifecycle
        "task_id_uuid_format": "task lifecycle",
        "task_status_state_enum": "task lifecycle",
        "task_status_timestamp_present": "task lifecycle",
        "task_history_shape": "task lifecycle",
        "task_artifacts_shape": "task lifecycle",
        # GetTask / CancelTask / ListTasks
        "tasks_get_returns_task": "GetTask / ListTasks / CancelTask",
        "tasks_get_not_found": "GetTask / ListTasks / CancelTask",
        "tasks_cancel_sets_canceled": "GetTask / ListTasks / CancelTask",
        "tasks_cancel_not_found": "GetTask / ListTasks / CancelTask",
        "tasks_list_sorted_desc": "GetTask / ListTasks / CancelTask",
        # Multi-turn
        "task_context_id_echoed": "multi-turn (contextId/taskId)",
        # Streaming SSE
        "streaming_response_content_type": "streaming (SSE)",
        "streaming_first_event_is_task": "streaming (SSE)",
        "streaming_event_kinds": "streaming (SSE)",
        "streaming_status_update_shape": "streaming (SSE)",
        "streaming_artifact_update_shape": "streaming (SSE)",
        "streaming_task_id_consistency": "streaming (SSE)",
        "streaming_terminal_state_closes": "streaming (SSE)",
        # Subscribe to task
        "subscribe_returns_stream": "subscribe to task",
        "subscribe_replays_state": "subscribe to task",
        "subscribe_not_found": "subscribe to task",
        "subscribe_capability_required": "subscribe to task",
        # Push notifications
        "push_set_persists": "push notifications",
        "push_get_returns_config": "push notifications",
        "push_list_returns_all": "push notifications",
        "push_delete_removes": "push notifications",
        "push_set_task_not_found": "push notifications",
        "push_get_task_not_found": "push notifications",
        "push_fires_on_completion": "push notifications",
        # Network (testbed-original)
        "fault_recovery": "network (original)",
        "observer_receives_traffic": "network (original)",
        "time_advance_visibility": "network (original)",
    }

    impl_by_cat: dict[str, int] = {}
    for stems in impl_files.values():
        for stem in stems:
            cat = CONTRACT_CATEGORY.get(stem)
            if cat is None:
                # Unmapped contract — treat as uncategorized so it's
                # visible. Adding to CONTRACT_CATEGORY is part of
                # "add a new contract" in CONTRIBUTING.md.
                cat = "uncategorized"
            impl_by_cat[cat] = impl_by_cat.get(cat, 0) + 1

    # Roadmap categories tracked in CATALOG.md. (label, implemented,
    # roadmap_total, spec_sections). When implemented count == 0 the
    # category is purely roadmap; when roadmap_total == 0 the category
    # is fully covered by the existing implementations.
    ROADMAP: list[tuple[str, int, int, str]] = [
        (
            "agentcard structural",
            impl_by_cat.get("agentcard structural", 0),
            0,
            "§4.4, §8.1, §8.2, §8.3",
        ),
        (
            "versioning",
            impl_by_cat.get("versioning", 0),
            2,  # ~3 total - 1 done
            "§3.6",
        ),
        (
            "authorization / security",
            impl_by_cat.get("authorization / security", 0),
            1,  # ~4 total - 3 done
            "§7, §13",
        ),
        ("json serialization", impl_by_cat.get("json serialization", 0), 0, "§5.5, §5.6.1"),
        (
            "jsonrpc envelope/errors",
            impl_by_cat.get("jsonrpc envelope/errors", 0),
            0,
            "§3.1.1, §9.3, §9.5",
        ),
        (
            "capability validation",
            impl_by_cat.get("capability validation", 0),
            2,  # ~5 - 3 done
            "§3.3.4, §3.1.2, §3.1.7, §3.5",
        ),
        (
            "extensions (spec-section)",
            impl_by_cat.get("extensions (spec-section)", 0),
            4,  # ~6 - 2 done
            "§4.4.4, §4.6",
        ),
        ("network (original)", impl_by_cat.get("network (original)", 0), 0, "(testbed-original)"),
        (
            "task lifecycle",
            impl_by_cat.get("task lifecycle", 0),
            2,  # ~7 - 5 done
            "§3.4, §4.1.1, §4.1.3",
        ),
        (
            "GetTask / ListTasks / CancelTask",
            impl_by_cat.get("GetTask / ListTasks / CancelTask", 0),
            5,  # ~10 - 5 done
            "§3.1.3–§3.1.5",
        ),
        (
            "multi-turn (contextId/taskId)",
            impl_by_cat.get("multi-turn (contextId/taskId)", 0),
            4,  # ~5 - 1 done
            "§3.4.1–§3.4.3",
        ),
        (
            "streaming (SSE)",
            impl_by_cat.get("streaming (SSE)", 0),
            0,  # ~7 - 7 done
            "§3.1.2, §4.1.6, §4.1.7",
        ),
        (
            "subscribe to task",
            impl_by_cat.get("subscribe to task", 0),
            0,  # ~4 - 4 done
            "§3.1.6",
        ),
        (
            "push notifications",
            impl_by_cat.get("push notifications", 0),
            0,  # ~7 - 7 done
            "§3.1.7–§3.1.10, §3.5",
        ),
    ]
    # Surface unmapped contracts at the bottom so a contributor who
    # adds a contract without updating CONTRACT_CATEGORY still sees
    # their work in the report (with a hint that the category map
    # needs updating).
    if impl_by_cat.get("uncategorized"):
        ROADMAP.append(
            (
                "uncategorized (update CONTRACT_CATEGORY)",
                impl_by_cat["uncategorized"],
                0,
                "—",
            )
        )

    implemented_total = sum(impl_by_cat.values())
    roadmap_total = sum(rt for _, _, rt, _ in ROADMAP)
    overall_total = implemented_total + roadmap_total
    pct = (implemented_total / overall_total * 100.0) if overall_total else 0.0

    # Header: the spec pin.
    console.print()
    console.print(
        f"[bold]{meta.name} {meta.version}[/bold] "
        f"[dim]commit[/dim] [cyan]{meta.short_commit or '—'}[/cyan]"
    )
    if meta.commit:
        console.print(f"[dim]Spec text:[/dim] [link]{meta.specification_url}[/link]")
    if meta.last_reviewed:
        try:
            reviewed = datetime.strptime(meta.last_reviewed, "%Y-%m-%d").date()
            next_due = reviewed + timedelta(days=90)
            today = date.today()
            stale_days = (today - next_due).days
            stale_label = (
                f"[red](overdue by {stale_days} days)[/red]"
                if stale_days > 0
                else "[green](on schedule)[/green]"
            )
            console.print(
                f"[dim]Last reviewed:[/dim] {meta.last_reviewed} · "
                f"[dim]next review due:[/dim] {next_due.isoformat()} "
                f"{stale_label}"
            )
        except ValueError:
            console.print(f"[dim]Last reviewed:[/dim] {meta.last_reviewed}")
    console.print()

    # Coverage table.
    table = Table(title="Contract coverage", show_lines=False)
    table.add_column("Category", style="cyan")
    table.add_column("Done", justify="right", style="green")
    table.add_column("Open", justify="right", style="dim")
    table.add_column("Spec sections", style="dim")

    for label, done, open_count, sections in ROADMAP:
        open_str = "—" if open_count == 0 else f"~{open_count}"
        done_str = str(done) if done > 0 else "[dim]0[/dim]"
        table.add_row(label, done_str, open_str, sections)

    console.print(table)
    console.print()
    console.print(
        f"[bold]Implemented:[/bold] {implemented_total}  "
        f"[dim]·[/dim]  [bold]Open:[/bold] ~{roadmap_total}  "
        f"[dim]·[/dim]  [bold]Coverage:[/bold] "
        f"{pct:.0f}% of ~{overall_total}"
    )
    console.print(
        "[dim]See "
        "src/a2a_testbed/contracts/CATALOG.md for the full clause "
        "breakdown and roadmap notes.[/dim]"
    )


# ----------------------------------------------------------------------
# ACS (Agent Control Specification) — local manifest validation.
#
# Microsoft's ACS launch ships no hosted/online validator; validation is
# local. This sub-group is the testbed's local equivalent. Grouped under
# `acs` so it sits beside the (separate) extension-manifest `validate`.
# ----------------------------------------------------------------------
acs_app = typer.Typer(
    name="acs",
    no_args_is_help=True,
    help="Agent Control Specification (ACS) tools: manifest validation.",
)
app.add_typer(acs_app, name="acs")


@acs_app.command(name="validate")
def acs_validate_cmd(
    manifest: Path = typer.Argument(
        ...,
        help="Path to an ACS manifest YAML file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero on warnings as well as errors (for CI gating).",
    ),
) -> None:
    """Validate an ACS manifest locally and print a findings table.

    Structural checks (does it parse into a well-formed manifest) plus
    semantic cross-checks (undeclared-policy references, Rego policies
    needing an external backend, model-call points not observable at the
    A2A wire seam). Exits 1 when any error-level finding is present, or
    on any finding under ``--strict``.
    """
    from a2a_testbed.acs import validate_manifest

    result = validate_manifest(manifest)

    table = Table(title=f"ACS manifest validation — {manifest.name}", show_lines=False)
    table.add_column("Result", style="bold")
    table.add_column("Where", style="cyan")
    table.add_column("Detail", style="dim", overflow="fold")

    style_for = {"ok": "green", "warn": "yellow", "error": "red"}
    for f in result.findings:
        bucket = "error" if f.is_error else ("warn" if f.kind.value.startswith("warn_") else "ok")
        mark = {"ok": "✓ OK", "warn": "▲ WARN", "error": "✗ ERROR"}[bucket]
        table.add_row(f"[{style_for[bucket]}]{mark}[/]", f.locus or "—", f.detail)
        for err in f.errors:
            table.add_row("", "", f"[red]· {err}[/red]")

    console.print(table)

    has_error = any(f.is_error for f in result.findings)
    has_warn = any(f.kind.value.startswith("warn_") for f in result.findings)
    if has_error:
        console.print("[red bold]Invalid:[/red bold] manifest has error-level findings.")
        raise typer.Exit(code=1)
    if strict and has_warn:
        console.print("[yellow bold]Strict:[/yellow bold] warnings present, failing as requested.")
        raise typer.Exit(code=1)
    console.print("[green bold]Valid.[/green bold]")


@acs_app.command(name="spec")
def acs_spec_cmd(
    manifest: Path = typer.Argument(
        ...,
        help="Path to an ACS manifest YAML file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the Markdown summary here instead of stdout.",
    ),
) -> None:
    """Render a human-readable governance summary of an ACS manifest.

    Turns the manifest into plain-English Markdown — which checkpoints,
    which policies, what each rule decides, evidence, tools — for review
    and audit. There is no `generate` command: an ACS manifest is
    authored governance intent, not a projection of a data model.
    """
    from a2a_testbed.acs import validate_manifest
    from a2a_testbed.acs.spec_md import render_spec_md

    result = validate_manifest(manifest)
    if result.manifest is None:
        problems = "; ".join(f.detail for f in result.findings if f.is_error)
        console.print(f"[red]Cannot summarize — invalid manifest:[/red] {problems}")
        raise typer.Exit(code=1)

    md = render_spec_md(result.manifest)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(md, encoding="utf-8")
        console.print(f"  → wrote [cyan]{output}[/cyan]")
    else:
        typer.echo(md)


@acs_app.command(name="init")
def acs_init_cmd(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write the scaffold here instead of stdout.",
    ),
    name: str = typer.Option("my-agent", "--name", help="metadata.name for the scaffold."),
) -> None:
    """Scaffold a starter ACS manifest to edit.

    Emits a commented manifest with one intervention point, a sample
    builtin rule, and a tool — a starting point for authoring, not a
    finished policy. Validate it with `acs validate`, summarize with
    `acs spec`.
    """
    from a2a_testbed.acs.spec_md import starter_manifest_yaml

    text = starter_manifest_yaml(name)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        console.print(f"  → wrote [cyan]{output}[/cyan]")
        console.print("Next: edit it, then `a2a-testbed acs validate` / `acs spec`.")
    else:
        typer.echo(text)


if __name__ == "__main__":
    app()
