# QuilLS incremental SAT engine
# Gộp 2 chiến lược tìm optimal depth:
#   - mode="lb": tăng dần t từ lower_bound (critical path depth) — code gốc engine.py
#   - mode="ub": giảm dần t từ một upper bound (đã verify SAT) xuống lower_bound — code gốc engine2.py

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from pysat.formula import CNF

from circuit.parser import Circuit
from quills_platform.topology import Topology
from circuit.dag import DAG, build_dependency_dag

from encoding.variables import VarPool
from encoding.mapping import MappingConstraints
from encoding.connectivity import ConnectivityConstraints
from encoding.gate_constraints import GateConstraints
from encoding.swap import SwapConstraints
from encoding.assumptions import AssumptionConstraints

from solver.base import SolverBase
from solver.factory import SolverFactory

from instrumentation.solve_log import SolveLogger

log = logging.getLogger(__name__)

# Result

@dataclass
class SolverResult:
    sat: bool
    optimal_depth: int

    model: list[int] = field(default_factory=list)

    # initial_mapping[q] = p at t=1
    initial_mapping: dict[int, int] = field(default_factory=dict)

    # mapping_at_t[t][q] = p (chỉ được điền ở mode="lb")
    mapping_at_t: dict[int, dict[int, int]] = field(default_factory=dict)

    # schedule[t][g] = True if gate g exe at t
    schedule: dict[int, list[int]] = field(default_factory=dict)

    elapsed_sec: float = 0.0
    iterations: int = 0 # number of t tried

    def __str__(self) -> str:
        if not self.sat:
            return "UNSAT"
        return (
            f"SAT | depth={self.optimal_depth} | "
            f"iterations={self.iterations} | "
            f"time={self.elapsed_sec:.3f}s"
        )

# Engine

class QuilLSEngine:
    def __init__(
        self,
        circuit: Circuit,
        topology: Topology,
        solver_tag: str | None = None,
        verbose: bool = True, # log
        mode: str = "lb",          # "lb" (tăng dần từ lower bound) | "ub" (giảm dần từ upper bound)
        ub: Optional[int] = None,  # chỉ dùng khi mode="ub": upper bound khởi điểm để probe.
                                    # Nếu None -> heuristic tạm: len(gates) * 2.
        ub_search: str = "binary", # chỉ dùng khi mode="ub": "binary" (nhị phân) | "linear" (giảm tuần tự từng t)
        solve_logger: Optional[SolveLogger] = None,  # nếu truyền vào, ghi lại
                                    # thống kê (conflicts/decisions/...) cho mỗi lần solve()
    ) -> None:
        self.circuit   = circuit
        self.topology  = topology
        self.verbose   = verbose

        if mode not in ("lb", "ub"):
            raise ValueError(f"mode phải là 'lb' hoặc 'ub', nhận được: {mode!r}")
        self.mode = mode
        self._ub_hint = ub

        if ub_search not in ("binary", "linear"):
            raise ValueError(f"ub_search phải là 'binary' hoặc 'linear', nhận được: {ub_search!r}")
        self._ub_search = ub_search

        self._solve_logger = solve_logger

        self._solver_tag = solver_tag or SolverFactory.default_tag()

        self._cnf:  CNF | None = None
        self._pool: VarPool | None = None
        self._dag:  DAG | None = None

        self._best_pool: VarPool | None = None
        self._prev_stats: dict = {"conflicts": 0, "decisions": 0, "propagations": 0, "restarts": 0}

        # Instrumentation: đếm clause THÊM MỚI theo từng module encoding
        # (mapping/connectivity/gates/swap/assumptions), lũy kế từ đầu run.
        # _prev_clause_counts / _prev_var_counts_snapshot dùng để tính delta
        # (giống _prev_stats ở trên) — "đã thêm bao nhiêu kể từ lần solve trước".
        self._clause_counts:          dict[str, int] = {}
        self._prev_clause_counts:     dict[str, int] = {}
        self._prev_var_counts:        dict[str, int] = {}


    # entry point
    def run(self) -> SolverResult:
        if self.mode == "ub":
            return self._run_ub()
        return self._run_lb()

    # ------------------------------------------------------------------
    # mode="lb" — tăng dần t từ lower_bound (code gốc engine.py)
    # ------------------------------------------------------------------
    def _run_lb(self) -> SolverResult:
        t_start = time.perf_counter()

        self._cnf  = CNF()
        self._pool = VarPool()
        self._dag  = build_dependency_dag(self.circuit)

        mapping      = MappingConstraints(self._cnf, self._pool, self.circuit, self.topology)
        connectivity = ConnectivityConstraints(self._cnf, self._pool, self.circuit, self.topology)
        gates        = GateConstraints(self._cnf, self._pool, self.circuit, self.topology, self._dag)
        swap         = SwapConstraints(self._cnf, self._pool, self.circuit, self.topology)
        assumptions  = AssumptionConstraints(self._cnf, self._pool, self.circuit, self.topology)

        self._encode_tracked("gates", gates.init_static)
        self._encode_tracked("swap", swap.init_static)

        lower_bound = self._critical_path_depth()
        if self.verbose:
            log.info(
                "Starting QuilLS (LB-first) | circuit=%s | topology=%dq | "
                "solver=%s | lower_bound=%d",
                self.circuit, self.topology.n_qubits,
                self._solver_tag, lower_bound,
            )

        result = SolverResult(sat=False, optimal_depth=-1)

        with SolverFactory.create(self._solver_tag) as solver:
            self._prev_stats = {"conflicts": 0, "decisions": 0, "propagations": 0, "restarts": 0}
            self._clause_counts, self._prev_clause_counts, self._prev_var_counts = {}, {}, {}
            t = 1
            while t >= 1:
                self._encode_tracked("mapping",      lambda: mapping.encode(t))
                self._encode_tracked("connectivity",  lambda: connectivity.encode(t))
                self._encode_tracked("gates",          lambda: gates.encode(t))
                self._encode_tracked("swap",           lambda: swap.encode(t))

                self._flush_clauses(solver)

                result.iterations = t

                if t < lower_bound:
                    t+=1
                    continue

                self._encode_tracked("assumptions", lambda: assumptions.encode(t))
                self._flush_clauses(solver)

                asm_lit = assumptions.assumption_lit(t)

                if self.verbose:
                    log.info("  t=%d  solving ...", t)

                solve_t0 = time.perf_counter()
                sat = solver.solve(assumptions=[asm_lit])
                solve_elapsed = time.perf_counter() - solve_t0

                self._record_solve(solver, t=t, phase="lb", sat=sat, elapsed_sec=solve_elapsed)

                if sat:
                    model = solver.get_model()
                    result.sat           = True
                    result.optimal_depth = t
                    result.model         = model
                    result.elapsed_sec   = time.perf_counter() - t_start
                    if self.verbose:
                        log.info("  SAT at t=%d", t)
                    self._extract_solution_lb(result)
                    return result
                else:
                    if self.verbose:
                        log.info("  UNSAT, at t=%d", t)
                t+=1

        result.elapsed_sec = time.perf_counter() - t_start
        return result

    # ------------------------------------------------------------------
    # mode="ub" — incremental: 1 solver + 1 CNF sống suốt quá trình, horizon
    # chỉ được MỞ RỘNG (không bao giờ rebuild), mỗi t chỉ khác nhau ở
    # assumption literal asm(t) (đã có sẵn vì d(gate,t) được encode cho mọi
    # bước đã tới horizon hiện tại). Tìm t nhỏ nhất SAT bằng binary search
    # trong khoảng [lower_bound, upper_bound_đã_verify_SAT].
    # ------------------------------------------------------------------
    def _run_ub(self) -> SolverResult:
        t_start = time.perf_counter()

        self._dag = build_dependency_dag(self.circuit)
        lower_bound = self._critical_path_depth()

        if self.verbose:
            log.info(
                "Starting QuilLS (UB-first, incremental, search=%s) | circuit=%s | topology=%dq | "
                "solver=%s | lower_bound=%d",
                self._ub_search, self.circuit, self.topology.n_qubits,
                self._solver_tag, lower_bound,
            )

        # Trạng thái persistent cho toàn bộ quá trình (1 CNF, 1 pool, không rebuild)
        self._cnf  = CNF()
        self._pool = VarPool()
        self._encoded_upto = 0
        self._asm_lits: dict[int, int] = {}

        self._ub_mapping      = MappingConstraints(self._cnf, self._pool, self.circuit, self.topology)
        self._ub_connectivity = ConnectivityConstraints(self._cnf, self._pool, self.circuit, self.topology)
        self._ub_gates        = GateConstraints(self._cnf, self._pool, self.circuit, self.topology, self._dag)
        self._ub_swap         = SwapConstraints(self._cnf, self._pool, self.circuit, self.topology)
        self._ub_assumptions  = AssumptionConstraints(self._cnf, self._pool, self.circuit, self.topology)

        # Reset bộ đếm instrumentation TRƯỚC khi encode bất cứ thứ gì (kể cả
        # init_static), để clause tĩnh cũng được tính vào breakdown theo module.
        self._clause_counts, self._prev_clause_counts, self._prev_var_counts = {}, {}, {}

        self._encode_tracked("gates", self._ub_gates.init_static)
        self._encode_tracked("swap",  self._ub_swap.init_static)

        # Heuristic tạm cho upper bound nếu người dùng không tự truyền --ub:
        # len(gates) * 2. Chỉ là phỏng đoán, nên vẫn PHẢI probe/verify bằng
        # SAT solve thật trước khi dùng làm điểm bắt đầu (xem bug cũ:
        # upper_bound không hợp lệ có thể gây false-negative UNSAT).
        if self._ub_hint is not None:
            upper_bound = max(self._ub_hint, lower_bound)
        else:
            upper_bound = max(len(self.circuit.gates) * 2, lower_bound)

        iterations = 0
        best_sat_t: Optional[int] = None
        best_model: Optional[list[int]] = None

        with SolverFactory.create(self._solver_tag) as solver:
            self._prev_stats = {"conflicts": 0, "decisions": 0, "propagations": 0, "restarts": 0}
            self._flush_clauses(solver)  # flush các clause init_static

            # --- Probe: mở rộng horizon (nhân đôi) cho tới khi tìm được t SAT ---
            while True:
                iterations += 1
                sat, model = self._solve_at(upper_bound, solver, phase="ub-probe")
                if sat:
                    best_sat_t, best_model = upper_bound, model
                    if self.verbose:
                        log.info("  probe: SAT at t=%d, dùng làm upper bound", upper_bound)
                    break
                if self.verbose:
                    log.info("  probe: UNSAT at t=%d, tăng upper bound ...", upper_bound)
                upper_bound *= 2

            # --- Tìm t nhỏ nhất SAT trong [lower_bound, best_sat_t] ---
            # lower_bound là chặn dưới lý thuyết (critical path), không cần
            # verify SAT/UNSAT riêng; best_sat_t đã được verify SAT ở trên.
            if self._ub_search == "binary":
                best_sat_t, best_model, iterations = self._search_binary(
                    lower_bound, best_sat_t, best_model, solver, iterations,
                )
            else:
                best_sat_t, best_model, iterations = self._search_linear(
                    lower_bound, best_sat_t, best_model, solver, iterations,
                )

        result = SolverResult(
            sat=True,
            optimal_depth=best_sat_t,
            model=best_model,
            iterations=iterations,
            elapsed_sec=time.perf_counter() - t_start,
        )
        self._extract_solution_ub(result)
        return result

    def _search_binary(
        self,
        lower_bound: int,
        best_sat_t:  int,
        best_model:  list[int],
        solver:      SolverBase,
        iterations:  int,
    ) -> tuple[int, list[int], int]:
        """Binary search t nhỏ nhất SAT trong [lower_bound, best_sat_t].
        Số lần solve: O(log(best_sat_t - lower_bound))."""
        lo, hi = lower_bound, best_sat_t
        while lo < hi:
            mid = (lo + hi) // 2
            iterations += 1
            sat, model = self._solve_at(mid, solver, phase="ub-binary")
            if sat:
                best_sat_t, best_model = mid, model
                hi = mid
                if self.verbose:
                    log.info("  SAT at t=%d, thử t nhỏ hơn ...", mid)
            else:
                lo = mid + 1
                if self.verbose:
                    log.info("  UNSAT at t=%d, thử t lớn hơn ...", mid)
        return best_sat_t, best_model, iterations

    def _search_linear(
        self,
        lower_bound: int,
        best_sat_t:  int,
        best_model:  list[int],
        solver:      SolverBase,
        iterations:  int,
    ) -> tuple[int, list[int], int]:
        """Giảm tuần tự từng t một, từ best_sat_t - 1 xuống lower_bound, dừng
        ngay khi gặp UNSAT đầu tiên. Số lần solve: O(best_sat_t - lower_bound)
        trong trường hợp xấu nhất (nhiều hơn binary search), nhưng mỗi lần
        solve vẫn incremental (không rebuild) nhờ _solve_at."""
        for t in range(best_sat_t - 1, lower_bound - 1, -1):
            iterations += 1
            sat, model = self._solve_at(t, solver, phase="ub-linear")
            if sat:
                best_sat_t, best_model = t, model
                if self.verbose:
                    log.info("  SAT at t=%d, thử t=%d ...", t, t - 1)
            else:
                if self.verbose:
                    log.info("  UNSAT at t=%d → optimal depth is t=%d", t, t + 1)
                break
        return best_sat_t, best_model, iterations

    def _ensure_horizon(self, H: int, solver: SolverBase) -> None:
        """Mở rộng CNF cho tới horizon H nếu chưa đủ. Không bao giờ rebuild
        các bước đã encode trước đó — chỉ thêm phần còn thiếu (H > encoded_upto)."""
        if H <= self._encoded_upto:
            return
        for step in range(self._encoded_upto + 1, H + 1):
            self._encode_tracked("mapping",      lambda s=step: self._ub_mapping.encode(s))
            self._encode_tracked("connectivity",  lambda s=step: self._ub_connectivity.encode(s))
            self._encode_tracked("gates",          lambda s=step: self._ub_gates.encode(s))
            self._encode_tracked("swap",           lambda s=step: self._ub_swap.encode(s))
        self._flush_clauses(solver)
        self._encoded_upto = H

    def _assumption_lit_for(self, t: int, solver: SolverBase) -> int:
        """Trả về assumption literal asm(t), tạo mới (và cache) nếu chưa có.
        Yêu cầu horizon đã được mở rộng tới ít nhất t (d(gate,t) phải tồn tại)."""
        if t not in self._asm_lits:
            self._encode_tracked("assumptions", lambda: self._ub_assumptions.encode(t))
            self._flush_clauses(solver)
            self._asm_lits[t] = self._ub_assumptions.assumption_lit(t)
        return self._asm_lits[t]

    def _solve_at(self, t: int, solver: SolverBase, phase: str = "ub") -> tuple[bool, Optional[list[int]]]:
        """Đảm bảo horizon đủ tới t, lấy assumption lit cho t (tái sử dụng
        nếu đã có), rồi solve trên CÙNG MỘT solver (giữ nguyên learned
        clauses từ các lần solve trước, dù t khác nhau).

        `phase` chỉ dùng để gắn nhãn khi ghi log instrumentation (phân biệt
        được lần solve này thuộc bước probe / binary-search / linear-search)."""
        self._ensure_horizon(t, solver)
        asm_lit = self._assumption_lit_for(t, solver)

        if self.verbose:
            log.info("  t=%d  solving ...", t)

        solve_t0 = time.perf_counter()
        sat = solver.solve(assumptions=[asm_lit])
        solve_elapsed = time.perf_counter() - solve_t0

        self._record_solve(solver, t=t, phase=phase, sat=sat, elapsed_sec=solve_elapsed)

        if not sat:
            return False, None
        return True, solver.get_model()

    # Solution extract (mode="lb": có mapping_at_t đầy đủ theo từng t)
    def _extract_solution_lb(self, result: SolverResult) -> None:
        if not result.model or self._pool is None:
            return

        true_vars: set[int] = {lit for lit in result.model if lit > 0}
        pool = self._pool
        t_star = result.optimal_depth

        # mapping_at_t[t][q] = p  cho mọi t từ 1 đến t_star
        for t in range(1, t_star + 1):
            mapping_t: dict[int, int] = {}
            for q in range(self.circuit.n_qubits):
                for p in range(self.topology.n_qubits):
                    if pool.mp(q, p, t) in true_vars:
                        mapping_t[q] = p
                        break
            result.mapping_at_t[t] = mapping_t

        # initial_mapping = mapping tại t=1
        result.initial_mapping = result.mapping_at_t.get(1, {})

        # Schedule
        for t in range(1, t_star + 1):
            executing = []
            for gate in self.circuit.gates:
                if pool.c(gate.gate_id, t) in true_vars:
                    executing.append(gate.gate_id)
            if executing:
                result.schedule[t] = executing

    # Solution extract (mode="ub")
    def _extract_solution_ub(self, result: SolverResult) -> None:
        """Trích initial_mapping + mapping_at_t (mọi t) + schedule.

        FIX: bản trước chỉ trích initial_mapping, không trích mapping_at_t.
        Vì vậy validator (cx_connectivity) phải dùng initial_mapping cho MỌI
        timestep, kể cả sau khi mapping đã đổi do SWAP — dẫn tới báo INVALID
        sai (false negative) với bất kỳ mạch nào cần SWAP để định tuyến.
        Giờ trích mapping_at_t giống hệt cách _extract_solution_lb làm."""
        if not result.model or self._pool is None:
            return

        true_vars: set[int] = {lit for lit in result.model if lit > 0}
        pool = self._pool
        t_star = result.optimal_depth

        # mapping_at_t[t][q] = p  cho mọi t từ 1 đến t_star
        for t in range(1, t_star + 1):
            mapping_t: dict[int, int] = {}
            for q in range(self.circuit.n_qubits):
                for p in range(self.topology.n_qubits):
                    if pool.mp(q, p, t) in true_vars:
                        mapping_t[q] = p
                        break
            result.mapping_at_t[t] = mapping_t

        # initial_mapping = mapping tại t=1
        result.initial_mapping = result.mapping_at_t.get(1, {})

        # schedule
        for t in range(1, t_star + 1):
            executing = []
            for gate in self.circuit.gates:
                if pool.c(gate.gate_id, t) in true_vars:
                    executing.append(gate.gate_id)
            if executing:
                result.schedule[t] = executing


    # Internal helpers
    def _encode_tracked(self, kind: str, fn) -> None:
        """Gọi fn() (một lời gọi .encode(...)/.init_static() của 1 module
        encoding), rồi cộng dồn số clause MỚI được thêm vào self._cnf vào
        self._clause_counts[kind]. Dùng để biết clause tại thời điểm bất kỳ
        đến từ module nào (mapping/connectivity/gates/swap/assumptions)."""
        before = len(self._cnf.clauses)
        fn()
        added = len(self._cnf.clauses) - before
        self._clause_counts[kind] = self._clause_counts.get(kind, 0) + added

    def _record_solve(self, solver: SolverBase, t: int, phase: str, sat: bool, elapsed_sec: float) -> None:
        """Ghi 1 SolveRecord vào solve_logger (nếu có), tính DELTA thống kê
        so với lần solve trước — vì solver.stats() (accum_stats của pysat)
        là LŨY KẾ từ lúc solver được tạo, không phải riêng của lần solve
        này. Không tính delta sẽ khiến các lần solve sau trong cùng 1
        solver luôn hiện conflicts/decisions cao hơn thực tế, gây hiểu
        nhầm khi so sánh chi phí SAT-call vs UNSAT-call."""
        if self._solve_logger is None:
            return

        current = solver.stats()
        delta = {k: current.get(k, 0) - self._prev_stats.get(k, 0) for k in current}
        self._prev_stats = current

        # Delta biến theo từng loại (mp/oc/e/c/a/d/u/sw/st/asm) kể từ lần solve trước
        current_var_counts = self._pool.stats() if self._pool is not None else {}
        var_delta = {
            k: current_var_counts.get(k, 0) - self._prev_var_counts.get(k, 0)
            for k in current_var_counts
        }
        self._prev_var_counts = current_var_counts

        # Delta clause theo từng module encoding kể từ lần solve trước
        clause_delta = {
            k: self._clause_counts.get(k, 0) - self._prev_clause_counts.get(k, 0)
            for k in self._clause_counts
        }
        self._prev_clause_counts = dict(self._clause_counts)

        self._solve_logger.record(
            t=t, phase=phase, sat=sat, elapsed_sec=elapsed_sec,
            stats=delta, n_vars=solver.nof_vars(), n_clauses=solver.nof_clauses(),
            var_counts_delta=var_delta, clause_counts_delta=clause_delta,
        )

    def _flush_clauses(self, solver: SolverBase) -> None:
        for clause in self._cnf.clauses:
            solver.add_clause(clause)
        self._cnf.clauses.clear()

    def _critical_path_depth(self) -> int:
        self._dag = self._dag or build_dependency_dag(self.circuit)

        gates = self.circuit.gates
        if not gates:
            return 1

        memo: dict[int, int] = {}

        def longest(g: int) -> int:
            if g in memo:
                return memo[g]
            succs = self._dag.successors(g)
            depth = 1 + (max(longest(s) for s in succs) if succs else 0)
            memo[g] = depth
            return depth

        return max(longest(gate.gate_id) for gate in gates)
