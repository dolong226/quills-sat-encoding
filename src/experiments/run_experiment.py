"""
Chạy full thí nghiệm so sánh LB vs UB trên một tập benchmark, với UB LẤY
RIÊNG CHO TỪNG FILE (ví dụ từ SABRE) thay vì 1 giá trị --ub chung cho cả batch
như main.py hiện hỗ trợ, và lặp N lần mỗi benchmark để lấy trung bình
(mean/std) thay vì tin vào 1 lần chạy đơn lẻ.

CÁCH DÙNG
---------
# Chỉ có heuristic UB (không có bảng UB riêng)
python experiments/run_experiment.py --benchmarks-dir benchmarks/ --repeats 5

# Có bảng UB riêng cho từng file (ví dụ từ SABRE)
python experiments/run_experiment.py --benchmarks-dir benchmarks/ \\
    --ub-map sabre_ub.csv --repeats 10 --output-dir results/

# Chỉ chạy 1 chiều (ví dụ chỉ ub, để re-run 1 phần)
python experiments/run_experiment.py --benchmarks-dir benchmarks/ --tools ub

Xem `experiments/ub_map.py` để biết định dạng file --ub-map.

ĐẦU RA (trong --output-dir, mặc định ./experiment_results/)
  summary.csv           1 dòng / (benchmark, tool) — mean/std/min/max, ub_source, ...
  comparison.csv        1 dòng / benchmark có CẢ lb và ub — ratio, winner, ...
  solve_logs/            CSV instrumentation thô (1 file / benchmark / tool / repeat)
  plots/                 các biểu đồ (xem experiments/analyze.py)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Cho phép chạy trực tiếp "python experiments/run_experiment.py" từ trong src/
# mà không cần cài package hay set PYTHONPATH thủ công.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli.topology_registry import build_topology  # noqa: E402
from circuit.parser import parse_qasm  # noqa: E402
from experiments.ub_map import load_ub_map  # noqa: E402
from runner.batch import _run_single  # noqa: E402
from runner.types import BenchmarkEntry, write_csv  # noqa: E402
from solver.factory import SolverFactory  # noqa: E402

log = logging.getLogger(__name__)


@dataclass
class ExperimentRow:
    """1 dòng trong summary.csv — BenchmarkEntry + thông tin riêng của thí nghiệm."""
    benchmark:        str
    tool:             str
    n_qubits:         int
    n_gates:          int
    status:           str
    optimal_depth:    int
    repeats:          int
    elapsed_mean:     float
    elapsed_std:      float
    elapsed_min:      float
    elapsed_max:      float
    n_ok:             int
    n_timeout:        int
    n_error:          int
    depth_consistent: Optional[bool]
    ub_value_used:    Optional[int]   # chỉ có ý nghĩa khi tool="ub"
    ub_source:        str             # "map" | "heuristic" | "n/a" (n/a nếu tool="lb")
    valid:            Optional[bool]
    cxdepth:          bool = False    # True nếu tối ưu CX-depth thay vì circuit depth thường
    objective:        str = "depth"   # "depth" | "cxdepth" — optimal_depth là giá trị gì
    depth:            int = -1        # depth thường post-hoc (luôn điền, bất kể objective)
    cx_depth:         int = -1        # CX-depth post-hoc (luôn điền, bất kể objective)
    cx_count:         int = -1        # CX-count post-hoc = CX gốc + 3*swaps (luôn điền)
    lower_bound:      int = -1        # cận dưới lý thuyết (critical path) dùng làm điểm xuất phát search


def _entry_to_row(entry: BenchmarkEntry, ub_value_used: Optional[int], ub_source: str) -> ExperimentRow:
    return ExperimentRow(
        benchmark=entry.benchmark, tool=entry.tool,
        n_qubits=entry.n_qubits, n_gates=entry.n_gates,
        status=entry.status, optimal_depth=entry.optimal_depth,
        repeats=entry.repeats,
        elapsed_mean=entry.elapsed_mean, elapsed_std=entry.elapsed_std,
        elapsed_min=entry.elapsed_min, elapsed_max=entry.elapsed_max,
        n_ok=entry.n_ok, n_timeout=entry.n_timeout, n_error=entry.n_error,
        depth_consistent=entry.depth_consistent,
        ub_value_used=ub_value_used, ub_source=ub_source,
        valid=entry.valid,
        cxdepth=entry.cxdepth, objective=entry.objective,
        depth=entry.depth, cx_depth=entry.cx_depth, cx_count=entry.cx_count,
        lower_bound=entry.lower_bound,
    )


def run_experiment(
    qasm_files:    list[Path],
    topology_name: str,
    solver_tag:    str,
    tools:         list[str],
    ub_map:        dict[str, int],
    repeats:       int,
    timeout_sec:   float,
    ub_search:     str,
    validate:      bool,
    output_dir:    Path,
    cxdepth:       bool = False,  # tối ưu CX-depth thay vì circuit depth thường (áp
                                    # dụng cho cả tool="lb" và tool="ub")
    solve_log:     bool = False,  # mặc định TẮT (giống main.py) — chỉ bật khi cần
                                   # phân tích bottleneck; bật mặc định trước đây khiến
                                   # MỌI lần solve() đều có thêm overhead (solver.stats(),
                                   # pool.stats(), json.dumps(), ...) dù không cần dùng
                                   # tới solve_logs/, làm kết quả benchmark thời gian
                                   # chậm hơn không cần thiết so với main.py thường.
) -> list[ExperimentRow]:
    solve_log_dir = (output_dir / "solve_logs") if solve_log else None
    rows: list[ExperimentRow] = []

    log.info(
        "Experiment | %d files | tools=%s | repeats=%d | ub_map=%d entries%s",
        len(qasm_files), ",".join(tools), repeats, len(ub_map),
        " | cxdepth" if cxdepth else "",
    )
    log.info("=" * 70)

    for i, qasm_path in enumerate(qasm_files):
        stem = qasm_path.stem
        for tool in tools:
            ub_value: Optional[int] = None
            ub_source = "n/a"
            if tool == "ub":
                if stem in ub_map:
                    ub_value, ub_source = ub_map[stem], "map"
                else:
                    ub_value, ub_source = None, "heuristic"  # engine tự dùng len(gates)*2

            print(f"===== [{i+1}/{len(qasm_files)}] {stem}  tool={tool}  ub_source={ub_source} =====", flush=True)

            entry = _run_single(
                qasm_path=qasm_path,
                topology_name=topology_name,
                solver_tag=solver_tag,
                timeout_sec=timeout_sec,
                validate=validate,
                tool=tool,
                cxdepth=cxdepth,
                ub=ub_value,
                ub_search=ub_search,
                solve_log_dir=solve_log_dir,
                repeats=repeats,
            )
            rows.append(_entry_to_row(entry, ub_value, ub_source))

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.csv"
    _write_rows_csv(rows, summary_path)
    log.info("Summary đã lưu → %s", summary_path)

    comparison = _build_comparison(rows)
    if comparison:
        comparison_path = output_dir / "comparison.csv"
        _write_dicts_csv(comparison, comparison_path)
        log.info("Comparison (lb vs ub) đã lưu → %s", comparison_path)

    return rows


def _write_rows_csv(rows: list[ExperimentRow], path: Path) -> None:
    import csv
    if not rows:
        return
    fieldnames = list(asdict(rows[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(asdict(r))


def _write_dicts_csv(dicts: list[dict], path: Path) -> None:
    import csv
    if not dicts:
        return
    fieldnames = list(dicts[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in dicts:
            writer.writerow(d)


def _build_comparison(rows: list[ExperimentRow]) -> list[dict]:
    """Gộp lb + ub (nếu cả 2 đều có) thành 1 dòng / benchmark để so sánh trực tiếp."""
    by_benchmark: dict[str, dict[str, ExperimentRow]] = {}
    for r in rows:
        by_benchmark.setdefault(r.benchmark, {})[r.tool] = r

    out = []
    for benchmark, per_tool in sorted(by_benchmark.items()):
        if "lb" not in per_tool or "ub" not in per_tool:
            continue
        lb, ub = per_tool["lb"], per_tool["ub"]
        ratio = (ub.elapsed_mean / lb.elapsed_mean) if lb.elapsed_mean > 0 else float("inf")
        out.append({
            "benchmark":        benchmark,
            "n_qubits":         lb.n_qubits,
            "n_gates":          lb.n_gates,
            "optimal_depth":    lb.optimal_depth,
            "depth_match":      lb.optimal_depth == ub.optimal_depth,
            "lb_mean":          lb.elapsed_mean,
            "lb_std":           lb.elapsed_std,
            "ub_mean":          ub.elapsed_mean,
            "ub_std":           ub.elapsed_std,
            "ub_value_used":    ub.ub_value_used,
            "ub_source":        ub.ub_source,
            "ratio_ub_over_lb": ratio,
            "winner":           "ub" if ratio < 1 else "lb",
        })
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_experiment",
        description="Chạy full thí nghiệm so sánh LB vs UB (UB theo từng file, lặp N lần lấy trung bình)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--benchmarks-dir", type=Path, required=True, metavar="DIR",
                    help="Thư mục chứa các file .qasm cần chạy")
    p.add_argument("--recursive", action="store_true", default=True,
                    help="Tìm .qasm đệ quy trong thư mục con (mặc định: bật)")
    p.add_argument("--topology", "-t", default="ibmq_guadalupe", metavar="NAME",
                    help="Topology phần cứng (mặc định: ibmq_guadalupe)")
    p.add_argument("--solver", "-s", default=SolverFactory.default_tag(), metavar="TAG",
                    help=f"SAT solver backend (mặc định: {SolverFactory.default_tag()})")
    p.add_argument("--tools", default="lb,ub", metavar="lb,ub",
                    help="Danh sách tool cần chạy, phân tách bởi dấu phẩy (mặc định: lb,ub — cả 2)")
    p.add_argument("--ub-map", type=Path, default=None, metavar="FILE",
                    help="File CSV (cột benchmark,ub) cung cấp UB riêng cho từng file — "
                         "ví dụ export từ SABRE. Xem experiments/ub_map.py. Benchmark nào "
                         "không có trong bảng sẽ dùng heuristic mặc định (len(gates)*2).")
    p.add_argument("--ub-search", choices=["binary", "linear"], default="binary", metavar="binary|linear",
                    help="Chiến lược tìm t sau probe khi tool=ub (mặc định: binary)")
    p.add_argument("--cxdepth", action="store_true",
                    help="Tối ưu CX-depth thay vì circuit depth thường — áp dụng cho cả "
                         "--tools lb và ub. Mặc định TẮT.")
    p.add_argument("--repeats", type=int, default=5, metavar="N",
                    help="Số lần lặp mỗi (benchmark, tool) để lấy mean/std (mặc định: 5). "
                         "Khuyến nghị 5-10 khi so sánh lb vs ub do variance giữa các lần chạy.")
    p.add_argument("--timeout", type=float, default=7200.0, metavar="SEC",
                    help="Timeout cứng (giây) cho MỖI lần chạy (mặc định: 7200s)")
    p.add_argument("--validate", action="store_true",
                    help="Validate lời giải SAT ở mỗi lần chạy")
    p.add_argument("--output-dir", type=Path, default=Path("experiment_results"), metavar="DIR",
                    help="Thư mục lưu kết quả: summary.csv, comparison.csv, solve_logs/, plots/ "
                         "(mặc định: ./experiment_results)")
    p.add_argument("--no-plots", action="store_true",
                    help="Bỏ qua bước vẽ biểu đồ (chỉ tạo summary.csv/comparison.csv)")
    p.add_argument("--solve-log", action="store_true",
                    help="Bật instrumentation chi tiết (conflicts/decisions/... mỗi lần "
                         "solve()), ghi ra <output-dir>/solve_logs/. Mặc định TẮT (giống "
                         "main.py) vì có overhead mỗi lần solve — chỉ bật khi cần phân "
                         "tích bottleneck, KHÔNG bật khi chỉ cần đo thời gian benchmark.")
    p.add_argument("--verbose", "-v", action="store_true", help="Bật DEBUG logging")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    if not args.benchmarks_dir.is_dir():
        log.error("Không tìm thấy thư mục: %s", args.benchmarks_dir)
        return 1

    pattern = "**/*.qasm" if args.recursive else "*.qasm"
    qasm_files = sorted(args.benchmarks_dir.glob(pattern))
    if not qasm_files:
        log.error("Không tìm thấy file .qasm nào trong %s", args.benchmarks_dir)
        return 1

    ub_map: dict[str, int] = {}
    if args.ub_map is not None:
        ub_map = load_ub_map(args.ub_map)
        log.info("Đã đọc %d entry từ --ub-map %s", len(ub_map), args.ub_map)

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    for t in tools:
        if t not in ("lb", "ub"):
            log.error("Tool không hợp lệ trong --tools: %s (chỉ chấp nhận lb/ub)", t)
            return 1

    rows = run_experiment(
        qasm_files=qasm_files,
        topology_name=args.topology,
        solver_tag=args.solver,
        tools=tools,
        ub_map=ub_map,
        repeats=args.repeats,
        timeout_sec=args.timeout,
        ub_search=args.ub_search,
        validate=args.validate,
        output_dir=args.output_dir,
        cxdepth=args.cxdepth,
        solve_log=args.solve_log,
    )

    if not args.no_plots:
        from experiments.analyze import generate_all_plots
        generate_all_plots(args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())