from encoding.base import ConstraintGroup
from encoding.helpers import *
from circuit.gate import *
from circuit.parser import *


class ConnectivityConstraints(ConstraintGroup):
    """
    Constraint (4) viết lại: O(|I| * |P|) mệnh đề thay vì O(|Q|^2 * |P|^2),
    với |I| = số cặp qubit logic thực sự xuất hiện chung trong một cổng CX.

    Tương đương logic (không phải xấp xỉ): vế "không kết nối ⇒ ¬e" của bản
    gốc được viết lại bằng phản đảo + constraint (1) (ExactlyOne trên mp theo
    p, mỗi q): "mọi p' ngoài conn(p) đều false" ⟺ "p' đúng phải nằm trong
    conn(p)". Vế "kết nối ⇒ e" (chiều soundness) giữ nguyên, không được bỏ.
    """

    @property
    def _gates(self) -> list[Gate]:
        return self.circuit.gates

    def encode(self, t: int) -> None:
        self._constraint_4(t)
        self._constraint_5(t)

    # cache các cặp (q, q1) thực sự xuất hiện cùng nhau trong 1 cổng CX
    # -> không cần định nghĩa e_lit / constraint (4) cho các cặp không liên quan
    @property
    def _cx_pairs(self) -> set[tuple[int, int]]:
        if not hasattr(self, "_cx_pairs_cache"):
            pairs = set()
            for gate in self.circuit.gates:
                if gate.is_cx:
                    q, q1 = gate.control_qubit, gate.target_qubit
                    pairs.add((min(q, q1), max(q, q1)))
            self._cx_pairs_cache = pairs
        return self._cx_pairs_cache

    # danh sách hàng xóm mỗi qubit vật lý — không đổi giữa các t, tính 1 lần
    @property
    def _neighbors(self) -> list[list[int]]:
        if not hasattr(self, "_neighbors_cache"):
            edges_set = self.topology.edge_set
            n_phys = self.topology.n_qubits
            self._neighbors_cache = [
                [p1 for p1 in range(n_phys) if p1 != p and tuple(sorted((p, p1))) in edges_set]
                for p in range(n_phys)
            ]
        return self._neighbors_cache

    # (4')
    def _constraint_4(self, t: int) -> None:
        n_phys = self.topology.n_qubits
        neighbors = self._neighbors
        edges_set = self.topology.edge_set

        for (q, q1) in self._cx_pairs:
            e_lit = self.pool.e(q, q1, t)

            # vế "không kết nối ⇒ ¬e", viết lại gọn theo constraint (1)
            for p in range(n_phys):
                mp_q_p = self.pool.mp(q, p, t)
                conn_p = neighbors[p]
                # e_lit ∧ mp_q_p ⇒ OR_{p1 ∈ conn(p)} mp_{q1,p1}
                clause = [-e_lit, -mp_q_p] + [self.pool.mp(q1, p1, t) for p1 in conn_p]
                self.cnf.append(clause)

            # vế "kết nối ⇒ e" — giữ nguyên, bắt buộc cho soundness
            for (p, p1) in edges_set:
                and_implies(self.cnf, [self.pool.mp(q, p, t), self.pool.mp(q1, p1, t)], e_lit)
                and_implies(self.cnf, [self.pool.mp(q, p1, t), self.pool.mp(q1, p, t)], e_lit)

    # (5) không đổi
    def _constraint_5(self, t: int) -> None:
        for gate in self.circuit.gates:
            if gate.is_cx:
                c_lit = self.pool.c(gate.gate_id, t)
                e_lit = self.pool.e(gate.control_qubit, gate.target_qubit, t)
                implies(self.cnf, c_lit, e_lit)
