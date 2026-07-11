# QuilLS incremental SAT engine

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
 
log = logging.getLogger(__name__)

# Result

@dataclass
class SolverResult:
    sat: bool
    optimal_depth: int
    
    model: list[int] = field(default_factory=list)
    
    # initial_mapping[q] = p at t=1
    initial_mapping: dict[int, int] = field(default_factory=dict)

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
        verbose: bool = True,
    ) -> None:
        self.circuit   = circuit
        self.topology  = topology
        self.verbose   = verbose

        self._solver_tag = solver_tag or SolverFactory.default_tag()

        self._cnf:  CNF | None = None
        self._pool: VarPool | None = None
        self._dag:  DAG | None = None

        self._best_pool: VarPool | None = None


    # entry point
    def run(self) -> SolverResult:
        t_start = time.perf_counter()

        self._dag = build_dependency_dag(self.circuit)

        lower_bound = self._critical_path_depth()

        # Upper bound: số gate là giới hạn tự nhiên (mỗi gate chiếm ít nhất 1 bước)
        upper_bound = len(self.circuit.gates)

        # Đảm bảo UB >= LB
        upper_bound = max(upper_bound, lower_bound)

        if self.verbose:
            log.info(
                "Starting QuilLS (UB-first) | circuit=%s | topology=%dq | "
                "solver=%s | lower_bound=%d | upper_bound=%d",
                self.circuit, self.topology.n_qubits,
                self._solver_tag, lower_bound, upper_bound,
            )

        result = SolverResult(sat=False, optimal_depth=-1)
        iterations = 0

        # Vòng lặp giảm dần từ UB xuống LB.
        # Vì mỗi lần t thay đổi ta cần encode lại toàn bộ từ bước 1..t,
        # không thể tái sử dụng solver cũ → rebuild CNF + solver mỗi vòng.
        for t in range(upper_bound, lower_bound - 1, -1):
            iterations += 1

            # --- Xây CNF mới cho horizon t ---
            self._cnf  = CNF()
            self._pool = VarPool()

            mapping      = MappingConstraints(self._cnf, self._pool, self.circuit, self.topology)
            connectivity = ConnectivityConstraints(self._cnf, self._pool, self.circuit, self.topology)
            gates        = GateConstraints(self._cnf, self._pool, self.circuit, self.topology, self._dag)
            swap         = SwapConstraints(self._cnf, self._pool, self.circuit, self.topology)
            assumptions  = AssumptionConstraints(self._cnf, self._pool, self.circuit, self.topology)

            gates.init_static()
            swap.init_static()

            for step in range(1, t + 1):
                mapping.encode(step)
                connectivity.encode(step)
                gates.encode(step)
                swap.encode(step)

            assumptions.encode(t)

            if self.verbose:
                log.info("  t=%d  solving ...", t)

            # --- Giải ---
            with SolverFactory.create(self._solver_tag) as solver:
                for clause in self._cnf.clauses:
                    solver.add_clause(clause)

                asm_lit = assumptions.assumption_lit(t)
                sat = solver.solve(assumptions=[asm_lit])

                if sat:
                    # Lưu kết quả tốt nhất, tiếp tục giảm t
                    result.sat           = True
                    result.optimal_depth = t
                    result.model         = solver.get_model()
                    self._best_pool      = self._pool   # giữ pool để extract sau
                    if self.verbose:
                        log.info("  SAT at t=%d, trying t=%d ...", t, t - 1)
                else:
                    # UNSAT tại t → không thể làm nhỏ hơn nữa
                    if self.verbose:
                        log.info("  UNSAT at t=%d → optimal depth is t=%d", t, t + 1)
                    break

        result.iterations  = iterations
        result.elapsed_sec = time.perf_counter() - t_start

        if result.sat:
            # Dùng pool của lần SAT cuối cùng để trích nghiệm
            self._pool = self._best_pool
            self._extract_solution(result)

        return result

    # Solution extract                                                     
    def _extract_solution(self, result: SolverResult) -> None:
        if not result.model or self._pool is None:
            return
 
        true_vars: set[int] = {lit for lit in result.model if lit > 0}
        pool = self._pool
        t_star = result.optimal_depth
 
        # initial_mapping
        for q in range(self.circuit.n_qubits):
            for p in range(self.topology.n_qubits):
                if pool.mp(q, p, 1) in true_vars:
                    result.initial_mapping[q] = p
                    break
 
        # schedule
        for t in range(1, t_star + 1):
            executing = []
            for gate in self.circuit.gates:
                if pool.c(gate.gate_id, t) in true_vars:
                    executing.append(gate.gate_id)
            if executing:
                result.schedule[t] = executing
        

    # Internal helpers                                                     
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