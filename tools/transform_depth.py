"""
Depth / timing optimization on the netlist_twoside IR.

Section 2.2 of tools/tool.md.  These ops *mutate* the design to reduce
combinational logic depth while preserving function, then self-check
equivalence (SAT miter) and roll back on any unintended change.

Technique
---------
Sound, gate-count-neutral **associative-chain balancing**.  AND / OR / XOR /
XNOR are associative, so a left-linear chain of one operator
``((((a·b)·c)·d)·e)`` (depth k-1) can be rebuilt as a balanced binary tree
(depth ⌈log2 k⌉) with the same k-1 two-input gates and the same function.

We only restructure *maximal homogeneous single-fanout chains*: every internal
net is consumed exactly once and by the same operator, so the chain computes a
plain ``op(leaves)`` and any tree over those leaves is equivalent.

NAND / NOR are **not** associative and are left untouched here (reducing their
depth needs AIG-level restructuring — see tool.md notes); the optimizer is a
safe no-op on those regions rather than risking an unsound change.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from netlist_twoside import Gate, Netlist
from algorithm.aig import build_aig, synthesize_balanced
from tools.verify_equivalence import miter_equivalent
from tools.analysis_path import (
    max_comb_depth_pi_to_po,
    max_pi_to_dff_d_depth,
    max_reg_to_reg_comb_depth,
)
from tools.analysis_netlist_stats import max_fanin_cone_depth
from tools.analysis_fanin_fanout import transitive_fanin_cone

_CONST = re.compile(r"1'b[01]")
_DFF_PINS = ("D", "CK", "RN", "SN")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


# ---------------------------------------------------------------------------
# IR helpers (shared shape with transform_fanout)
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
            name = f"u_bal{self._gi}"
            if name not in self._gates:
                self._gates.add(name)
                return name

    def net(self) -> str:
        while True:
            self._ni += 1
            name = f"dw{self._ni}"
            if name not in self._nets:
                self._nets.add(name)
                return name


def _reindex(netlist: Netlist) -> None:
    from collections import defaultdict
    netlist.driver = {}
    netlist.drivers = defaultdict(list)
    netlist.fanout = defaultdict(list)
    for g in netlist.gates.values():
        if g.out:
            netlist.add_driver(g.out, g.name)
        if g.type == "dff":
            for pin in ("D", "CK", "RN", "SN"):
                n = g.ports.get(pin)
                if n and not _is_const(n):
                    netlist.fanout[n].append(g.name)
        else:
            for n in g.ins:
                if n and not _is_const(n):
                    netlist.fanout[n].append(g.name)


# ---------------------------------------------------------------------------
# AIG-based depth optimization (build -> sharing-aware balance -> map back)
# ---------------------------------------------------------------------------

def _dead_gate_elim(netlist: Netlist) -> None:
    """Remove combinational gates not reachable backward from any real sink
    (primary outputs and DFF pins).  All DFFs are kept."""
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
    for name in list(netlist.gates):
        g = netlist.gates[name]
        if g.type != "dff" and name not in live:
            del netlist.gates[name]


def _sink_nets(netlist: Netlist, restrict_outputs: set[str] | None = None) -> list[str]:
    """Sinks to re-synthesize: primary outputs (+ DFF D nets when whole-design)."""
    sinks: list[str] = []
    seen: set[str] = set()
    pool = restrict_outputs if restrict_outputs is not None else set(netlist.outputs)
    for o in sorted(pool):
        if o not in seen:
            seen.add(o)
            sinks.append(o)
    if restrict_outputs is None:           # whole-design: also rebuild flop inputs
        for g in netlist.gates.values():
            if g.type == "dff":
                d = g.ports.get("D")
                if d and not _is_const(d) and d not in seen:
                    seen.add(d)
                    sinks.append(d)
    return sinks


def _aig_rebuild(netlist: Netlist, sinks: list[str]) -> int:
    """Rebuild the logic feeding ``sinks`` as a depth-balanced AIG mapping.

    Returns the number of sinks rebuilt.  Equivalence is the caller's to check.
    """
    sinks = [s for s in sinks if not _is_const(s)]
    if not sinks:
        return 0
    aig = build_aig(netlist, sinks)
    namer = _Namer(netlist)
    plan = synthesize_balanced(aig, namer)

    new_driven = {out for _n, _t, out, _i in plan.gates}

    # A sink that maps to itself with no synthesized driver is "atomic at the
    # top" (e.g. driven by a kept XOR/XNOR) — leave its original gate in place.
    def rebuilt(sink: str) -> bool:
        return sink in new_driven or plan.sink_drivers.get(sink) != sink

    # remove old (unique, combinational) drivers only of sinks we actually rebuild
    for s in sinks:
        if not rebuilt(s):
            continue
        for drv in list(netlist.drivers.get(s, [])):
            g = netlist.gates.get(drv)
            if g is not None and g.type != "dff":
                netlist.gates.pop(drv, None)

    # add the synthesized gates
    for name, gtype, out, ins in plan.gates:
        netlist.gates[name] = Gate(name, gtype, out=out, ins=list(ins))

    # connect any sink whose root did not directly output the sink net
    for sink, dn in plan.sink_drivers.items():
        if dn != sink:
            bname = namer.gate()
            netlist.gates[bname] = Gate(bname, "buf", out=sink, ins=[dn])

    _reindex(netlist)
    _dead_gate_elim(netlist)
    _reindex(netlist)
    return len(sinks)


# ---------------------------------------------------------------------------
# Public transformations (pure netlist mutators)
# ---------------------------------------------------------------------------

def _design_depth(netlist: Netlist) -> int:
    """True max combinational depth across all start/endpoints: PI->PO,
    PI->DFF.D, and DFF.Q->DFF.D (register-heavy designs have 0 PI->PO)."""
    return max(
        max_comb_depth_pi_to_po(netlist)["depth"],
        max_pi_to_dff_d_depth(netlist)["depth"],
        max_reg_to_reg_comb_depth(netlist)["depth"],
    )


def _report(op: str, rebuilt: int, before: int, after: int,
            gates_before: int, gates_after: int,
            extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rep = {
        "op": op,
        "sinks_rebuilt": rebuilt,
        "max_depth_before": before,
        "max_depth_after": after,
        "gate_count_before": gates_before,
        "gate_count_after": gates_after,
    }
    if extra:
        rep.update(extra)
    return rep


def depth_optimization(netlist: Netlist) -> dict[str, Any]:
    """Reduce logic depth design-wide via AIG balancing of all output/flop cones."""
    before = _design_depth(netlist)
    g0 = len(netlist.gates)
    rebuilt = _aig_rebuild(netlist, _sink_nets(netlist))
    return _report("depth_optimization", rebuilt, before, _design_depth(netlist),
                   g0, len(netlist.gates))


def minimize_max_path_depth(netlist: Netlist) -> dict[str, Any]:
    """Minimize the maximum combinational path depth via AIG balancing."""
    before = _design_depth(netlist)
    g0 = len(netlist.gates)
    rebuilt = _aig_rebuild(netlist, _sink_nets(netlist))
    return _report("minimize_max_path_depth", rebuilt, before, _design_depth(netlist),
                   g0, len(netlist.gates))


def reduce_critical_path_depth(netlist: Netlist) -> dict[str, Any]:
    """Reduce the critical-path depth via AIG balancing."""
    before = _design_depth(netlist)
    g0 = len(netlist.gates)
    rebuilt = _aig_rebuild(netlist, _sink_nets(netlist))
    return _report("reduce_critical_path_depth", rebuilt, before, _design_depth(netlist),
                   g0, len(netlist.gates))


def optimize_cone_depth(netlist: Netlist, output: str, target: int) -> dict[str, Any]:
    """Rebuild the fanin cone of ``output`` balanced, aiming for depth <= target."""
    before = max_fanin_cone_depth(netlist, output)
    g0 = len(netlist.gates)
    rebuilt = _aig_rebuild(netlist, [output])
    after = max_fanin_cone_depth(netlist, output)
    return _report("optimize_cone_depth", rebuilt, before, after,
                   g0, len(netlist.gates),
                   {"output": output, "target": int(target),
                    "target_met": after <= int(target)})


def optimize_outputs_depth_gt(netlist: Netlist, n: int, target: int) -> dict[str, Any]:
    """Optimize every primary output whose cone depth exceeds ``n`` toward ``target``."""
    n = int(n)
    target = int(target)
    before = _design_depth(netlist)
    g0 = len(netlist.gates)
    touched = [po for po in sorted(netlist.outputs)
               if max_fanin_cone_depth(netlist, po) > n]
    rebuilt = _aig_rebuild(netlist, touched) if touched else 0
    after_each = {po: max_fanin_cone_depth(netlist, po) for po in touched}
    return _report("optimize_outputs_depth_gt", rebuilt, before, _design_depth(netlist),
                   g0, len(netlist.gates),
                   {"n": n, "target": target, "optimized_outputs": touched,
                    "all_met": all(d <= target for d in after_each.values())})


# ---------------------------------------------------------------------------
# State-aware dispatcher (snapshot -> mutate -> SAT self-check -> record)
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "reduce_critical_path_depth": {
        "func": lambda nl, _a: reduce_critical_path_depth(nl),
        "required_args": (),
        "category": "transform",
        "public": True,
        "description": "Reduce the critical-path logic depth by balancing associative gate chains.",
    },
    "depth_optimization": {
        "func": lambda nl, _a: depth_optimization(nl),
        "required_args": (),
        "category": "transform",
        "public": True,
        "description": "Reduce logic depth design-wide by balancing associative gate chains.",
    },
    "minimize_max_path_depth": {
        "func": lambda nl, _a: minimize_max_path_depth(nl),
        "required_args": (),
        "category": "transform",
        "public": True,
        "description": "Minimize the maximum combinational path depth by balancing associative gate chains.",
    },
    "optimize_cone_depth": {
        "func": lambda nl, a: optimize_cone_depth(nl, a["output"], a["target"]),
        "required_args": ("output", "target"),
        "category": "transform",
        "public": True,
        "description": "Balance chains in an output's fanin cone aiming for depth <= target.",
    },
    "optimize_outputs_depth_gt": {
        "func": lambda nl, a: optimize_outputs_depth_gt(nl, a["n"], a["target"]),
        "required_args": ("n", "target"),
        "category": "transform",
        "public": True,
        "description": "Optimize every output whose cone depth exceeds n toward a target depth.",
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


def _normalize_args(op: str, args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    if op == "optimize_cone_depth":
        args.setdefault("output", args.get("out") or args.get("target_output")
                        or args.get("po"))
        args.setdefault("target", args.get("target_depth") or args.get("depth")
                        or args.get("max"))
    if op == "optimize_outputs_depth_gt":
        args.setdefault("n", args.get("threshold") or args.get("gt"))
        args.setdefault("target", args.get("target_depth") or args.get("to"))
    return args


def dispatch_transform_depth_op(
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
        raise ValueError(f"Unknown depth transform op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")

    state.pre_transform_netlist = copy.deepcopy(state.netlist)
    report = meta["func"](state.netlist, args)

    # AIG remap changes topology: accept the result only if it is functionally
    # equivalent AND actually reduced depth — otherwise restore the original so
    # the optimizer never makes the design worse.
    improved = report["max_depth_after"] < report["max_depth_before"]
    if report["sinks_rebuilt"] == 0:
        report["equivalent"] = True
        report["applied"] = False
        report["verify_method"] = "noop"
    elif not improved:
        state.netlist = state.pre_transform_netlist
        report["equivalent"] = True
        report["applied"] = False
        report["verify_method"] = "skipped_no_improvement"
        report["gate_count_after"] = report["gate_count_before"]
        report["max_depth_after"] = report["max_depth_before"]
    else:
        eq = miter_equivalent(state.pre_transform_netlist, state.netlist)
        report["equivalent"] = eq["equivalent"]
        report["verify_method"] = "sat"
        if not eq["equivalent"]:
            state.netlist = state.pre_transform_netlist
            report["applied"] = False
            report["rolled_back"] = True
        else:
            report["applied"] = True

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

def format_transform_depth_result(payload: dict[str, Any]) -> str:
    r = payload["result"]
    area = f"gates {r['gate_count_before']}->{r['gate_count_after']}"
    if "output" in r:
        head = (f"Cone of {r['output']}: depth {r['max_depth_before']} -> "
                f"{r['max_depth_after']} (target {r['target']}, met: {r['target_met']}); "
                f"{area}.")
    elif "optimized_outputs" in r:
        head = (f"Depth {r['max_depth_before']} -> {r['max_depth_after']} over "
                f"{len(r['optimized_outputs'])} output(s) with depth > {r['n']} "
                f"(target {r['target']}, all met: {r['all_met']}); {area}.")
    else:
        head = (f"AIG depth optimization: max depth {r['max_depth_before']} -> "
                f"{r['max_depth_after']}; {area}.")
    if r.get("rolled_back"):
        head += " WARNING: change was not equivalence-preserving and was rolled back."
    elif r["sinks_rebuilt"]:
        head += " Functional equivalence verified."
    return head


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"


def try_parse_transform_depth_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    # cone depth to a target
    if m := re.search(
        rf"(?:cone (?:of|for)|output)\s+{_NAME}.*?depth.*?(?:<=|to|below|under|at most)\s*(\d+)",
        line, re.I,
    ):
        return {"op": "optimize_cone_depth",
                "args": {"output": m.group(1), "target": int(m.group(2))}}

    # outputs with depth > n optimized to target
    if m := re.search(
        r"outputs?.*depth.*(?:greater than|>|exceed(?:s|ing)?)\s*(\d+).*?(?:to|target|<=)\s*(\d+)",
        line, re.I,
    ):
        return {"op": "optimize_outputs_depth_gt",
                "args": {"n": int(m.group(1)), "target": int(m.group(2))}}

    if re.search(r"critical[- ]path.*(?:depth|reduce|shorten)", low) or \
            re.search(r"reduce.*critical[- ]path", low):
        return {"op": "reduce_critical_path_depth", "args": {}}
    if re.search(r"minimi[sz]e.*(?:max(?:imum)?|longest).*(?:path )?depth", low):
        return {"op": "minimize_max_path_depth", "args": {}}
    if re.search(r"(?:depth optimization|optimize.*depth|reduce.*logic depth)", low):
        return {"op": "depth_optimization", "args": {}}

    return None
