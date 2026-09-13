from encoding.base import ConstraintGroup
from encoding.helpers import implies

class AssumptionConstraints(ConstraintGroup):
    def encode(self, t: int) -> None:
        asm_t = self.pool.asm(t)
        for gate in self.circuit.gates:
            implies(self.cnf, asm_t, -self.pool.d(gate.gate_id, t))

    def assumption_lit(self, t: int) -> int:
        return self.pool.asm(t)