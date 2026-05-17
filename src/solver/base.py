from abc import ABC, abstractmethod
from typing import Optional

class SolverBase(ABC):
    @abstractmethod 
    def add_clause(self, clause: list[int]) -> None:
        """"""

    @abstractmethod
    def solve(self, assumption: list[int] | None = None) -> bool:
        """"""        

    @abstractmethod
    def get_model(self) -> list[int]:
        """return the setifsuing assg"""

    @abstractmethod
    def close(self) -> None:
        """Release all resources"""

    # convenience

    def add_clauses(self, clauses: list[list[int]]) -> None:
        for clause in clauses:
            self.add_clause(clause)

    @property
    @abstractmethod
    def name(self) -> str:
        """"""
        