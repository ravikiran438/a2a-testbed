"""Serve a test agent for the Action self-test workflow.

    uv run --extra dev python scripts/ci/serve_oracle.py {1.0|0.3|dual|drift} PORT

``1.0`` / ``0.3`` / ``dual`` are agents built on the official a2a-sdk
(tests/oracles/sdk_agents.py); ``drift`` advertises A2A 1.0 but serves
only 0.3 method names, the bug the conformance gate exists to catch.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.integration.test_protocol_versions import _drift_agent  # noqa: E402
from tests.oracles.sdk_agents import build_sdk_agent, serve  # noqa: E402


async def main(kind: str, port: int) -> None:
    factory = _drift_agent if kind == "drift" else (lambda base: build_sdk_agent(base, kind))
    async with serve(factory, port=port) as url:
        print(f"serving {kind} agent at {url}", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
