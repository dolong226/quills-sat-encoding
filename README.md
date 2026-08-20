# QuilLS — Depth-Optimal Quantum Layout Synthesis via SAT

Cài đặt SAT encoding cho bài toán layout synthesis tối ưu độ sâu (depth-optimal
qubit layout synthesis), dựa trên: https://arxiv.org/abs/2506.06752

Repo gồm 2 phần:
- **`src/`** — engine SAT chính + CLI chạy từng file / batch (`main.py`)
- **`src/experiments/`** — bộ công cụ chạy thí nghiệm so sánh LB vs UB trên
  nhiều benchmark, lặp lại nhiều lần lấy trung bình, xuất bảng + biểu đồ

---

## 1. Cài đặt

```bash
pip install python-sat[pblib,aiger]   # SAT solver backend (CaDiCaL, Kissat, Glucose, ...)
pip install pandas matplotlib          # chỉ cần cho src/experiments/ (bảng + biểu đồ)
```

Yêu cầu Python 3.10+ (dùng cú pháp kiểu `int | None`, `dict[str, int]`).

---

## 2. Cấu trúc thư mục

```
src/
  main.py                       entry point CLI — chạy 1 file hoặc 1 folder
  cli/
    parser.py                   toàn bộ định nghĩa argparse của main.py
    topology_registry.py        danh sách + tra cứu topology phần cứng
  runner/
    types.py                    BenchmarkEntry (1 dòng kết quả) + ghi CSV
    single.py                   chạy 1 file .qasm, in kết quả chi tiết
    batch.py                    chạy nhiều file (multiprocessing + timeout + repeats)
  instrumentation/
    solve_log.py                 SolveLogger — log conflicts/decisions/... mỗi lần solve()
  solver/
    engine.py                    QuilLSEngine — thuật toán SAT chính (lb & ub mode)
    base.py, backends.py, factory.py   SAT solver backends (pysat wrapper)
  circuit/                       parser QASM + biểu diễn mạch + dependency DAG
  encoding/                       các nhóm ràng buộc CNF (mapping/connectivity/gates/swap/assumptions)
  quills_platform/                topology phần cứng (định nghĩa qubit + kết nối)
  validation/                     kiểm tra tính hợp lệ của lời giải SAT
  experiments/
    run_experiment.py             chạy full thí nghiệm LB vs UB (UB theo từng file, lặp N lần)
    analyze.py                    đọc kết quả có sẵn, vẽ lại biểu đồ (không cần chạy lại)
    ub_map.py                     đọc file CSV ánh xạ benchmark -> upper bound riêng
```

**Nguyên tắc:** `main.py` chỉ parse CLI args rồi dispatch sang `runner.single`
hoặc `runner.batch` — không chứa logic. Muốn sửa cách chạy 1 file → sửa
`runner/single.py`. Muốn sửa cách chạy batch/timeout → sửa `runner/batch.py`.
Muốn sửa thuật toán SAT → sửa `solver/engine.py`.

---

## 3. `main.py` — chạy 1 file hoặc 1 folder

### 3.1. Cú pháp

```bash
python src/main.py <file.qasm | thư_mục>  [options]
```

Input là **file** → single mode (in kết quả chi tiết ra console).
Input là **thư mục** → batch mode (chạy tuần tự từng `.qasm`, có timeout,
xuất CSV tổng hợp).

### 3.2. Toàn bộ option

| Option | Áp dụng | Mặc định | Ý nghĩa |
|---|---|---|---|
| `input` | cả 2 | — | File `.qasm` hoặc thư mục |
| `--topology`, `-t` | cả 2 | `ibmq_guadalupe` | Topology phần cứng. Xem `--list-topologies` |
| `--solver`, `-s` | cả 2 | solver mặc định của `SolverFactory` | SAT solver backend. Xem `--list-solvers` |
| `--max-depth`, `-d` | cả 2 | `10000` | Giới hạn trên tuyệt đối cho makespan (chống vòng lặp vô hạn) |
| `--tool` | cả 2 | `lb` | `lb` = tăng dần từ lower bound (gốc paper) · `ub` = giảm dần từ upper bound |
| `--ub` | chỉ `--tool ub` | `None` (heuristic `len(gates)*2`) | Upper bound khởi điểm để probe. Luôn được **verify bằng SAT solve thật** trước khi dùng (tự nhân đôi nếu chưa đủ) — xem mục 5 |
| `--ub-search` | chỉ `--tool ub` | `binary` | `binary` (nhị phân, ít lần solve hơn) hoặc `linear` (giảm tuần tự từng t) |
| `--repeats` | cả 2 | `1` | Chạy mỗi benchmark N lần, lấy mean/std/min/max thay vì tin 1 lần chạy đơn lẻ. **Khuyến nghị 5–10 khi so sánh lb vs ub** (SAT solving có variance lớn — xem mục 6) |
| `--timeout` | batch | `7200.0` | Timeout (giây) cho **mỗi lần chạy** (không phải cả batch). Mỗi lần chạy trong 1 process con riêng |
| `--output`, `-o` | batch | `None` | Lưu kết quả batch ra CSV |
| `--recursive`, `-r` | batch | bật | Tìm `.qasm` đệ quy trong thư mục con |
| `--validate` | cả 2 | tắt | Kiểm tra lời giải SAT (mapping đầy đủ, đúng thứ tự phụ thuộc, CX chỉ chạy trên cặp qubit kề nhau, không xung đột physical qubit, ...) |
| `--verbose`, `-v` | cả 2 | tắt | Bật DEBUG log + log chi tiết từng bước solve (chỉ rõ ở single mode) |
| `--solve-log DIR` | cả 2 | `None` (tắt) | Ghi thống kê **từng lần gọi `solver.solve()`** ra CSV (xem mục 5). Có overhead nhỏ, chỉ bật khi cần phân tích bottleneck |
| `--list-solvers` | — | — | In danh sách SAT solver rồi thoát |
| `--list-topologies` | — | — | In danh sách topology rồi thoát |

### 3.3. Ví dụ

```bash
# Chạy 1 file, thuật toán mặc định
python src/main.py circuit.qasm

# Batch, timeout 60s/file, validate, lưu CSV
python src/main.py benchmarks/ --timeout 60 --validate --output results.csv

# UB-first với upper bound tự chọn (SABRE, Q-Synth, ...), quét nhị phân
python src/main.py circuit.qasm --tool ub --ub 92

# Lặp 8 lần lấy trung bình (khuyến nghị khi so sánh lb/ub)
python src/main.py benchmarks/ --repeats 8 --output results.csv

# Bật instrumentation để tìm bottleneck
python src/main.py benchmarks/ --tool ub --solve-log ./solve_logs
```

---

## 4. So sánh LB vs UB: `--tool lb` và `--tool ub`

- **`lb`** (mặc định, đúng thiết kế gốc trong paper): tăng dần `t` từ
  `lower_bound` (critical-path depth của mạch — chặn dưới lý thuyết, luôn
  đúng), dừng ngay khi gặp `t` đầu tiên SAT. Dùng 1 solver duy nhất sống suốt
  quá trình, mỗi bước chỉ **thêm** clause mới (incremental) — không rebuild.

- **`ub`**: giảm dần `t` từ 1 upper bound đã **verify SAT thật** xuống
  `lower_bound`. Cũng dùng 1 solver duy nhất sống suốt quá trình + CNF chỉ
  **mở rộng** (không bao giờ co lại) — mỗi `t` khác nhau chỉ khác ở
  assumption literal `asm(t)`, không cần rebuild.
  - `--ub` không truyền → heuristic tạm `len(gates) * 2`. Đây **chỉ là
    phỏng đoán lỏng**, không đảm bảo đủ lớn — engine luôn tự "probe" (solve
    thật) tại giá trị này trước, và tự **nhân đôi** nếu UNSAT, cho tới khi
    tìm được 1 horizon chắc chắn SAT, rồi mới bắt đầu quét giảm dần.
  - Nếu bạn đã có 1 upper bound tốt hơn từ nơi khác (SABRE, Q-Synth, ...),
    truyền qua `--ub N` để bỏ qua phần lớn công đoạn probe.

**UB không phải lúc nào cũng chậm hơn LB** — thực nghiệm cho thấy kết quả phụ
thuộc vào việc `lower_bound` (critical path) "chặt" tới đâu so với optimal
depth, so với việc UB heuristic "chặt" tới đâu — 2 đại lượng này độc lập theo
từng mạch. Xem `src/experiments/` để tự đo trên bộ benchmark của bạn.

---

## 5. Instrumentation: `--solve-log DIR`

Ghi 1 dòng CSV cho **mỗi lần gọi `solver.solve()`** (không phải mỗi benchmark):

| Cột | Ý nghĩa |
|---|---|
| `t` | Giá trị horizon đang thử |
| `phase` | `lb` \| `ub-probe` \| `ub-binary` \| `ub-linear` |
| `sat` | Kết quả SAT/UNSAT của lần solve này |
| `elapsed_sec` | Thời gian riêng của lần solve này |
| `conflicts`, `decisions`, `propagations`, `restarts` | Thống kê CDCL — **DELTA** so với lần solve trước (không phải lũy kế — `accum_stats()` của pysat vốn lũy kế từ lúc tạo solver, đã tự động trừ đi) |
| `n_vars`, `n_clauses` | Tổng số biến/clause trong solver TẠI THỜI ĐIỂM đó (lũy kế, không phải delta) |
| `var_counts_delta` | JSON string: số biến MỚI tạo (từ lần solve trước), theo từng loại (`mp`, `oc`, `e`, `c`, `a`, `d`, `u`, `sw`, `st`, `asm` — xem `encoding/variables.py`) |
| `clause_counts_delta` | JSON string: số clause MỚI thêm, theo từng module encoding (`mapping`, `connectivity`, `gates`, `swap`, `assumptions`) |

Ghi ra `<DIR>/<tên_file>_<tool>.csv` (single mode / `--repeats 1`), hoặc
`<DIR>/<tên_file>_<tool>_rep<N>.csv` (khi `--repeats > 1`, mỗi lần lặp 1 file
riêng để không ghi đè lẫn nhau).

Dùng để trả lời các câu hỏi kiểu: "chi phí nằm ở SAT-call hay UNSAT-call?",
"CNF của UB có bị 'bloat' so với LB không?", "clause nào chiếm phần lớn?" —
xem ví dụ phân tích thực tế trong lịch sử phát triển repo này (tóm tắt: hoá ra
bottleneck chính của `mod_mult_55` là 1 lần solve bất thường chiếm >90% tổng
thời gian — không phải hiện tượng hệ thống, mà là 1 outlier).

---

## 6. `experiments/` — chạy thí nghiệm so sánh LB vs UB có hệ thống

**Vấn đề mà `main.py` batch mode KHÔNG giải quyết được:** `--ub` chỉ nhận 1
giá trị áp dụng cho **toàn bộ** batch, trong khi mỗi mạch cần 1 UB khác nhau
(ví dụ độ sâu do SABRE tạo ra cho từng mạch). `experiments/run_experiment.py`
giải quyết việc này bằng file `--ub-map` (UB riêng theo từng file), đồng thời
tự động chạy N lần mỗi benchmark, tổng hợp bảng so sánh + vẽ biểu đồ.

### 6.1. `run_experiment.py`

```bash
python src/experiments/run_experiment.py --benchmarks-dir DIR [options]
```

| Option | Mặc định | Ý nghĩa |
|---|---|---|
| `--benchmarks-dir DIR` | **bắt buộc** | Thư mục chứa `.qasm` |
| `--recursive` | bật | Tìm `.qasm` đệ quy |
| `--topology`, `-t` | `ibmq_guadalupe` | Topology phần cứng |
| `--solver`, `-s` | mặc định của `SolverFactory` | SAT solver backend |
| `--tools` | `lb,ub` | Danh sách tool cần chạy, cách nhau bởi dấu phẩy (có thể chỉ `lb` hoặc chỉ `ub`) |
| `--ub-map FILE` | `None` | File CSV cấp UB riêng cho từng benchmark (xem 6.2) |
| `--ub-search` | `binary` | Giống `main.py` |
| `--repeats N` | `5` | Số lần lặp mỗi (benchmark, tool). Khuyến nghị 5–10 |
| `--timeout SEC` | `7200.0` | Timeout mỗi lần chạy |
| `--validate` | tắt | Validate lời giải SAT |
| `--output-dir DIR` | `./experiment_results` | Nơi lưu `summary.csv`, `comparison.csv`, `solve_logs/`, `plots/` |
| `--no-plots` | tắt | Bỏ qua bước vẽ biểu đồ (chỉ tạo 2 file CSV) |
| `--verbose`, `-v` | tắt | DEBUG logging |

### 6.2. Định dạng file `--ub-map`

CSV với header `benchmark,ub`. `benchmark` là **tên file KHÔNG có đuôi
`.qasm`**:

```csv
benchmark,ub
mod_mult_55,92
tof_5,90
4gt13_92,94
```

Benchmark nào không có trong file này sẽ tự dùng heuristic mặc định của
engine (`len(gates) * 2`) và được đánh dấu `ub_source=heuristic` trong kết
quả (khác với `ub_source=map` khi lấy từ file).

### 6.3. Ví dụ

```bash
# Không có UB map — chỉ dùng heuristic, chạy cả lb và ub, lặp 5 lần
python src/experiments/run_experiment.py --benchmarks-dir benchmarks/ --repeats 5

# Có UB map từ SABRE, lặp 10 lần, lưu vào thư mục riêng
python src/experiments/run_experiment.py \
    --benchmarks-dir benchmarks/ \
    --ub-map sabre_ub.csv \
    --repeats 10 \
    --output-dir results/sabre_comparison/

# Chỉ re-run nhánh ub (ví dụ sau khi sửa engine, không cần chạy lại lb)
python src/experiments/run_experiment.py --benchmarks-dir benchmarks/ --tools ub --repeats 10
```

### 6.4. Đầu ra

```
<output-dir>/
  summary.csv        1 dòng / (benchmark, tool): mean/std/min/max, ub_value_used, ub_source, depth_consistent, ...
  comparison.csv      1 dòng / benchmark có CẢ lb và ub: ratio_ub_over_lb, winner, depth_match, ...
  solve_logs/          CSV instrumentation thô (1 file / benchmark / tool / lần lặp)
  plots/
    01_mean_time_lb_vs_ub.png   bar chart (log scale), error bar = std
    02_speedup_ratio.png         ratio ub/lb mỗi benchmark (xanh = ub nhanh hơn)
    03_n_solves_lb_vs_ub.png     số lần gọi solver.solve() thực tế (đọc từ solve_logs/, đáng
                                   tin hơn trường 'iterations' vì lb/ub tính iterations khác ý nghĩa)
    04_repeat_variance.png       box plot thời gian mỗi lần lặp — lộ rõ outlier
```

`depth_consistent` trong `summary.csv`: `False` nghĩa là các lần lặp SAT ra
`optimal_depth` KHÁC NHAU — dấu hiệu bất thường (solver không deterministic
hoặc có bug), cần kiểm tra ngay, không nên bỏ qua.

### 6.5. Vẽ lại biểu đồ mà không cần chạy lại thí nghiệm

```bash
python src/experiments/analyze.py --output-dir results/sabre_comparison/
```

Đọc lại `summary.csv`/`comparison.csv`/`solve_logs/` đã có sẵn trong thư mục
đó và vẽ lại toàn bộ 4 biểu đồ — hữu ích khi chỉ muốn chỉnh style biểu đồ mà
không cần chạy lại SAT solver (rất tốn thời gian).

---

## 7. Ghi chú thực nghiệm (rút ra trong quá trình phát triển)

- **SAT solving có variance đáng kể giữa các lần chạy** — quan sát thực tế:
  1 lần solve tại 1 giá trị `t` cụ thể có thể chiếm >90% tổng thời gian của cả
  benchmark (conflict count tương đương các lần lân cận, nhưng tốc độ xử
  lý/conflict giảm hơn 30 lần). Luôn dùng `--repeats >= 5` khi so sánh
  lb vs ub, đừng kết luận từ 1 lần chạy đơn lẻ.
- **UB không phải lúc nào cũng chậm hơn LB** — phụ thuộc việc `lower_bound`
  (critical path) chặt tới đâu so với optimal, so với việc UB heuristic chặt
  tới đâu. Hai đại lượng này độc lập theo từng mạch cụ thể.
- **`len(gates)` không phải upper bound hợp lệ** cho makespan — mỗi SWAP
  chiếm dụng thêm timestep riêng để định tuyến, không tính vào số cổng gốc.
  Engine luôn probe/verify bằng SAT solve thật trước khi tin bất kỳ giá trị
  UB nào (heuristic hay do người dùng truyền vào).
- Khi chạy batch trên Windows, kết quả từ mỗi process con **phải được đọc từ
  `multiprocessing.Queue` trước khi `join()`**, không phải sau — nếu không sẽ
  deadlock khi payload (circuit + model + schedule) lớn hơn buffer của pipe
  nội bộ hệ điều hành.
