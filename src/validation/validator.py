"""
---------
1. mapping_completeness  — mọi qubit logic có ánh xạ vật lý riêng, không trùng
2. all_gates_scheduled   — mọi gate xuất hiện đúng 1 lần trong schedule
3. no_gate_duplicates    — không gate nào bị lên lịch 2 lần
4. dependency_ordering   — nếu A → B (data dep), thì t(A) < t(B)
5. cx_connectivity       — CX gate chỉ chạy trên cặp physical qubit kề nhau
6. no_physical_conflicts — mỗi timestep, mỗi physical qubit dùng bởi tối đa 1 gate
"""

from __future__ import annotations

import logging

from circuit.dag import build_dependency_dag
from circuit.gate import GateType
from circuit.parser import Circuit
from quills_platform.topology import Topology
from solver.engine import SolverResult

log = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised khi lời giải vi phạm một ràng buộc."""

# Public API

def validate_solution(
    circuit:  Circuit,
    topology: Topology,
    result:   SolverResult,
) -> tuple[bool, str]:
    try:
        _check_sat(result)
        _check_mapping_completeness(circuit, topology, result)
        _check_all_gates_scheduled(circuit, result)
        _check_no_gate_duplicates(result)
        _check_dependency_ordering(circuit, result)
        _check_cx_connectivity(circuit, topology, result)
        _check_no_physical_conflicts(circuit, topology, result)
    except ValidationError as exc:
        return False, str(exc)

    return True, "OK"


def validate_solution_verbose(
    circuit:  Circuit,
    topology: Topology,
    result:   SolverResult,
) -> list[tuple[str, bool, str]]:
    checks = [
        ("sat",                  lambda r: _check_sat(r)),
        ("mapping_completeness", lambda r: _check_mapping_completeness(circuit, topology, r)),
        ("all_gates_scheduled",  lambda r: _check_all_gates_scheduled(circuit, r)),
        ("no_gate_duplicates",   lambda r: _check_no_gate_duplicates(r)),
        ("dependency_ordering",  lambda r: _check_dependency_ordering(circuit, r)),
        ("cx_connectivity",      lambda r: _check_cx_connectivity(circuit, topology, r)),
        ("no_physical_conflicts",lambda r: _check_no_physical_conflicts(circuit, topology, r)),
    ]

    report: list[tuple[str, bool, str]] = []
    for name, fn in checks:
        try:
            fn(result)
            report.append((name, True, "OK"))
        except ValidationError as exc:
            report.append((name, False, str(exc)))

    return report


def print_report(
    report:   list[tuple[str, bool, str]],
    circuit:  Circuit,
    result:   SolverResult,
) -> None:
    """In bảng kết quả validation ra stdout."""
    sep = "─" * 60
    print(sep)
    print(f"Validation  |  {circuit}  |  depth={result.optimal_depth}")
    print(sep)
    for name, passed, msg in report:
        icon = "✓" if passed else "✗"
        print(f"  {icon}  {name:<26}  {msg}")
    print(sep)
    all_passed = all(p for _, p, _ in report)
    print("  Result:", "VALID ✓" if all_passed else "INVALID ✗")
    print(sep)


# Checks

def _check_sat(result: SolverResult) -> None:
    if not result.sat:
        raise ValidationError("Result is UNSAT — nothing to validate.")


def _check_mapping_completeness(
    circuit:  Circuit,
    topology: Topology,
    result:   SolverResult,
) -> None:
    mapping = result.initial_mapping

    for q in range(circuit.n_qubits):
        if q not in mapping:
            raise ValidationError(f"[mapping_completeness] q{q} has no physical mapping.")

    phys_used: dict[int, int] = {}
    for logical, physical in mapping.items():
        if physical in phys_used:
            raise ValidationError(
                f"[mapping_completeness] p{physical} assigned to both "
                f"q{phys_used[physical]} and q{logical}."
            )
        phys_used[physical] = logical

    for logical, physical in mapping.items():
        if physical >= topology.n_qubits:
            raise ValidationError(
                f"[mapping_completeness] q{logical} → p{physical} out of range "
                f"(topology has {topology.n_qubits} qubits)."
            )


def _check_all_gates_scheduled(circuit: Circuit, result: SolverResult) -> None:
    scheduled: set[int] = {gid for gs in result.schedule.values() for gid in gs}
    all_ids   = {g.gate_id for g in circuit.gates}
    missing   = all_ids - scheduled
    if missing:
        raise ValidationError(
            f"[all_gates_scheduled] Gates not in schedule: {sorted(missing)}"
        )


def _check_no_gate_duplicates(result: SolverResult) -> None:
    seen: dict[int, int] = {}
    for t, gates_at_t in result.schedule.items():
        for gid in gates_at_t:
            if gid in seen:
                raise ValidationError(
                    f"[no_gate_duplicates] g{gid} scheduled at both t={seen[gid]} and t={t}."
                )
            seen[gid] = t


def _check_dependency_ordering(circuit: Circuit, result: SolverResult) -> None:
    gate_time: dict[int, int] = {
        gid: t
        for t, gs in result.schedule.items()
        for gid in gs
    }
    dag = build_dependency_dag(circuit)

    for gate in circuit.gates:
        for succ_id in dag.successors(gate.gate_id):
            t_pred = gate_time.get(gate.gate_id)
            t_succ = gate_time.get(succ_id)
            if t_pred is None or t_succ is None:
                continue
            if t_pred >= t_succ:
                raise ValidationError(
                    f"[dependency_ordering] g{gate.gate_id} (t={t_pred}) must precede "
                    f"g{succ_id} (t={t_succ})."
                )


def _check_cx_connectivity(
    circuit:  Circuit,
    topology: Topology,
    result:   SolverResult,
) -> None:
    gate_by_id = {g.gate_id: g for g in circuit.gates}
 
    for t, gates_at_t in result.schedule.items():
        # mapping tại đúng timestep gate thực thi
        mapping = result.mapping_at_t.get(t) or result.initial_mapping
 
        for gid in gates_at_t:
            gate = gate_by_id.get(gid)
            if gate is None or gate.gate_type != GateType.CX:
                continue
 
            ctrl_phys = mapping.get(gate.control_qubit)
            tgt_phys  = mapping.get(gate.target_qubit)
            if ctrl_phys is None or tgt_phys is None:
                continue
 
            if not topology.is_connected(ctrl_phys, tgt_phys):
                raise ValidationError(
                    f"[cx_connectivity] g{gid} (CX q{gate.control_qubit}→q{gate.target_qubit}) "
                    f"at t={t}: p{ctrl_phys}-p{tgt_phys} not adjacent in topology."
                )

def _check_no_physical_conflicts(
    circuit:  Circuit,
    topology: Topology,
    result:   SolverResult,
) -> None:
    gate_by_id = {g.gate_id: g for g in circuit.gates}
 
    for t, gates_at_t in result.schedule.items():
        mapping   = result.mapping_at_t.get(t) or result.initial_mapping
        phys_used: dict[int, int] = {}
        for gid in gates_at_t:
            gate = gate_by_id.get(gid)
            if gate is None:
                continue
            for log_q in gate.qubits:
                phys_q = mapping.get(log_q)
                if phys_q is None:
                    continue
                if phys_q in phys_used:
                    raise ValidationError(
                        f"[no_physical_conflicts] t={t}: p{phys_q} used by "
                        f"both g{phys_used[phys_q]} and g{gid}."
                    )
                phys_used[phys_q] = gid