"""
QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT

Usage

---------
# Chạy một file
python main.py circuit.qasm --topology ibmq_guadalupe

# Chạy một folder (tuần tự, có timeout mỗi file)
python main.py benchmarks/collection/ --timeout 60

# Chạy folder và validate lời giải SAT
python main.py benchmarks/collection/ --timeout 60 --validate

# Lưu kết quả batch ra CSV
python main.py benchmarks/ --timeout 120 --output results.csv

# Xem danh sách solver / topology
python main.py --list-solvers
python main.py --list-topologies
"""

from __future__ import annotations

import argparse
import csv
import logging
import multiprocessing
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from circuit.parser import Circuit, parse_qasm
from quills_platform.presets import ibmq_guadalupe
from quills_platform.topology import Topology
from solver.engine import QuilLSEngine, SolverResult
from solver.factory import SolverFactory
from validation.validator import validate_solution_verbose, print_report

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Topology
# ─────────────────────────────────────────────────────────────────────────────

print("===== MAIN.PY =====")


_TOPOLOGY_PRESETS: dict[str, str] = {
    "ibmq_guadalupe": "IBM Guadalupe — 16 qubits",
}


def _build_topology(name: str) -> Topology:
    if name.lower() == "ibmq_guadalupe":
        return ibmq_guadalupe()
    raise ValueError(f"Unknown topology '{name}'. Available: {', '.join(_TOPOLOGY_PRESETS)}")


# ─────────────────────────────────────────────────────────────────────────────
# Batch — dataclass + worker + run_single
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkEntry:
    """Kết quả của một lần chạy benchmark."""
    benchmark:     str
    n_qubits:      int
    n_gates:       int
    topology:      str
    solver:        str
    timeout_sec:   float
    status:        str            # SAT | UNSAT | TIMEOUT | ERROR
    optimal_depth: int            # -1 nếu không SAT
    elapsed_sec:   float
    iterations:    int
    valid:         Optional[bool] = None  # chỉ điền khi --validate


def _worker(
    qasm_path:     str,
    topology_name: str,
    solver_tag:    str,

    queue:         multiprocessing.Queue,
) -> None:
    """
    Chạy trong process con.
    Gửi về ("ok", SolverResult, Circuit) hoặc ("error", message, None).
    """
    try:
        circuit  = parse_qasm(qasm_path)
        topology = _build_topology(topology_name)
        engine   = QuilLSEngine(
            circuit=circuit,
            topology=topology,
            solver_tag=solver_tag,
            verbose=False,
        )
        result = engine.run()
        queue.put(("ok", result, circuit))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", str(exc), None))


def _run_single(
    qasm_path:     Path,
    topology_name: str,
    solver_tag:    str,
    timeout_sec:   float,
    validate:      bool,
) -> BenchmarkEntry:
    """
    Chạy một file .qasm trong process con riêng, áp timeout cứng.

    Luồng:
      1. Parse circuit (để lấy metadata trước)
      2. Tạo Queue + Process(target=_worker)
      3. p.start() → p.join(timeout) → p.terminate() nếu vẫn còn sống
      4. Đọc kết quả từ Queue
      5. Nếu --validate và SAT → chạy validator
    """
    # Parse trước để lấy n_qubits / n_gates cho entry
    try:
        circuit  = parse_qasm(str(qasm_path))
        n_qubits = circuit.n_qubits
        n_gates  = len(circuit.gates)
    except Exception as exc:
        log.error("  ERROR    %-40s  parse failed: %s", qasm_path.name, exc)
        return BenchmarkEntry(
            benchmark=qasm_path.name, n_qubits=0, n_gates=0,
            topology=topology_name, solver=solver_tag, timeout_sec=timeout_sec,
            status="ERROR", optimal_depth=-1, elapsed_sec=0.0, iterations=0,
        )

    # Entry mặc định: TIMEOUT (sẽ ghi đè nếu kịp)
    entry = BenchmarkEntry(
        benchmark=qasm_path.name, n_qubits=n_qubits, n_gates=n_gates,
        topology=topology_name, solver=solver_tag, timeout_sec=timeout_sec,
        status="TIMEOUT", optimal_depth=-1, elapsed_sec=timeout_sec, iterations=0,
    )

    queue: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(
        target=_worker,
        args=(str(qasm_path), topology_name, solver_tag, queue),
        daemon=True,
    )

    t0 = time.perf_counter()
    p.start()
    p.join(timeout=timeout_sec)
    elapsed = time.perf_counter() - t0

    if p.is_alive():
        p.terminate()
        p.join()
        entry.elapsed_sec = elapsed
        log.warning("  TIMEOUT  %-40s  (%.1fs)", qasm_path.name, elapsed)
        return entry

    try:
        tag, payload, solved_circuit = queue.get_nowait()
    except Exception:
        entry.elapsed_sec = elapsed
        entry.status = "ERROR"
        log.error("  ERROR    %-40s  process exited with no result", qasm_path.name)
        return entry

    if tag == "error":
        entry.elapsed_sec = elapsed
        entry.status = "ERROR"
        log.error("  ERROR    %-40s  %s", qasm_path.name, payload)
        return entry

    result: SolverResult = payload
    entry.elapsed_sec   = result.elapsed_sec
    entry.iterations    = result.iterations
    entry.optimal_depth = result.optimal_depth
    entry.status        = "SAT" if result.sat else "UNSAT"

    # Validation (chỉ khi SAT và được yêu cầu)
    if validate and result.sat:
        topology = _build_topology(topology_name)
        report   = validate_solution_verbose(circuit, topology, result)
        all_ok   = all(passed for _, passed, _ in report)
        entry.valid = all_ok
        if not all_ok:
            failures = [name for name, passed, _ in report if not passed]
            log.warning("  INVALID  %-40s  failed: %s", qasm_path.name, ", ".join(failures))

    depth_str = str(entry.optimal_depth) if entry.optimal_depth >= 0 else "-"
    valid_str = f"  valid={entry.valid}" if validate and entry.status == "SAT" else ""
    log.info(
        "  %-7s  %-40s  depth=%-4s  time=%.2fs  iter=%d%s",
        entry.status, qasm_path.name, depth_str,
        entry.elapsed_sec, entry.iterations, valid_str,
    )

    return entry


def _run_batch(
    qasm_files:    list[Path],
    topology_name: str,
    solver_tag:    str,
    timeout_sec:   float,
    validate:      bool,
    output_csv:    Optional[Path],
) -> list[BenchmarkEntry]:
    """Chạy tuần tự từng file, in summary, export CSV nếu có."""
    log.info(
        "Batch | %d files | topology=%s | solver=%s | timeout=%.0fs",
        len(qasm_files), topology_name, solver_tag, timeout_sec, 
    )
    log.info("-" * 70)

    # entries = [
    #     _run_single(f, topology_name, solver_tag, timeout_sec, validate)
    #     for f in qasm_files
    # ]

    # for debugging
    entries = []

    for i, f in enumerate(qasm_files):
        print(f"===== {i}: {f} =====", flush=True)

        entry = _run_single(
            qasm_path=f,
            topology_name=topology_name,
            solver_tag=solver_tag,
            timeout_sec=timeout_sec,
            validate=validate,
        )

        print(f"===== DONE {i} =====", flush=True)

    entries.append(entry)

    # Summary
    total     = len(entries)
    n_sat     = sum(1 for e in entries if e.status == "SAT")
    n_unsat   = sum(1 for e in entries if e.status == "UNSAT")
    n_timeout = sum(1 for e in entries if e.status == "TIMEOUT")
    n_error   = sum(1 for e in entries if e.status == "ERROR")
    log.info("=" * 70)
    log.info(
        "Summary: total=%d | SAT=%d | UNSAT=%d | TIMEOUT=%d | ERROR=%d",
        total, n_sat, n_unsat, n_timeout, n_error,
    )
    if validate:
        n_invalid = sum(1 for e in entries if e.valid is False)
        log.info("Validation failures: %d / %d SAT instances", n_invalid, n_sat)

    if output_csv:
        _write_csv(entries, output_csv)
        log.info("Results saved → %s", output_csv)

    return entries


def _write_csv(entries: list[BenchmarkEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(entries[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow(asdict(e))


# ─────────────────────────────────────────────────────────────────────────────
# Single — kết quả cho một file
# ─────────────────────────────────────────────────────────────────────────────

def _run_file(
    qasm_path:     Path,
    topology_name: str,
    solver_tag:    str,
    validate:      bool,
    verbose:       bool,
) -> int:
    """Chạy một file duy nhất, in kết quả chi tiết. Trả về exit code."""
    log.info("Parsing: %s", qasm_path)
    try:
        circuit = parse_qasm(str(qasm_path))
    except FileNotFoundError:
        log.error("File not found: %s", qasm_path)
        return 1

    log.info("  %s  (%d gates)", circuit, len(circuit.gates))

    try:
        topology = _build_topology(topology_name)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    if topology.n_qubits < circuit.n_qubits:
        log.error(
            "Topology has %d qubits but circuit needs %d",
            topology.n_qubits, circuit.n_qubits,
        )
        return 1

    log.info("Running QuilLS | solver=%s", solver_tag)
    engine = QuilLSEngine(
        circuit=circuit,
        topology=topology,
        solver_tag=solver_tag,
        verbose=verbose,
    )
    result = engine.run()

    # Print result
    sep = "─" * 52
    print(sep)
    print(result)
    print(sep)

    if result.sat:
        if result.initial_mapping:
            print("\nInitial mapping (logical -> physical):")
            for q in sorted(result.initial_mapping):
                print(f"  q{q} -> p{result.initial_mapping[q]}")
        if result.schedule:
            print("\nGate schedule (timestep -> gate ids):")
            for t in sorted(result.schedule):
                print(f"  t={t:3d}  gates: {result.schedule[t]}")
        print()

        # Validation
        if validate:
            report = validate_solution_verbose(circuit, topology, result)
            print_report(report, circuit, result)
            if not all(passed for _, passed, _ in report):
                return 3

    return 0 if result.sat else 2


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quills",
        description="QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # một file
  python main.py circuit.qasm
ib
  # một folder (batch, timeout 60s mỗi file)
  python main.py benchmarks/collection/ --timeout 60

  # batch + validate + lưu CSV
  python main.py benchmarks/ --timeout 120 --validate --output results.csv
""",
    )

    p.add_argument(
        "input",
        nargs="?",
        metavar="FILE_OR_DIR",
        help="File .qasm hoặc folder chứa các file .qasm",
    )
    p.add_argument(
        "--topology", "-t",
        default="ibmq_guadalupe",
        metavar="NAME",
        help="Topology phần cứng (mặc định: ibmq_guadalupe)",
    )
    p.add_argument(
        "--solver", "-s",
        default=SolverFactory.default_tag(),
        metavar="TAG",
        help=f"SAT solver (mặc định: {SolverFactory.default_tag()})",
    )
    p.add_argument(
        "--max-depth", "-d",
        type=int,
        default=10000,
        metavar="N",
        help="Giới hạn trên makespan (mặc định: 10000)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=7200.0,
        metavar="SEC",
        help="Timeout mỗi instance khi chạy batch (mặc định:7200s)",
    )
    p.add_argument(
        "--validate",
        action="store_true",
        help="Kiểm tra tính hợp lệ của lời giải SAT",
    )
    p.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Lưu kết quả batch ra file CSV (chỉ dùng khi input là folder)",
    )
    p.add_argument(
        "--recursive", "-r",
        action="store_true",
        default=True,
        help="Tìm đệ quy .qasm trong folder (mặc định: bật)",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Bật DEBUG logging",
    )
    p.add_argument(
        "--list-solvers",
        action="store_true",
        help="In danh sách solver và thoát",
    )
    p.add_argument(
        "--list-topologies",
        action="store_true",
        help="In danh sách topology và thoát",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args   = parser.parse_args(argv)

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    # ── Info commands ─────────────────────────────────────────────────────────
    if args.list_solvers:
        SolverFactory.list_available()
        return 0

    if args.list_topologies:
        print(f"{'Name':<20} Description")
        print("-" * 50)
        for name, desc in _TOPOLOGY_PRESETS.items():
            print(f"  {name:<18} {desc}")
        return 0

    if not args.input:
        parser.print_help()
        return 1

    input_path = Path(args.input)

    # ── Folder → batch mode ───────────────────────────────────────────────────
    if input_path.is_dir():
        pattern    = "**/*.qasm" if args.recursive else "*.qasm"
        qasm_files = sorted(input_path.glob(pattern))

        if not qasm_files:
            log.error("Không tìm thấy file .qasm nào trong %s", input_path)
            return 1

        _run_batch(
            qasm_files=qasm_files,
            topology_name=args.topology,
            solver_tag=args.solver,
            timeout_sec=args.timeout,
            validate=args.validate,
            output_csv=args.output,
        )
        return 0

    # ── File đơn → single mode ────────────────────────────────────────────────
    if not input_path.exists():
        log.error("Không tìm thấy file: %s", input_path)
        return 1

    return _run_file(
        qasm_path=input_path,
        topology_name=args.topology,
        solver_tag=args.solver,
        validate=args.validate,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    multiprocessing.freeze_support() 
    sys.exit(main())