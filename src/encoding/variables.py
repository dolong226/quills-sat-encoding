from dataclasses import dataclass
from pysat.formula import IDPool

VarKey = tuple

class VarPool:
    def __init__(self):
        self._pool = IDPool()
        self._reverse: dict[int, VarKey] = {}

    # API
    def _var(self, key: VarKey) -> int:
        lit = self._pool.id(key)
        if lit not in self._reverse:
            self._reverse[lit] = key

        return lit
    
    # Debug
    def name(self, lit:int) -> VarKey | None:
        return self._reverse.get(abs(lit))
    
    # def explain(self, lit: int) -> str:
    #     """
    #     Trả về chuỗi mô tả dễ đọc cho một literal.

    #     Ví dụ:
    #         pool.explain(5)   → " mp(q=0, p=1, t=3)"
    #         pool.explain(-5)  → "¬mp(q=0, p=1, t=3)"
    #     """
    #     key = self.name(lit)
    #     if key is None:
    #         return f"{'¬' if lit < 0 else ' '}UNKNOWN({abs(lit)})"
    #     sign = "¬" if lit < 0 else " "
    #     return f"{sign}{_format_key(key)}"

    # def explain_clause(self, clause: list[int]) -> str:
    #     """In một clause dạng dễ đọc, tiện để in CNF khi debug."""
    #     return "(" + " ∨ ".join(self.explain(lit) for lit in clause) + ")"

    # def dump(self) -> None:
    #     """In toàn bộ bảng biến đã tạo ra. Dùng khi cần kiểm tra."""
    #     print(f"{'ID':>5}  Biến")
    #     print("-" * 40)
    #     for lit, key in sorted(self._reverse.items()):
    #         print(f"{lit:>5}  {_format_key(key)}")

    def mp(self, q: int, p: int, t: int) -> int:
        # mapping q <--> t
        return self._var(("mp", q, p , t))

    def oc(self, p: int, t: int) -> int:
        # p đang bị chiếm giữ
        return self._var(("oc", p, t))
    
    def e(self, q: int, q2: int, t: int) -> int:
        # q, q2 được ánh xạ đến 2 qubit vật lý có kết nối
        a, b = (q, q2) if q <= q2 else (q2, q)
        return self._var(("e", a, b, t))

    def c(self, g: int, t: int) -> int:
        # cổng g đang được thực hiện
        return self._var(("c", g, t))

    def a(self, g: int, t: int) -> int:
        # cổng g đã được thực hiện
        return self._var(("a", g, t))

    def d(self, g: int, t: int) -> int:
        # cổng g đang đợi thực hiện (chưa thực hiện)
        return self._var(("d", g, t))

    def u(self, p: int, t: int) -> int:
        # qubit vật lý p có thể được sử dụng (không bị chiếm dụng bởi SWAP)
        return self._var(("u", p, t))

    def sw(self, p: int, p2: int, t: int) -> int:
        # p,p2 đang swap tại t, t-1, t-2
        a, b = (p, p2) if p <= p2 else (p2, p)
        return self._var(("sw", a, b, t))

    def st(self, p: int, t: int) -> int:
        # qubit p đang tham gia vào swap trong khoảng t,t-1,t-2
        return self._var(("st", p, t))

    def asm(self, t: int) -> int:
        # t là bước thời gian cuối cùng
        return self._var(("asm", t))

    # Instrumentation — đếm biến theo từng loại (mp/oc/e/c/a/d/u/sw/st/asm)
    def stats(self) -> dict[str, int]:
        """Trả về {kind: số biến đã tạo thuộc kind đó}. Dùng cho instrumentation
        (xem cột var_counts trong solve-log), không ảnh hưởng logic encode."""
        counts: dict[str, int] = {}
        for key in self._reverse.values():
            kind = key[0]
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def n_vars(self) -> int:
        """Tổng số biến đã tạo (bất kể loại)."""
        return len(self._reverse)
    
def _format_key(key: VarKey) -> str:
    # Chuyển VarKey thành chuỗi
    name = key[0]
    args = key[1:]

    # Định nghĩa tên tham số cho từng loại biến
    _param_names: dict[str, list[str]] = {
        "mp":  ["q", "p", "t"],
        "oc":  ["p", "t"],
        "e":  ["q", "q'", "t"],
        "c":  ["g", "t"],
        "a":  ["g", "t"],
        "d":  ["g", "t"],
        "u":  ["p", "t"],
        "sw":  ["p", "p'", "t"],
        "st":  ["p", "t"],
        "asm": ["t"],
    }

    param_names = _param_names.get(name, [f"x{i}" for i in range(len(args))])
    pairs = ", ".join(
        f"{pname}={val}"
        for pname, val in zip(param_names, args)
    )
    return f"{name}({pairs})"