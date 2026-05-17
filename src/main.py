"""
python main.py circuit.qasm --topology ibmq_guadalupe

python main.py circuit.qasm --topology ibmq_guadalupe --solver kissat404

python main.py circuit.qasm --topology ibmq_guadalupe --verbose

# List available solvers
python main.py --list-solvers
"""

from __future__ import annotations

import argparse
import logging
import sys

from circuit.parser import parse_qasm
from quills_platform.presets import ibmq_guadalupe
from quills_platform.topology import Topology

from solver.factory import SolverFactory
from solver.engine import QuilLSEngine


# Logging setup

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )

# Topology helpers

_TOPOLOGY_PRESETS: dict[str, str] = {
    "ibmq_guadalupe": "IBM"
}


def _build_topology(name: str, n_qubits: int) -> Topology:
    name = name.lower()
    if name in ("ibmq_guadalupe"):
        return ibmq_guadalupe()
    raise ValueError(f"Unknown topology '{name}'. ")


# Result printer

def _print_result(result) -> None:
    sep = "─" * 52
    print(sep)
    print(result)
    print(sep)

    if not result.sat:
        return

    if result.initial_mapping:
        print("\nInitial mapping (logical -> physical):")
        for q in sorted(result.initial_mapping):
            print(f"  q{q} -:> p{result.initial_mapping[q]}")

    if result.schedule:
        print("\nGate schedule (timestep -> gate ids):")
        for t in sorted(result.schedule):
            gates = result.schedule[t]
            print(f"  t={t:3d}  gates: {gates}")

    print()


# CLI

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quills",
        description="QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT",
    )

    p.add_argument(
        "qasm_file",
        nargs="?",
        help="Path to the input .qasm circuit file",
    )
    p.add_argument(
        "--topology", "-t",
        default="ibmq_guadalupe",
        metavar="NAME",
        help=(
            "Hardware topology preset: "
            + ", ".join(_TOPOLOGY_PRESETS)
            + "  (default: ibmq_guadalupe)"
        ),
    )
    p.add_argument(
        "--solver", "-s",
        default=SolverFactory.default_tag(),
        metavar="TAG",
        help=f"SAT solver to use (default: {SolverFactory.default_tag()})",
    )
    p.add_argument(
        "--max-depth", "-d",
        type=int,
        default=200,
        metavar="N",
        help="Hard upper bound on makespan search (default: 200)",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    p.add_argument(
        "--list-solvers",
        action="store_true",
        help="Print all available SAT solvers and exit",
    )
    p.add_argument(
        "--list-topologies",
        action="store_true",
        help="Print all topology presets and exit",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    # Info commands
    if args.list_solvers:
        SolverFactory.list_available()
        return 0

    if args.list_topologies:
        print(f"{'Name':<12} Description")
        print("-" * 50)
        for name, desc in _TOPOLOGY_PRESETS.items():
            print(f"  {name:<10} {desc}")
        return 0

    # Validate inputs 
    if not args.qasm_file:
        parser.print_help()
        return 1

    # Parse circuit
    log.info("Parsing circuit: %s", args.qasm_file)
    try:
        circuit = parse_qasm(args.qasm_file)
    except FileNotFoundError:
        log.error("File not found: %s", args.qasm_file)
        return 1

    log.info("  %s  (%d gates)", circuit, len(circuit.gates))

    # Build topology
    log.info("Building topology: %s", args.topology)
    try:
        topology = _build_topology(args.topology, circuit.n_qubits)
    except ValueError as e:
        log.error("%s", e)
        return 1

    if topology.n_qubits < circuit.n_qubits:
        log.error(
            "Topology has %d qubits but circuit needs %d",
            topology.n_qubits, circuit.n_qubits,
        )
        return 1

    # Validate solver
    try:
        SolverFactory.create(args.solver).close()   # quick smoke-test
    except ValueError as e:
        log.error("%s", e)
        return 1

    # Run engine
    engine = QuilLSEngine(
        circuit=circuit,
        topology=topology,
        solver_tag=args.solver,
        max_depth=args.max_depth,
        verbose=args.verbose,
    )

    log.info("Running QuilLS with solver=%s ...", args.solver)
    result = engine.run()

    _print_result(result)
    return 0 if result.sat else 2


if __name__ == "__main__":
    sys.exit(main())