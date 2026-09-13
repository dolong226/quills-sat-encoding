from encoding.base import ConstraintGroup
from encoding.helpers import at_most_one, exactly_one, iff_or


class MappingConstraints(ConstraintGroup):

    @property
    def _qubits(self) -> range:
        return range(self.circuit.n_qubits)

    @property
    def _physicals(self) -> range:
        return range(self.topology.n_qubits)

    def encode(self, t: int) -> None:
        self._constraint_1(t)
        self._constraint_2(t)
        self._constraint_3(t)

    # (1) ExactlyOne( mp^t_{q,p0}, …, mp^t_{q,pn} )  for every logical q
    def _constraint_1(self, t: int) -> None:
        for q in self._qubits:
            lits = [self.pool.mp(q, p, t) for p in self._physicals]
            exactly_one(self.cnf, lits)

    # (2) AtMostOne( mp^t_{q0,p}, …, mp^t_{qm,p} )  for every physical p
    def _constraint_2(self, t: int) -> None:
        for p in self._physicals:
            lits = [self.pool.mp(q, p, t) for q in self._qubits]
            at_most_one(self.cnf, lits)

    # (3) oc^t_p  ⟺  ( mp^t_{q0,p} ∨ … ∨ mp^t_{qm,p} )
    def _constraint_3(self, t: int) -> None:
        for p in self._physicals:
            oc_lit = self.pool.oc(p, t)
            mp_lits = [self.pool.mp(q, p, t) for q in self._qubits]
            iff_or(self.cnf, self.pool, oc_lit, mp_lits)