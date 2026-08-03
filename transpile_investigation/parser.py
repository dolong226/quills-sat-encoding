# Parse file .qasm -> gate + qubit
import re
from dataclasses import dataclass, field

from circuit.gate import Gate, GateType

# Circuit Representation
@dataclass
class Circuit:
    n_qubits: int
    gates: list[Gate] = field(default_factory=list)

    def __str__(self):
        return f"Circuit(qubits={self.n_qubits}, gates={len(self.gates)})"
    

# Supported Gate Sets
# QUAN TRỌNG: "sx" (√X, sqrt-X) là 1 trong các gate NATIVE của basis IBM
# ['id','rz','sx','x','cx','reset'] — nếu thiếu, mạch đã transpile (theo đúng
# quy trình của tác giả gốc, xem transpile_for_quills.py) sẽ bị ÂM THẦM MẤT
# phần lớn gate (thực tế đo được: 29/48 gate của vqe_8_1_5_100.qasm sau
# transpile là "sx" — thiếu "sx" nghĩa là mất ~60% mạch mà không có lỗi nào
# được báo ra). "id" (identity, gate rỗng) và "reset" cũng thuộc basis này —
# "id" đã có sẵn ở đây, "reset" được xử lý riêng bên dưới (bỏ qua, giống
# creg/measure/barrier, vì reset không cần lịch trình hoá trong mô hình depth).
_UNARY_GATES = {"u", "h", "s", "x", "y", "z", "t", "tdg", "rx", "ry", "rz", "u1", "u2", "u3", "id", "sx", "sxdg"}

_QUBIT_RE = re.compile(r"\w+\[(\d+)\]")

# Main Parser
def parse_qasm(path: str) -> Circuit:
    n_qubits = 0
    gates: list[Gate] = []
    gate_id = 0

    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("//"):
                continue
            if line.startswith("OPENQASM") or line.startswith("include"):
                continue

            # parser qreg
            if line.startswith("qreg"):
                m = re.search(r"\[(\d+)\]", line)

                if m:
                    n_qubits += int(m.group(1))

                continue

            # Ignore classical operations / operations không cần lịch trình hoá
            # ("reset" thuộc basis IBM native ['id','rz','sx','x','cx','reset']
            # — có thể xuất hiện trong mạch đã transpile)
            if line.startswith(("creg", "measure", "barrier", "reset")):
                continue

            # Parser gate instruction
            line = line.rstrip(";")

            parts = line.split(None, 1)
            if not parts:
                continue

            op = parts[0].lower().split("(")[0]

            args_str = parts[1] if len(parts) > 1 else ""

            # Extract qubit indices (q[1], q[3] -> [1,3])
            qubit_str = args_str.split(")")[-1] if ")" in args_str else args_str
            qubit_indices = [int(m) for m in _QUBIT_RE.findall(args_str)]


            # CX gate
            if op == "cx":
                if len(qubit_indices) < 2:
                    continue

                g = Gate(gate_id=gate_id, name="cx", gate_type=GateType.CX, qubits=(qubit_indices[0], qubit_indices[1]))
                gates.append(g)
                gate_id += 1

            # UNARY gate
            elif op in _UNARY_GATES:
                if len(qubit_indices) < 1:
                    continue

                g = Gate(gate_id=gate_id, name=op, gate_type=GateType.UNARY, qubits = (qubit_indices[0],))
                gates.append(g)
                gate_id += 1
            
            

    
    return Circuit(n_qubits=n_qubits, gates=gates)

                     
            