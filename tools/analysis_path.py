"""
Path / depth analysis on top of the netlist_twoside IR.

Section 1.3 of tools/tool.md.  Mirrors the structure of
tools.analysis_fanin_fanout / tools.analysis_netlist_stats: pure query
functions first, then an OP_TABLE dispatcher, a formatter, and a rule-based
prompt parser.

Combinational graph model
-------------------------
Nodes are *nets*; every non-DFF gate contributes one edge per input:
``input_net --(gate)--> output_net``.  A path's "depth" is the number of gates
(edges) traversed.  DFFs are sequential boundaries: their Q acts as a PI-like
source and their D as a PO-like sink, so no edge ever crosses a flop and
combinational depth never runs through one.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from netlist_twoside import Netlist

_CONST = re.compile(r"1'b[01]")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


# ---------------------------------------------------------------------------
# Combinational net graph
# ---------------------------------------------------------------------------

def _build_net_graph(netlist: Netlist) -> tuple[dict, dict]:
    """Build forward / backward net adjacency, skipping DFF (boundary) edges.

    ``fwd[net]`` lists ``(next_net, gate_name)`` consumers; ``bwd[net]`` lists
    ``(prev_net, gate_name)`` drivers.
    """
    fwd: dict = defaultdict(list)
    bwd: dict = defaultdict(list)
    for g in netlist.gates.values():
        if g.type == "dff":
            continue
        out = g.out
        if not out:
            continue
        for src in g.ins:
            if src is None:
                continue
            fwd[src].append((out, g.name))
            bwd[out].append((src, g.name))
    return fwd, bwd


def _const_source_nets(netlist: Netlist, fwd: dict) -> set:
    return {net for net in fwd if _is_const(net)}


def _dff_pin_nets(netlist: Netlist, pin: str) -> set:
    nets = set()
    for g in netlist.gates.values():
        if g.type == "dff":
            net = g.ports.get(pin)
            if net and not _is_const(net):
                nets.add(net)
    return nets


def _all_nets(netlist: Netlist, fwd: dict, bwd: dict) -> set:
    nets = set(fwd) | set(bwd)
    nets |= set(netlist.inputs) | set(netlist.outputs)
    nets |= _dff_pin_nets(netlist, "Q") | _dff_pin_nets(netlist, "D")
    return nets


def _resolve_src(netlist: Netlist, name: str) -> str | None:
    """A gate name resolves to the net it drives (DFF -> Q); else the net itself."""
    g = netlist.gates.get(name)
    if g is not None:
        return g.out
    return name


def _resolve_dst(netlist: Netlist, name: str) -> str | None:
    """A gate name resolves to its sink net (DFF -> D pin); else the net itself."""
    g = netlist.gates.get(name)
    if g is not None:
        if g.type == "dff":
            return g.ports.get("D")
        return g.out
    return name


def _split_node(netlist: Netlist, node: str | None) -> tuple[set, set]:
    """Map a gate-or-net into the (blocked_nets, blocked_gates) to remove it.

    Blocking a gate is done by blocking the net it drives, which severs every
    path through it.
    """
    blocked_nets: set = set()
    blocked_gates: set = set()
    if node is None:
        return blocked_nets, blocked_gates
    g = netlist.gates.get(node)
    if g is not None:
        blocked_gates.add(node)
        if g.out:
            blocked_nets.add(g.out)
    else:
        blocked_nets.add(node)
    return blocked_nets, blocked_gates


def _reachable(
    fwd: dict,
    starts,
    blocked_nets: set | None = None,
    blocked_gates: set | None = None,
) -> set:
    """Nets reachable from ``starts`` over ``fwd``, honouring blocked nodes."""
    blocked_nets = blocked_nets or set()
    blocked_gates = blocked_gates or set()
    seen: set = set()
    stack = [s for s in starts if s is not None and s not in blocked_nets]
    while stack:
        net = stack.pop()
        if net in seen:
            continue
        seen.add(net)
        for nxt, gname in fwd.get(net, []):
            if nxt in blocked_nets or gname in blocked_gates:
                continue
            if nxt not in seen:
                stack.append(nxt)
    return seen


def _longest_dp(adj: dict, all_nets: set, seeds) -> dict:
    """Longest gate-count from any seed net to every net, via Kahn topo order.

    Seeds start at depth 0 (a floor) and may still grow if a longer path
    reaches them.  Unreachable nets map to ``None``.  Iterative, so it is safe
    on the largest (124k-gate) designs.
    """
    seeds = set(seeds)
    indeg = {n: 0 for n in all_nets}
    for n in all_nets:
        for m, _g in adj.get(n, []):
            if m in indeg:
                indeg[m] += 1

    dp: dict = {n: None for n in all_nets}
    for s in seeds:
        if s in dp:
            dp[s] = 0

    queue = deque(n for n in all_nets if indeg[n] == 0)
    while queue:
        n = queue.popleft()
        dn = dp[n]
        for m, _g in adj.get(n, []):
            if m not in indeg:
                continue
            if dn is not None:
                cand = dn + 1
                if dp[m] is None or cand > dp[m]:
                    dp[m] = cand
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    return dp


# ---------------------------------------------------------------------------
# Point-to-point path queries
# ---------------------------------------------------------------------------

def path_exists(
    netlist: Netlist, src: str, dst: str, avoid: str | None = None
) -> bool:
    """Whether a combinational path src->dst exists, optionally avoiding a node."""
    fwd, _ = _build_net_graph(netlist)
    s = _resolve_src(netlist, src)
    d = _resolve_dst(netlist, dst)
    if s is None or d is None:
        return False
    blocked_nets, blocked_gates = _split_node(netlist, avoid)
    if s in blocked_nets or d in blocked_nets:
        return False
    return d in _reachable(fwd, [s], blocked_nets, blocked_gates)


def enumerate_paths(
    netlist: Netlist, src: str, dst: str, limit: int = 2000
) -> dict:
    """Enumerate combinational paths src->dst as net / gate sequences."""
    fwd, bwd = _build_net_graph(netlist)
    s = _resolve_src(netlist, src)
    d = _resolve_dst(netlist, dst)
    paths: list = []
    truncated = False
    if s is not None and d is not None:
        # Only follow nets that can still reach dst; avoids exploring dead
        # branches that fan out to unrelated outputs in large designs.
        to_dst = _reachable(bwd, [d])
        stack = [(s, (s,), ())]
        while stack:
            net, npath, gpath = stack.pop()
            if net == d:
                paths.append({"nets": list(npath), "gates": list(gpath)})
                if len(paths) >= limit:
                    truncated = True
                    break
                continue
            for nxt, gname in fwd.get(net, []):
                if nxt not in to_dst or nxt in npath:
                    continue
                stack.append((nxt, npath + (nxt,), gpath + (gname,)))
    return {
        "src": s,
        "dst": d,
        "paths": paths,
        "count": len(paths),
        "truncated": truncated,
    }


def _point_depth(netlist: Netlist, src: str, dst: str) -> int | None:
    fwd, bwd = _build_net_graph(netlist)
    s = _resolve_src(netlist, src)
    d = _resolve_dst(netlist, dst)
    if s is None or d is None:
        return None
    all_nets = _all_nets(netlist, fwd, bwd)
    all_nets.add(s)
    all_nets.add(d)
    dp = _longest_dp(fwd, all_nets, {s})
    return dp.get(d)


def max_logic_depth(netlist: Netlist, src: str, dst: str) -> int | None:
    """Maximum logic depth (gate levels) on any path src->dst; None if none."""
    return _point_depth(netlist, src, dst)


def longest_comb_path_depth(netlist: Netlist, src: str, dst: str) -> int | None:
    """Longest combinational path depth src->dst (same metric as max_logic_depth)."""
    return _point_depth(netlist, src, dst)


def critical_path_depth(netlist: Netlist, src: str, dst: str) -> int | None:
    """Critical (longest) path depth src->dst."""
    return _point_depth(netlist, src, dst)


def all_paths_pass_through(
    netlist: Netlist, src: str, dst: str, node: str
) -> dict:
    """Whether every combinational path src->dst passes through ``node``."""
    fwd, _ = _build_net_graph(netlist)
    s = _resolve_src(netlist, src)
    d = _resolve_dst(netlist, dst)
    reachable = s is not None and d is not None and d in _reachable(fwd, [s])
    if not reachable:
        return {"src": s, "dst": d, "node": node,
                "reachable": False, "all_pass": False}
    blocked_nets, blocked_gates = _split_node(netlist, node)
    survives = d in _reachable(fwd, [s], blocked_nets, blocked_gates)
    return {"src": s, "dst": d, "node": node,
            "reachable": True, "all_pass": not survives}


def articulation_points_between(netlist: Netlist, src: str, dst: str) -> dict:
    """Nets through which *every* combinational path src->dst must pass."""
    fwd, bwd = _build_net_graph(netlist)
    s = _resolve_src(netlist, src)
    d = _resolve_dst(netlist, dst)
    if s is None or d is None or d not in _reachable(fwd, [s]):
        return {"src": s, "dst": d, "reachable": False, "points": []}

    forward = _reachable(fwd, [s])
    backward = _reachable(bwd, [d])          # nets that can reach d
    candidates = (forward & backward) - {s, d}

    points: list = []
    for net in sorted(candidates):
        if d not in _reachable(fwd, [s], {net}, set()):
            points.append(net)
    return {"src": s, "dst": d, "reachable": True, "points": points}


# ---------------------------------------------------------------------------
# Design-level depth queries
# ---------------------------------------------------------------------------

def _depth_to_best_sink(netlist: Netlist, seeds: set, sinks: set):
    fwd, bwd = _build_net_graph(netlist)
    all_nets = _all_nets(netlist, fwd, bwd) | seeds | sinks
    dp = _longest_dp(fwd, all_nets, seeds)
    best_net = None
    best_depth = -1
    for sink in sorted(sinks):
        depth = dp.get(sink)
        if depth is not None and depth > best_depth:
            best_depth = depth
            best_net = sink
    if best_net is None:
        return (None, 0, dp)
    return (best_net, best_depth, dp)


def max_comb_depth_pi_to_po(netlist: Netlist) -> dict:
    """Largest PI->PO combinational depth across the whole design."""
    fwd, _ = _build_net_graph(netlist)
    seeds = set(netlist.inputs) | _const_source_nets(netlist, fwd)
    sinks = set(netlist.outputs)
    net, depth, _dp = _depth_to_best_sink(netlist, seeds, sinks)
    return {"output": net, "depth": depth}


def max_pi_to_dff_d_depth(netlist: Netlist) -> dict:
    """Largest combinational depth from any PI to any DFF D pin."""
    fwd, _ = _build_net_graph(netlist)
    seeds = set(netlist.inputs) | _const_source_nets(netlist, fwd)
    sinks = _dff_pin_nets(netlist, "D")
    net, depth, _dp = _depth_to_best_sink(netlist, seeds, sinks)
    return {"dff_d_net": net, "depth": depth}


def max_reg_to_reg_comb_depth(netlist: Netlist) -> dict:
    """Largest register-to-register combinational depth (DFF Q -> DFF D)."""
    seeds = _dff_pin_nets(netlist, "Q")
    sinks = _dff_pin_nets(netlist, "D")
    net, depth, _dp = _depth_to_best_sink(netlist, seeds, sinks)
    return {"dff_d_net": net, "depth": depth}


def outputs_with_depth_gt(netlist: Netlist, n: int) -> list:
    """Primary outputs whose combinational logic depth exceeds ``n``."""
    fwd, bwd = _build_net_graph(netlist)
    seeds = (set(netlist.inputs)
             | _const_source_nets(netlist, fwd)
             | _dff_pin_nets(netlist, "Q"))
    all_nets = _all_nets(netlist, fwd, bwd) | seeds
    dp = _longest_dp(fwd, all_nets, seeds)
    result: list = []
    for po in sorted(netlist.outputs):
        depth = dp.get(po)
        if depth is not None and depth > n:
            result.append((po, depth))
    return result


def paths_length_zero_pi_to_po(netlist: Netlist) -> list:
    """PIs wired straight to a PO with no gate in between (length-0 paths)."""
    return sorted(set(netlist.inputs) & set(netlist.outputs))


def gate_on_max_depth_path(netlist: Netlist, gate: str) -> dict:
    """Whether ``gate`` lies on a maximum-depth combinational path of the design."""
    g = netlist.gates.get(gate)
    if g is None:
        raise ValueError(f"No gate named '{gate}' in the design.")

    fwd, bwd = _build_net_graph(netlist)
    all_nets = _all_nets(netlist, fwd, bwd)
    fwd_seeds = (set(netlist.inputs)
                 | _const_source_nets(netlist, fwd)
                 | _dff_pin_nets(netlist, "Q"))
    bwd_seeds = set(netlist.outputs) | _dff_pin_nets(netlist, "D")

    fdepth = _longest_dp(fwd, all_nets, fwd_seeds)
    bdepth = _longest_dp(bwd, all_nets, bwd_seeds)

    global_max = -1
    for net in all_nets:
        f = fdepth.get(net)
        b = bdepth.get(net)
        if f is not None and b is not None and f + b > global_max:
            global_max = f + b

    out = g.out
    f = fdepth.get(out)
    b = bdepth.get(out)
    through = f + b if (f is not None and b is not None) else None
    on_path = through is not None and through == global_max and global_max >= 0
    return {
        "gate": gate,
        "on_max_path": on_path,
        "path_depth_through": through,
        "max_depth": global_max if global_max >= 0 else 0,
    }


def register_to_register_paths(netlist: Netlist) -> list:
    """List register-to-register pairs connected by a combinational path."""
    fwd, _ = _build_net_graph(netlist)
    d_net_to_ff: dict = defaultdict(list)
    q_ffs: list = []
    for g in netlist.gates.values():
        if g.type != "dff":
            continue
        d = g.ports.get("D")
        q = g.ports.get("Q")
        if d and not _is_const(d):
            d_net_to_ff[d].append(g.name)
        if q and not _is_const(q):
            q_ffs.append((g.name, q))

    pairs: set = set()
    for src_ff, q in q_ffs:
        reached = _reachable(fwd, [q])
        for d_net in reached:
            for dst_ff in d_net_to_ff.get(d_net, []):
                pairs.add((src_ff, dst_ff))
    return [{"from": a, "to": b} for a, b in sorted(pairs)]


def wire_is_cut_between_pi_po(netlist: Netlist, wire: str) -> dict:
    """Whether removing ``wire`` disconnects every PI from every PO."""
    fwd, _ = _build_net_graph(netlist)
    pis = list(set(netlist.inputs) | _const_source_nets(netlist, fwd))
    pos = set(netlist.outputs)

    reached = _reachable(fwd, pis)
    connected = bool(pos & reached)

    reached_avoid = _reachable(fwd, pis, {wire}, set())
    connected_avoid = bool(pos & reached_avoid)

    return {
        "wire": wire,
        "pi_po_connected": connected,
        "is_cut": connected and not connected_avoid,
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict = {
    "path_exists": {
        "func": lambda nl, a: path_exists(nl, a["src"], a["dst"], a.get("avoid")),
        "required_args": ("src", "dst"),
        "optional_args": ("avoid",),
        "category": "path_depth_query",
        "public": True,
        "description": "Check whether a combinational path exists between two nodes, optionally avoiding a node.",
    },
    "enumerate_paths": {
        "func": lambda nl, a: enumerate_paths(nl, a["src"], a["dst"]),
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "public": True,
        "description": "Enumerate all combinational paths between two nodes.",
    },
    "max_logic_depth": {
        "func": lambda nl, a: max_logic_depth(nl, a["src"], a["dst"]),
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "public": True,
        "description": "Maximum logic depth (gate levels) on any path between two nodes.",
    },
    "longest_comb_path_depth": {
        "func": lambda nl, a: longest_comb_path_depth(nl, a["src"], a["dst"]),
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "public": True,
        "description": "Longest combinational path depth between two nodes.",
    },
    "critical_path_depth": {
        "func": lambda nl, a: critical_path_depth(nl, a["src"], a["dst"]),
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "public": True,
        "description": "Critical (longest) path depth between two nodes.",
    },
    "max_comb_depth_pi_to_po": {
        "func": lambda nl, _a: max_comb_depth_pi_to_po(nl),
        "required_args": (),
        "category": "path_depth_query",
        "public": True,
        "description": "Largest PI-to-PO combinational depth across the whole design.",
    },
    "paths_length_zero_pi_to_po": {
        "func": lambda nl, _a: paths_length_zero_pi_to_po(nl),
        "required_args": (),
        "category": "path_depth_query",
        "public": True,
        "description": "Primary inputs wired directly to a primary output (length-0 paths).",
    },
    "all_paths_pass_through": {
        "func": lambda nl, a: all_paths_pass_through(nl, a["src"], a["dst"], a["node"]),
        "required_args": ("src", "dst", "node"),
        "category": "path_depth_query",
        "public": True,
        "description": "Whether every path between two nodes passes through a given node.",
    },
    "gate_on_max_depth_path": {
        "func": lambda nl, a: gate_on_max_depth_path(nl, a["gate"]),
        "required_args": ("gate",),
        "category": "path_depth_query",
        "public": True,
        "description": "Whether a gate lies on a maximum-depth combinational path of the design.",
    },
    "register_to_register_paths": {
        "func": lambda nl, _a: register_to_register_paths(nl),
        "required_args": (),
        "category": "path_depth_query",
        "public": True,
        "description": "List register-to-register pairs connected by a combinational path.",
    },
    "max_reg_to_reg_comb_depth": {
        "func": lambda nl, _a: max_reg_to_reg_comb_depth(nl),
        "required_args": (),
        "category": "path_depth_query",
        "public": True,
        "description": "Largest register-to-register (DFF Q to DFF D) combinational depth.",
    },
    "max_pi_to_dff_d_depth": {
        "func": lambda nl, _a: max_pi_to_dff_d_depth(nl),
        "required_args": (),
        "category": "path_depth_query",
        "public": True,
        "description": "Largest combinational depth from any PI to any DFF D pin.",
    },
    "outputs_with_depth_gt": {
        "func": lambda nl, a: outputs_with_depth_gt(nl, int(a["n"])),
        "required_args": ("n",),
        "category": "path_depth_query",
        "public": True,
        "description": "Primary outputs whose combinational logic depth exceeds n.",
    },
    "articulation_points_between": {
        "func": lambda nl, a: articulation_points_between(nl, a["src"], a["dst"]),
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "public": True,
        "description": "Nets through which every combinational path between two nodes must pass.",
    },
    "wire_is_cut_between_pi_po": {
        "func": lambda nl, a: wire_is_cut_between_pi_po(nl, a["wire"]),
        "required_args": ("wire",),
        "category": "path_depth_query",
        "public": True,
        "description": "Whether a wire is a cut separating all primary inputs from all primary outputs.",
    },
}

PUBLIC_OP_TABLE = {name: meta for name, meta in OP_TABLE.items() if meta.get("public")}


def get_public_op_catalog() -> list:
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


def _normalize_args(op: str, args: dict) -> dict:
    args = dict(args)
    if op in ("path_exists", "enumerate_paths", "max_logic_depth",
              "longest_comb_path_depth", "critical_path_depth",
              "all_paths_pass_through", "articulation_points_between"):
        args.setdefault("src", args.get("source") or args.get("from") or args.get("start"))
        args.setdefault("dst", args.get("dest") or args.get("target")
                        or args.get("to") or args.get("end"))
    if op == "path_exists":
        args.setdefault("avoid", args.get("avoid_node") or args.get("exclude"))
    if op == "all_paths_pass_through":
        args.setdefault("node", args.get("through") or args.get("via")
                        or args.get("gate"))
    if op == "gate_on_max_depth_path":
        args.setdefault("gate", args.get("name") or args.get("target"))
    if op == "outputs_with_depth_gt":
        args.setdefault("n", args.get("threshold") or args.get("depth"))
    if op == "wire_is_cut_between_pi_po":
        args.setdefault("wire", args.get("signal") or args.get("net"))
    return args


def dispatch_path_op(
    netlist: Netlist,
    request: dict,
    *,
    public_only: bool = False,
) -> dict:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown path analysis op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](netlist, args)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_path_result(payload: dict) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "path_exists":
        ans = "Yes" if result else "No"
        extra = f" (avoiding {args['avoid']})" if args.get("avoid") else ""
        return f"Path from {args['src']} to {args['dst']}{extra}: {ans}"

    if op == "enumerate_paths":
        from tools.history_compact import MAX_PATH_PREVIEW

        count = result["count"]
        header = (
            f"Paths from {result['src']} to {result['dst']}: {count}"
            + (" (truncated)" if result["truncated"] else "")
        )
        lines = [header]
        preview = result["paths"][:MAX_PATH_PREVIEW]
        for i, p in enumerate(preview, 1):
            chain = " -> ".join(p["nets"])
            gates = ", ".join(p["gates"]) if p["gates"] else "(direct)"
            lines.append(f"  {i}. {chain}  [gates: {gates}]")
        if count > len(preview):
            lines.append(
                f"  ... ({count - len(preview)} more path(s) omitted from display)"
            )
        return "\n".join(lines)

    if op in ("max_logic_depth", "longest_comb_path_depth", "critical_path_depth"):
        if result is None:
            return f"No combinational path from {args['src']} to {args['dst']}."
        return f"Depth from {args['src']} to {args['dst']}: {result}"

    if op == "max_comb_depth_pi_to_po":
        if result["output"] is None:
            return "No PI-to-PO combinational path found."
        return (f"Maximum PI-to-PO combinational depth: {result['depth']} "
                f"(at output {result['output']})")

    if op == "max_pi_to_dff_d_depth":
        if result["dff_d_net"] is None:
            return "No PI-to-DFF-D combinational path found."
        return (f"Maximum PI-to-DFF-D depth: {result['depth']} "
                f"(at D net {result['dff_d_net']})")

    if op == "max_reg_to_reg_comb_depth":
        if result["dff_d_net"] is None:
            return "No register-to-register combinational path found."
        return (f"Maximum register-to-register depth: {result['depth']} "
                f"(at D net {result['dff_d_net']})")

    if op == "outputs_with_depth_gt":
        if not result:
            return f"No outputs with depth greater than {args['n']}."
        body = ", ".join(f"{po} (depth={d})" for po, d in result)
        return f"Outputs with depth > {args['n']} ({len(result)}): {body}"

    if op == "paths_length_zero_pi_to_po":
        if not result:
            return "No length-0 PI-to-PO paths."
        return f"Length-0 PI-to-PO nets ({len(result)}): {', '.join(result)}"

    if op == "all_paths_pass_through":
        if not result["reachable"]:
            return (f"No combinational path from {result['src']} "
                    f"to {result['dst']}.")
        ans = "Yes" if result["all_pass"] else "No"
        return (f"All paths from {result['src']} to {result['dst']} pass "
                f"through {result['node']}: {ans}")

    if op == "gate_on_max_depth_path":
        ans = "Yes" if result["on_max_path"] else "No"
        return (f"Gate {result['gate']} on a maximum-depth path: {ans} "
                f"(path depth through it = {result['path_depth_through']}, "
                f"design max depth = {result['max_depth']})")

    if op == "register_to_register_paths":
        if not result:
            return "No register-to-register paths."
        lines = [f"Register-to-register paths ({len(result)}):"]
        for p in result:
            lines.append(f"  {p['from']} -> {p['to']}")
        return "\n".join(lines)

    if op == "articulation_points_between":
        if not result["reachable"]:
            return (f"No combinational path from {result['src']} "
                    f"to {result['dst']}.")
        if not result["points"]:
            return (f"No articulation points between {result['src']} "
                    f"and {result['dst']}.")
        return (f"Articulation points between {result['src']} and "
                f"{result['dst']} ({len(result['points'])}): "
                f"{', '.join(result['points'])}")

    if op == "wire_is_cut_between_pi_po":
        ans = "Yes" if result["is_cut"] else "No"
        return f"Wire {result['wire']} is a PI-PO cut: {ans}"

    return f"{op}: {result}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"

# Filler words that may precede a net/gate name in natural language, e.g.
# "from input n12", "node n1127", "primary output n25[0]". They are consumed
# (optionally) so the captured group is the actual net name.
_FILLER = r"(?:primary\s+|the\s+)*(?:input|output|node|signal|wire|gate|net|pin|port)s?\s+"
# A net name, tolerant of an optional leading filler word.
_NM = rf"(?:{_FILLER})?([\w\[\]\.]+)"


def _clean_name(name: str) -> str:
    """Strip trailing sentence punctuation captured from natural language
    (e.g. "n1127." -> "n1127"). Net names never end in these characters,
    while bus indices like "n25[0]" end in ']' and are preserved."""
    return name.rstrip(".,;:!?'\")") if name else name


def _extract_pair(line: str):
    """Extract a (src, dst) node pair from common NL connective phrasings."""
    patterns = (
        rf"from\s+{_NM}\s+(?:to|and)\s+{_NM}",
        rf"connecting\s+{_NM}\s+(?:to|and|with|->|and to)\s+{_NM}",
        rf"between\s+{_NM}\s+and\s+{_NM}",
        rf"originating\s+(?:at|from|in)\s+{_NM}.*?terminating\s+(?:at|in|on)\s+{_NM}",
        rf"starting\s+(?:at|from|in)\s+{_NM}.*?ending\s+(?:at|in|on)\s+{_NM}",
    )
    for pat in patterns:
        if m := re.search(pat, line, re.I):
            return _clean_name(m.group(1)), _clean_name(m.group(2))
    return None


def _extract_avoid(line: str):
    """Extract the node a path must avoid, from 'avoiding X', 'without X',
    'does not traverse/pass through X', etc."""
    if m := re.search(
        rf"(?:avoid(?:ing)?|without)\s+(?:passing\s+through\s+|traversing\s+|"
        rf"going\s+through\s+)?{_NM}",
        line, re.I,
    ):
        return _clean_name(m.group(1))
    if m := re.search(
        rf"(?:not|n't)\s+(?:traverse|traversing|pass(?:ing)?\s+through|"
        rf"go(?:ing)?\s+through|visit(?:ing)?|cross(?:ing)?)\s+{_NM}",
        line, re.I,
    ):
        return _clean_name(m.group(1))
    return None


def try_parse_path_request(line: str) -> dict | None:
    low = line.lower()
    pair = _extract_pair(line)

    # all paths pass through a node (must check before path_exists/depth)
    if pair and re.search(r"\b(?:all|every|each)\b", low) \
            and re.search(r"pass(?:es)?\s+through|go(?:es)?\s+through|"
                          r"route[d]?\s+through|via", low):
        node = None
        if tm := re.search(
            rf"(?:pass(?:es)?|go(?:es)?|route[d]?)\s+through\s+{_NM}", line, re.I
        ):
            node = _clean_name(tm.group(1))
        elif tm := re.search(rf"\bvia\s+{_NM}", line, re.I):
            node = _clean_name(tm.group(1))
        if node is not None:
            return {"op": "all_paths_pass_through",
                    "args": {"src": pair[0], "dst": pair[1], "node": node}}

    # articulation points
    if pair and re.search(r"articulation point", low):
        return {"op": "articulation_points_between",
                "args": {"src": pair[0], "dst": pair[1]}}

    # point-to-point depth
    if pair and re.search(r"\bdepth\b|how\s+(?:deep|many\s+levels)|"
                          r"\blevels?\b", low):
        if "critical" in low:
            op = "critical_path_depth"
        elif "longest" in low:
            op = "longest_comb_path_depth"
        else:
            op = "max_logic_depth"
        return {"op": op, "args": {"src": pair[0], "dst": pair[1]}}

    # enumerate paths
    if pair and re.search(
        r"enumerat|list\s+(?:all|every|each)|all\s+paths?|every\s+path|"
        r"each\s+path|complete\s+(?:list|enumeration|set).*paths?|"
        r"originating", low
    ):
        return {"op": "enumerate_paths",
                "args": {"src": pair[0], "dst": pair[1]}}

    # path existence, optionally avoiding a node
    if pair and re.search(
        r"\bpath\b|connect|reach|exists?\b|is\s+there|does\s+.*\bpath\b", low
    ):
        avoid = _extract_avoid(line)
        args = {"src": pair[0], "dst": pair[1]}
        if avoid is not None:
            args["avoid"] = avoid
        return {"op": "path_exists", "args": args}

    # design-wide depth queries
    if re.search(r"(?:max|maximum|longest).*(?:pi|primary input).*(?:po|primary output)", low) \
            or re.search(r"longest combinational path .*design", low):
        return {"op": "max_comb_depth_pi_to_po", "args": {}}
    if re.search(r"(?:pi|primary input).*(?:dff|flop|register).*d (?:pin|input)", low):
        return {"op": "max_pi_to_dff_d_depth", "args": {}}
    if re.search(r"register[- ]to[- ]register.*depth", low) or \
            re.search(r"max.*reg.*reg.*depth", low):
        return {"op": "max_reg_to_reg_comb_depth", "args": {}}
    if re.search(r"register[- ]to[- ]register paths?", low):
        return {"op": "register_to_register_paths", "args": {}}

    # length-0 PI->PO
    if re.search(r"length[- ]?(?:0|zero).*(?:pi|primary input).*(?:po|primary output)", low) \
            or re.search(r"primary inputs?.*directly.*primary outputs?", low):
        return {"op": "paths_length_zero_pi_to_po", "args": {}}

    # outputs with depth > n
    if m := re.search(r"outputs? (?:with|whose).*depth (?:greater than|>|exceeds?)\s*(\d+)", line, re.I):
        return {"op": "outputs_with_depth_gt", "args": {"n": int(m.group(1))}}

    # gate on max-depth path
    if m := re.search(rf"(?:is\s+)?{_NAME}\s+on (?:the|a) (?:max|maximum|critical).*path", line, re.I):
        return {"op": "gate_on_max_depth_path", "args": {"gate": m.group(1)}}

    # wire is a PI-PO cut
    if m := re.search(rf"(?:is\s+)?{_NAME}\s+a (?:cut|cut[- ]point).*(?:pi|primary input).*(?:po|primary output)", line, re.I):
        return {"op": "wire_is_cut_between_pi_po", "args": {"wire": m.group(1)}}
    if m := re.search(rf"cut .*between (?:pi|primary inputs?) and (?:po|primary outputs?).*\b{_NAME}", line, re.I):
        return {"op": "wire_is_cut_between_pi_po", "args": {"wire": m.group(1)}}

    return None
