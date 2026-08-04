"""Đăng ký các topology phần cứng có sẵn (preset)."""

from __future__ import annotations

from quills_platform.presets import ibmq_guadalupe, sycamore
from quills_platform.topology import Topology

TOPOLOGY_PRESETS: dict[str, str] = {
    "ibmq_guadalupe": "IBM Guadalupe — 16 qubits",
    "sycamore": "Google Sycamore — 54 qubits",
}


def build_topology(name: str) -> Topology:
    if name.lower() == "ibmq_guadalupe":
        return ibmq_guadalupe()
    if name.lower() == "sycamore":
        return sycamore()
    raise ValueError(f"Unknown topology '{name}'. Available: {', '.join(TOPOLOGY_PRESETS)}")
