"""Định nghĩa argparse parser cho QuilLS CLI.

Các tham số được nhóm theo chức năng bên dưới:
  1. Input                — file hay folder cần chạy
  2. Bài toán              — topology, solver, giới hạn depth
  3. Thuật toán tìm depth  — --tool / --ub / --ub-search
  4. Batch mode            — --timeout, --output, --recursive
  5. Debug / instrumentation — --validate, --verbose, --solve-log
  6. Info commands         — --list-solvers, --list-topologies
"""

from __future__ import annotations

import argparse
from pathlib import Path

from solver.factory import SolverFactory


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quills",
        description="QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # một file
  python main.py circuit.qasm

  # một folder (batch, timeout 60s mỗi file)
  python main.py benchmarks/collection/ --timeout 60

  # batch + validate + lưu CSV
  python main.py benchmarks/ --timeout 120 --validate --output results.csv
""",
    )

    # ── 1. Input ───────────────────────────────────────────────────────────────
    p.add_argument(
        "input",
        nargs="?",  # optional vì --list-solvers/--list-topologies không cần input
        metavar="FILE_OR_DIR",
        help="File .qasm (single mode) hoặc folder chứa các file .qasm (batch mode). "
             "main.py tự phân biệt 2 chế độ dựa vào input là file hay thư mục.",
    )

    # ── 2. Bài toán: topology / solver / giới hạn depth ────────────────────────
    p.add_argument(
        "--topology", "-t",
        default="guadalupe",
        metavar="NAME",
        help="Topology phần cứng — quy định các cặp qubit vật lý được kết nối ",
    )
    p.add_argument(
        "--solver", "-s",
        default=SolverFactory.default_tag(),
        metavar="TAG",
        help=f"SAT solver (default: {SolverFactory.default_tag()}). "
             "--list-solvers for full lists (cadical195, kissat404, glucose42, ...).",
    )
    p.add_argument(
        "--max-depth", "-d",
        type=int,
        default=10000,
        metavar="N",
        help="Giới hạn trên tuyệt đối cho makespan/depth - dùng để tránh vòng lặp "
    )

    # ── 3. Thuật toán tìm optimal depth: lb (mặc định) hoặc ub ─────────────────
    p.add_argument(
        "--tool",
        choices=["lb", "ub"],
        default="lb",
        metavar="lb|ub",
        help="Search strategy",
    )
    p.add_argument(
        "--ub",
        type=int,
        default=None,
        metavar="N",
        help="Chỉ dùng khi tool là ub, nếu không truyền UB, nó sẽ lấy theo heuristic",
    )
    p.add_argument(
        "--ub-search",
        choices=["binary", "linear"],
        default="linear",
        metavar="binary|linear",
        help="Chiến lược tìm kiếm từ UB: linear hoặc binary giữa UB/LB",
    )

    # ── 4. Batch mode: timeout / output / đệ quy ───────────────────────────────
    p.add_argument(
        "--timeout",
        type=float,
        default=7200.0,
        metavar="SEC"
    )
    p.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Lưu kết quả batch ra file CSV (chỉ có tác dụng khi input là folder). "
             "Mỗi dòng là 1 BenchmarkEntry (xem runner/types.py): benchmark, "
             "n_qubits, n_gates, tool, status, optimal_depth, elapsed_sec, ...",
    )
    p.add_argument(
        "--recursive", "-r",
        action="store_true",
        default=True,
        help="Tìm .qasm đệ quy trong các thư mục con (default: on). "
    )

    # ── 5. Debug / kiểm tra / instrumentation ──────────────────────────────────
    p.add_argument(
        "--validate",
        action="store_true",
        help="Sau khi tìm được lời giải SAT, chạy validator (validation/validator.py) "
             "để kiểm tra 6 điều kiện: mapping đầy đủ, mọi gate được xếp lịch đúng "
             "1 lần, thứ tự phụ thuộc đúng, CX chỉ chạy trên cặp qubit kề nhau, "
             "không có 2 gate cùng dùng 1 qubit vật lý tại cùng 1 timestep.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Bật debug logging + log chi tiết từng bước solve (t=... solving ...) "
             "từ QuilLSEngine. Chỉ có tác dụng rõ ở single mode (batch mode luôn "
             "chạy engine với verbose=False để log không bị rối khi nhiều process "
             "con in cùng lúc).",
    )
    p.add_argument(
        "--solve-log",
        type=Path,
        default=None,
        metavar="DIR",
        help="Bật instrumentation cho mỗi lần gọi solver.solve(): ghi ra 1 dòng CSV "
             "gồm t, phase (lb/ub-probe/ub-binary/ub-linear), sat/unsat, thời gian, "
             "conflicts/decisions/propagations/restarts (delta so với lần solve "
             "trước, không phải lũy kế), và breakdown số biến/clause mới thêm theo "
             "từng module encoding (mapping/connectivity/gates/swap/assumptions). "
             "Ghi ra <DIR>/<tên_file>_<tool>.csv, 1 file mỗi benchmark. "
             "Mặc định None vì có overhead nhỏ mỗi lần solve"
    )

    # ── 6. Info commands: in thông tin rồi thoát ngay, không chạy solver ───────
    p.add_argument(
        "--list-solvers",
        action="store_true",
        help="In danh sách SAT solver backend có sẵn rồi thoát.",
    )
    p.add_argument(
        "--list-topologies",
        action="store_true",
        help="In danh sách topology phần cứng có sẵn rồi thoát.",
    )

    return p
