"""
Plain Boolean expression and ROBDD utilities.

This module is intentionally netlist-agnostic.  EDA tool wrappers build
BoolExpr objects from their IR, then use this file for equivalence,
constant, dependency, and symmetry queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Callable, Iterable


@dataclass(frozen=True)
class BoolExpr:
    op: str
    args: tuple["BoolExpr", ...] = ()
    name: str | None = None
    value: bool | None = None


def const(value: bool) -> BoolExpr:
    return BoolExpr("const", value=bool(value))


def var(name: str) -> BoolExpr:
    return BoolExpr("var", name=name)


CONST0 = const(False)
CONST1 = const(True)


def is_const(expr: BoolExpr, value: bool | None = None) -> bool:
    if expr.op != "const":
        return False
    return value is None or expr.value is bool(value)


def make_not(expr: BoolExpr) -> BoolExpr:
    if is_const(expr):
        return CONST1 if not expr.value else CONST0
    if expr.op == "not":
        return expr.args[0]
    return BoolExpr("not", (expr,))


def _dedupe_sorted(args: Iterable[BoolExpr]) -> tuple[BoolExpr, ...]:
    return tuple(sorted(set(args), key=format_expr))


def make_and(args: Iterable[BoolExpr]) -> BoolExpr:
    flat: list[BoolExpr] = []
    for arg in args:
        if is_const(arg, False):
            return CONST0
        if is_const(arg, True):
            continue
        if arg.op == "and":
            flat.extend(arg.args)
        else:
            flat.append(arg)
    items = _dedupe_sorted(flat)
    if not items:
        return CONST1
    if len(items) == 1:
        return items[0]
    return BoolExpr("and", items)


def make_or(args: Iterable[BoolExpr]) -> BoolExpr:
    flat: list[BoolExpr] = []
    for arg in args:
        if is_const(arg, True):
            return CONST1
        if is_const(arg, False):
            continue
        if arg.op == "or":
            flat.extend(arg.args)
        else:
            flat.append(arg)
    items = _dedupe_sorted(flat)
    if not items:
        return CONST0
    if len(items) == 1:
        return items[0]
    return BoolExpr("or", items)


def make_xor(args: Iterable[BoolExpr]) -> BoolExpr:
    parity = False
    counts: dict[BoolExpr, int] = {}
    for arg in args:
        if is_const(arg):
            parity ^= bool(arg.value)
            continue
        if arg.op == "xor":
            for child in arg.args:
                counts[child] = counts.get(child, 0) + 1
        else:
            counts[arg] = counts.get(arg, 0) + 1

    items = [arg for arg, count in counts.items() if count % 2 == 1]
    items = list(_dedupe_sorted(items))
    if parity:
        items.append(CONST1)
    if not items:
        return CONST0
    if len(items) == 1:
        return items[0]
    return BoolExpr("xor", tuple(items))


def gate_expr(gate_type: str, inputs: Iterable[BoolExpr]) -> BoolExpr:
    gtype = gate_type.lower()
    args = tuple(inputs)
    if gtype == "buf":
        return args[0] if args else CONST0
    if gtype == "not":
        return make_not(args[0] if args else CONST0)
    if gtype == "and":
        return make_and(args)
    if gtype == "or":
        return make_or(args)
    if gtype == "xor":
        return make_xor(args)
    if gtype == "nand":
        return make_not(make_and(args))
    if gtype == "nor":
        return make_not(make_or(args))
    if gtype == "xnor":
        return make_not(make_xor(args))
    raise ValueError(f"Unsupported Boolean gate type: {gate_type}")


def expr_support(expr: BoolExpr) -> set[str]:
    if expr.op == "var":
        return {expr.name or ""}
    if expr.op == "const":
        return set()
    support: set[str] = set()
    for child in expr.args:
        support |= expr_support(child)
    return support


_PREC = {
    "const": 5,
    "var": 5,
    "not": 4,
    "and": 3,
    "xor": 2,
    "or": 1,
}


def format_expr(expr: BoolExpr, parent_prec: int = 0) -> str:
    if expr.op == "const":
        return "1'b1" if expr.value else "1'b0"
    if expr.op == "var":
        return expr.name or ""
    if expr.op == "not":
        child = expr.args[0]
        text = "~" + format_expr(child, _PREC["not"])
    else:
        sep = {"and": " & ", "or": " | ", "xor": " ^ "}[expr.op]
        prec = _PREC[expr.op]
        text = sep.join(format_expr(child, prec) for child in expr.args)

    if _PREC[expr.op] < parent_prec:
        return f"({text})"
    return text


class BDDManager:
    """Reduced ordered BDD manager with terminal nodes 0/1."""

    def __init__(self, variables: Iterable[str] = ()):
        self.var_order: dict[str, int] = {}
        for name in variables:
            self._ensure_var(name)
        self.nodes: list[tuple[str | None, int, int]] = [
            (None, 0, 0),
            (None, 1, 1),
        ]
        self.unique: dict[tuple[str, int, int], int] = {}
        self._not_cache: dict[int, int] = {}
        self._apply_cache: dict[tuple[str, int, int], int] = {}
        self._restrict_cache: dict[tuple[int, str, bool], int] = {}

    def _ensure_var(self, name: str) -> None:
        if name not in self.var_order:
            self.var_order[name] = len(self.var_order)

    def mk(self, name: str, low: int, high: int) -> int:
        if low == high:
            return low
        self._ensure_var(name)
        key = (name, low, high)
        if key in self.unique:
            return self.unique[key]
        node_id = len(self.nodes)
        self.nodes.append(key)
        self.unique[key] = node_id
        return node_id

    def var(self, name: str) -> int:
        self._ensure_var(name)
        return self.mk(name, 0, 1)

    def top_var(self, node_id: int) -> str | None:
        return self.nodes[node_id][0]

    def negate(self, node_id: int) -> int:
        if node_id == 0:
            return 1
        if node_id == 1:
            return 0
        if node_id in self._not_cache:
            return self._not_cache[node_id]
        name, low, high = self.nodes[node_id]
        result = self.mk(name, self.negate(low), self.negate(high))
        self._not_cache[node_id] = result
        return result

    def _top(self, left: int, right: int) -> str:
        names = [self.top_var(n) for n in (left, right) if self.top_var(n)]
        return min(names, key=lambda name: self.var_order[name])

    def _cofactor_for_top(self, node_id: int, top: str) -> tuple[int, int]:
        name, low, high = self.nodes[node_id]
        if name == top:
            return low, high
        return node_id, node_id

    def apply(self, op: str, left: int, right: int) -> int:
        if op == "and":
            if left == 0 or right == 0:
                return 0
            if left == 1:
                return right
            if right == 1:
                return left
            if left == right:
                return left
        elif op == "or":
            if left == 1 or right == 1:
                return 1
            if left == 0:
                return right
            if right == 0:
                return left
            if left == right:
                return left
        elif op == "xor":
            if left == 0:
                return right
            if right == 0:
                return left
            if left == right:
                return 0
            if left == 1:
                return self.negate(right)
            if right == 1:
                return self.negate(left)

        if left > right:
            left, right = right, left
        key = (op, left, right)
        if key in self._apply_cache:
            return self._apply_cache[key]

        if left in (0, 1) and right in (0, 1):
            lb = left == 1
            rb = right == 1
            if op == "and":
                result = 1 if lb and rb else 0
            elif op == "or":
                result = 1 if lb or rb else 0
            elif op == "xor":
                result = 1 if lb ^ rb else 0
            else:
                raise ValueError(f"Unsupported BDD op: {op}")
            self._apply_cache[key] = result
            return result

        top = self._top(left, right)
        l0, l1 = self._cofactor_for_top(left, top)
        r0, r1 = self._cofactor_for_top(right, top)
        result = self.mk(top, self.apply(op, l0, r0), self.apply(op, l1, r1))
        self._apply_cache[key] = result
        return result

    def fold(self, op: str, nodes: Iterable[int]) -> int:
        items = tuple(nodes)
        if not items:
            return 1 if op == "and" else 0
        return reduce(lambda a, b: self.apply(op, a, b), items)

    def from_expr(self, expr: BoolExpr) -> int:
        memo: dict[BoolExpr, int] = {}

        def build(node: BoolExpr) -> int:
            if node in memo:
                return memo[node]
            if node.op == "const":
                result = 1 if node.value else 0
            elif node.op == "var":
                result = self.var(node.name or "")
            elif node.op == "not":
                result = self.negate(build(node.args[0]))
            elif node.op in ("and", "or", "xor"):
                result = self.fold(node.op, (build(child) for child in node.args))
            else:
                raise ValueError(f"Unsupported expression op: {node.op}")
            memo[node] = result
            return result

        return build(expr)

    def restrict(self, node_id: int, name: str, value: bool) -> int:
        key = (node_id, name, bool(value))
        if key in self._restrict_cache:
            return self._restrict_cache[key]
        if node_id in (0, 1):
            return node_id
        node_name, low, high = self.nodes[node_id]
        if self.var_order.get(node_name, -1) > self.var_order.get(name, -1):
            return node_id
        if node_name == name:
            result = self.restrict(high if value else low, name, value)
        else:
            result = self.mk(
                node_name,
                self.restrict(low, name, value),
                self.restrict(high, name, value),
            )
        self._restrict_cache[key] = result
        return result

    def depends_on(self, node_id: int, name: str) -> bool:
        self._ensure_var(name)
        return self.restrict(node_id, name, False) != self.restrict(node_id, name, True)

    def symmetric_in(self, node_id: int, name_a: str, name_b: str) -> bool:
        self._ensure_var(name_a)
        self._ensure_var(name_b)
        f01 = self.restrict(self.restrict(node_id, name_a, False), name_b, True)
        f10 = self.restrict(self.restrict(node_id, name_a, True), name_b, False)
        return f01 == f10


def build_bdd(expr: BoolExpr, variables: Iterable[str] | None = None) -> tuple[BDDManager, int]:
    if variables is None:
        variables = sorted(expr_support(expr))
    manager = BDDManager(variables)
    return manager, manager.from_expr(expr)


def bdd_equivalent(left: BoolExpr, right: BoolExpr) -> bool:
    variables = sorted(expr_support(left) | expr_support(right))
    manager = BDDManager(variables)
    return manager.from_expr(left) == manager.from_expr(right)


def bdd_is_const(expr: BoolExpr, value: bool) -> bool:
    manager, node = build_bdd(expr)
    return node == (1 if value else 0)


def bdd_depends_on(expr: BoolExpr, name: str) -> bool:
    variables = sorted(expr_support(expr) | {name})
    manager, node = build_bdd(expr, variables)
    return manager.depends_on(node, name)


def bdd_symmetric_in(expr: BoolExpr, name_a: str, name_b: str) -> bool:
    variables = sorted(expr_support(expr) | {name_a, name_b})
    manager, node = build_bdd(expr, variables)
    return manager.symmetric_in(node, name_a, name_b)
