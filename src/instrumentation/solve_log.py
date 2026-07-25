"""
Instrumentation cho từng lần gọi solver.solve() bên trong QuilLSEngine.

Mục đích: thay vì chỉ đo tổng thời gian chạy (hộp đen), ta cần biết CHI TIẾT
từng lần solve tại mỗi t: có bao nhiêu conflicts/decisions/propagations, kích
thước CNF tại thời điểm đó, và solve đó là SAT hay UNSAT. Đây là dữ liệu tối
thiểu để xác định bottleneck nằm ở đâu (xem thảo luận: SAT call thường rẻ,
UNSAT call thường đắt — cần số liệu thật để xác nhận thay vì đoán).

Thiết kế: SolveLogger chỉ gom record trong bộ nhớ (self.records), việc ghi ra
CSV do caller quyết định thời điểm/đường dẫn. Trong chế độ batch (multiprocessing),
mỗi process con tự ghi file CSV của riêng nó trực tiếp ra đĩa — KHÔNG gửi
records qua multiprocessing.Queue, để tránh lặp lại bug deadlock cũ khi
payload lớn hơn buffer của pipe (xem phần sửa lỗi batch mode trước đó).
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SolveRecord:
    """Một dòng thống kê cho đúng 1 lần gọi solver.solve()."""
    t:            int
    phase:        str    # "lb" | "ub-probe" | "ub-binary" | "ub-linear"
    sat:          bool
    elapsed_sec:  float
    conflicts:    int
    decisions:    int
    propagations: int
    restarts:     int
    n_vars:       int
    n_clauses:    int

    # Breakdown theo từng loại ràng buộc (mapping/connectivity/gates/swap/
    # assumptions) — chỉ tính phần THÊM MỚI kể từ lần solve trước (delta),
    # cùng logic với conflicts/decisions ở trên. Lưu dạng JSON string vì số
    # loại "kind" biến (mp/oc/e/c/a/d/u/sw/st/asm) không cố định tuyệt đối,
    # để không phải hardcode cột cho từng loại.
    var_counts_delta:    str = "{}"   # {"mp": 12, "d": 3, ...} — biến MỚI tạo
    clause_counts_delta: str = "{}"   # {"mapping": 40, "swap": 12, ...} — clause MỚI thêm, theo từng module encoding


class SolveLogger:
    """Gom SolveRecord trong bộ nhớ trong lúc engine chạy."""

    def __init__(self) -> None:
        self.records: list[SolveRecord] = []

    def record(
        self,
        t:                   int,
        phase:               str,
        sat:                 bool,
        elapsed_sec:         float,
        stats:               dict,
        n_vars:              int,
        n_clauses:           int,
        var_counts_delta:    dict | None = None,
        clause_counts_delta: dict | None = None,
    ) -> None:
        self.records.append(SolveRecord(
            t=t, phase=phase, sat=sat, elapsed_sec=elapsed_sec,
            conflicts=stats.get("conflicts", 0),
            decisions=stats.get("decisions", 0),
            propagations=stats.get("propagations", 0),
            restarts=stats.get("restarts", 0),
            n_vars=n_vars, n_clauses=n_clauses,
            var_counts_delta=json.dumps(var_counts_delta or {}),
            clause_counts_delta=json.dumps(clause_counts_delta or {}),
        ))

    def write_csv(self, path: Path) -> None:
        """Ghi toàn bộ record ra 1 file CSV. Không làm gì nếu chưa có record nào."""
        if not self.records:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(asdict(self.records[0]).keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.records:
                writer.writerow(asdict(r))
