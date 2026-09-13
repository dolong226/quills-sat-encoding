from encoding.base import ConstraintGroup
from encoding.helpers import *
from circuit.gate import *
from circuit.parser import *

class ConnectivityConstraints(ConstraintGroup):

    @property
    def _gates(self) -> list[Gate]:
        return self.circuit.gates
    
    def encode(self, t: int) -> None:
        self._constraint_4(t)
        self._constraint_5(t)

    # (4) 
    def _constraint_4(self, t: int) -> None:
        n_log = self.circuit.n_qubits
        edges_set = self.topology.edge_set

        for q in range(n_log):
            for q1 in range(q + 1, n_log):

                e_lit = self.pool.e(q, q1, t)

                
                for p in range(self.topology.n_qubits):
                    for p1 in range(self.topology.n_qubits):
                        if p == p1:
                            continue

                        mp_q_p = self.pool.mp(q, p, t)
                        mp_q1_p1 = self.pool.mp(q1, p1, t)

                        connected = tuple(sorted((p, p1))) in edges_set

                        if connected:
                            and_implies(self.cnf, [mp_q_p, mp_q1_p1], e_lit)
                        else:
                            and_implies(self.cnf, [mp_q_p, mp_q1_p1], -e_lit)

    # (5)
    def _constraint_5(self, t: int) -> None:
        for gate in self.circuit.gates:
            if gate.is_cx:
                c_lit = self.pool.c(gate.gate_id, t)
                e_lit = self.pool.e(gate.control_qubit, gate.target_qubit, t)
                implies(self.cnf, c_lit, e_lit) 

# from encoding.base import ConstraintGroup
# from encoding.helpers import *
# from circuit.gate import *
# from circuit.parser import *


# class ConnectivityConstraints(ConstraintGroup):

#     @property
#     def _gates(self) -> list[Gate]:
#         return self.circuit.gates

#     def encode(self, t: int) -> None:
#         self._constraint_4(t)
#         self._constraint_5(t)

#     # cache pairs (q, q1) that actually appear together in some CX gate
#     # -> avoid instantiating e_lit / constraint (4) for irrelevant pairs
#     @property
#     def _cx_pairs(self) -> set[tuple[int, int]]:
#         if not hasattr(self, "_cx_pairs_cache"):
#             pairs = set()
#             for gate in self.circuit.gates:
#                 if gate.is_cx:
#                     q, q1 = gate.control_qubit, gate.target_qubit
#                     pairs.add((min(q, q1), max(q, q1)))
#             self._cx_pairs_cache = pairs
#         return self._cx_pairs_cache

#     # (4) — rewritten: O(n_log^2 * n_phys) instead of O(n_log^2 * n_phys^2)
#     def _constraint_4(self, t: int) -> None:
#         edges_set = self.topology.edge_set
#         n_phys = self.topology.n_qubits

#         # precompute neighbor list once per call (cheap, independent of t)
#         neighbors = [
#             [p1 for p1 in range(n_phys) if p1 != p and tuple(sorted((p, p1))) in edges_set]
#             for p in range(n_phys)
#         ]

#         for (q, q1) in self._cx_pairs:
#             e_lit = self.pool.e(q, q1, t)

#             for p in range(n_phys):
#                 mp_q_p = self.pool.mp(q, p, t)
#                 conn_p = neighbors[p]

#                 # e_lit ∧ mp_q_p  ⇒  OR_{p1 ∈ conn(p)} mp_{q1,p1}
#                 # CNF: ¬e_lit ∨ ¬mp_q_p ∨ mp_q1_p1_1 ∨ mp_q1_p1_2 ∨ ...
#                 clause = [-e_lit, -mp_q_p] + [self.pool.mp(q1, p1, t) for p1 in conn_p]
#                 self.cnf.append(clause)

#         # positive direction (connected ⇒ e) — must stay, gives soundness
#         for (q, q1) in self._cx_pairs:
#             e_lit = self.pool.e(q, q1, t)
#             for (p, p1) in edges_set:
#                 and_implies(self.cnf, [self.pool.mp(q, p, t), self.pool.mp(q1, p1, t)], e_lit)
#                 and_implies(self.cnf, [self.pool.mp(q, p1, t), self.pool.mp(q1, p, t)], e_lit)

#     # (5) unchanged
#     def _constraint_5(self, t: int) -> None:
#         for gate in self.circuit.gates:
#             if gate.is_cx:
#                 c_lit = self.pool.c(gate.gate_id, t)
#                 e_lit = self.pool.e(gate.control_qubit, gate.target_qubit, t)
#                 implies(self.cnf, c_lit, e_lit)