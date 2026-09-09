# Tính tự đẳng cấu (automorphism), quỹ đạo (orbit) và miền cơ bản
# (fundamental domain) của coupling graph — dùng cho Symmetry Breaking
# Predicates (SBP) trong encoding/symmetry_breaking.py.
#
# Xem tài liệu methodology (Symmetry Breaking cho exact QLS) để có định
# nghĩa/chứng minh đầy đủ. Tóm tắt các khái niệm dùng ở đây:
#   - Aut(G_H): nhóm tự đẳng cấu của coupling graph.
#   - Quỹ đạo (orbit) của 1 đỉnh p: tập mọi đỉnh mà p có thể "biến thành"
#     qua một tự đẳng cấu.
#   - Miền cơ bản P_core: 1 đại diện / orbit — dùng cho SBP Tầng 1.
#   - Nhóm ổn định Gamma_p (stabilizer): các tự đẳng cấu giữ p đứng yên;
#     quỹ đạo dưới Gamma_p (của các đỉnh còn lại) dùng cho SBP Tầng 2.
#
# CHIẾN LƯỢC TÍNH: dùng networkx.algorithms.isomorphism.GraphMatcher để
# liệt kê TOÀN BỘ tự đẳng cấu của coupling graph (ánh xạ G vào chính nó).
# Với các hardware topology dùng trong benchmark của QuilLS (<=127 qubit,
# degree thấp 2-4, vd Guadalupe/Sycamore), |Aut(G)| thường chỉ vài chục
# phần tử nên liệt kê toàn bộ là khả thi trong vài giây.
#
# VAN AN TOÀN _MAX_AUTOMORPHISMS: nếu topology nào đó có nhóm đối xứng lớn
# bất thường, ta dừng liệt kê sớm. Dùng một tập con (không đầy đủ) các tự
# đẳng cấu để tính orbit vẫn AN TOÀN cho Định lý 1 (không làm SAI —
# orbit tính từ tập con luôn là orbit con của orbit thật, nên P_core tính
# ra có thể lớn hơn cần thiết -> SBP cắt tỉa ÍT HƠN, nhưng KHÔNG BAO GIỜ
# loại bỏ nghiệm tối ưu do lập luận Tầng 1/Tầng 2 chỉ cần "orbit dưới MỘT
# nhóm con nào đó của Aut(G)", không bắt buộc là toàn bộ Aut(G)).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence

import networkx as nx

from quills_platform.topology import Topology

_MAX_AUTOMORPHISMS = 20_000  # van an toàn, xem ghi chú ở đầu file

# Cache theo (n_qubits, edge_set) — tránh liệt kê lại automorphism mỗi khi
# SymmetryModel.build() được gọi trên CÙNG 1 topology (vd: _run_lb_cxdepth
# tạo sub_engine mới nhưng dùng lại đúng topology của engine cha; hoặc
# --repeats N chạy lại nhiều lần).
_MODEL_CACHE: Dict[tuple, "SymmetryModel"] = {}


def _build_networkx_graph(topology: Topology) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(topology.nodes)
    g.add_edges_from(topology.edge_set)
    return g


def _enumerate_automorphisms(g: nx.Graph) -> List[Dict[int, int]]:
    """Liệt kê tự đẳng cấu của g (ánh xạ g vào chính nó, bảo toàn cạnh).
    Luôn chứa ít nhất identity. Dừng sớm nếu vượt _MAX_AUTOMORPHISMS."""
    matcher = nx.algorithms.isomorphism.GraphMatcher(g, g)
    autos: List[Dict[int, int]] = []
    for mapping in matcher.isomorphisms_iter():
        autos.append(dict(mapping))
        if len(autos) >= _MAX_AUTOMORPHISMS:
            break
    return autos


def _orbits_from_automorphisms(
    nodes: Sequence[int], automorphisms: Sequence[Dict[int, int]]
) -> List[FrozenSet[int]]:
    """Union-Find: hai node cùng orbit nếu tồn tại 1 automorphism (trong
    danh sách đã cho) đưa node này thành node kia."""
    parent = {n: n for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for gamma in automorphisms:
        for u, v in gamma.items():
            if u in parent and v in parent:
                union(u, v)

    groups: Dict[int, list] = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)

    return [frozenset(members) for members in groups.values()]


@dataclass
class SymmetryModel:
    """Kết quả tính đối xứng của 1 coupling graph — chỉ phụ thuộc topology,
    KHÔNG phụ thuộc circuit, nên tính 1 lần là dùng lại được cho mọi mạch
    chạy trên cùng topology (xem SymmetryModel.build)."""

    topology: Topology
    automorphisms: List[Dict[int, int]] = field(default_factory=list)
    orbits: List[FrozenSet[int]] = field(default_factory=list)

    @classmethod
    def build(cls, topology: Topology) -> "SymmetryModel":
        key = (topology.n_qubits, frozenset(topology.edge_set))
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached

        g = _build_networkx_graph(topology)
        autos = _enumerate_automorphisms(g)
        orbits = _orbits_from_automorphisms(topology.nodes, autos)

        model = cls(topology=topology, automorphisms=autos, orbits=orbits)
        _MODEL_CACHE[key] = model
        return model

    # ---- Tầng 1: miền cơ bản (fundamental domain) --------------------------
    def fundamental_domain(self) -> List[int]:
        """P_core — 1 đại diện / orbit. Quy ước: chọn phần tử NHỎ NHẤT mỗi
        orbit để kết quả deterministic giữa các lần chạy (không phụ thuộc
        thứ tự liệt kê automorphism của networkx)."""
        return sorted(min(orbit) for orbit in self.orbits)

    # ---- Tầng 2: quỹ đạo dưới nhóm ổn định (stabilizer) --------------------
    def stabilizer_transversal(self, anchor: int) -> List[int]:
        """P_stab(anchor) — 1 đại diện / orbit của các đỉnh KHÁC anchor,
        dưới nhóm con Gamma_anchor = {gamma in Aut(G_H) | gamma(anchor) == anchor}."""
        stab_autos = [g for g in self.automorphisms if g.get(anchor) == anchor]
        remaining = [n for n in self.topology.nodes if n != anchor]
        orbits = _orbits_from_automorphisms(remaining, stab_autos)
        return sorted(min(orbit) for orbit in orbits)
