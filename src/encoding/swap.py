from encoding.base import ConstraintGroup
from encoding.helpers import at_most_n, iff, iff_or, implies, implies_all

class SwapConstraints(ConstraintGroup):

    def init_static(self) -> None:
        # Constraint 15
        for (p, p2) in self.topology.edge_set:
            for t_bound in (1, 2, 3):
                self.cnf.append([-self.pool.sw(p, p2, t_bound)])

    def encode(self, t: int) -> None:
        self._constraint_13(t)
        self._constraint_14(t)
        self._constraint_16(t)
        self._constraint_17(t)
        if t > 1:
            self._constraint_18(t)
            self._constraint_19(t)


    def _constraint_13(self, t: int) -> None:
        for p in range(self.topology.n_qubits):
            lits: list[int] = []
            for t2 in (t, t - 1, t - 2):
                if t2 < 1:
                    continue
                for p2 in self.topology.neighbors(p):
                    lits.append(self.pool.sw(p, p2, t2))

            if len(lits) >= 2:
                at_most_n(self.cnf, self.pool, 1, lits, tag=("c13", p, t))

    def _constraint_14(self, t: int) -> None:
        for p in range(self.topology.n_qubits):
            st_p = self.pool.st(p, t)
            for t2 in (t, t - 1, t - 2):
                if t2 < 1:
                    continue
                implies(self.cnf, st_p, -self.pool.u(p, t2))

    def _constraint_16(self, t: int) -> None:
        for (p, p2) in self.topology.edge_set:
            sw_lit = self.pool.sw(p, p2, t)
            oc_p   = self.pool.oc(p,  t)
            oc_p2  = self.pool.oc(p2, t)
            # sw → (oc_p ∨ oc_p2)
            self.cnf.append([-sw_lit, oc_p, oc_p2])

    def _constraint_17(self, t: int) -> None:
        for p in range(self.topology.n_qubits):
            st_p   = self.pool.st(p, t)
            sw_lits = [self.pool.sw(p, p2, t) for p2 in self.topology.neighbors(p)]
            iff_or(self.cnf, self.pool, st_p, sw_lits)

    def _constraint_18(self, t: int) -> None:
        for p in range(self.topology.n_qubits):
            st_p = self.pool.st(p, t)
            for q in range(self.circuit.n_qubits):
                mp_prev = self.pool.mp(q, p, t - 1)
                mp_curr = self.pool.mp(q, p, t)

                self.cnf.append([st_p, -mp_prev,  mp_curr])
                self.cnf.append([st_p,  mp_prev, -mp_curr])

    def _constraint_19(self, t: int) -> None:
        for (p, p2) in self.topology.edge_set:
            sw_lit = self.pool.sw(p, p2, t)
            for q in range(self.circuit.n_qubits):

                mp_prev_p   = self.pool.mp(q, p,  t - 1)
                mp_curr_p2  = self.pool.mp(q, p2, t)

                self.cnf.append([-sw_lit, -mp_prev_p,  mp_curr_p2])
                self.cnf.append([-sw_lit,  mp_prev_p, -mp_curr_p2])

                mp_prev_p2  = self.pool.mp(q, p2, t - 1)
                mp_curr_p   = self.pool.mp(q, p,  t)
                self.cnf.append([-sw_lit, -mp_prev_p2,  mp_curr_p])
                self.cnf.append([-sw_lit,  mp_prev_p2, -mp_curr_p])