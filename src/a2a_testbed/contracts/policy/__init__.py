# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""ACS runtime-governance contracts.

Unlike transport/network contracts (which probe a live A2A agent),
policy contracts assert properties of the ACS control layer itself
against a supplied manifest + snapshot: that enforcement yields the
declared verdict, and that the layer fails closed when evidence or
policy evaluation errors. They are testbed-original, citing the ACS
spec rather than the A2A spec.
"""

from a2a_testbed.contracts.policy.acs_enforcement import (
    make_acs_enforcement_contract,
)
from a2a_testbed.contracts.policy.acs_fail_closed import (
    make_acs_fail_closed_contract,
)


__all__ = [
    "make_acs_enforcement_contract",
    "make_acs_fail_closed_contract",
]
