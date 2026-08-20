"""Kiểu dữ liệu dùng chung cho kết quả benchmark (single lẫn batch mode)."""

from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BenchmarkEntry:
    """Kết quả (đã tổng hợp qua N lần lặp, nếu --repeats > 1) của một benchmark."""
    benchmark:     str
    n_qubits:      int
    n_gates:       int
    topology:      str
    solver:        str
    tool:          str            # lb | ub
    timeout_sec:   float
    status:        str            # SAT | UNSAT | TIMEOUT | ERROR (của lần chạy ĐẦU TIÊN
                                   # trong batch các repeat — dùng để hiển thị nhanh; xem
                                   # n_ok/n_timeout/n_error để biết chi tiết toàn bộ repeats)
    optimal_depth: int            # -1 nếu không SAT
    elapsed_sec:   float          # = elapsed_mean (giữ tên cũ để tương thích ngược với CSV/script cũ)
    iterations:    int            # = iterations của lần chạy đầu tiên thành công
    valid:         Optional[bool] = None  # chỉ điền khi --validate

    # Thống kê qua nhiều lần lặp (điền đầy đủ khi --repeats > 1; khi
    # repeats=1 thì elapsed_std=0.0, elapsed_min=elapsed_max=elapsed_sec)
    repeats:            int = 1
    elapsed_mean:        float = 0.0
    elapsed_std:         float = 0.0
    elapsed_min:         float = 0.0
    elapsed_max:         float = 0.0
    n_ok:                int = 0   # số lần chạy ra SAT/UNSAT (không timeout/error)
    n_timeout:           int = 0
    n_error:             int = 0
    depth_consistent:    Optional[bool] = None  # False nếu các lần lặp SAT ra optimal_depth khác nhau
                                                  # (dấu hiệu solver không deterministic — đáng nghi ngờ)
    cxdepth:             bool = False  # True nếu tối ưu CX-depth thay vì circuit depth thường
    objective:           str = "depth"  # "depth" | "cxdepth" — giá trị optimal_depth là gì
    depth:               int = -1  # depth thường post-hoc (luôn điền, bất kể objective)
    cx_depth:            int = -1  # CX-depth post-hoc (luôn điền, bất kể objective)
    cx_count:            int = -1  # CX-count post-hoc = CX gốc + 3*swaps (luôn điền)
    lower_bound:         int = -1  # cận dưới lý thuyết (critical path) dùng làm điểm xuất phát search

    # Kết quả TẠM THỜI khi bị TIMEOUT giữa chừng (status sẽ là "TIMEOUT_PARTIAL"
    # thay vì "TIMEOUT" trắng tay) — xem solver/engine.py::_report_progress.
    partial_kind:        str = ""   # "ub_best_sat" | "lb_last_unsat" | "" (không có/không timeout)
    partial_bound:       int = -1   # mode=ub: best_sat_t hợp lệ tìm được (1 UPPER BOUND thật, dùng được)
                                     # mode=lb: t cao nhất đã CHỨNG MINH UNSAT (optimal chắc chắn > giá trị này)


def summarize_repeats(elapsed_list: list[float]) -> tuple[float, float, float, float]:
    """Tính (mean, std, min, max) cho danh sách thời gian của các lần lặp
    THÀNH CÔNG (không tính các lần TIMEOUT/ERROR). Trả về (0,0,0,0) nếu rỗng."""
    if not elapsed_list:
        return 0.0, 0.0, 0.0, 0.0
    mean = statistics.mean(elapsed_list)
    std  = statistics.stdev(elapsed_list) if len(elapsed_list) > 1 else 0.0
    return mean, std, min(elapsed_list), max(elapsed_list)


def write_csv(entries: list[BenchmarkEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(entries[0]).keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow(asdict(e))
