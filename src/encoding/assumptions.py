from encoding.base import ConstraintGroup
from encoding.helpers import implies

class AssumptionConstraints(ConstraintGroup):
    def encode(self, t: int) -> None:
        asm_t = self.pool.asm(t)
        for gate in self.circuit.gates:
            # asm^t ⇒ ¬d^t_g  ==  asm^t ⇒ x(g, t)
            implies(self.cnf, asm_t, self.pool.x(gate.gate_id, t))

    def assumption_lit(self, t: int) -> int:
        return self.pool.asm(t)
