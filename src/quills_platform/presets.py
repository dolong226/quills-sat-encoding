# Standard topologies: line, tenerife, guadalupe,...
from quills_platform.topology import Topology

def line_topology(n: int) -> Topology:
    edges = [(i, i+1) for i in range (n-1)]

    return Topology(n_qubits=n, edges=edges)

def ibmq_guadalupe() -> Topology:
    return Topology(
        n_qubits=16,
        edges=[
            (0, 1), (1, 2), (1, 4),
            (2, 3), (3, 5), (4, 7),
            (5, 8), (6, 7), (7, 10),
            (8, 9), (8, 11), (10, 12),
            (11, 14), (12, 13), (12, 15),
            (13, 14)
        ]
    )