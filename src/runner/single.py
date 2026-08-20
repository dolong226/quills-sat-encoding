"""Chạy QuilLS trên một file .qasm duy nhất, in kết quả chi tiết ra console."""

from __future__ import annotations

import logging
import statistics
from pathlib import Path
from typing import Optional

from circuit.parser import parse_qasm
from cli.topology_registry import build_topology
from instrumentation.solve_log import SolveLogger
from solver.engine import QuilLSEngine
from validation.validator import validate_solution_verbose, print_report

log = logging.getLogger(__name__)


def run_file(
    qasm_path:     Path,
    topology_name: str,
    solver_tag:    str,
    validate:      bool,
    verbose:       bool,
    tool:          str = "lb",
    cxdepth:       bool = False,
    ub:            Optional[int] = None,
    ub_search:     str = "binary",
    solve_log_dir: Optional[Path] = None,
    repeats:       int = 1,
) -> int:
    """Chạy một file duy nhất, in kết quả chi tiết. Trả về exit code.

    Nếu `repeats > 1`: chạy engine N lần, in 1 dòng gọn cho mỗi lần lặp, rồi
    in bảng thống kê (mean/std/min/max) ở cuối. Chi tiết đầy đủ (mapping,
    schedule, validation) chỉ in cho LẦN LẶP CUỐI, vì kết quả SAT (mapping,
    schedule) giống hệt nhau giữa các lần lặp — chỉ thời gian chạy khác nhau.
    """
    log.info("Parsing: %s", qasm_path)
    try:
        circuit = parse_qasm(str(qasm_path))
    except FileNotFoundError:
        log.error("File not found: %s", qasm_path)
        return 1

    log.info("  %s  (%d gates)", circuit, len(circuit.gates))

    try:
        topology = build_topology(topology_name)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    if topology.n_qubits < circuit.n_qubits:
        log.error(
            "Topology has %d qubits but circuit needs %d",
            topology.n_qubits, circuit.n_qubits,
        )
        return 1

    log.info(
        "Running QuilLS | solver=%s | tool=%s%s%s%s%s", solver_tag, tool,
        f" | ub={ub}" if tool == "ub" and ub is not None else "",
        f" | ub_search={ub_search}" if tool == "ub" else "",
        " | cxdepth" if cxdepth else "",
        f" | repeats={repeats}" if repeats > 1 else "",
    )

    results     = []
    depths_seen = set()

    for rep in range(repeats):
        solve_logger = SolveLogger() if solve_log_dir is not None else None

        engine = QuilLSEngine(
            circuit=circuit,
            topology=topology,
            solver_tag=solver_tag,
            verbose=verbose and repeats == 1,  # tránh log quá rối khi lặp nhiều lần
            mode=tool,
            cxdepth=cxdepth,
            ub=ub,
            ub_search=ub_search,
            solve_logger=solve_logger,
        )
        result = engine.run()
        results.append(result)
        if result.sat:
            depths_seen.add(result.optimal_depth)

        if solve_logger is not None:
            suffix = f"_rep{rep}" if repeats > 1 else ""
            tool_tag = f"{tool}-cx" if cxdepth else tool
            out_path = solve_log_dir / f"{qasm_path.stem}_{tool_tag}{suffix}.csv"
            solve_logger.write_csv(out_path)
            log.info("Solve-log saved → %s", out_path)

        if repeats > 1:
            log.info(
                "  [rep %d/%d] %-7s  depth=%-4s  time=%.2fs  iter=%d",
                rep + 1, repeats,
                "SAT" if result.sat else "UNSAT",
                str(result.optimal_depth) if result.sat else "-",
                result.elapsed_sec, result.iterations,
            )

    if repeats > 1:
        elapsed_list = [r.elapsed_sec for r in results]
        mean = statistics.mean(elapsed_list)
        std  = statistics.stdev(elapsed_list) if len(elapsed_list) > 1 else 0.0
        print("─" * 52)
        print(f"Aggregate over {repeats} runs:")
        print(f"  mean = {mean:.3f}s   std = {std:.3f}s   min = {min(elapsed_list):.3f}s   max = {max(elapsed_list):.3f}s")
        if len(depths_seen) > 1:
            print(f"  ⚠ CẢNH BÁO: optimal_depth KHÔNG nhất quán giữa các lần lặp: {sorted(depths_seen)}")
        print("─" * 52)
        print(f"(Chi tiết dưới đây là của lần lặp CUỐI, rep {repeats}/{repeats})")

    result = results[-1]

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
