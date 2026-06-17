"""
Equivalence verification on top of the netlist_twoside IR.

Section 1.7 of tools/tool.md.  Unlike the pure analysis modules, these ops
compare the *current* design against a reference design (the originally loaded
netlist, the pre-transform snapshot, or the file on disk), so dispatch takes
the whole ``state`` rather than a single netlist.

Sequential equivalence is reduced to combinational equivalence at the register
boundary: flip-flops are matched by their Q net, then every primary output and
every matched flop's D-pin function is compared as a Boolean function over the
shared free variables (primary inputs and flop Q nets) using BDDs.
"""

from __future__ import annotations

import os
import re
from typing import Any

from netlist_twoside import Netlist, parse, PRIM_GATES
from algorithm.boolean_logic import bdd_equivalent
from tools.analysis_logic import build_logic_context

_CONST = re.compile(r"1'b[01]")


def _dff_by_q(netlist: Netlist) -> dict[str, Any]:
    by_q: dict[str, Any] = {}
    for g in netlist.gates.values():
        if g.type == "dff":
            q = g.ports.get("Q")
            if q:
                by_q[q] = g
    return by_q


def netlists_equivalent(ref: Netlist, cur: Netlist) -> dict[str, Any]:
    """Combinational/register-boundary equivalence between two netlists."""
    if set(ref.inputs) != set(cur.inputs):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "reason": "primary input sets differ"}
    if set(ref.outputs) != set(cur.outputs):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "reason": "primary output sets differ"}

    ref_ff = _dff_by_q(ref)
    cur_ff = _dff_by_q(cur)
    if set(ref_ff) != set(cur_ff):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "reason": "flip-flop (register) sets differ"}

    ref_ctx = build_logic_context(ref)
    cur_ctx = build_logic_context(cur)

    checked = 0

    # primary outputs
    for po in sorted(ref.outputs):
        if not bdd_equivalent(ref_ctx.expr_for_signal(po),
                              cur_ctx.expr_for_signal(po)):
            return {"equivalent": False, "checked_points": checked,
                    "first_mismatch": po,
                    "reason": f"output {po} has a different Boolean function"}
        checked += 1

    # flip-flop D-pin functions, matched by Q net
    for q in sorted(ref_ff):
        ref_d = ref_ff[q].ports.get("D")
        cur_d = cur_ff[q].ports.get("D")
        ref_expr = ref_ctx.expr_for_signal(ref_d) if ref_d else None
        cur_expr = cur_ctx.expr_for_signal(cur_d) if cur_d else None
        if ref_expr is None or cur_expr is None:
            if ref_d != cur_d:
                return {"equivalent": False, "checked_points": checked,
                        "first_mismatch": q,
                        "reason": f"flip-flop on Q={q} has a different D connection"}
        elif not bdd_equivalent(ref_expr, cur_expr):
            return {"equivalent": False, "checked_points": checked,
                    "first_mismatch": q,
                    "reason": f"flip-flop on Q={q} has a different next-state function"}
        checked += 1

    return {"equivalent": True, "checked_points": checked,
            "first_mismatch": None, "reason": "all comparison points match"}


# ---------------------------------------------------------------------------
# Miter + SAT engine (Tseitin CNF -> miter -> pysat Glucose3)
# ---------------------------------------------------------------------------
#
# Scales where BDDs blow up (deep XOR cones), and returns a concrete
# counterexample input assignment when the designs differ.

# Map each primitive gate to a positive base op plus an output-negation flag.
_BASE_OP = {
    "and": ("and", False), "nand": ("and", True),
    "or": ("or", False), "nor": ("or", True),
    "xor": ("xor", False), "xnor": ("xor", True),
    "buf": ("buf", False), "not": ("buf", True),
}


class _CnfMiter:
    """Tseitin encoder that shares primary-input / flop-Q variables across two
    netlist copies so a single CNF can express both designs at once."""

    def __init__(self) -> None:
        self.nvars = 0
        self.clauses: list[list[int]] = []
        self.shared: dict[str, int] = {}     # leaf net (PI / Q / undriven) -> var
        self.cache: dict[tuple[str, str], int] = {}  # (scope, net) -> literal
        self.true_lit = self._new_var()
        self.clauses.append([self.true_lit])  # force constant-1 variable true

    def _new_var(self) -> int:
        self.nvars += 1
        return self.nvars

    def shared_var(self, net: str) -> int:
        if net not in self.shared:
            self.shared[net] = self._new_var()
        return self.shared[net]

    def _const_lit(self, net: str) -> int:
        return self.true_lit if net == "1'b1" else -self.true_lit

    def lit(self, netlist: Netlist, net: str, scope: str) -> int:
        """Literal representing ``net`` in one netlist copy (``scope`` = A/B)."""
        if net is None:
            return -self.true_lit
        if _CONST.fullmatch(net):
            return self._const_lit(net)

        drv = netlist.unique_driver(net)
        gate = netlist.gates.get(drv) if drv else None
        if gate is None or gate.type == "dff" or gate.type not in PRIM_GATES:
            return self.shared_var(net)      # free leaf, shared between copies

        key = (scope, net)
        if key in self.cache:
            return self.cache[key]
        self.cache[key] = self.shared_var(net)   # loop guard (combinational DAG)
        ins = [self.lit(netlist, n, scope) for n in gate.ins]
        out = self._encode(gate.type, ins)
        self.cache[key] = out
        return out

    def _encode(self, gtype: str, ins: list[int]) -> int:
        base, neg = _BASE_OP[gtype]
        if base == "buf":
            lit = ins[0]
        elif base in ("and", "or"):
            lit = self._encode_and_or(base, ins)
        else:  # xor, folded pairwise
            lit = ins[0]
            for b in ins[1:]:
                lit = self._encode_xor2(lit, b)
        return -lit if neg else lit

    def _encode_and_or(self, base: str, ins: list[int]) -> int:
        v = self._new_var()
        if base == "and":
            for a in ins:
                self.clauses.append([-v, a])
            self.clauses.append([v] + [-a for a in ins])
        else:  # or
            for a in ins:
                self.clauses.append([v, -a])
            self.clauses.append([-v] + list(ins))
        return v

    def _encode_xor2(self, a: int, b: int) -> int:
        v = self._new_var()
        self.clauses.append([-v, -a, -b])
        self.clauses.append([-v, a, b])
        self.clauses.append([v, -a, b])
        self.clauses.append([v, a, -b])
        return v


def miter_equivalent(ref: Netlist, cur: Netlist) -> dict[str, Any]:
    """SAT-based equivalence: build a miter and prove it is unsatisfiable."""
    try:
        from pysat.solvers import Glucose3
    except ImportError as exc:        # pragma: no cover - environment guard
        raise RuntimeError(
            "miter+SAT engine needs the python-sat package (pysat)."
        ) from exc

    if set(ref.inputs) != set(cur.inputs):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "engine": "sat", "reason": "primary input sets differ"}
    if set(ref.outputs) != set(cur.outputs):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "engine": "sat", "reason": "primary output sets differ"}

    ref_ff = _dff_by_q(ref)
    cur_ff = _dff_by_q(cur)
    if set(ref_ff) != set(cur_ff):
        return {"equivalent": False, "checked_points": 0, "first_mismatch": None,
                "engine": "sat", "reason": "flip-flop (register) sets differ"}

    m = _CnfMiter()
    diff_to_point: dict[int, str] = {}

    # comparison points: primary outputs, then flop D functions (matched by Q)
    points: list[tuple[str, str, str]] = [(po, po, po) for po in sorted(ref.outputs)]
    for q in sorted(ref_ff):
        points.append((f"Q={q}", ref_ff[q].ports.get("D"), cur_ff[q].ports.get("D")))

    diff_vars: list[int] = []
    for label, ref_net, cur_net in points:
        la = m.lit(ref, ref_net, "A")
        lb = m.lit(cur, cur_net, "B")
        d = m._encode_xor2(la, lb)       # d == 1  iff the two sides differ
        diff_vars.append(d)
        diff_to_point[d] = label

    if not diff_vars:
        return {"equivalent": True, "checked_points": 0, "first_mismatch": None,
                "engine": "sat", "reason": "no comparison points"}

    # assert at least one comparison point differs; UNSAT => equivalent
    m.clauses.append(list(diff_vars))

    solver = Glucose3(bootstrap_with=m.clauses)
    sat = solver.solve()
    model = solver.get_model() if sat else None
    solver.delete()

    if not sat:
        return {"equivalent": True, "checked_points": len(diff_vars),
                "first_mismatch": None, "engine": "sat",
                "reason": "miter is UNSAT (functionally equivalent)"}

    truth = {abs(v): (v > 0) for v in model}
    mismatch = next((diff_to_point[d] for d in diff_vars if truth.get(d, False)),
                    None)
    counterexample = {
        net: int(truth.get(var, False))
        for net, var in sorted(m.shared.items())
        if net in ref.inputs
    }
    return {"equivalent": False, "checked_points": len(diff_vars),
            "first_mismatch": mismatch, "engine": "sat",
            "counterexample": counterexample,
            "reason": f"miter is SAT; outputs differ at {mismatch}"}


# ---------------------------------------------------------------------------
# State-aware operations
# ---------------------------------------------------------------------------

def _require_current(state: Any) -> Netlist:
    if getattr(state, "netlist", None) is None:
        raise ValueError("No design loaded.")
    return state.netlist


def verify_equivalent_to_original(state: Any) -> dict[str, Any]:
    """Compare the current design against the originally loaded design."""
    cur = _require_current(state)
    ref = getattr(state, "original_netlist", None)
    if ref is None:
        ref = cur                       # nothing changed since load
    return {"reference": "original", **netlists_equivalent(ref, cur)}


def verify_equivalent_to_pre_transform(state: Any) -> dict[str, Any]:
    """Compare the current design against the snapshot before the last transform."""
    cur = _require_current(state)
    ref = getattr(state, "pre_transform_netlist", None)
    if ref is None:                     # no transform performed yet
        ref = getattr(state, "original_netlist", None) or cur
    return {"reference": "pre_transform", **netlists_equivalent(ref, cur)}


def prove_equivalent_to_loaded(state: Any) -> dict[str, Any]:
    """Compare the current design against the original file on disk."""
    cur = _require_current(state)
    path = getattr(state, "loaded_path", None)
    if not path or not os.path.exists(path):
        raise ValueError("Original design file is not available on disk.")
    ref = parse(path)
    return {"reference": f"disk:{path}", **netlists_equivalent(ref, cur)}


def verify_equivalent_sat(state: Any) -> dict[str, Any]:
    """Verify equivalence to the originally loaded design with the miter+SAT
    engine (handles deep XOR cones where BDDs blow up; gives a counterexample)."""
    cur = _require_current(state)
    ref = getattr(state, "original_netlist", None)
    if ref is None:
        ref = cur
    return {"reference": "original", **miter_equivalent(ref, cur)}


# ---------------------------------------------------------------------------
# Dispatcher (state-aware)
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "verify_equivalent_to_original": {
        "func": verify_equivalent_to_original,
        "required_args": (),
        "category": "verification",
        "public": True,
        "description": "Verify the current design is equivalent to the originally loaded design.",
    },
    "verify_equivalent_to_pre_transform": {
        "func": verify_equivalent_to_pre_transform,
        "required_args": (),
        "category": "verification",
        "public": True,
        "description": "Verify the current design is equivalent to the snapshot before the last transform.",
    },
    "prove_equivalent_to_loaded": {
        "func": prove_equivalent_to_loaded,
        "required_args": (),
        "category": "verification",
        "public": True,
        "description": "Prove the current design is equivalent to the original design file on disk.",
    },
    "verify_equivalent_sat": {
        "func": verify_equivalent_sat,
        "required_args": (),
        "category": "verification",
        "public": True,
        "description": "Verify equivalence to the originally loaded design using a miter and SAT solver (robust on deep XOR logic; returns a counterexample if not equivalent).",
    },
}

PUBLIC_OP_TABLE = {name: meta for name, meta in OP_TABLE.items() if meta.get("public")}


def get_public_op_catalog() -> list[dict[str, Any]]:
    return [
        {
            "op": name,
            "required_args": list(meta["required_args"]),
            "category": meta["category"],
            "description": meta["description"],
        }
        for name, meta in PUBLIC_OP_TABLE.items()
    ]


def dispatch_verify_op(
    state: Any,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown verification op: {op}")
    return {"op": op, "args": request.get("args", {}), "result": table[op]["func"](state)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_verify_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    result = payload["result"]
    verdict = "EQUIVALENT" if result["equivalent"] else "NOT EQUIVALENT"
    ref = {
        "verify_equivalent_to_original": "originally loaded design",
        "verify_equivalent_to_pre_transform": "pre-transform snapshot",
        "prove_equivalent_to_loaded": "original design file on disk",
        "verify_equivalent_sat": "originally loaded design (SAT)",
    }.get(op, result.get("reference", "reference"))

    head = f"Current design vs {ref}: {verdict}."
    engine = f", engine={result['engine']}" if result.get("engine") else ""
    detail = (f" ({result['reason']}; {result['checked_points']} comparison "
              f"points checked{engine}")
    if result.get("first_mismatch"):
        detail += f", first mismatch at {result['first_mismatch']}"
    detail += ")."
    if result.get("counterexample"):
        ce = ", ".join(f"{n}={v}" for n, v in list(result["counterexample"].items())[:12])
        more = " ..." if len(result["counterexample"]) > 12 else ""
        detail += f" Counterexample input: {ce}{more}"
    return head + detail


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

def try_parse_verify_request(line: str) -> dict[str, Any] | None:
    low = line.lower()
    if "equivalent" not in low and "equivalence" not in low and "preserv" not in low:
        return None

    # explicit SAT / miter engine request
    if "sat" in low or "miter" in low:
        return {"op": "verify_equivalent_sat", "args": {}}

    if "pre-transform" in low or "previous" in low or "before the transform" in low \
            or "before transformation" in low or "last transform" in low:
        return {"op": "verify_equivalent_to_pre_transform", "args": {}}

    if "on disk" in low or "original file" in low or "loaded file" in low \
            or "file on disk" in low:
        return {"op": "prove_equivalent_to_loaded", "args": {}}

    # default: compare against the originally loaded design
    return {"op": "verify_equivalent_to_original", "args": {}}
