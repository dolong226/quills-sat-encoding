"""
Sinh UB map bằng SABRE — HOÀN TOÀN ĐỘC LẬP với code QuilLS (chỉ dùng qiskit).
Chạy trên mạch ĐÃ TRANSPILE (vì UB cần cùng basis gate với input đưa vào QuilLS).

Coupling map truyền qua JSON để tách khỏi Topology class nội bộ:
  coupling.json = [[0,1],[1,2],[1,6],...]   (list các cặp qubit vật lý nối nhau)

CÁCH DÙNG:
  python sabre_ub.py --benchmarks-dir benchmarks/transpiled --coupling coupling.json \
      --output sabre_ub.csv --trials 20 --seed 0
"""
import argparse
import csv
from pathlib import Path

from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap


def sabre_ub(qasm_path: Path, coupling_map: CouplingMap, basis_gates: list[str],
             trials: int, seed: int, optimization_level: int = 3) -> int:
    # QUAN TRỌNG: paper SABRE gốc chạy 5 initial mapping ngẫu nhiên x 3
    # traversal (fwd-bwd-fwd), lấy tốt nhất. SabreLayout của Qiskit có tham
    # số layout_trials/swap_trials tương đương "5 lần thử mapping" — set trực
    # tiếp qua transpiler_staged thay vì chỉ lặp seed_transpiler (không chắc
    # đủ để khớp 100% vì Qiskit không public δ/W/|E| của paper, chỉ là xấp
    # xỉ tốt nhất có thể).
    from qiskit.transpiler.passes import SabreLayout
    qc = QuantumCircuit.from_qasm_file(str(qasm_path))
    best_depth = None
    for i in range(trials):
        try:
            out = transpile(
                qc,
                coupling_map=coupling_map,
                basis_gates=basis_gates,
                layout_method="sabre",
                routing_method="sabre",
                optimization_level=optimization_level,
                seed_transpiler=seed + i,
                layout_trials=5,   # ~ "5 initial mapping" của paper gốc
                swap_trials=5,
            )
        except TypeError:
            # bản Qiskit cũ không nhận layout_trials/swap_trials qua transpile()
            out = transpile(
                qc, coupling_map=coupling_map, basis_gates=basis_gates,
                layout_method="sabre", routing_method="sabre",
                optimization_level=optimization_level, seed_transpiler=seed + i,
            )
        d = out.depth()
        if best_depth is None or d < best_depth:
            best_depth = d
    return best_depth


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--benchmarks-dir", required=True, help="Thư mục chứa .qasm ĐÃ transpile")
    p.add_argument("--coupling", required=True, help="File JSON: list [[p1,p2], ...]")
    p.add_argument("--basis-gates", default="id,rz,sx,x,cx",
                    help="Basis gates, phân cách bởi dấu phẩy (mặc định: basis IBM native)")
    p.add_argument("--output", required=True, help="File CSV output (benchmark,ub)")
    p.add_argument("--trials", type=int, default=20,
                    help="Số lần chạy SABRE (random) mỗi benchmark, lấy depth NHỎ NHẤT làm UB "
                         "(SABRE có yếu tố ngẫu nhiên qua seed — chạy nhiều lần mới ra UB tốt)")
    p.add_argument("--optimization-level", type=int, default=3, choices=[0,1,2,3],
                    help="Qiskit optimization_level (mặc định 3 — SABRE layout tốt hơn hẳn "
                         "level thấp; nếu UB vẫn cao hơn nhiều so với paper, thử tăng --trials")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--recursive", "-r", action="store_true", default=True,
                    help="Tìm .qasm đệ quy trong thư mục con (mặc định: bật)")
    args = p.parse_args()

    import json
    edges = json.loads(Path(args.coupling).read_text())
    coupling_map = CouplingMap(edges)
    basis_gates = args.basis_gates.split(",")

    pattern = "**/*.qasm" if args.recursive else "*.qasm"
    qasm_files = sorted(Path(args.benchmarks_dir).glob(pattern))
    rows = []
    for i, f in enumerate(qasm_files, 1):
        print(f"[{i}/{len(qasm_files)}] {f.name} ...", flush=True)
        try:
            ub = sabre_ub(f, coupling_map, basis_gates, args.trials, args.seed, args.optimization_level)
            rows.append((f.stem, ub))
            print(f"  -> ub={ub}")
        except Exception as e:
            print(f"  LỖI: {e}")

    with open(args.output, "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["benchmark", "ub"])
        w.writerows(rows)
    print(f"Xong. Đã ghi: {args.output}")


if __name__ == "__main__":
    main()
