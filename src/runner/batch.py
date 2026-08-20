"""
Chạy QuilLS trên nhiều file .qasm (batch mode).

Mỗi file được chạy trong 1 process con riêng (multiprocessing) để có thể
áp timeout cứng — nếu 1 instance treo/quá lâu, ta terminate() process đó mà
không ảnh hưởng tới các file còn lại.

QUAN TRỌNG (xem lịch sử sửa lỗi): việc đọc kết quả từ multiprocessing.Queue
PHẢI được làm trước/song song với việc join() process, không phải sau —
nếu không sẽ deadlock khi payload (circuit + model + schedule) lớn hơn
buffer của pipe nội bộ trên Windows. Xem `_run_single` bên dưới.
"""

from __future__ import annotations

import logging
import multiprocessing
import time
from pathlib import Path
from typing import Optional

from circuit.parser import parse_qasm
from cli.topology_registry import build_topology
from instrumentation.solve_log import SolveLogger
from runner.types import BenchmarkEntry, summarize_repeats, write_csv
from solver.engine import QuilLSEngine

log = logging.getLogger(__name__)


def _worker(
    qasm_path:     str,
    topology_name: str,
    solver_tag:    str,
    queue:         multiprocessing.Queue,
    tool:          str = "lb",
    cxdepth:       bool = False,
    ub:            Optional[int] = None,
    ub_search:     str = "binary",
    solve_log_path: Optional[str] = None,
) -> None:
    """
    Chạy trong process con.
    Gửi về ("ok", SolverResult, Circuit) hoặc ("error", message, None).

    Nếu solve_log_path được truyền, ghi thống kê solve() ra đúng file CSV đó
    TRỰC TIẾP từ process con (không gửi qua queue) — tránh payload lớn qua pipe.
    """
    try:
        circuit  = parse_qasm(qasm_path)
        topology = build_topology(topology_name)

        solve_logger = SolveLogger() if solve_log_path is not None else None

        engine = QuilLSEngine(
            circuit=circuit,
            topology=topology,
            solver_tag=solver_tag,
            verbose=False,
            mode=tool,
            cxdepth=cxdepth,
            ub=ub,
            ub_search=ub_search,
            solve_logger=solve_logger,
            progress_queue=queue,  # cùng queue với kết quả cuối, phân biệt qua tag
        )
        result = engine.run()

        if solve_logger is not None:
            solve_logger.write_csv(Path(solve_log_path))

        queue.put(("ok", result, circuit))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", str(exc), None))


def _run_once(
    qasm_path:     Path,
    topology_name: str,
    solver_tag:    str,
    timeout_sec:   float,
    validate:      bool,
    tool:          str = "lb",
    cxdepth:       bool = False,
    ub:            Optional[int] = None,
    ub_search:     str = "binary",
    solve_log_dir: Optional[Path] = None,
    repeat_index:  Optional[int] = None,
    quiet:         bool = False,
) -> BenchmarkEntry:
    """Chạy 1 file ĐÚNG 1 LẦN trong process con, có timeout. Trả về BenchmarkEntry.

    `repeat_index` (0, 1, 2, ...) chỉ dùng để đặt tên file solve-log riêng cho
    từng lần lặp khi gọi từ `_run_single` với `repeats > 1` — tránh các lần
    lặp ghi đè lên nhau.

    `quiet=True` bỏ qua dòng log chi tiết cuối cùng — dùng khi `_run_single`
    gọi hàm này nhiều lần (nó tự in dòng "[rep i/N] ..." gọn hơn thay thế)."""
    try:
        circuit = parse_qasm(str(qasm_path))
        n_qubits, n_gates = circuit.n_qubits, len(circuit.gates)
    except Exception as exc:  # noqa: BLE001
        log.error("  ERROR    %-40s  parse failed: %s", qasm_path.name, exc)
        return BenchmarkEntry(
            benchmark=qasm_path.name, n_qubits=0, n_gates=0,
            topology=topology_name, solver=solver_tag, tool=tool, timeout_sec=timeout_sec,
            status="ERROR", optimal_depth=-1, elapsed_sec=0.0, iterations=0,
            cxdepth=cxdepth,
        )

    entry = BenchmarkEntry(
        benchmark=qasm_path.name, n_qubits=n_qubits, n_gates=n_gates,
        topology=topology_name, solver=solver_tag, tool=tool, timeout_sec=timeout_sec,
        status="TIMEOUT", optimal_depth=-1, elapsed_sec=timeout_sec, iterations=0,
        cxdepth=cxdepth,
    )

    solve_log_path = None
    if solve_log_dir is not None:
        suffix = f"_rep{repeat_index}" if repeat_index is not None else ""
        tool_tag = f"{tool}-cx" if cxdepth else tool
        solve_log_path = str(Path(solve_log_dir) / f"{qasm_path.stem}_{tool_tag}{suffix}.csv")

    queue: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(
        target=_worker,
        args=(
            str(qasm_path), topology_name, solver_tag, queue,
            tool, cxdepth, ub, ub_search, solve_log_path,
        ),
        daemon=True,
    )

    t0 = time.perf_counter()
    p.start()

    # QUAN TRỌNG: phải đọc queue TRƯỚC khi join(), không phải sau (xem docstring module).
    got_result    = False
    crashed       = False
    last_progress = None   # kết quả TẠM THỜI gần nhất (xem solver/engine.py::_report_progress)
    tag = payload = solved_circuit = None
    poll_step = 0.2
    while True:
        remaining = timeout_sec - (time.perf_counter() - t0)
        if remaining <= 0:
            break
        try:
            tag, payload, solved_circuit = queue.get(timeout=min(poll_step, remaining))
            if tag == "progress":
                last_progress = payload
                continue   # không phải kết quả cuối — tiếp tục chờ
            got_result = True
            break
        except Exception:
            if not p.is_alive():
                try:
                    while True:
                        tag, payload, solved_circuit = queue.get_nowait()
                        if tag == "progress":
                            last_progress = payload
                            continue
                        got_result = True
                        break
                except Exception:
                    if not got_result:
                        crashed = True
                break

    elapsed = time.perf_counter() - t0

    if crashed and not got_result:
        p.join()
        entry.elapsed_sec = elapsed
        entry.status = "ERROR"
        log.error("  ERROR    %-40s  process exited with no result", qasm_path.name)
        return entry

    if not got_result:
        if p.is_alive():
            p.terminate()
        p.join()
        entry.elapsed_sec = elapsed

        if last_progress is not None:
            # Cứu được kết quả tạm thời trước khi bị timeout — xem
            # solver/engine.py::_report_progress. status="TIMEOUT_PARTIAL"
            # để phân biệt rõ với TIMEOUT trắng tay (không có gì để dùng).
            entry.status = "TIMEOUT_PARTIAL"
            entry.partial_kind = last_progress.get("kind", "")
            if last_progress.get("kind") == "ub_best_sat":
                entry.partial_bound = last_progress.get("best_sat_t", -1)
                log.warning(
                    "  TIMEOUT_PARTIAL  %-40s  (%.1fs) — best_sat_t=%d (upper bound "
                    "hợp lệ, CHƯA CHẮC optimal)",
                    qasm_path.name, elapsed, entry.partial_bound,
                )
            elif last_progress.get("kind") == "lb_last_unsat":
                entry.partial_bound = last_progress.get("last_unsat_t", -1)
                log.warning(
                    "  TIMEOUT_PARTIAL  %-40s  (%.1fs) — đã chứng minh UNSAT tới "
                    "t=%d (optimal chắc chắn > %d, nhưng CHƯA có nghiệm SAT nào)",
                    qasm_path.name, elapsed, entry.partial_bound, entry.partial_bound,
                )
        else:
            log.warning("  TIMEOUT  %-40s  (%.1fs)", qasm_path.name, elapsed)

        return entry

    p.join(timeout=5)
    if p.is_alive():
        p.terminate()
        p.join()

    if tag == "error":
        entry.elapsed_sec = elapsed
        entry.status = "ERROR"
        log.error("  ERROR    %-40s  %s", qasm_path.name, payload)
        return entry

    result = payload
    entry.elapsed_sec   = result.elapsed_sec
    entry.iterations    = result.iterations
    entry.optimal_depth = result.optimal_depth
    entry.status        = "SAT" if result.sat else "UNSAT"
    entry.objective      = result.objective
    entry.depth          = result.depth
    entry.cx_depth       = result.cx_depth
    entry.cx_count       = result.cx_count
    entry.lower_bound    = result.lower_bound

    if validate and result.sat:
        from validation.validator import validate_solution_verbose
        topology = build_topology(topology_name)
        report   = validate_solution_verbose(solved_circuit, topology, result)
        all_ok   = all(passed for _, passed, _ in report)
        entry.valid = all_ok
        if not all_ok:
            failures = [name for name, passed, _ in report if not passed]
            log.warning("  INVALID  %-40s  failed: %s", qasm_path.name, ", ".join(failures))

    depth_str = str(entry.optimal_depth) if entry.optimal_depth >= 0 else "-"
    valid_str = f"  valid={entry.valid}" if validate and entry.status == "SAT" else ""
    if not quiet:
        log.info(
            "  %-7s  %-40s  depth=%-4s  time=%.2fs  iter=%d%s",
            entry.status, qasm_path.name, depth_str,
            entry.elapsed_sec, entry.iterations, valid_str,
        )

    return entry


def _run_single(
    qasm_path:     Path,
    topology_name: str,
    solver_tag:    str,
    timeout_sec:   float,
    validate:      bool,
    tool:          str = "lb",
    cxdepth:       bool = False,
    ub:            Optional[int] = None,
    ub_search:     str = "binary",
    solve_log_dir: Optional[Path] = None,
    repeats:       int = 1,
) -> BenchmarkEntry:
    """Chạy `_run_once()` đúng `repeats` lần, tổng hợp thời gian (mean/std/min/max).

    Lý do cần: SAT solving có thể có variance rất lớn giữa các lần chạy (đã
    quan sát thực tế: 1 lần solve bất thường chiếm >90% tổng thời gian của cả
    benchmark, xem phân tích outlier mod_mult_55) — 1 lần chạy đơn lẻ không đủ
    tin cậy để so sánh lb vs ub. `repeats > 1` giúp lấy trung bình, đồng thời
    lộ ra variance thật (elapsed_std) và giúp phát hiện outlier tương tự.
    """
    raw_entries: list[BenchmarkEntry] = []
    for rep in range(repeats):
        entry = _run_once(
            qasm_path=qasm_path, topology_name=topology_name, solver_tag=solver_tag,
            timeout_sec=timeout_sec, validate=validate, tool=tool, cxdepth=cxdepth, ub=ub,
            ub_search=ub_search, solve_log_dir=solve_log_dir,
            repeat_index=rep if repeats > 1 else None,
            quiet=repeats > 1,
        )
        raw_entries.append(entry)
        if repeats > 1:
            depth_str = str(entry.optimal_depth) if entry.optimal_depth >= 0 else "-"
            log.info(
                "    [rep %d/%d] %-7s  depth=%-4s  time=%.2fs",
                rep + 1, repeats, entry.status, depth_str, entry.elapsed_sec,
            )

    if repeats == 1:
        # Không cần tổng hợp gì thêm — trả nguyên kết quả lần chạy duy nhất,
        # chỉ điền thêm các trường thống kê để CSV có cột nhất quán.
        entry = raw_entries[0]
        entry.repeats = 1
        entry.elapsed_mean = entry.elapsed_sec
        entry.elapsed_min  = entry.elapsed_sec
        entry.elapsed_max  = entry.elapsed_sec
        entry.n_ok      = 1 if entry.status in ("SAT", "UNSAT") else 0
        entry.n_timeout = 1 if entry.status in ("TIMEOUT", "TIMEOUT_PARTIAL") else 0
        entry.n_error   = 1 if entry.status == "ERROR" else 0
        return entry

    ok_entries   = [e for e in raw_entries if e.status in ("SAT", "UNSAT")]
    elapsed_list = [e.elapsed_sec for e in ok_entries]
    mean, std, mn, mx = summarize_repeats(elapsed_list)

    sat_depths = {e.optimal_depth for e in ok_entries if e.status == "SAT"}
    depth_consistent = (len(sat_depths) <= 1) if sat_depths else None
    if depth_consistent is False:
        log.warning(
            "  KHÔNG NHẤT QUÁN  %-40s  các lần lặp SAT ra optimal_depth khác nhau: %s "
            "(đáng ngờ — solver không deterministic hoặc có bug)",
            qasm_path.name, sorted(sat_depths),
        )

    first = raw_entries[0]
    agg = BenchmarkEntry(
        benchmark=first.benchmark, n_qubits=first.n_qubits, n_gates=first.n_gates,
        topology=topology_name, solver=solver_tag, tool=tool, timeout_sec=timeout_sec,
        status=first.status,
        optimal_depth=first.optimal_depth,
        elapsed_sec=mean if ok_entries else raw_entries[-1].elapsed_sec,
        iterations=first.iterations,
        valid=first.valid,
        repeats=repeats,
        elapsed_mean=mean, elapsed_std=std, elapsed_min=mn, elapsed_max=mx,
        n_ok=len(ok_entries),
        n_timeout=sum(1 for e in raw_entries if e.status in ("TIMEOUT", "TIMEOUT_PARTIAL")),
        n_error=sum(1 for e in raw_entries if e.status == "ERROR"),
        depth_consistent=depth_consistent,
        cxdepth=cxdepth,
        objective=first.objective,
        depth=first.depth,
        cx_depth=first.cx_depth,
        cx_count=first.cx_count,
        lower_bound=first.lower_bound,
        partial_kind=first.partial_kind, partial_bound=first.partial_bound,
    )

    log.info(
        "  => %-40s  %d/%d ok  mean=%.2fs  std=%.2fs  min=%.2fs  max=%.2fs",
        qasm_path.name, agg.n_ok, repeats, mean, std, mn, mx,
    )

    return agg


def run_batch(
    qasm_files:    list[Path],
    topology_name: str,
    solver_tag:    str,
    timeout_sec:   float,
    validate:      bool,
    output_csv:    Optional[Path],
    tool:          str = "lb",
    cxdepth:       bool = False,
    ub:            Optional[int] = None,
    ub_search:     str = "binary",
    solve_log_dir: Optional[Path] = None,
    repeats:       int = 1,
) -> list[BenchmarkEntry]:
    """Chạy tuần tự từng file, in summary, export CSV nếu có."""
    log.info(
        "Batch | %d files | topology=%s | solver=%s | timeout=%.0fs | tool=%s%s%s%s | repeats=%d",
        len(qasm_files), topology_name, solver_tag, timeout_sec, tool,
        f" | ub={ub}" if tool == "ub" and ub is not None else "",
        f" | ub_search={ub_search}" if tool == "ub" else "",
        " | cxdepth" if cxdepth else "",
        repeats,
    )
    log.info("-" * 70)

    entries: list[BenchmarkEntry] = []

    for i, f in enumerate(qasm_files):
        print(f"===== {i}: {f} =====", flush=True)

        entry = _run_single(
            qasm_path=f,
            topology_name=topology_name,
            solver_tag=solver_tag,
            timeout_sec=timeout_sec,
            validate=validate,
            tool=tool,
            cxdepth=cxdepth,
            ub=ub,
            ub_search=ub_search,
            solve_log_dir=solve_log_dir,
            repeats=repeats,
        )
        entries.append(entry)

        print(f"===== DONE {i} =====", flush=True)

    # Summary
    n_sat     = sum(1 for e in entries if e.status == "SAT")
    n_unsat   = sum(1 for e in entries if e.status == "UNSAT")
    n_timeout = sum(1 for e in entries if e.status in ("TIMEOUT", "TIMEOUT_PARTIAL"))
    n_error   = sum(1 for e in entries if e.status == "ERROR")

    log.info("=" * 70)
    log.info(
        "Summary: total=%d | SAT=%d | UNSAT=%d | TIMEOUT=%d | ERROR=%d",
        len(entries), n_sat, n_unsat, n_timeout, n_error,
    )
    if validate:
        n_invalid = sum(1 for e in entries if e.valid is False)
        log.info("Validation failures: %d / %d SAT instances", n_invalid, n_sat)

    if output_csv is not None:
        write_csv(entries, output_csv)
        log.info("Results saved → %s", output_csv)

    return entries
