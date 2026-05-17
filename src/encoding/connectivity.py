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