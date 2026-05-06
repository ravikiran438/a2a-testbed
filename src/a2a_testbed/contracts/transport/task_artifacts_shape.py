# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Transport contract: Task.artifacts (when present) is a typed array.

  Spec:    A2A 1.0 §4.1.1 (Task), §4.1.5 (Artifact)
  Source:  docs/specification.md (LF AI & Data A2A repo)
  Clause:  ``Task.artifacts`` is an OPTIONAL array carrying the
           Task's outputs. Each entry MUST be an Artifact object
           with at minimum an ``artifactId`` (string) and ``parts``
           (a non-empty Part array). Clients enumerate artifacts to
           extract results; entries missing identity are unaddressable.
"""

from __future__ import annotations

from a2a_testbed.contracts.base import Contract, ContractCategory
from a2a_testbed.contracts.transport._task_helpers import probe_for_task
from a2a_testbed.transport import Transport


def make_task_artifacts_shape_contract(
    transport: Transport, agent_url: str
) -> Contract:
    async def verify() -> str | None:
        task = await probe_for_task(transport, agent_url)
        if task is None:
            return "skipped — agent did not return a Task envelope"
        artifacts = task.get("artifacts")
        if artifacts is None:
            return None  # OPTIONAL field
        assert isinstance(artifacts, list), (
            "Task.artifacts MUST be an array when present"
        )
        for i, art in enumerate(artifacts):
            assert isinstance(art, dict), (
                f"Task.artifacts[{i}] MUST be an Artifact object"
            )
            artifact_id = art.get("artifactId")
            assert isinstance(artifact_id, str) and artifact_id, (
                f"Task.artifacts[{i}].artifactId is REQUIRED, non-empty string"
            )
            parts = art.get("parts")
            assert isinstance(parts, list) and parts, (
                f"Task.artifacts[{i}].parts MUST be a non-empty array"
            )
        return None

    return Contract(
        id="transport.task_artifacts_shape",
        description=(
            "Task.artifacts (when present) is a well-formed Artifact array (§4.1.1 + §4.1.5)"
        ),
        category=ContractCategory.TRANSPORT,
        verify_fn=verify,
    )
