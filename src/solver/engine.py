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

    mapping_at_t: dict[int, dict[int, int]] = field(default_factory=dict)
    
    # schedule[t][g] = True if gate g exe at t
    schedule: dict[int, list[int]] = field(default_factory=dict)

    elapsed_sec: float = 0.0
    iterations: int = 0 # number of t inc tried

    def __str__(self) -> str:
        if not self.sat:
            return "UNSAT"
        return (
            f"SAT | depth={self.optimal_depth} | "
            f"iterations={self.iterations} | "
            f"time={self.elapsed_sec:.3f}s"
        )

# Engine
#

class QuilLSEngine:
    def __init__(
        self,
        circuit: Circuit,
        topology: Topology,
        solver_tag: str | None = None,
        max_depth: int = math.inf,
        verbose: bool = True, # log
    ) -> None:
        self.circuit   = circuit
        self.topology  = topology
        self.max_depth = max_depth
        self.verbose   = verbose

        self._solver_tag = solver_tag or SolverFactory.default_tag()

        self._cnf:  CNF | None = None
        self._pool: VarPool | None = None
        self._dag:  DAG | None = None


    # entry points
    def run(self) -> SolverResult:
        t_start = time.perf_counter()

        self._cnf  = CNF()
        self._pool = VarPool()
        self._dag  = build_dependency_dag(self.circuit)

        mapping      = MappingConstraints(self._cnf, self._pool, self.circuit, self.topology)
        connectivity = ConnectivityConstraints(self._cnf, self._pool, self.circuit, self.topology)
        gates        = GateConstraints(self._cnf, self._pool, self.circuit, self.topology, self._dag)
        swap         = SwapConstraints(self._cnf, self._pool, self.circuit, self.topology)
        assumptions  = AssumptionConstraints(self._cnf, self._pool, self.circuit, self.topology)

        gates.init_static()
        swap.init_static()

        lower_bound = self._critical_path_depth()
        if self.verbose:
            log.info(
                "Starting QuilLS | circuit=%s | topology=%dq | "
                "solver=%s | lower_bound=%d | max_depth=%d",
                self.circuit, self.topology.n_qubits,
                self._solver_tag, lower_bound, self.max_depth,
            )
        
        result = SolverResult(sat=False, optimal_depth=-1)

        # with SolverFactory.create(self._solver_tag) as solver:
        #     for t in range(1, self.max_depth + 1):
        #         mapping.encode(t)
        #         connectivity.encode(t)
        #         gates.encode(t)
        #         swap.encode(t)

        #         self._flush_clauses(solver)

        #         result.iterations = t

        #         if t < lower_bound:
        #             continue

        #         assumptions.encode(t)
        #         self._flush_clauses(solver)

        #         asm_lit = assumptions.assumption_lit(t)

        #         if self.verbose:
        #             log.info("  t=%d  solving ...", t)

        #         sat = solver.solve(assumptions=[asm_lit])

        #         if sat:
        #             model = solver.get_model()
        #             result.sat           = True
        #             result.optimal_depth = t
        #             result.model         = model
        #             result.elapsed_sec   = time.perf_counter() - t_start
        #             if self.verbose:
        #                 log.info("  SAT at t=%d", t)
        #             self._extract_solution(result)
        #             return result
        #         else:
        #             if self.verbose:
        #                 log.info("  UNSAT, at t=%d", t)

        with SolverFactory.create(self._solver_tag) as solver:
            for t in range(1, self.max_depth + 1):
                mapping.encode(t)
                connectivity.encode(t)
                gates.encode(t)
                swap.encode(t)

                self._flush_clauses(solver)

                result.iterations = t

                if t < lower_bound:
                    continue

                assumptions.encode(t)
                self._flush_clauses(solver)

                asm_lit = assumptions.assumption_lit(t)

                if self.verbose:
                    log.info("  t=%d  solving ...", t)

                sat = solver.solve(assumptions=[asm_lit])

                if sat:
                    model = solver.get_model()
                    result.sat           = True
                    result.optimal_depth = t
                    result.model         = model
                    result.elapsed_sec   = time.perf_counter() - t_start
                    if self.verbose:
                        log.info("  SAT at t=%d", t)
                    self._extract_solution(result)
                    return result
                else:
                    if self.verbose:
                        log.info("  UNSAT, at t=%d", t)
 
        result.elapsed_sec = time.perf_counter() - t_start
        return result
    

    # Solution extract

    def _extract_solution(self, result: SolverResult) -> None:
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
 
 

    # Internal helpers
    def _flush_clauses(self, solver: SolverBase) -> None:
        for clause in self._cnf.clauses:
            solver.add_clause(clause)
        self._cnf.clauses.clear()
 
    def _critical_path_depth(self) -> int:
        if self._dag is None:
            return 1
 
        gates = self.circuit.gates
        if not gates:
            return 1
 
        # 
        memo: dict[int, int] = {}
 
        def longest(g: int) -> int:
            if g in memo:
                return memo[g]
            succs = self._dag.successors(g)
            depth = 1 + (max(longest(s) for s in succs) if succs else 0)
            memo[g] = depth
            return depth
 
        return max(longest(gate.gate_id) for gate in gates)