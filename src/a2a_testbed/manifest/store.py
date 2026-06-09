# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""ManifestStore: pluggable backend for fetching extension manifests.

Production deployments fetch over HTTP from the manifest URL derived
from the extension URI. Tests and offline use fetch from disk or an
in-memory dict. The store interface hides those concerns so the
validator code stays the same.

## URI -> manifest URL convention

By default a manifest for extension URI ``X`` is hosted at
``<X>/manifest.json``. Implementations MAY override
``manifest_url_for_uri`` to encode site-specific conventions (e.g.
GitHub Pages, ``.well-known`` paths).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

import httpx

from a2a_testbed.manifest.types import ExtensionManifest


def manifest_url_for_uri(extension_uri: str) -> str:
    """Default convention: append ``/manifest.json`` to the extension URI."""
    return extension_uri.rstrip("/") + "/manifest.json"


class ManifestStore(Protocol):
    """Anything that can resolve an extension URI to an ExtensionManifest."""

    async def fetch(self, extension_uri: str) -> Optional[ExtensionManifest]:
        """Return the manifest for ``extension_uri``, or None if not found."""
        ...


class HttpManifestStore:
    """Fetches manifests over HTTP, caching responses in memory."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._client = client
        self._cache: dict[str, ExtensionManifest] = {}

    async def fetch(self, extension_uri: str) -> Optional[ExtensionManifest]:
        if extension_uri in self._cache:
            return self._cache[extension_uri]
        url = manifest_url_for_uri(extension_uri)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own_client = self._client is None
        try:
            try:
                resp = await client.get(url)
            except httpx.HTTPError:
                return None
            if resp.status_code != 200:
                return None
            try:
                manifest = ExtensionManifest.model_validate_json(resp.text)
            except Exception:
                return None
            self._cache[extension_uri] = manifest
            return manifest
        finally:
            if own_client:
                await client.aclose()


class LocalManifestStore:
    """Loads manifests from a directory keyed by URI.

    Layout: ``<root>/<uri-path>/manifest.json``. The URI path is the
    URI's host + path with no trailing slash. Useful for local dev
    where you'd rather not run an HTTP server while iterating.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._cache: dict[str, ExtensionManifest] = {}

    def _path_for(self, extension_uri: str) -> Path:
        # Strip scheme + collapse to a relative path under root.
        without_scheme = extension_uri.split("://", 1)[-1]
        without_scheme = without_scheme.rstrip("/")
        return self._root / without_scheme / "manifest.json"

    async def fetch(self, extension_uri: str) -> Optional[ExtensionManifest]:
        if extension_uri in self._cache:
            return self._cache[extension_uri]
        path = self._path_for(extension_uri)
        if not path.exists():
            return None
        try:
            manifest = ExtensionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        self._cache[extension_uri] = manifest
        return manifest


class InMemoryManifestStore:
    """Pre-populated mapping from URI to ExtensionManifest. For tests."""

    def __init__(self, manifests: Optional[dict[str, ExtensionManifest]] = None) -> None:
        self._manifests = dict(manifests or {})

    def add(self, manifest: ExtensionManifest) -> None:
        self._manifests[manifest.extension.uri] = manifest

    def add_from_dict(self, payload: dict) -> None:
        m = ExtensionManifest.model_validate(payload)
        self.add(m)

    def add_from_json(self, raw: str) -> None:
        m = ExtensionManifest.model_validate_json(raw)
        self.add(m)

    async def fetch(self, extension_uri: str) -> Optional[ExtensionManifest]:
        return self._manifests.get(extension_uri)


class CompositeManifestStore:
    """Try each store in order; return the first hit. Falls through on miss.

    Typical layout: ``[InMemory(test fixtures), Local(dev cache), Http(production)]``.
    """

    def __init__(self, stores: list[ManifestStore]) -> None:
        self._stores = list(stores)

    async def fetch(self, extension_uri: str) -> Optional[ExtensionManifest]:
        for store in self._stores:
            m = await store.fetch(extension_uri)
            if m is not None:
                return m
        return None
