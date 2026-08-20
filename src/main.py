"""
QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT

===============================================================================
CÁCH DÙNG
===============================================================================
# Chạy một file, dùng thuật toán mặc định (lb = tăng dần từ lower bound)
python main.py circuit.qasm --topology ibmq_guadalupe

# Chạy một folder (batch, tuần tự từng file, có timeout cứng mỗi file)
python main.py benchmarks/collection/ --timeout 60

# Chạy folder, validate lời giải SAT, lưu kết quả ra CSV
python main.py benchmarks/collection/ --timeout 60 --validate --output results.csv

# Dùng chiến lược UB-first (giảm dần từ upper bound) thay vì mặc định LB-first
python main.py circuit.qasm --tool ub

# UB-first với upper bound tự truyền vào (thay vì heuristic len(gates)*2)
python main.py circuit.qasm --tool ub --ub 150

# UB-first, quét giảm dần tuần tự thay vì nhị phân (để so sánh/debug)
python main.py circuit.qasm --tool ub --ub-search linear

# Bật instrumentation: ghi lại thống kê (conflicts/decisions/...) cho từng
# lần gọi solver.solve(), để tìm bottleneck. 1 file CSV / benchmark.
python main.py benchmarks/ --tool ub --solve-log ./solve_logs

# Xem danh sách solver / topology có sẵn
python main.py --list-solvers
python main.py --list-topologies

===============================================================================
CẤU TRÚC MODULE (sau khi tách khỏi main.py để dễ mở rộng)
===============================================================================
  cli/parser.py                 định nghĩa toàn bộ argparse (--tool, --ub, ...)
  cli/topology_registry.py      danh sách + tra cứu topology phần cứng có sẵn
  runner/types.py                BenchmarkEntry (1 dòng kết quả) + ghi CSV
  runner/single.py               chạy 1 file .qasm, in kết quả chi tiết ra console
  runner/batch.py                 chạy nhiều file (multiprocessing + timeout cứng,
                                  xem docstring trong file đó về bug deadlock đã sửa)
  instrumentation/solve_log.py    SolveLogger — log conflicts/decisions/... mỗi lần solve()
  solver/engine.py                QuilLSEngine — thuật toán SAT chính (lb & ub mode)

main.py (file này) CHỈ làm 2 việc: (1) parse CLI args, (2) dispatch sang
runner.single hoặc runner.batch tuỳ input là file hay folder. Không chứa logic
thuật toán/IO — muốn sửa cách chạy 1 file thì sửa runner/single.py, muốn sửa
cách chạy batch thì sửa runner/batch.py, muốn sửa thuật toán SAT thì sửa
solver/engine.py.
"""

from __future__ import annotations

import logging
import multiprocessing
import sys
from pathlib import Path

from cli.parser import build_parser
from cli.topology_registry import TOPOLOGY_PRESETS
from runner.batch import run_batch
from runner.single import run_file
from solver.factory import SolverFactory

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Entry point. `argv=None` nghĩa là lấy từ sys.argv (dùng thật khi chạy
    CLI); truyền argv tường minh hữu ích khi viết test (gọi main(["file.qasm", "--tool", "ub"]))."""
    parser = build_parser()
    args   = parser.parse_args(argv)

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    # ── Info commands: chỉ in thông tin rồi thoát, không chạy solver ──────────
    if args.list_solvers:
        SolverFactory.list_available()
        return 0

    if args.list_topologies:
        print(f"{'Name':<20} Description")
        print("-" * 50)
        for name, desc in TOPOLOGY_PRESETS.items():
            print(f"  {name:<18} {desc}")
        return 0

    if not args.input:
        # Không có input (không phải file, không phải folder) -> in help và thoát.
        parser.print_help()
        return 1

    input_path = Path(args.input)

    # ── Folder → batch mode ───────────────────────────────────────────────────
    # input là 1 thư mục: quét tất cả file .qasm (đệ quy nếu --recursive, mặc
    # định luôn bật) rồi chạy tuần tự từng file qua runner.batch.run_batch().
    # Mỗi file chạy trong 1 process con riêng để có thể áp timeout cứng
    # (--timeout), không để 1 file khó/treo làm hỏng cả batch.
    if input_path.is_dir():
        pattern    = "**/*.qasm" if args.recursive else "*.qasm"
        qasm_files = sorted(input_path.glob(pattern))

        if not qasm_files:
            log.error("Không tìm thấy file .qasm nào trong %s", input_path)
            return 1

        run_batch(
            qasm_files=qasm_files,
            topology_name=args.topology,   # topology phần cứng dùng chung cho cả batch
            solver_tag=args.solver,        # SAT solver backend (cadical195, kissat404, ...)
            timeout_sec=args.timeout,      # timeout cứng (giây) cho MỖI file, không phải cả batch
            validate=args.validate,        # có chạy validator sau khi SAT hay không
            output_csv=args.output,        # đường dẫn CSV tổng hợp kết quả batch (None = không lưu)
            tool=args.tool,                # "lb" | "ub" — thuật toán tìm optimal depth
            cxdepth=args.cxdepth,          # tối ưu CX-depth thay vì circuit depth thường
            ub=args.ub,                    # chỉ dùng khi tool="ub": upper bound khởi điểm
            ub_search=args.ub_search,      # chỉ dùng khi tool="ub": "binary" | "linear"
            solve_log_dir=args.solve_log,  # thư mục ghi CSV instrumentation (None = tắt, mặc định)
            repeats=args.repeats,           # số lần lặp mỗi file để lấy mean/std (mặc định 1 = không lặp)
        )
        return 0

    # ── File đơn → single mode ────────────────────────────────────────────────
    # input là 1 file .qasm: chạy trực tiếp (không qua multiprocessing/timeout),
    # in kết quả chi tiết (mapping, schedule, validation nếu có) ra console.
    if not input_path.exists():
        log.error("Không tìm thấy file: %s", input_path)
        return 1

    return run_file(
        qasm_path=input_path,
        topology_name=args.topology,
        solver_tag=args.solver,
        validate=args.validate,
        verbose=args.verbose,          # bật log chi tiết từng bước (t=... solving ...) từ QuilLSEngine
        tool=args.tool,
        cxdepth=args.cxdepth,
        ub=args.ub,
        ub_search=args.ub_search,
        solve_log_dir=args.solve_log,
        repeats=args.repeats,
    )


if __name__ == "__main__":
    # freeze_support(): bắt buộc trên Windows khi dùng multiprocessing.Process
    # trong 1 script được đóng gói (PyInstaller/cx_Freeze); vô hại nếu không
    # đóng gói, nên luôn gọi cho an toàn.
    multiprocessing.freeze_support()
    sys.exit(main())
