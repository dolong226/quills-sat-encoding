from encoding.base import ConstraintGroup
from encoding.helpers import *
from circuit.gate import GateType
from circuit.dag import DAG


class GateConstraints(ConstraintGroup):
    """
    x(g, t) := "cổng g đã hoàn thành tính đến hết thời điểm t", đơn điệu.
        a^t_g == x(g, t-1)      d^t_g == ¬x(g, t)
    c(g,t) vẫn là biến SAT thật (ConnectivityConstraints._constraint_5 và
    _constraint_11_12 dưới đây đọc trực tiếp pool.c), nhưng định nghĩa qua
    Tseitin từ x thay vì qua ExactlyOne 3 nhánh + biconditional chain.

    Constraint 6, 7, 9 (bản gốc) KHÔNG còn được encode tường minh — chúng tự
    động đúng khi có tính đơn điệu của x + định nghĩa c ở trên (chứng minh
    đại số: xem tài liệu optimizations.tex, mục 4).

    Constraint 8: chỉ duyệt successors(g), bỏ predecessors(g) — hai vòng lặp
    gốc sinh trùng lặp cùng một mệnh đề nhìn từ hai đầu một cạnh.

    Constraint 10: chỉ duyệt full_successors(g), bỏ full_predecessors(g) —
    cùng lý do dedup (quan hệ comparable trên DAG là đối xứng).

    CẢNH BÁO: nếu có module khác đọc self.pool.a(...) / self.pool.d(...)
    trực tiếp (vd. bước trích xuất lời giải sau khi solve), nó sẽ đọc một
    biến KHÔNG bị ràng buộc bởi mệnh đề nào — không lỗi cú pháp nhưng sai
    ngữ nghĩa âm thầm. Grep toàn repo tìm "pool.a(" / "pool.d(" trước khi
    dùng bản này. self.pool.c(...) vẫn an toàn để dùng ở bất kỳ đâu.
    """

    def __init__(self, cnf, pool, circuit, topology, dag: DAG) -> None:
        super().__init__(cnf, pool, circuit, topology)
        self._dag = dag

    # Biên: chưa gì hoàn thành trước khi mạch bắt đầu (thay constraint 7 cũ)
    def init_static(self) -> None:
        for gate in self.circuit.gates:
            self.cnf.append([-self.pool.x(gate.gate_id, 0)])

    def encode(self, t: int) -> None:
        self._constraint_monotone(t)
        self._define_c(t)
        self._constraint_8(t)
        self._constraint_10(t)
        self._constraint_11_12(t)

    # x(g, t-1) ⇒ x(g, t)
    def _constraint_monotone(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            implies(self.cnf, self.pool.x(g, t - 1), self.pool.x(g, t))

    # c(g,t) ⇔ x(g,t) ∧ ¬x(g,t-1)
    def _define_c(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            c_g = self.pool.c(g, t)
            x_t = self.pool.x(g, t)
            x_prev = self.pool.x(g, t - 1)
            self.cnf.append([-c_g, x_t])           # c ⇒ x(t)
            self.cnf.append([-c_g, -x_prev])       # c ⇒ ¬x(t-1)
            self.cnf.append([c_g, -x_t, x_prev])   # x(t) ∧ ¬x(t-1) ⇒ c

    # x(g2, t) ⇒ x(g, t-1), chỉ duyệt successors(g) (thay cho constraint 8 cũ)
    def _constraint_8(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            x_g_prev = self.pool.x(g, t - 1)
            for g2 in self._dag.successors(g):
                implies(self.cnf, self.pool.x(g2, t), x_g_prev)

    # redundant clause (giữ chủ đích để tăng tốc BCP, đúng tinh thần gốc),
    # chỉ duyệt full_successors(g) để khử trùng lặp cặp
    def _constraint_10(self, t: int) -> None:
        for gate in self.circuit.gates:
            g = gate.gate_id
            c_g = self.pool.c(g, t)
            for g2 in self._dag.full_successors(g):
                c_g2 = self.pool.c(g2, t)
                implies(self.cnf, c_g, -c_g2)

    def _constraint_11_12(self, t: int) -> None:
        n_phys = self.topology.n_qubits
        for gate in self.circuit.gates:
            g = gate.gate_id
            c_g = self.pool.c(g, t)
            for p in range(n_phys):
                u_p = self.pool.u(p, t)
                for q in gate.qubits:
                    mp_qp = self.pool.mp(q, p, t)
                    and_implies(self.cnf, [c_g, mp_qp], u_p)
