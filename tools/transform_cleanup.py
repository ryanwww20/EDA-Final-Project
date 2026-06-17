"""
Cleanup / simplification transformations on the netlist_twoside IR.

Section 2.3 of tools/tool.md.  Every op mutates the design and is checked for
functional equivalence with the SAT miter (rollback on any unintended change),
recording a report in ``state.last_transform_report`` / ``transform_history``.

These are all equivalence-preserving by construction; the goal is fewer gates /
shallower logic, not a functional change.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any

from netlist_twoside import Gate, Netlist
from tools.verify_equivalence import miter_equivalent
from tools.analysis_structural_health import (
    dangling_gates,
    redundant_gates,
    find_floating_signals,
)

_CONST = re.compile(r"1'b[01]")
_DFF_PINS = ("D", "CK", "RN", "SN")
_COMMUTATIVE = {"and", "or", "nand", "nor", "xor", "xnor"}


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


# ---------------------------------------------------------------------------
# Shared IR-edit helpers
# ---------------------------------------------------------------------------

def _all_nets(netlist: Netlist) -> set[str]:
    nets: set[str] = set(netlist.inputs) | set(netlist.outputs)
    for g in netlist.gates.values():
        if g.out:
            nets.add(g.out)
        for n in g.ins:
            if n:
                nets.add(n)
        for n in g.ports.values():
            if n:
                nets.add(n)
    return {n for n in nets if n and not _is_const(n)}


class _Namer:
    def __init__(self, netlist: Netlist) -> None:
        self._gates = set(netlist.gates)
        self._nets = _all_nets(netlist)
        self._gi = 0
        self._ni = 0

    def gate(self) -> str:
        while True:
            self._gi += 1
            name = f"u_cl{self._gi}"
            if name not in self._gates:
                self._gates.add(name)
                return name

    def net(self) -> str:
        while True:
            self._ni += 1
            name = f"cw{self._ni}"
            if name not in self._nets:
                self._nets.add(name)
                return name


def _reindex(netlist: Netlist) -> None:
    netlist.driver = {}
    netlist.drivers = defaultdict(list)
    netlist.fanout = defaultdict(list)
    for g in netlist.gates.values():
        if g.out:
            netlist.add_driver(g.out, g.name)
        if g.type == "dff":
            for pin in _DFF_PINS:
                n = g.ports.get(pin)
                if n and not _is_const(n):
                    netlist.fanout[n].append(g.name)
        else:
            for n in g.ins:
                if n and not _is_const(n):
                    netlist.fanout[n].append(g.name)


def _replace_consumers(netlist: Netlist, old: str, new: str) -> None:
    """Point every consumer of net ``old`` at ``new`` (drivers untouched)."""
    if old == new:
        return
    for g in netlist.gates.values():
        if g.type == "dff":
            for pin in _DFF_PINS:
                if g.ports.get(pin) == old:
                    g.ports[pin] = new
        else:
            g.ins = [new if s == old else s for s in g.ins]


def _dead_gate_elim(netlist: Netlist) -> int:
    """Remove combinational gates not reachable backward from PO / DFF pins."""
    live: set[str] = set()
    stack: list[str] = list(netlist.outputs)
    for g in netlist.gates.values():
        if g.type == "dff":
            live.add(g.name)
            for pin in _DFF_PINS:
                n = g.ports.get(pin)
                if n:
                    stack.append(n)
    seen: set[str] = set()
    while stack:
        net = stack.pop()
        if net in seen or _is_const(net):
            continue
        seen.add(net)
        for drv in netlist.drivers.get(net, []):
            g = netlist.gates.get(drv)
            if g is None or g.name in live:
                continue
            live.add(g.name)
            if g.type != "dff":
                stack.extend(g.ins)
    removed = 0
    for name in list(netlist.gates):
        g = netlist.gates[name]
        if g.type != "dff" and name not in live:
            del netlist.gates[name]
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Dead-logic removal (dangling / unused / floating)
# ---------------------------------------------------------------------------

def remove_dangling_gates(netlist: Netlist) -> dict[str, Any]:
    """Remove gates that do not reach any primary output or flop input."""
    before = sorted(dangling_gates(netlist))
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "remove_dangling_gates", "removed_gates": before,
            "removed_count": removed}


def prune_unused_gates(netlist: Netlist) -> dict[str, Any]:
    """Prune logic whose value is never observed at an output (alias of DCE)."""
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "prune_unused_gates", "removed_count": removed}


def remove_floating_nodes(netlist: Netlist) -> dict[str, Any]:
    """Remove gates with floating (undriven) inputs and dead outputs."""
    floating = find_floating_signals(netlist)["signals"]
    # gates whose output never feeds anything are dead; covered by DCE.  Gates
    # reading a floating (undriven, non-PI) net are also unobservable downstream.
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "remove_floating_nodes", "floating_signals": floating,
            "removed_count": removed}


# ---------------------------------------------------------------------------
# Back-to-back inverter collapse
# ---------------------------------------------------------------------------

def collapse_back_to_back_inverters(netlist: Netlist) -> dict[str, Any]:
    """Collapse NOT(NOT(x)) (and BUF) into a direct wire to x."""
    collapsed = 0
    for g in list(netlist.gates.values()):
        if g.type not in ("not", "buf"):
            continue
        src = g.ins[0] if g.ins else None
        if g.type == "buf":
            if src is not None:
                _replace_consumers(netlist, g.out, src)
                collapsed += 1
            continue
        # g is a NOT; check its driver is also a NOT
        drv = netlist.unique_driver(src) if src else None
        d = netlist.gates.get(drv) if drv else None
        if d is not None and d.type == "not":
            _replace_consumers(netlist, g.out, d.ins[0])
            collapsed += 1
    _reindex(netlist)
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "collapse_back_to_back_inverters",
            "collapsed": collapsed, "removed_count": removed}


# ---------------------------------------------------------------------------
# Constant propagation
# ---------------------------------------------------------------------------

def _const_val(net: str | None) -> int | None:
    if net == "1'b0":
        return 0
    if net == "1'b1":
        return 1
    return None


def _simplify_gate(g: Gate) -> tuple[str, str] | None:
    """Return ('const', "1'b0"/"1'b1") | ('wire', net) | ('not', net) | None."""
    t = g.type
    if t in ("not", "buf"):
        c = _const_val(g.ins[0]) if g.ins else None
        if c is None:
            return None
        if t == "buf":
            return ("const", f"1'b{c}")
        return ("const", f"1'b{1 - c}")
    if len(g.ins) != 2:
        return None
    a, b = g.ins
    ca, cb = _const_val(a), _const_val(b)
    if ca is None and cb is None:
        return None
    other = b if ca is not None else a
    c = ca if ca is not None else cb
    if t == "and":
        return ("const", "1'b0") if c == 0 else ("wire", other)
    if t == "or":
        return ("const", "1'b1") if c == 1 else ("wire", other)
    if t == "nand":
        return ("const", "1'b1") if c == 0 else ("not", other)
    if t == "nor":
        return ("const", "1'b0") if c == 1 else ("not", other)
    if t == "xor":
        return ("wire", other) if c == 0 else ("not", other)
    if t == "xnor":
        return ("not", other) if c == 0 else ("wire", other)
    return None


def constant_propagation(netlist: Netlist, type: str | None = None) -> dict[str, Any]:
    """Simplify gates with constant inputs to a fixpoint.  ``type`` optionally
    restricts which gate types are simplified."""
    namer = _Namer(netlist)
    types = None
    if type and type.strip().lower() not in ("all", "any", "*"):
        types = {t.strip().lower() for t in re.split(r"[,\s]+", type) if t.strip()}
    simplified = 0
    frozen: set[str] = set()                # gates already finalized (PO buffers)
    changed = True
    while changed:
        changed = False
        for g in list(netlist.gates.values()):
            if g.type == "dff" or g.name not in netlist.gates or g.name in frozen:
                continue
            if types is not None and g.type not in types:
                continue
            res = _simplify_gate(g)
            if res is None:
                continue
            kind, val = res
            if kind == "not":
                repl = namer.net()
                nn = namer.gate()
                netlist.gates[nn] = Gate(nn, "not", out=repl, ins=[val])
            else:                                   # const or wire
                repl = val
            _replace_consumers(netlist, g.out, repl)
            if g.out in netlist.outputs:
                # PO must stay driven: turn this gate into a frozen buffer.
                g.type = "buf"
                g.ins = [repl]
                frozen.add(g.name)
            else:
                del netlist.gates[g.name]
            simplified += 1
            changed = True
        _reindex(netlist)
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "constant_propagation", "type": type or "all",
            "simplified": simplified, "removed_count": removed}


# ---------------------------------------------------------------------------
# Gate merging (structural duplicate / functional equivalence)
# ---------------------------------------------------------------------------

def _struct_key(g: Gate):
    ins = tuple(sorted(g.ins)) if g.type in _COMMUTATIVE else tuple(g.ins)
    return (g.type, ins)


def merge_structural_duplicate_gates(netlist: Netlist) -> dict[str, Any]:
    """Merge gates with identical type and inputs into one, to a fixpoint."""
    merged = 0
    changed = True
    while changed:
        changed = False
        seen: dict[Any, str] = {}
        for name in sorted(netlist.gates):
            g = netlist.gates.get(name)
            if g is None or g.type == "dff":
                continue
            key = _struct_key(g)
            canon = seen.get(key)
            if canon is None:
                seen[key] = g.out
                continue
            _replace_consumers(netlist, g.out, canon)
            if g.out not in netlist.outputs:
                del netlist.gates[name]
                merged += 1
                changed = True
        _reindex(netlist)
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "merge_structural_duplicate_gates",
            "merged": merged, "removed_count": removed}


def merge_functionally_equivalent_gates(
    netlist: Netlist, max_support: int = 12
) -> dict[str, Any]:
    """Merge gates whose outputs are functionally equal.  Structural duplicates
    first (cheap), then a BDD pass over signals with small support."""
    struct = merge_structural_duplicate_gates(netlist)["merged"]

    from tools.analysis_logic import build_logic_context
    from algorithm.boolean_logic import expr_support, bdd_equivalent

    ctx = build_logic_context(netlist)
    buckets: dict[tuple, list[str]] = defaultdict(list)
    sig_expr: dict[str, Any] = {}
    for g in list(netlist.gates.values()):
        if g.type == "dff" or not g.out or g.out in netlist.outputs:
            continue
        try:
            expr = ctx.expr_for_signal(g.out)
        except Exception:
            continue
        support = expr_support(expr)
        if len(support) > max_support or not support:
            continue
        sig_expr[g.out] = expr
        buckets[tuple(sorted(support))].append(g.out)

    merged = 0
    for _support, sigs in buckets.items():
        if len(sigs) < 2:
            continue
        reps: list[str] = []                       # canonical signals seen so far
        for sig in sigs:
            if netlist.unique_driver(sig) is None:
                continue
            match = next((r for r in reps
                          if bdd_equivalent(sig_expr[sig], sig_expr[r])), None)
            if match is not None and sig not in netlist.outputs:
                drv = netlist.unique_driver(sig)
                _replace_consumers(netlist, sig, match)
                if drv in netlist.gates:
                    del netlist.gates[drv]
                merged += 1
            else:
                reps.append(sig)
        _reindex(netlist)
    removed = _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "merge_functionally_equivalent_gates",
            "structural_merged": struct, "functional_merged": merged,
            "removed_count": removed}


# ---------------------------------------------------------------------------
# Redundant-gate removal
# ---------------------------------------------------------------------------

def remove_redundant_gates(netlist: Netlist) -> dict[str, Any]:
    """Remove structurally redundant gates (duplicates of another gate)."""
    red = redundant_gates(netlist)
    keep_of = {r["name"]: r["equivalent_to"] for r in red}
    removed = 0
    for dup, keeper_name in keep_of.items():
        g = netlist.gates.get(dup)
        keeper = netlist.gates.get(keeper_name)
        if g is None or keeper is None:
            continue
        _replace_consumers(netlist, g.out, keeper.out)
        if g.out not in netlist.outputs:
            del netlist.gates[dup]
            removed += 1
    _reindex(netlist)
    removed += _dead_gate_elim(netlist)
    _reindex(netlist)
    return {"op": "remove_redundant_gates",
            "redundant_found": len(red), "removed_count": removed}


# ---------------------------------------------------------------------------
# State-aware dispatcher (snapshot -> mutate -> SAT self-check -> record)
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "remove_dangling_gates": {
        "func": lambda nl, _a: remove_dangling_gates(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Remove gates that do not reach any primary output or flop input.",
    },
    "prune_unused_gates": {
        "func": lambda nl, _a: prune_unused_gates(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Prune logic whose value is never observed at an output.",
    },
    "remove_floating_nodes": {
        "func": lambda nl, _a: remove_floating_nodes(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Remove gates with floating (undriven) inputs and dead outputs.",
    },
    "collapse_back_to_back_inverters": {
        "func": lambda nl, _a: collapse_back_to_back_inverters(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Collapse NOT(NOT(x)) and buffers into a direct wire.",
    },
    "constant_propagation": {
        "func": lambda nl, a: constant_propagation(nl, a.get("type")),
        "required_args": (), "optional_args": ("type",),
        "category": "transform", "public": True,
        "description": "Simplify gates with constant (1'b0/1'b1) inputs to a fixpoint.",
    },
    "merge_structural_duplicate_gates": {
        "func": lambda nl, _a: merge_structural_duplicate_gates(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Merge gates with identical type and inputs.",
    },
    "merge_functionally_equivalent_gates": {
        "func": lambda nl, _a: merge_functionally_equivalent_gates(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Merge gates whose outputs are functionally equivalent (structural + BDD).",
    },
    "remove_redundant_gates": {
        "func": lambda nl, _a: remove_redundant_gates(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Remove structurally redundant duplicate gates.",
    },
}

PUBLIC_OP_TABLE = {name: meta for name, meta in OP_TABLE.items() if meta.get("public")}


def get_public_op_catalog() -> list[dict[str, Any]]:
    return [
        {
            "op": name,
            "required_args": list(meta["required_args"]),
            "optional_args": list(meta.get("optional_args", ())),
            "category": meta["category"],
            "description": meta["description"],
        }
        for name, meta in PUBLIC_OP_TABLE.items()
    ]


def _normalize_args(op: str, args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    if op == "constant_propagation":
        args.setdefault("type", args.get("gate_type") or args.get("gtype"))
    return args


def dispatch_transform_cleanup_op(
    state: Any,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    if getattr(state, "netlist", None) is None:
        raise ValueError("No design loaded.")
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown cleanup transform op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")

    state.pre_transform_netlist = copy.deepcopy(state.netlist)
    g0 = len(state.netlist.gates)
    report = meta["func"](state.netlist, args)
    report["gate_count_before"] = g0
    report["gate_count_after"] = len(state.netlist.gates)

    eq = miter_equivalent(state.pre_transform_netlist, state.netlist)
    report["equivalent"] = eq["equivalent"]
    report["verify_method"] = "sat"
    if not eq["equivalent"]:
        state.netlist = state.pre_transform_netlist
        report["rolled_back"] = True
        report["gate_count_after"] = g0

    state.last_transform_report = report
    history = getattr(state, "transform_history", None)
    if not isinstance(history, list):
        history = []
        state.transform_history = history
    history.append(report)
    return {"op": op, "args": args, "result": report}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_transform_cleanup_result(payload: dict[str, Any]) -> str:
    r = payload["result"]
    area = f"gates {r['gate_count_before']}->{r['gate_count_after']}"
    op = r["op"]
    detail = {
        "remove_dangling_gates": lambda: f"removed {r['removed_count']} dangling gate(s)",
        "prune_unused_gates": lambda: f"pruned {r['removed_count']} unused gate(s)",
        "remove_floating_nodes": lambda: f"removed {r['removed_count']} gate(s); "
                                         f"{len(r['floating_signals'])} floating signal(s)",
        "collapse_back_to_back_inverters": lambda: f"collapsed {r['collapsed']}, "
                                                   f"removed {r['removed_count']}",
        "constant_propagation": lambda: f"simplified {r['simplified']}, "
                                        f"removed {r['removed_count']}",
        "merge_structural_duplicate_gates": lambda: f"merged {r['merged']}",
        "merge_functionally_equivalent_gates": lambda: f"merged "
            f"{r['structural_merged']}+{r['functional_merged']} (struct+func)",
        "remove_redundant_gates": lambda: f"removed {r['removed_count']} of "
                                          f"{r['redundant_found']} redundant",
    }.get(op, lambda: "")
    head = f"{op}: {detail()}; {area}."
    if r.get("rolled_back"):
        head += " WARNING: not equivalence-preserving, rolled back."
    else:
        head += " Functional equivalence verified."
    return head


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_GATE_WORD = r"(AND|OR|NAND|NOR|XOR|XNOR|NOT|BUF)"


def try_parse_transform_cleanup_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    if re.search(r"back[- ]?to[- ]?back invert|double invert|collapse.*invert", low):
        return {"op": "collapse_back_to_back_inverters", "args": {}}
    if m := re.search(rf"constant propagat\w*.*\b{_GATE_WORD}\b", line, re.I):
        return {"op": "constant_propagation", "args": {"type": m.group(1).lower()}}
    if re.search(r"constant propagat|propagate constant", low):
        return {"op": "constant_propagation", "args": {}}
    if re.search(r"dangling", low):
        return {"op": "remove_dangling_gates", "args": {}}
    if re.search(r"floating", low):
        return {"op": "remove_floating_nodes", "args": {}}
    if re.search(r"redundant", low):
        return {"op": "remove_redundant_gates", "args": {}}
    if re.search(r"functionally equivalent|functional.*merge|merge.*equivalent", low):
        return {"op": "merge_functionally_equivalent_gates", "args": {}}
    if re.search(r"structural.*duplicate|duplicate.*gate|merge.*duplicate", low):
        return {"op": "merge_structural_duplicate_gates", "args": {}}
    if re.search(r"prune|unused|dead (?:logic|gate)", low):
        return {"op": "prune_unused_gates", "args": {}}

    return None
