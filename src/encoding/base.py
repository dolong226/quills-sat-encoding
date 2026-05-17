from abc import ABC, abstractmethod

from pysat.formula import CNF

from circuit.parser import Circuit
from quills_platform.topology import Topology
from encoding.variables import VarPool

class ConstraintGroup(ABC):
    def __init__(
            self,
            cnf: CNF,
            pool: VarPool,
            circuit: Circuit,
            topology: Topology,
    ) -> None:
        self.cnf = cnf
        self.pool = pool
        self.circuit = circuit
        self.topology = topology


    @abstractmethod
    def encode(self, t: int) -> None:
        # Thêm mọi clauses ở bước t vào cnf.
        # Gọi Inc SAT loop
        pass

    def init_static(self) -> None:
        pass

    