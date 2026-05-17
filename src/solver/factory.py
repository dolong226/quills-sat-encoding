from solver.base import SolverBase
from solver.backends import (
    CaDiCaL153,
    CaDiCaL195,
    Glucose4,
    Glucose42,
    Kissat404,
    MapleChronoBT,
)

# Registry: tag -> (class, description)
_REGISTRY: dict[str, tuple[type[SolverBase], str]] = {
    "cadical195":  (CaDiCaL195,     "CaDiCaL 1.9.5"),
    "cadical153":  (CaDiCaL153,     "CaDiCaL 1.5.3"),
    "kissat404":   (Kissat404,      "Kissat 4.0.4"),
    "glucose42":   (Glucose42,      "Glucose 4.2"),
    "glucose4":    (Glucose4,       "Glucose 4.1"),
    "maplechrono": (MapleChronoBT,  "MapleSAT"),
}
_DEFAULT = "cadical195"

class SolverFactory:

    @staticmethod
    def create(tag: str = _DEFAULT) -> SolverBase:
        key = tag.lower()
        if key not in _REGISTRY:
            available = ", ".join(_REGISTRY)
            raise ValueError(
                f"Unknown solver '{tag}'."
            )
        cls, _ = _REGISTRY[key]
        return cls()

    @staticmethod
    def list_available() -> None:
        print(f"{'Tag':<16} Description")
        print("-" * 60)
        for tag, (_, desc) in _REGISTRY.items():
            marker = " (default)" if tag == _DEFAULT else ""
            print(f"  {tag:<14} {desc}{marker}")
    @staticmethod
    def default_tag() -> str:
        return _DEFAULT