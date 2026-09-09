# Symmetry Breaking Predicates (SBP) cho exact depth-optimal QLS.
#
# Ý tưởng & chứng minh: xem tài liệu methodology "CDCL-Compatible Symmetry
# Breaking" — tóm tắt lại đây:
#
#   - P_core (miền cơ bản): 1 đại diện / orbit của coupling graph dưới
#     Aut(G_H) (xem encoding/symmetry.py). TẦNG 1 ép q_max (qubit LOGIC
#     bậc cao nhất — nhiều tương tác CX nhất) chỉ được đặt vào P_core tại
#     t=1 (bước mapping đầu tiên).
#         Eq(1):  ⋀_{p ∉ P_core} ¬mp^1_{q_max,p}
#
#   - P_stab(p') (transversal dưới nhóm ổn định của p'): sau khi q_max neo
#     vào 1 đại diện cụ thể p' ∈ P_core, TẦNG 2 ép q_next (qubit logic kề
#     q_max, bậc cao nhất — có fallback nếu q_max cô lập) chỉ được đặt vào
#     P_stab(p').
#         Eq(2):  ⋀_{p'∈P_core} ( mp^1_{q_max,p'} => ⋀_{p∉P_stab(p')} ¬mp^1_{q_next,p} )
#
#   - Theorem 1 (chứng minh trong tài liệu methodology): 2 ràng buộc trên
#     KHÔNG loại bỏ nghiệm tối ưu toàn cục nào — nếu có nghiệm tối ưu L ở
#     đâu đó, luôn "xoay" được L (bằng 1 tự đẳng cấu của G_H, áp lên MỌI
#     biến mp/sw ở MỌI bước thời gian) thành 1 nghiệm L'' vẫn tối ưu và
#     thoả cả Eq(1), Eq(2).
#
# LƯU Ý QUAN TRỌNG: các clause ở đây chỉ nói về mapping tại t=1 (initial
# mapping) — không lặp lại theo từng bước thời gian như Mapping/Connectivity
# Constraints. Vì vậy toàn bộ SBP được thêm ĐÚNG 1 LẦN trong init_static(),
# giống cách GateConstraints (constraint 7) và SwapConstraints (constraint
# 15) thêm clause tĩnh của riêng chúng — encode(t) ở đây là no-op.

from __future__ import annotations

import logging
from typing import Optional, Set

from circuit.gate import GateType
from encoding.base import ConstraintGroup
from encoding.symmetry import SymmetryModel

log = logging.getLogger(__name__)

# Bước thời gian của "initial mapping" trong encoding này (VarPool.mp dùng
# t bắt đầu từ 1, xem solver/engine.py: t = 1 ở đầu vòng lặp _run_lb/_run_ub).
_ANCHOR_T = 1


class SymmetryBreakingConstraints(ConstraintGroup):
    """Tầng 1 (orbit transversal anchoring) + Tầng 2 (stabilizer breaking).

    Không ghi đè `encode(t)` với logic thật — mọi clause đều tĩnh (không
    phụ thuộc t) nên nằm hết trong `init_static()`.
    """

    def __init__(self, cnf, pool, circuit, topology) -> None:
        super().__init__(cnf, pool, circuit, topology)
        self._sym: Optional[SymmetryModel] = None

    def encode(self, t: int) -> None:  # SBP không lặp theo t — không dùng
        pass

    def init_static(self) -> None:
        self._sym = SymmetryModel.build(self.topology)

        q_max = self._highest_degree_qubit()
        if q_max is None:
            log.debug("SBP: mạch không có qubit logic nào — bỏ qua.")
            return

        p_core = self._sym.fundamental_domain()
        self._add_level1(q_max, p_core)
        log.debug(
            "SBP Tầng 1: q_max=q%d bị neo vào P_core=%s (|P_core|=%d/%d)",
            q_max, p_core, len(p_core), self.topology.n_qubits,
        )

        q_next = self._highest_degree_neighbor(q_max)
        if q_next is None:
            log.debug(
                "SBP: q_max=q%d không có ứng viên q_next nào (mạch chỉ có "
                "1 qubit logic) — chỉ áp Tầng 1.", q_max,
            )
            return

        self._add_level2(q_max, q_next, p_core)
        log.debug("SBP Tầng 2: q_next=q%d bị neo theo stabilizer của từng p' trong P_core", q_next)

    # ---- chọn q_max / q_next (dựa trên bậc tương tác CX trong mạch) -------

    def _interaction_degree(self) -> dict[int, int]:
        """Bậc tương tác (số cổng CX) của mỗi qubit logic."""
        degree: dict[int, int] = {q: 0 for q in range(self.circuit.n_qubits)}
        for gate in self.circuit.gates:
            if gate.gate_type == GateType.CX:
                degree[gate.control_qubit] += 1
                degree[gate.target_qubit] += 1
        return degree

    def _highest_degree_qubit(self) -> Optional[int]:
        if self.circuit.n_qubits == 0:
            return None
        degree = self._interaction_degree()
        # max() trên dict theo key -> cần key ổn định (thứ tự q=0,1,2,...)
        # để deterministic khi có nhiều qubit đồng bậc cao nhất.
        return max(sorted(degree), key=lambda q: degree[q])

    def _highest_degree_neighbor(self, q_max: int) -> Optional[int]:
        """q_next = qubit kề q_max (chung >=1 cổng CX) có bậc cao nhất.

        Trường hợp biên (fallback, xem tài liệu methodology): nếu q_max
        không có hàng xóm CX nào (cô lập, hoặc mạch chỉ có unary gate trên
        q_max), chọn q_next là qubit có bậc cao THỨ HAI trên toàn mạch.
        """
        degree = self._interaction_degree()

        neighbors: Set[int] = set()
        for gate in self.circuit.gates:
            if gate.gate_type == GateType.CX and q_max in gate.qubits:
                neighbors.update(q for q in gate.qubits if q != q_max)

        if neighbors:
            return max(sorted(neighbors), key=lambda q: degree[q])

        # Fallback: bậc cao thứ hai toàn mạch (khác q_max)
        candidates = [q for q in degree if q != q_max]
        if not candidates:
            return None
        return max(sorted(candidates), key=lambda q: degree[q])

    # ---- Tầng 1: Eq(1) ------------------------------------------------------

    def _add_level1(self, q_max: int, p_core: list[int]) -> None:
        core_set = set(p_core)
        for p in self._physicals:
            if p not in core_set:
                # ¬mp^1_{q_max, p}  — unit clause
                self.cnf.append([-self.pool.mp(q_max, p, _ANCHOR_T)])

    # ---- Tầng 2: Eq(2) ------------------------------------------------------

    def _add_level2(self, q_max: int, q_next: int, p_core: list[int]) -> None:
        for p_anchor in p_core:
            stab = set(self._sym.stabilizer_transversal(p_anchor))
            mp_anchor = self.pool.mp(q_max, p_anchor, _ANCHOR_T)
            for p in self._physicals:
                if p == p_anchor or p in stab:
                    continue
                # mp^1_{q_max,p_anchor} => ¬mp^1_{q_next,p}
                #   <=>  (-mp_anchor) ∨ (-mp^1_{q_next,p})
                self.cnf.append([-mp_anchor, -self.pool.mp(q_next, p, _ANCHOR_T)])

    @property
    def _physicals(self) -> range:
        return range(self.topology.n_qubits)
