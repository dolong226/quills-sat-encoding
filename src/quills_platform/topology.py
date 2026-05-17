# undirected graph P = (node, Pconn)

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple
from collections import defaultdict, deque

@dataclass
class Topology:
    # Hardware coupling graph P = (nodes, edges)

    n_qubits: int
    edges: List[Tuple[int, int]]
    adjacency: Dict[int, Set[int]] = field(default_factory=dict)

    def __post_init__(self):

        self.adjacency = defaultdict(set)

        for u, v in self.edges:
            self.adjacency[u].add(v)
            self.adjacency[v].add(u)

    def is_connected(self, q1: int, q2: int) -> bool:
        return q2 in self.adjacency[q1]
    
    def neighbors(self, q: int) -> Set[int]:
        return self.adjacency[q]
    
    def degree(self, q:int) -> int:
        return len(self.adjacency[q])
    
    def shortest_distance(self, src: int, dst: int) -> int:
        """
        BFS shortest path length.
        """

        if src == dst:
            return 0

        visited = {src}
        queue = deque([(src, 0)])

        while queue:

            node, dist = queue.popleft()

            for nxt in self.adjacency[node]:

                if nxt == dst:
                    return dist + 1

                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, dist + 1))

        raise ValueError(f"No path between {src} and {dst}")
        

    # Utility

    @property
    def nodes(self) -> List[int]:
        return list(range(self.n_quits))
    
    @property
    def edge_set(self) -> Set[Tuple[int, int]]:
        return {tuple(sorted((u, v))) for u, v in self.edges}
    
    def __str__(self) -> str:
        return (
            f"Topology(n_qubits={self.n_qubits}, "
            f"edges={self.edges})"
        )

