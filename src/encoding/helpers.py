# AMO, EO, AMN, ...
from itertools import combinations
from pysat.formula import CNF
from encoding.variables import VarPool

# AMO
def at_most_one(cnf: CNF, lits: list[int]) -> None:
    for xi, xj in combinations(lits, 2):
        cnf.append([-xi, -xj])

# EXO
def exactly_one(cnf: CNF, lits: list[int]) -> None:
    cnf.append(lits[:])
    at_most_one(cnf, lits)

# AMN
def at_most_n(cnf: CNF, pool: VarPool, n: int, lits: list[int], tag: object = None) -> None:
    k = len(lits)

    if n <= 0:
        for lit in lits:
            cnf.append([-lit])
        return
    
    if n >= k:
        return 
    
    # Lấy literal của biến phụ trợ r[i][j]
    def r(i: int, j: int) -> int:
        return pool._var(("_amn_r", tag, i, j))
    
    for i, xi in enumerate(lits):
        for j in range(n):
            r_ij = r(i, j)

            if j == 0:
                cnf.append([-xi, r_ij])
            else:
                if i > 0:
                    cnf.append([-xi, -r(i - 1, j - 1), r_ij])

            if i > 0:
                cnf.append([-r(i - 1, j), r_ij])

            if j == n - 1 and i > 0:
                cnf.append([-xi, -r(i - 1, j)])


# Implication helpers

def implies(cnf: CNF, a: int, b: int) -> None:
    # a suy ra b
    cnf.append([-a, b])


def implies_all(cnf: CNF, a: int, bs: list[int]) -> None:
    # a -> (b1 ∧ b2 ∧ ... ∧ bn) 8,11,12,14,20
    for b in bs:
        cnf.append([-a, b])


def and_implies(cnf: CNF, antecedents: list[int], consequent: int) -> None:
    # (a1 ∧ a2 ∧ ... ∧ an) -> c 4,19
    cnf.append([-a for a in antecedents] + [consequent])


def iff(cnf: CNF, a: int, b: int) -> None:
    # a tương đương b 3,9,18
    cnf.append([-a, b])
    cnf.append([-b, a])


def iff_or(cnf: CNF, pool: VarPool, a: int, bs: list[int]) -> None:
    # a ⟺ (b1 v b2 v ... v bn) 3,17
    cnf.append([-a] + bs)
    for b in bs:
        cnf.append([-b, a])