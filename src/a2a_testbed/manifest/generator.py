# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Generate ExtensionManifest documents from pydantic models.

The hard part of writing a manifest is the JSON Schema for the
AgentCard payload. Pydantic models already produce conforming JSON
Schema via ``model_json_schema()``, so any protocol that types its
``*Ref`` class as a pydantic model gets a manifest for free.
"""

from __future__ import annotations

import importlib
from typing import Any, Optional

from pydantic import BaseModel

from a2a_testbed.manifest.types import (
    ExtensionManifest,
    ExtensionMetadata,
    WireArtefact,
)


def _import_class(dotted_path: str) -> type[BaseModel]:
    """Import a class from a ``module.path:ClassName`` or ``module.path.ClassName``.

    Both forms are supported because typer/CLI-friendly invocation
    typically uses ``:`` to separate module from attribute, while
    Python's stdlib uses ``.``. We accept either.
    """
    if ":" in dotted_path:
        module_path, attr = dotted_path.split(":", 1)
    else:
        module_path, _, attr = dotted_path.rpartition(".")
        if not module_path:
            raise ValueError(
                f"Invalid dotted path: {dotted_path!r} "
                "(expected 'module.path:ClassName' or 'module.path.ClassName')"
            )
    module = importlib.import_module(module_path)
    cls = getattr(module, attr, None)
    if cls is None:
        raise ImportError(f"Module {module_path!r} has no attribute {attr!r}")
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        raise TypeError(
            f"{dotted_path!r} resolved to {cls!r}; expected a subclass of pydantic.BaseModel"
        )
    return cls


def generate_manifest(
    *,
    extension_uri: str,
    name: str,
    version: str,
    ref_class: type[BaseModel] | str | None = None,
    description: Optional[str] = None,
    publisher: Optional[str] = None,
    human_readable_spec: Optional[str] = None,
    machine_readable_spec: Optional[str] = None,
    wire_artefacts: Optional[list[dict[str, Any]]] = None,
    invariants: Optional[list[str]] = None,
) -> ExtensionManifest:
    """Build an ExtensionManifest from a pydantic ``*Ref`` class.

    ``ref_class`` may be a class object (used by code-level callers), a
    dotted path string ``module.path:ClassName`` (used by the CLI), or
    None for extensions that augment runtime behavior without adding
    AgentCard fields. When None, the manifest's
    ``agent_card_payload_schema`` defaults to a permissive
    ``OpaquePayload`` schema.

    ``wire_artefacts`` accepts a list of dicts with keys matching the
    ``WireArtefact`` model: ``name``, optional ``description``,
    ``endpoint_field``, ``method`` (default POST), and ``schema`` (a
    JSON Schema or a dotted path to another pydantic model — if the
    latter is supplied, we resolve it to a JSON Schema here).
    """
    schema: Optional[dict] = None
    if ref_class is not None:
        if isinstance(ref_class, str):
            ref_class = _import_class(ref_class)
        elif not (isinstance(ref_class, type) and issubclass(ref_class, BaseModel)):
            raise TypeError(f"ref_class must be a pydantic.BaseModel subclass; got {ref_class!r}")
        schema = ref_class.model_json_schema()

    artefacts: list[WireArtefact] = []
    for raw in wire_artefacts or []:
        spec = dict(raw)
        # If the schema is a dotted path, resolve it.
        artefact_schema = spec.get("schema")
        if isinstance(artefact_schema, str):
            artefact_cls = _import_class(artefact_schema)
            spec["schema"] = artefact_cls.model_json_schema()
        artefacts.append(WireArtefact.model_validate(spec))

    kwargs: dict[str, Any] = dict(
        extension=ExtensionMetadata(
            uri=extension_uri,
            name=name,
            description=description,
            version=version,
            publisher=publisher,
            human_readable_spec=human_readable_spec,
            machine_readable_spec=machine_readable_spec,
        ),
        wire_artefacts=artefacts,
        invariants=list(invariants or []),
    )
    if schema is not None:
        kwargs["agent_card_payload_schema"] = schema
    return ExtensionManifest(**kwargs)
