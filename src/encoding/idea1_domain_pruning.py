# Idea 1 — Domain pruning: distance cuts, arc consistency, symmetry anchor.
#
# Cài đặt bám sát quills_improvements_theory.tex (mục "Idea 1"). Thứ tự ưu
# tiên đúng như kết luận của tài liệu (mục "Kết luận hiện tại về Idea 1"):
#
#   (1) symmetry anchor an toàn                -> _build_symmetry_anchor()
#   (2) deadline-aware relational cuts         -> _deadline_relational_cuts()
#   (3) arc-consistency closure                -> _arc_consistency()
#   (4) selector theo horizon (guard)          -> mọi cut phụ thuộc H được
#                                                  guard bởi CHÍNH biến
#                                                  asm(H) đã có sẵn của
#                                                  QuilLS (encoding/
#                                                  assumptions.py) — không
#                                                  cần định nghĩa selector
#                                                  z_H riêng, vì asm(H) của
#                                                  engine hiện tại ĐÃ đóng
#                                                  đúng vai trò đó (asm(t)
#                                                  = "t là layer cuối", tức
#                                                  chính là H trong lý
#                                                  thuyết).
#
# QUAN TRỌNG — module này CHỈ THÊM CLAUSE (được guard bởi asm(H)), không bao
# giờ xoá biến mp/d nào đã tồn tại. Theo mục "Clause pruning và variable
# elimination là hai việc khác nhau" của tài liệu, đây là chế độ
# "incremental relational cuts", KHÔNG phải "non-incremental variable
# elimination" (việc đó cần rebuild instance riêng theo miền đã prune, chưa
# làm ở bản này).
#
# Vì mọi cut phụ thuộc H (deadline cuts, unary domain cuts từ arc
# consistency) được guard bởi asm(H), corollary "Bảo toàn độ sâu tối ưu"
# (mục 3) và Định lý "Tính đúng của incremental guarded cuts" (mục 8.1) cho
# phép gọi encode_for_horizon(H, asm_lit) nhiều lần, với H tăng dần, mà
# không phá vỡ tính khả thỏa tương đương với F_H gốc ở bất kỳ H nào đã thử.

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

try:
    import networkx as nx
except ImportError:  # pragma: no cover — an toàn nếu môi trường thiếu networkx
    nx = None

from encoding.base import ConstraintGroup
from circuit.dag import DAG

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Distance oracle: BFS all-pairs một lần cho coupling graph, cache các quả
# cầu Ball(p, B) đã dùng. Dùng lại cho MỌI horizon (không đổi theo H).
# ---------------------------------------------------------------------------
class _DistanceOracle:
    def __init__(self, topology) -> None:
        n = topology.n_qubits
        INF = float("inf")
        dist: List[List[float]] = [[INF] * n for _ in range(n)]

        for src in range(n):
            dist[src][src] = 0
            dq = deque([src])
            while dq:
                u = dq.popleft()
                for v in topology.neighbors(u):
                    if dist[src][v] == INF:
                        dist[src][v] = dist[src][u] + 1
                        dq.append(v)

        self._dist = dist
        finite = [d for row in dist for d in row if d != INF]
        self.diameter = int(max(finite)) if finite else 0
        self._ball_cache: Dict[Tuple[int, int], Tuple[int, ...]] = {}

    def dist(self, p: int, p2: int) -> float:
        return self._dist[p][p2]

    def ball(self, p: int, radius: int) -> Tuple[int, ...]:
        """{ x : dist(p,x) <= radius }. radius < 0 -> rỗng (Ball(p,B)=∅)."""
        if radius < 0:
            return ()
        key = (p, radius)
        cached = self._ball_cache.get(key)
        if cached is not None:
            return cached
        row = self._dist[p]
        out = tuple(x for x, d in enumerate(row) if d <= radius)
        self._ball_cache[key] = out
        return out


# ---------------------------------------------------------------------------
# Gate window: R(g) = số đỉnh trên suffix path dài nhất bắt đầu ở g, dùng để
# tính L_H(g) = H - R(g) + 1 (eq:idea2-latest — hệ quả trực tiếp của
# recurrence gốc L_H(g)=min_{h∈Succ(g)}L_H(h)-1 dùng trong Idea 1 mục 4.2).
# R(g) KHÔNG phụ thuộc horizon, tính một lần.
# ---------------------------------------------------------------------------
class _GateWindow:
    def __init__(self, dag: DAG, gate_ids: List[int]) -> None:
        self._dag = dag
        self._suffix_len: Dict[int, int] = {}
        for g in gate_ids:
            self._compute(g)

    def _compute(self, g: int) -> int:
        if g in self._suffix_len:
            return self._suffix_len[g]
        succs = self._dag.successors(g)
        depth = 1 + (max((self._compute(s) for s in succs), default=0))
        self._suffix_len[g] = depth
        return depth

    def R(self, g: int) -> int:
        return self._suffix_len[g]

    def latest(self, g: int, H: int) -> int:
        # L_H(g) = H - R(g) + 1
        return H - self._suffix_len[g] + 1


# ---------------------------------------------------------------------------
# rho(t,s) = max(0, floor((s-t+1)/3))     (eq:rho, dạng sàn tương đương)
# B_{g,t,H} = 1 + 2*rho(t, L_H(g))        (eq:deadline-radius)
# ---------------------------------------------------------------------------
def rho(t: int, s: int) -> int:
    if s <= t:
        return 0
    return max(0, (s - t + 1) // 3)


def deadline_radius(t: int, L: int) -> int:
    return 1 + 2 * rho(t, L)


# ---------------------------------------------------------------------------
# Symmetry anchor: automorphism của coupling graph VÔ HƯỚNG TRẦN. Topology
# hiện tại không có hướng/trọng số/nhãn lỗi, nên automorphism thô là hợp lệ
# (mục 7.3: "nếu phần cứng có hướng/trọng số/lỗi/cấm cạnh, Γ phải bảo toàn
# TOÀN BỘ nhãn đó" — ở đây không có nhãn nào khác ngoài đồ thị).
#
# CHỈ cần đủ automorphism để gộp các đỉnh cùng orbit vào union-find — không
# cần liệt kê toàn bộ nhóm Γ. An toàn vì mỗi lần gộp (p, φ(p)) đều đến từ
# một φ CÓ THẬT đã được networkx xác nhận là automorphism; thiếu vài φ chỉ
# làm orbit tính được COARSER hơn (ít gộp hơn) chứ không bao giờ gộp SAI.
# ---------------------------------------------------------------------------
def _orbit_representatives(topology, max_automorphisms: int = 2000) -> List[int]:
    n = topology.n_qubits
    if n <= 1 or nx is None:
        return list(range(n))

    G = nx.Graph()
    G.add_nodes_from(range(n))
    G.add_edges_from(topology.edge_set)

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    try:
        matcher = nx.algorithms.isomorphism.GraphMatcher(G, G)
        count = 0
        for mapping in matcher.isomorphisms_iter():
            for src, dst in mapping.items():
                union(src, dst)
            count += 1
            if count >= max_automorphisms:
                break
    except Exception as exc:  # pragma: no cover — không để lỗi automorphism chặn pipeline
        log.warning(
            "Idea1 symmetry anchor: tìm automorphism thất bại (%s) — bỏ qua anchor.",
            exc,
        )
        return list(range(n))

    reps: Dict[int, int] = {}
    order: List[int] = []
    for v in range(n):
        r = find(v)
        if r not in reps:
            reps[r] = v
            order.append(v)
    return order


# ---------------------------------------------------------------------------
# Main constraint group
# ---------------------------------------------------------------------------
class DomainPruningConstraints(ConstraintGroup):
    """Idea 1: distance cuts + arc consistency + symmetry anchor.

    Cách dùng (xem solver/engine.py):

        dp = DomainPruningConstraints(cnf, pool, circuit, topology, dag)
        dp.init_static()                     # 1 lần, không phụ thuộc horizon
        ...
        dp.encode_for_horizon(H, asm_lit)    # mỗi khi có một candidate
                                              # horizon H mới cần test;
                                              # asm_lit PHẢI là đúng biến
                                              # asm(H) đã tồn tại từ
                                              # encoding/assumptions.py cho
                                              # horizon này.
    """

    def __init__(
        self,
        cnf,
        pool,
        circuit,
        topology,
        dag: DAG,
        anchor_qubit: Optional[int] = None,
        max_automorphisms: int = 2000,
        max_relational_clauses: int = 200_000,
    ) -> None:
        super().__init__(cnf, pool, circuit, topology)
        self._dag = dag
        self._dist = _DistanceOracle(topology)
        gate_ids = [g.gate_id for g in circuit.gates]
        self._window = _GateWindow(dag, gate_ids)
        self._cx_gates = [g for g in circuit.gates if g.is_cx]
        self._anchor_qubit = anchor_qubit
        self._max_automorphisms = max_automorphisms
        self._anchor_domain: Optional[Tuple[int, ...]] = None  # R tại t=1
        self._horizons_done: Set[int] = set()

        # An toàn để tránh clause blow-up trên circuit/topology lớn: bỏ cut
        # KHÔNG BAO GIỜ làm sai (Định lý domain pruning chỉ cần over-
        # approximation, không cần TOÀN BỘ cut khả dĩ) — chỉ làm pruning
        # yếu đi. Ngân sách tính TOÀN CỤC qua mọi horizon đã gọi
        # encode_for_horizon(), không phải mỗi lần gọi.
        self._relational_budget = max_relational_clauses
        self._relational_budget_hit = False

        # Instrumentation nhẹ — không ảnh hưởng logic, chỉ để so sánh với
        # baseline khi benchmark thực nghiệm sau này.
        self.stats: Dict[str, int] = {"anchor": 0, "relational": 0, "unary": 0}

    # ConstraintGroup là ABC yêu cầu encode(t); module này không dùng lược
    # đồ "mỗi t một lần" như mapping/gates/swap — mọi việc được lái qua
    # encode_for_horizon() (mỗi candidate horizon một lần), vì các đại
    # lượng cốt lõi (L_H(g), B_{g,t,H}) phụ thuộc H chứ không phải riêng t.
    def encode(self, t: int) -> None:
        pass

    # (1) symmetry anchor — thêm đúng 1 lần, KHÔNG guard vì valid ở MỌI
    #     horizon (Định lý "Neo đối xứng bảo toàn khả thỏa", mục 7.3).
    def init_static(self) -> None:
        self._build_symmetry_anchor()

    def _build_symmetry_anchor(self) -> None:
        if not self._cx_gates:
            return  # không có CX -> anchor không giúp lan truyền gì, bỏ qua

        if self._anchor_qubit is None:
            # Định lý không đòi hỏi q0 đặc biệt — chọn logical qubit "bận"
            # nhất (tham gia nhiều CX nhất) chỉ để tối đa hoá lợi ích lan
            # truyền domain ở bước arc-consistency phía sau.
            usage: Dict[int, int] = {}
            for g in self._cx_gates:
                for q in g.qubits:
                    usage[q] = usage.get(q, 0) + 1
            self._anchor_qubit = max(usage, key=usage.get)

        reps = _orbit_representatives(self.topology, self._max_automorphisms)
        n_phys = self.topology.n_qubits
        if len(reps) >= n_phys:
            # Không automorphism không tầm thường nào được xác nhận -> R =
            # toàn bộ Pset -> anchor vô nghĩa, bỏ qua để khỏi thêm clause vô ích.
            self._anchor_domain = None
            return

        q0 = self._anchor_qubit
        lits = [self.pool.mp(q0, p, 1) for p in reps]
        self.cnf.append(lits)  # eq:symmetry-anchor
        self.stats["anchor"] += 1
        self._anchor_domain = tuple(reps)

    # (2)+(3)+(4): relational cuts + arc consistency, guarded bởi asm_lit
    # của horizon H. Idempotent theo H (an toàn nếu lỡ gọi lại cùng H).
    def encode_for_horizon(self, H: int, asm_lit: int) -> None:
        if H in self._horizons_done:
            return
        self._horizons_done.add(H)

        if not self._cx_gates or H < 1:
            return

        domains = self._initial_domains(H)
        self._arc_consistency(H, domains)
        self._deadline_relational_cuts(H, asm_lit, domains)
        self._emit_unary_domain_clauses(H, asm_lit, domains)

    # --- domain khởi tạo cho horizon H ---
    # Mọi (q,t): full physical set, TRỪ anchor qubit ở t=1 (nếu có anchor)
    # bị giới hạn về R, rồi lan truyền theo rho (tổng quát hoá công thức
    # eta(1,t) đặc thù mục 7.2 — dùng rho() chung cho mọi cặp layer thay vì
    # công thức eta riêng cho t0=1, vẫn là over-approximation an toàn vì
    # cùng cơ chế "mỗi lần đổi vị trí ứng với 1 SWAP kết thúc, hai lần kết
    # thúc liên tiếp cách nhau ít nhất 3 layer" — không phụ thuộc t0=1).
    def _initial_domains(self, H: int) -> Dict[Tuple[int, int], Set[int]]:
        n_phys = self.topology.n_qubits
        full = set(range(n_phys))
        domains: Dict[Tuple[int, int], Set[int]] = {}

        for q in range(self.circuit.n_qubits):
            if q == self._anchor_qubit and self._anchor_domain is not None:
                domains[(q, 1)] = set(self._anchor_domain)
            else:
                domains[(q, 1)] = set(full)

        if self._anchor_domain is not None:
            q0 = self._anchor_qubit
            for t in range(2, H + 1):
                r = rho(1, t)
                grown: Set[int] = set()
                for p in self._anchor_domain:
                    grown.update(self._dist.ball(p, r))
                domains[(q0, t)] = grown

        for q in range(self.circuit.n_qubits):
            for t in range(2, H + 1):
                domains.setdefault((q, t), set(full))

        return domains

    # --- (3) arc consistency (REVISE tới fixed point) dùng distance
    #     relation của mọi CX gate còn có thể pending tại layer t. ---
    def _arc_consistency(self, H: int, domains: Dict[Tuple[int, int], Set[int]]) -> None:
        relations: List[Tuple[int, int, int, int]] = []
        for gate in self._cx_gates:
            g = gate.gate_id
            q, r = gate.control_qubit, gate.target_qubit
            L = self._window.latest(g, H)
            if L < 1:
                continue  # horizon quá nhỏ cho gate này — sẽ bị phát hiện
                          # UNSAT qua cơ chế assumption chuẩn, bỏ qua ở đây
            for t in range(1, min(H, L)):
                B = deadline_radius(t, L)
                relations.append((t, q, r, B))

        if not relations:
            return

        changed = True
        guard = 0
        max_iters = 4 * (len(relations) + 1) * max(1, self.topology.n_qubits)
        while changed and guard < max_iters:
            changed = False
            guard += 1
            for (t, q, r, B) in relations:
                Dq = domains[(q, t)]
                Dr = domains[(r, t)]
                if not Dq or not Dr:
                    continue

                new_Dq = {p for p in Dq if any(p2 in Dr for p2 in self._dist.ball(p, B))}
                if new_Dq != Dq:
                    domains[(q, t)] = new_Dq
                    changed = True

                Dr_now = domains[(r, t)]
                Dq_now = domains[(q, t)]
                new_Dr = {
                    p2 for p2 in Dr_now
                    if any(p in Dq_now for p in self._dist.ball(p2, B))
                }
                if new_Dr != Dr_now:
                    domains[(r, t)] = new_Dr
                    changed = True

    # --- (2) deadline-aware relational cuts (eq:deadline-cut / eq:support-
    #     clause), guarded. Dùng domain ĐÃ được arc-consistency thu hẹp để
    #     giảm số cặp phải xét (không ảnh hưởng tính đúng — chỉ hiệu năng).
    #
    #     Mục 8 của tài liệu: "Không có encoding nào luôn tốt hơn" — chọn
    #     forbidden-pair clauses (eq:deadline-cut) khi số cặp bị cấm nhỏ
    #     hơn số cặp còn hợp lệ, ngược lại dùng support clauses
    #     (eq:support-clause, gọn hơn khi số cặp bị cấm gần |Pset|^2).
    def _deadline_relational_cuts(
        self, H: int, asm_lit: int, domains: Dict[Tuple[int, int], Set[int]]
    ) -> None:
        if self._relational_budget_hit:
            return

        n_phys = self.topology.n_qubits
        full_range = range(n_phys)

        for gate in self._cx_gates:
            if self._relational_budget_hit:
                break
            g = gate.gate_id
            q, r = gate.control_qubit, gate.target_qubit
            L = self._window.latest(g, H)
            if L < 1:
                continue

            for t in range(1, min(H, L)):
                if self._relational_budget_hit:
                    break
                B = deadline_radius(t, L)
                if B >= self._dist.diameter:
                    continue  # mục 8: bỏ cut nếu B lớn hơn đường kính — vô ích

                d_g_t = self.pool.d(g, t)
                Dq = domains.get((q, t), full_range)
                Dr = domains.get((r, t), full_range)
                if not Dq or not Dr:
                    continue

                # support[p] = các p' trong Dr mà (p,p') còn hợp lệ theo distance bound
                support: Dict[int, List[int]] = {}
                n_forbidden = 0
                for p in Dq:
                    ball_p = set(self._dist.ball(p, B))
                    ok = [p2 for p2 in Dr if p2 in ball_p]
                    support[p] = ok
                    n_forbidden += len(Dr) - len(ok)

                if n_forbidden == 0:
                    continue

                total_pairs = len(Dq) * len(Dr)
                use_forbidden_pairs = n_forbidden <= (total_pairs - n_forbidden)

                if use_forbidden_pairs:
                    for p in Dq:
                        ok_set = set(support[p])
                        for p2 in Dr:
                            if p2 in ok_set:
                                continue
                            self.cnf.append([
                                -asm_lit, -d_g_t,
                                -self.pool.mp(q, p, t), -self.pool.mp(r, p2, t),
                            ])
                            self.stats["relational"] += 1
                            self._relational_budget -= 1
                            if self._relational_budget <= 0:
                                self._on_relational_budget_hit()
                                return
                else:
                    for p in Dq:
                        ok = support[p]
                        if len(ok) == len(Dr):
                            continue  # mọi p' đều hợp lệ -> không cần cut cho p này
                        clause = [-asm_lit, -d_g_t, -self.pool.mp(q, p, t)]
                        clause += [self.pool.mp(r, p2, t) for p2 in ok]
                        self.cnf.append(clause)
                        self.stats["relational"] += 1
                        self._relational_budget -= 1
                        if self._relational_budget <= 0:
                            self._on_relational_budget_hit()
                            return

    def _on_relational_budget_hit(self) -> None:
        if not self._relational_budget_hit:
            self._relational_budget_hit = True
            log.info(
                "Idea1: đã đạt ngân sách relational-cut (%d clause) — dừng thêm "
                "forbidden-pair/support cuts mới (vẫn AN TOÀN, chỉ pruning yếu "
                "hơn; unary domain cuts từ arc-consistency vẫn tiếp tục).",
                self.stats["relational"],
            )

    # --- (4) unit clauses guarded bởi asm(H) cho mọi p đã bị arc
    #     consistency loại khỏi domain(q,t). ---
    def _emit_unary_domain_clauses(
        self, H: int, asm_lit: int, domains: Dict[Tuple[int, int], Set[int]]
    ) -> None:
        n_phys = self.topology.n_qubits
        full = set(range(n_phys))
        for (q, t), D in domains.items():
            if t < 1 or t > H:
                continue
            if D == full:
                continue
            for p in full - D:
                self.cnf.append([-asm_lit, -self.pool.mp(q, p, t)])
                self.stats["unary"] += 1
