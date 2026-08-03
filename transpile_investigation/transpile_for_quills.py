"""
Tiền xử lý transpile TRƯỚC KHI đưa mạch vào QuilLS — tái tạo CHÍNH XÁC cách
tác giả gốc tạo benchmark transpiled (xem email Anders Clausen + commit
bad7cd7:src/transpiler.py của repo quills).

QUAN TRỌNG: coupling_map được override thành ALL-TO-ALL (mọi cặp qubit đều
"nối" với nhau) — nghĩa là Qiskit CHỈ viết lại gate về đúng basis gate của
backend (rz, sx, x, cx, id, reset), TUYỆT ĐỐI không tự chèn SWAP/routing gì
cả. Toàn bộ layout + routing vẫn để QuilLS tự giải qua SAT.

Cài đặt để tái tạo byte-identical với repo gốc (theo email Anders):
    pip install "qiskit==1.0.2" "qiskit-ibm-runtime==0.22.0"

CÁCH DÙNG:
    # 1 file
    python transpile_for_quills.py benchmarks/collection/adder.qasm guadalupe -o transpiled/adder.qasm

    # cả thư mục (giữ nguyên tên file, ghi vào thư mục đích)
    python transpile_for_quills.py benchmarks/collection guadalupe -o transpiled/ --batch
"""
import argparse
import sys
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.circuit import QuantumRegister, Qubit
from qiskit.compiler import transpile
import qiskit_ibm_runtime.fake_provider as _fp

# qiskit-ibm-runtime đổi tên Fake*  ->  Fake*V2 ở các bản mới, và một số máy
# cũ nhỏ (Tenerife, Tokyo) đã bị XOÁ HẲN ở bản mới nhất (IBM đã retire khỏi
# fleet, không chỉ đổi tên) — bản 0.22.0 mà Anders dùng vẫn còn đủ cả 4.
# -> Import KIỂU LAZY (chỉ báo lỗi khi thực sự cần platform đó), để ít nhất
# các platform còn tồn tại (vd guadalupe) vẫn chạy được ngay cả khi máy bạn
# cài bản qiskit-ibm-runtime mới nhất.
_FAKE_BACKEND_NAMES = {
    "tenerife":  ("FakeTenerife",  "FakeTenerifeV2"),
    "tokyo":     ("FakeTokyo",     "FakeTokyoV2"),
    "cambridge": ("FakeCambridge", "FakeCambridgeV2"),
    "guadalupe": ("FakeGuadalupe", "FakeGuadalupeV2"),
}


def _get_fake_backend_class(platform: str):
    name_v1, name_v2 = _FAKE_BACKEND_NAMES[platform]
    if hasattr(_fp, name_v1):
        return getattr(_fp, name_v1)
    if hasattr(_fp, name_v2):
        return getattr(_fp, name_v2)
    raise ImportError(
        f"Không tìm thấy '{name_v1}'/'{name_v2}' trong qiskit_ibm_runtime.fake_provider — "
        f"bản qiskit-ibm-runtime bạn đang cài có thể đã bỏ hẳn platform '{platform}' "
        f"(máy cũ, IBM đã retire khỏi fleet). Cài đúng bản Anders dùng để chắc chắn có "
        f"đủ: pip install \"qiskit-ibm-runtime==0.22.0\""
    )

# QuantumCircuit.qasm() bị XOÁ ở các bản Qiskit mới (deprecated từ ~0.45, xoá
# hẳn ở 1.x/2.x trở lên) — API thay thế là qiskit.qasm2.dumps(). Thử cả 2 để
# chạy được trên nhiều version Qiskit khác nhau.
def _circuit_to_qasm(circuit: QuantumCircuit) -> str:
    try:
        from qiskit import qasm2
        return qasm2.dumps(circuit)
    except ImportError:
        return circuit.qasm()  # fallback cho Qiskit bản cũ (<1.0)


# QUAN TRỌNG: transpile(backend=..., coupling_map=all-to-all) trả về mạch
# TRÊN TOÀN BỘ n qubit của backend (vd 16 qubit của guadalupe), dù mạch gốc
# chỉ có 5 qubit logic — vì coupling_map all-to-all khiến Qiskit chọn trivial
# layout (qubit logic i -> qubit vật lý i), các slot còn lại (5..15) luôn
# rỗng. save_circuit() gốc của quills (util/circuits.py, commit bad7cd7) CẮT
# GỌN lại đúng bằng cách này — thiếu bước này sẽ ra file "qreg q[16]" thay vì
# "qreg q[5]" (đã tự phát hiện qua so sánh byte-for-byte với file ground-truth
# thật lấy từ git history).
def _trim_to_logical_qubits(circuit: QuantumCircuit, num_qubits: int) -> QuantumCircuit:
    register = QuantumRegister(num_qubits, "q")
    output_circuit = QuantumCircuit(register)
    for instr in circuit.data:
        new_instr = instr.replace(
            qubits=[Qubit(register, q._index) for q in instr.qubits]
        )
        output_circuit.append(new_instr)
    return output_circuit

def transpile_for_quills(qasm_path: str, platform: str) -> str:
    if platform not in _FAKE_BACKEND_NAMES:
        raise ValueError(f"Platform '{platform}' chưa hỗ trợ. Có: {list(_FAKE_BACKEND_NAMES)}")

    backend_cls = _get_fake_backend_class(platform)
    backend = backend_cls()
    n_qubits = (
        backend.configuration().n_qubits
        if hasattr(backend, "configuration")
        else backend.num_qubits
    )

    full_connectivity = [
        [p1, p2] for p1 in range(n_qubits) for p2 in range(n_qubits) if p1 != p2
    ]

    input_circuit = QuantumCircuit.from_qasm_file(qasm_path)
    transpiled = transpile(input_circuit, backend=backend, coupling_map=full_connectivity)
    trimmed = _trim_to_logical_qubits(transpiled, input_circuit.num_qubits)

    return _circuit_to_qasm(trimmed)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="File .qasm, hoặc thư mục nếu dùng --batch")
    p.add_argument("platform", choices=list(_FAKE_BACKEND_NAMES), help="Platform đích")
    p.add_argument("-o", "--output", required=True,
                    help="File .qasm đích (single mode), hoặc thư mục đích (--batch)")
    p.add_argument("--batch", action="store_true",
                    help="Coi 'input' là thư mục, transpile TẤT CẢ file .qasm bên trong "
                         "(giữ nguyên tên file, ghi vào thư mục --output)")
    args = p.parse_args()

    if args.batch:
        in_dir = Path(args.input)
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        qasm_files = sorted(in_dir.glob("*.qasm"))
        if not qasm_files:
            print(f"Không tìm thấy file .qasm nào trong {in_dir}", file=sys.stderr)
            sys.exit(1)
        for i, f in enumerate(qasm_files, 1):
            print(f"[{i}/{len(qasm_files)}] {f.name} ...", flush=True)
            try:
                qasm_out = transpile_for_quills(str(f), args.platform)
                (out_dir / f.name).write_text(qasm_out)
            except Exception as e:
                print(f"  LỖI khi transpile {f.name}: {e}", file=sys.stderr)
        print(f"Xong. Đã ghi vào: {out_dir}")
    else:
        qasm_out = transpile_for_quills(args.input, args.platform)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(qasm_out)
        print(f"Đã ghi: {out_path}")


if __name__ == "__main__":
    main()
