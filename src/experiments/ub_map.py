"""
Đọc bảng ánh xạ benchmark -> upper bound (ví dụ: độ sâu do SABRE tạo ra).

Vấn đề cần giải quyết: CLI của main.py (`--tool ub --ub N`) chỉ nhận được
MỘT giá trị --ub áp dụng cho TOÀN BỘ batch. Nhưng mỗi mạch cần một UB khác
nhau (ví dụ: SABRE cho ra độ sâu khác nhau cho từng mạch). File CSV này cho
phép khai báo UB riêng cho từng benchmark.

Định dạng file CSV (bắt buộc có header):
    benchmark,ub
    mod_mult_55,92
    tof_5,90
    4gt13_92,94

`benchmark` là TÊN FILE KHÔNG CÓ ĐUÔI .qasm (ví dụ file `mod_mult_55.qasm`
thì ghi `mod_mult_55`). Nếu 1 file .qasm trong benchmarks-dir không có trong
bảng này, run_experiment.py sẽ tự dùng heuristic mặc định của engine
(len(gates) * 2) và đánh dấu ub_source="heuristic" trong bảng kết quả.
"""

from __future__ import annotations

import csv
from pathlib import Path


def load_ub_map(path: Path) -> dict[str, int]:
    """Đọc file CSV (cột benchmark,ub) thành dict {benchmark: ub}."""
    mapping: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "benchmark" not in reader.fieldnames or "ub" not in reader.fieldnames:
            raise ValueError(
                f"{path}: file phải có header 'benchmark,ub' (tìm thấy: {reader.fieldnames})"
            )
        for row in reader:
            name = row["benchmark"].strip()
            if not name:
                continue
            mapping[name] = int(row["ub"])
    return mapping
