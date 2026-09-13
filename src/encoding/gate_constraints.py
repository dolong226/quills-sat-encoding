from encoding.base import ConstraintGroup
from encoding.helpers import *
from circuit.gate import GateType
from circuit.dag import DAG

class GateConstraints(ConstraintGroup):

    def __init__(self, cnf, pool, circuit, topology, dag: DAG) -> None:
        super().__init__(cnf, pool, circuit, topology)
        self._dag = dag

    # Constraint 7
    def init_static(self) -> None:
        for g in self.circuit.gates:
            self.cnf.append([-self.pool.a(g.gate_id, 1)])

    def encode(self, t: int) -> None:
        self._constraint_6(t)
        self._constraint_8(t)
        if t > 1: 
            self._constraint_9(t)
        self._constraint_10(t)
        self._constraint_11_12(t)

    def _constraint_6(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            exactly_one(self.cnf, [self.pool.c(g, t),
                                   self.pool.a(g, t),
                                   self.pool.d(g, t)])
            
    def _constraint_8(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            c_g = self.pool.c(g, t)
            a_g = self.pool.a(g, t)
            d_g = self.pool.d(g, t)

            for gate2 in self._dag.successors(g):
                d_g2 = self.pool.d(gate2, t)
                
                implies(self.cnf, c_g, d_g2)
                implies(self.cnf, d_g, d_g2)

            for gate2 in self._dag.predecessors(g):
                a_g2 = self.pool.a(gate2, t)
                
                implies(self.cnf, c_g, a_g2)
                implies(self.cnf, a_g, a_g2)
            
    def _constraint_9(self, t: int) -> None:
        for gate in self.circuit.gates:
            g    = gate.gate_id
            c_t1 = self.pool.c(g, t - 1)
            a_t1 = self.pool.a(g, t - 1)
            a_t  = self.pool.a(g, t)
            d_t1 = self.pool.d(g, t - 1)
            c_t  = self.pool.c(g, t)
            d_t  = self.pool.d(g, t)
 
            implies(self.cnf, c_t1, a_t)
            implies(self.cnf, a_t1, a_t)
 
            self.cnf.append([-a_t, c_t1, a_t1])
 
            self.cnf.append([-d_t1, c_t, d_t])
 
            implies(self.cnf, c_t, d_t1)
            implies(self.cnf, d_t, d_t1)

    def _constraint_10(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            c_g = self.pool.c(g, t)

            for g2 in self._dag.full_successors(g):
                c_g_2 = self.pool.c(g2, t)
                implies(self.cnf, c_g, -c_g_2)

            for g2 in self._dag.full_predecessors(g):
                c_g_2 = self.pool.c(g2, t)
                implies(self.cnf, c_g, -c_g_2)

    def _constraint_11_12(self, t: int) -> None:
        n_phys = self.topology.n_qubits
        for gate in self.circuit.gates:
            g   = gate.gate_id
            c_g = self.pool.c(g, t)
 
            for p in range(n_phys):
                u_p = self.pool.u(p, t)
 
                for q in gate.qubits:
                    mp_qp = self.pool.mp(q, p, t)
                    # c_g ∧ mp_{q,p} -> u_p
                    and_implies(self.cnf, [c_g, mp_qp], u_p)

