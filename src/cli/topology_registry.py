"""Đăng ký các topology phần cứng có sẵn (preset)."""

from __future__ import annotations

from quills_platform.presets import ibmq_guadalupe
from quills_platform.topology import Topology

TOPOLOGY_PRESETS: dict[str, str] = {
    "ibmq_guadalupe": "IBM Guadalupe — 16 qubits",
}


def build_topology(name: str) -> Topology:
    if name.lower() == "ibmq_guadalupe":
        return ibmq_guadalupe()
    raise ValueError(f"Unknown topology '{name}'. Available: {', '.join(TOPOLOGY_PRESETS)}")
