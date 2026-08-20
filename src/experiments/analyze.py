"""
Đọc kết quả từ run_experiment.py (summary.csv, comparison.csv, solve_logs/)
và vẽ biểu đồ so sánh LB vs UB. Có thể chạy độc lập (không cần chạy lại thí
nghiệm) trên bất kỳ --output-dir nào đã có sẵn:

    python experiments/analyze.py --output-dir experiment_results/

Các biểu đồ tạo ra trong <output-dir>/plots/:
  01_mean_time_lb_vs_ub.png   bar chart (log scale) so sánh thời gian trung bình
  02_speedup_ratio.png         ratio ub/lb mỗi benchmark, đường mốc =1
  03_n_solves_lb_vs_ub.png     số lần gọi solver.solve() thực tế mỗi bên (đọc
                                 từ solve_logs/, không dùng trường 'iterations'
                                 built-in vì nó không đồng nhất ý nghĩa giữa lb/ub)
  04_repeat_variance.png       box plot thời gian mỗi lần lặp — lộ rõ outlier
                                 (xem phân tích mod_mult_55 trước đó)
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger(__name__)

# Tên file solve-log: "<stem>_<tool>.csv" hoặc "<stem>_<tool>_rep<N>.csv"
_SOLVE_LOG_RE = re.compile(r"^(?P<benchmark>.+)_(?P<tool>lb|ub)(?:_rep(?P<repeat>\d+))?\.csv$")


def load_summary(output_dir: Path) -> pd.DataFrame | None:
    path = output_dir / "summary.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def load_comparison(output_dir: Path) -> pd.DataFrame | None:
    path = output_dir / "comparison.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def load_solve_logs(output_dir: Path) -> pd.DataFrame | None:
    """Gộp toàn bộ CSV trong solve_logs/ thành 1 DataFrame, thêm cột
    benchmark/tool/repeat được parse từ tên file."""
    solve_log_dir = output_dir / "solve_logs"
    if not solve_log_dir.is_dir():
        return None

    frames = []
    for f in sorted(solve_log_dir.glob("*.csv")):
        m = _SOLVE_LOG_RE.match(f.name)
        if not m:
            continue
        df = pd.read_csv(f)
        if df.empty:
            continue
        df["benchmark"] = m.group("benchmark")
        df["tool_run"]  = m.group("tool")
        df["repeat"]    = int(m.group("repeat")) if m.group("repeat") else 0
        frames.append(df)

    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def plot_mean_time_bar(summary_df: pd.DataFrame, out_path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    pivot = summary_df.pivot_table(index="benchmark", columns="tool", values="elapsed_mean")
    err   = summary_df.pivot_table(index="benchmark", columns="tool", values="elapsed_std")
    pivot = pivot.sort_index()
    err   = err.reindex(pivot.index)

    tools = [t for t in ["lb", "ub"] if t in pivot.columns]
    x = np.arange(len(pivot.index))
    width = 0.8 / max(len(tools), 1)

    fig, ax = plt.subplots(figsize=(max(8, len(pivot.index) * 0.6), 5))
    for i, tool in enumerate(tools):
        ax.bar(
            x + i * width, pivot[tool].fillna(0), width,
            yerr=err[tool].fillna(0) if tool in err else None,
            label=tool, capsize=3,
        )
    ax.set_yscale("log")
    ax.set_ylabel("Thời gian trung bình (s, log scale)")
    ax.set_xlabel("Benchmark")
    ax.set_title("Thời gian trung bình: LB vs UB (error bar = std qua các lần lặp)")
    ax.set_xticks(x + width * (len(tools) - 1) / 2)
    ax.set_xticklabels(pivot.index, rotation=45, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_speedup_ratio(comparison_df: pd.DataFrame, out_path: Path) -> None:
    import matplotlib.pyplot as plt

    df = comparison_df.sort_values("ratio_ub_over_lb")
    colors = ["tab:green" if r < 1 else "tab:red" for r in df["ratio_ub_over_lb"]]

    fig, ax = plt.subplots(figsize=(max(8, len(df) * 0.6), 5))
    ax.bar(df["benchmark"], df["ratio_ub_over_lb"], color=colors)
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax.set_yscale("log")
    ax.set_ylabel("ratio = ub_mean / lb_mean (log scale)")
    ax.set_title("Tốc độ UB so với LB (xanh: UB nhanh hơn, đỏ: UB chậm hơn)")
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(df["benchmark"], rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_n_solves(solve_logs_df: pd.DataFrame, out_path: Path) -> None:
    """Số lần gọi solver.solve() THỰC TẾ (đếm dòng trong solve_logs, trung bình
    qua các lần lặp) — phản ánh đúng 'khoảng cách cần quét' của mỗi bên, khác
    với trường 'iterations' built-in (không đồng nhất ý nghĩa giữa lb/ub)."""
    import matplotlib.pyplot as plt
    import numpy as np

    counts = (
        solve_logs_df.groupby(["benchmark", "tool_run", "repeat"])
        .size()
        .groupby(["benchmark", "tool_run"])
        .mean()
        .unstack("tool_run")
        .sort_index()
    )

    tools = [t for t in ["lb", "ub"] if t in counts.columns]
    x = np.arange(len(counts.index))
    width = 0.8 / max(len(tools), 1)

    fig, ax = plt.subplots(figsize=(max(8, len(counts.index) * 0.6), 5))
    for i, tool in enumerate(tools):
        ax.bar(x + i * width, counts[tool].fillna(0), width, label=tool)
    ax.set_ylabel("Số lần gọi solver.solve() (trung bình qua các lần lặp)")
    ax.set_xlabel("Benchmark")
    ax.set_title("Số lần solve thực tế: LB vs UB")
    ax.set_xticks(x + width * (len(tools) - 1) / 2)
    ax.set_xticklabels(counts.index, rotation=45, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_repeat_variance(solve_logs_df: pd.DataFrame, out_path: Path) -> None:
    """Box plot: với mỗi (benchmark, tool), tổng thời gian solve của TỪNG lần
    lặp (1 điểm / repeat) — giúp phát hiện outlier như trường hợp mod_mult_55
    (1 lần chạy chiếm >90% tổng thời gian)."""
    import matplotlib.pyplot as plt

    per_repeat_total = (
        solve_logs_df.groupby(["benchmark", "tool_run", "repeat"])["elapsed_sec"]
        .sum()
        .reset_index()
    )
    per_repeat_total["label"] = per_repeat_total["benchmark"] + "\n(" + per_repeat_total["tool_run"] + ")"

    labels = sorted(per_repeat_total["label"].unique())
    data   = [per_repeat_total.loc[per_repeat_total["label"] == lb, "elapsed_sec"].values for lb in labels]

    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.7), 5))
    try:
        ax.boxplot(data, tick_labels=labels, showmeans=True)  # matplotlib >= 3.9
    except TypeError:
        ax.boxplot(data, labels=labels, showmeans=True)       # matplotlib < 3.9
    ax.set_yscale("log")
    ax.set_ylabel("Tổng thời gian solve / lần lặp (s, log scale)")
    ax.set_title("Variance giữa các lần lặp (mỗi điểm/outlier = 1 lần lặp)")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def generate_all_plots(output_dir: Path) -> None:
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    summary    = load_summary(output_dir)
    comparison = load_comparison(output_dir)
    solve_logs = load_solve_logs(output_dir)

    if summary is not None and not summary.empty:
        plot_mean_time_bar(summary, plots_dir / "01_mean_time_lb_vs_ub.png")
        log.info("Đã vẽ %s", plots_dir / "01_mean_time_lb_vs_ub.png")
    else:
        log.warning("Không có summary.csv (hoặc rỗng) — bỏ qua biểu đồ 01")

    if comparison is not None and not comparison.empty:
        plot_speedup_ratio(comparison, plots_dir / "02_speedup_ratio.png")
        log.info("Đã vẽ %s", plots_dir / "02_speedup_ratio.png")
    else:
        log.warning("Không có comparison.csv (cần cả lb và ub cho ít nhất 1 benchmark) — bỏ qua biểu đồ 02")

    if solve_logs is not None and not solve_logs.empty:
        plot_n_solves(solve_logs, plots_dir / "03_n_solves_lb_vs_ub.png")
        log.info("Đã vẽ %s", plots_dir / "03_n_solves_lb_vs_ub.png")
        plot_repeat_variance(solve_logs, plots_dir / "04_repeat_variance.png")
        log.info("Đã vẽ %s", plots_dir / "04_repeat_variance.png")
    else:
        log.warning("Không có solve_logs/ — bỏ qua biểu đồ 03, 04 (cần chạy run_experiment.py, "
                     "không tắt --solve-log)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="analyze",
        description="Vẽ lại biểu đồ từ 1 thư mục kết quả đã có sẵn (không cần chạy lại thí nghiệm)",
    )
    p.add_argument("--output-dir", type=Path, required=True, metavar="DIR",
                    help="Thư mục kết quả đã tạo bởi run_experiment.py "
                         "(chứa summary.csv/comparison.csv/solve_logs/)")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s  %(levelname)-7s  %(message)s",
                          datefmt="%H:%M:%S", level=logging.INFO)
    args = build_parser().parse_args(argv)
    if not args.output_dir.is_dir():
        log.error("Không tìm thấy thư mục: %s", args.output_dir)
        return 1
    generate_all_plots(args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
