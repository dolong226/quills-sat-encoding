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

    def stats(self) -> dict:
        """Thống kê solver-level (conflicts/decisions/propagations/restarts)
        của lần solve() gần nhất. Mặc định rỗng nếu backend không hỗ trợ —
        dùng cho instrumentation, không bắt buộc phải override."""
        return {}

    def nof_vars(self) -> int:
        """Số biến hiện có trong solver. Mặc định 0 nếu backend không hỗ trợ."""
        return 0

    def nof_clauses(self) -> int:
        """Số clause hiện có trong solver. Mặc định 0 nếu backend không hỗ trợ."""
        return 0

    @property
    @abstractmethod
    def name(self) -> str:
        """"""
        