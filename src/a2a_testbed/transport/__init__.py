# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Wire-format transport abstraction.

The orchestration layer (scenario runner, network, observers, faults,
time controller) talks to agents only through ``Transport``. A future
protocol implements one `Transport` subclass and the rest of the
testbed works untouched. See SOW §12.1.
"""

from a2a_testbed.transport.a2a_transport import A2ATransport
from a2a_testbed.transport.base import (
    AgentDescriptor,
    Transport,
    WireMessage,
    WireResponse,
)

__all__ = [
    "A2ATransport",
    "AgentDescriptor",
    "Transport",
    "WireMessage",
    "WireResponse",
]
