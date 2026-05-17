from pysat.solvers import Solver as _PySatSolver
 
from solver.base import SolverBase

class _PySatWrapper (SolverBase):
    _SOLVER_TAG: str

    def __init__(self) -> None:
        self._solver = _PySatSolver(name=self._SOLVER_TAG)

    def add_clause(self, clause: list[int]) ->  None:
        return self._solver.add_clause(clause)

    def solve(self, assumptions: list[int] | None = None) -> bool:
        return self._solver.solve(assumptions=assumptions or [])
    
    def get_model(self) -> list[int]:
        return self._solver.get_model() or []
    
    def close(self) -> None:
        self._solver.delete()

    @property
    def name(self) -> str:
        return self._SOLVER_TAG
    
    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
    

# Concrete solver classes
class CaDiCaL195(_PySatWrapper):
    _SOLVER_TAG = "cadical195"

class CaDiCaL153(_PySatWrapper):
    _SOLVER_TAG = "cadical153"
 
 
class Kissat404(_PySatWrapper):
    _SOLVER_TAG = "kissat404"
 
 
class Glucose42(_PySatWrapper):
    _SOLVER_TAG = "glucose42"
 
 
class Glucose4(_PySatWrapper):
    _SOLVER_TAG = "glucose4"
 
 
class MapleChronoBT(_PySatWrapper):
    _SOLVER_TAG = "maplechrono"