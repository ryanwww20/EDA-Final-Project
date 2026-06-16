"""
Fanin / fanout / cone analysis on top of the netlist_twoside IR.

Builds wire_driver / wire_loads indexes from an existing Netlist and exposes
combinational graph queries.  DFF Q is a fanin boundary; DFF D is a fanout
boundary (no sequential traversal through the flop).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from algorithm.graph_traversal import dfs
from netlist_twoside import Gate, Netlist

_CONST = re.compile(r"1'b[01]")

# ---------------------------------------------------------------------------
# IR adapter helpers — hide netlist_twoside field names
# ---------------------------------------------------------------------------

def get_all_gates(netlist: Netlist) -> list[Gate]:
    return list(netlist.gates.values())


def get_gate_name(gate: Gate) -> str:
    return gate.name


def get_gate_type(gate: Gate) -> str:
    return gate.type


def get_gate_inputs(gate: Gate) -> list[str]:
    if gate.type == "dff":
        d = gate.ports.get("D")
        return [d] if d else []
    return list(gate.ins)


def get_gate_output(gate: Gate) -> str | None:
    return gate.out


def get_combinational_input_nets(netlist: Netlist, gate: Gate) -> list[str]:
    return [n for n in netlist.combinational_fanins(gate) if n]


def get_primary_inputs(netlist: Netlist) -> set[str]:
    return set(netlist.inputs)


def get_primary_outputs(netlist: Netlist) -> set[str]:
    return set(netlist.outputs)


def get_all_signals(netlist: Netlist) -> set[str]:
    signals: set[str] = set()
    signals |= netlist.inputs
    signals |= netlist.outputs
    for gate in get_all_gates(netlist):
        out = get_gate_output(gate)
        if out:
            signals.add(out)
        for net in get_gate_inputs(gate):
            if net:
                signals.add(net)
        if gate.type == "dff":
            for pin in ("D", "CK", "RN", "SN", "Q"):
                net = gate.ports.get(pin)
                if net:
                    signals.add(net)
    return signals


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


def _is_boundary_source(netlist: Netlist, net: str) -> bool:
    return net in netlist.inputs or _is_const(net)


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------

def build_fanin_fanout_index(netlist: Netlist) -> dict[str, Any]:
    """Build driver/load indexes from a Netlist.

    ``wire_driver`` is kept as a compatibility view and only contains signals
    with a unique driver.  ``wire_drivers`` carries the full multi-driver view.
    """
    wire_driver: dict[str, tuple[str, str]] = {}
    wire_drivers: dict[str, list[tuple[str, str]]] = defaultdict(list)
    wire_loads: dict[str, list[tuple[str, str]]] = defaultdict(list)
    gate_by_name = netlist.gates
    output_to_gates: dict[str, list[str]] = defaultdict(list)

    for pi in sorted(netlist.inputs):
        wire_drivers[pi].append(("PI", pi))

    for gate in get_all_gates(netlist):
        gname = get_gate_name(gate)
        out = get_gate_output(gate)
        if out:
            wire_drivers[out].append(("GATE", gname))
            output_to_gates[out].append(gname)

        if gate.type == "dff":
            pin_nets = [
                ("D", gate.ports.get("D")),
                ("CK", gate.ports.get("CK")),
                ("RN", gate.ports.get("RN")),
                ("SN", gate.ports.get("SN")),
            ]
            for pin, net in pin_nets:
                if net and not _is_const(net):
                    wire_loads[net].append((gname, pin))
        else:
            for idx, net in enumerate(get_gate_inputs(gate)):
                if net and not _is_const(net):
                    wire_loads[net].append((gname, f"in{idx}"))

    for net in get_all_signals(netlist):
        if _is_const(net) and net not in wire_drivers:
            wire_drivers[net].append(("CONST", net))

    for net in wire_loads:
        wire_loads[net].sort(key=lambda item: (item[0], item[1]))
    for net in wire_drivers:
        wire_drivers[net].sort(key=lambda item: (item[0], item[1]))
        if len(wire_drivers[net]) == 1:
            wire_driver[net] = wire_drivers[net][0]

    return {
        "wire_driver": wire_driver,
        "wire_drivers": dict(wire_drivers),
        "wire_loads": dict(wire_loads),
        "gate_by_name": gate_by_name,
        "output_to_gate": {
            net: gates[0]
            for net, gates in output_to_gates.items()
            if len(gates) == 1
        },
        "output_to_gates": dict(output_to_gates),
    }


def get_driver(index: dict[str, Any], signal: str) -> tuple[str, str] | None:
    return index["wire_driver"].get(signal)


def get_drivers(index: dict[str, Any], signal: str) -> list[tuple[str, str]]:
    return list(index.get("wire_drivers", {}).get(signal, []))


def _load_matches_filter(
    index: dict[str, Any], gate_name: str, pin: str, load_filter: str
) -> bool:
    if load_filter == "all":
        return True

    gate = index["gate_by_name"][gate_name]
    if load_filter == "data":
        return gate.type != "dff" or pin == "D"
    if load_filter == "combinational":
        return gate.type != "dff"
    raise ValueError(f"Unknown load_filter: {load_filter}")


def get_loads(
    index: dict[str, Any], signal: str, load_filter: str = "all"
) -> list[tuple[str, str]]:
    return [
        (gate_name, pin)
        for gate_name, pin in index["wire_loads"].get(signal, [])
        if _load_matches_filter(index, gate_name, pin, load_filter)
    ]


def resolve_to_signal(
    netlist: Netlist, index: dict[str, Any], gate_or_signal: str
) -> str:
    if gate_or_signal in index["gate_by_name"]:
        gate = index["gate_by_name"][gate_or_signal]
        out = get_gate_output(gate)
        if not out:
            raise ValueError(f"Gate '{gate_or_signal}' has no output signal.")
        return out
    return gate_or_signal


def _load_gate_names(
    index: dict[str, Any], signal: str, load_filter: str = "all"
) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for gate_name, _pin in get_loads(index, signal, load_filter):
        if gate_name not in seen:
            seen.add(gate_name)
            names.append(gate_name)
    return sorted(names)


# ---------------------------------------------------------------------------
# Immediate fanin / fanout
# ---------------------------------------------------------------------------

def _predecessor_gates(
    netlist: Netlist, index: dict[str, Any], gate_name: str
) -> list[str]:
    gate = index["gate_by_name"][gate_name]
    preds: list[str] = []
    seen: set[str] = set()
    for net in get_combinational_input_nets(netlist, gate):
        if _is_boundary_source(netlist, net):
            continue
        for drv in get_drivers(index, net):
            if drv[0] != "GATE":
                continue
            pname = drv[1]
            if pname not in seen:
                seen.add(pname)
                preds.append(pname)
    return sorted(preds)


def immediate_fanin_gates(netlist: Netlist, gate_or_signal: str) -> list[str]:
    index = build_fanin_fanout_index(netlist)

    if gate_or_signal in index["gate_by_name"]:
        return _predecessor_gates(netlist, index, gate_or_signal)

    preds: set[str] = set()
    for drv in get_drivers(index, gate_or_signal):
        if drv[0] == "GATE":
            preds.update(_predecessor_gates(netlist, index, drv[1]))
    return sorted(preds)


def immediate_fanout_gates(netlist: Netlist, gate_or_signal: str) -> list[str]:
    index = build_fanin_fanout_index(netlist)
    signal = resolve_to_signal(netlist, index, gate_or_signal)
    return _load_gate_names(index, signal)


def immediate_data_fanout_gates(netlist: Netlist, gate_or_signal: str) -> list[str]:
    index = build_fanin_fanout_index(netlist)
    signal = resolve_to_signal(netlist, index, gate_or_signal)
    return _load_gate_names(index, signal, "data")


# ---------------------------------------------------------------------------
# Transitive cones
# ---------------------------------------------------------------------------

def _fanin_cone_starts(index: dict[str, Any], target: str) -> list[str]:
    if target in index["gate_by_name"]:
        return [target]
    return [drv[1] for drv in get_drivers(index, target) if drv[0] == "GATE"]


def _fanin_gate_neighbors(
    netlist: Netlist, index: dict[str, Any], gname: str
) -> list[str]:
    gate = index["gate_by_name"][gname]

    preds: list[str] = []
    for net in get_combinational_input_nets(netlist, gate):
        if _is_boundary_source(netlist, net):
            continue
        for drv in get_drivers(index, net):
            if drv[0] != "GATE":
                continue
            preds.append(drv[1])
    return preds


def transitive_fanin_cone(netlist: Netlist, target: str) -> list[str]:
    index = build_fanin_fanout_index(netlist)
    starts = _fanin_cone_starts(index, target)
    if not starts:
        return []

    target_is_gate = target in index["gate_by_name"]

    def should_expand(gname: str) -> bool:
        gate = index["gate_by_name"][gname]
        return gate.type != "dff" or (target_is_gate and gname == target)

    visited = dfs(
        starts,
        lambda gname: _fanin_gate_neighbors(netlist, index, gname),
        should_expand=should_expand,
    )
    return sorted(visited)


def _fanout_net_neighbors(
    index: dict[str, Any],
    net: str,
    collected: set[str],
    load_filter: str = "all",
) -> list[str]:
    next_nets: list[str] = []
    for gate_name, _pin in get_loads(index, net, load_filter):
        collected.add(gate_name)
        gate = index["gate_by_name"][gate_name]
        if gate.type == "dff":
            continue
        out = get_gate_output(gate)
        if out:
            next_nets.append(out)
    return next_nets


def transitive_fanout_cone(netlist: Netlist, source: str) -> list[str]:
    index = build_fanin_fanout_index(netlist)
    signal = resolve_to_signal(netlist, index, source)

    collected: set[str] = set()
    dfs(
        [signal],
        lambda net: _fanout_net_neighbors(index, net, collected),
    )
    return sorted(collected)


def count_fanin_cone_gates(netlist: Netlist, target: str) -> int:
    return len(transitive_fanin_cone(netlist, target))


def count_fanout_cone_gates(netlist: Netlist, source: str) -> int:
    return len(transitive_fanout_cone(netlist, source))


def shared_fanin_cone_gates(
    netlist: Netlist, target1: str, target2: str
) -> list[str]:
    cone1 = set(transitive_fanin_cone(netlist, target1))
    cone2 = set(transitive_fanin_cone(netlist, target2))
    return sorted(cone1 & cone2)


# ---------------------------------------------------------------------------
# Design-level summaries
# ---------------------------------------------------------------------------

def _highest_fanout_signal(
    netlist: Netlist, load_filter: str = "all"
) -> tuple[str, int]:
    index = build_fanin_fanout_index(netlist)
    best_signal = ""
    best_count = -1
    for signal in sorted(index["wire_loads"]):
        count = len(get_loads(index, signal, load_filter))
        if count > best_count:
            best_count = count
            best_signal = signal
    if best_count < 0:
        return ("", 0)
    return (best_signal, best_count)


def highest_fanout_signal(netlist: Netlist) -> tuple[str, int]:
    return _highest_fanout_signal(netlist, "all")


def highest_data_fanout_signal(netlist: Netlist) -> tuple[str, int]:
    return _highest_fanout_signal(netlist, "data")


def _highest_fanout_primary_input(
    netlist: Netlist, load_filter: str = "all"
) -> tuple[str, int]:
    index = build_fanin_fanout_index(netlist)
    best_pi = ""
    best_count = -1
    for pi in sorted(get_primary_inputs(netlist)):
        count = len(get_loads(index, pi, load_filter))
        if count > best_count:
            best_count = count
            best_pi = pi
    if best_count < 0:
        return ("", 0)
    return (best_pi, best_count)


def highest_fanout_primary_input(netlist: Netlist) -> tuple[str, int]:
    return _highest_fanout_primary_input(netlist, "all")


def highest_data_fanout_primary_input(netlist: Netlist) -> tuple[str, int]:
    return _highest_fanout_primary_input(netlist, "data")


def largest_fanin_cone_output(netlist: Netlist) -> tuple[str, int]:
    best_po = ""
    best_size = -1
    for po in sorted(get_primary_outputs(netlist)):
        size = count_fanin_cone_gates(netlist, po)
        if size > best_size:
            best_size = size
            best_po = po
    if best_size < 0:
        return ("", 0)
    return (best_po, best_size)


# ---------------------------------------------------------------------------
# Dispatcher for main.py
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "immediate_fanin_gates": {
        "func": lambda nl, a: immediate_fanin_gates(nl, a["gate_or_signal"]),
        "required_args": ("gate_or_signal",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return gates that directly drive the inputs of a gate or signal.",
    },
    "immediate_fanout_gates": {
        "func": lambda nl, a: immediate_fanout_gates(nl, a["gate_or_signal"]),
        "required_args": ("gate_or_signal",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return gates directly loaded by a gate output or signal.",
    },
    "immediate_data_fanout_gates": {
        "func": lambda nl, a: immediate_data_fanout_gates(nl, a["gate_or_signal"]),
        "required_args": ("gate_or_signal",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return data-path gates loaded by a gate output or signal, excluding DFF clock/reset/set pins.",
    },
    "transitive_fanin_cone": {
        "func": lambda nl, a: transitive_fanin_cone(nl, a["target"]),
        "required_args": ("target",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return all gates in the transitive fanin cone of a target gate or signal.",
    },
    "transitive_fanout_cone": {
        "func": lambda nl, a: transitive_fanout_cone(nl, a["source"]),
        "required_args": ("source",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return all gates in the transitive fanout cone of a source gate or signal.",
    },
    "count_fanin_cone_gates": {
        "func": lambda nl, a: count_fanin_cone_gates(nl, a["target"]),
        "required_args": ("target",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the number of gates in the transitive fanin cone of a target.",
    },
    "count_fanout_cone_gates": {
        "func": lambda nl, a: count_fanout_cone_gates(nl, a["source"]),
        "required_args": ("source",),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the number of gates in the transitive fanout cone of a source.",
    },
    "shared_fanin_cone_gates": {
        "func": lambda nl, a: shared_fanin_cone_gates(nl, a["target1"], a["target2"]),
        "required_args": ("target1", "target2"),
        "category": "graph_analysis",
        "public": True,
        "description": "Return gates shared by the fanin cones of two targets.",
    },
    "highest_fanout_signal": {
        "func": lambda nl, _a: highest_fanout_signal(nl),
        "required_args": (),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the signal with the highest direct fanout in the design.",
    },
    "highest_data_fanout_signal": {
        "func": lambda nl, _a: highest_data_fanout_signal(nl),
        "required_args": (),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the signal with the highest data fanout, excluding DFF clock/reset/set pins.",
    },
    "highest_fanout_primary_input": {
        "func": lambda nl, _a: highest_fanout_primary_input(nl),
        "required_args": (),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the primary input with the highest direct fanout.",
    },
    "highest_data_fanout_primary_input": {
        "func": lambda nl, _a: highest_data_fanout_primary_input(nl),
        "required_args": (),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the primary input with the highest data fanout, excluding DFF clock/reset/set pins.",
    },
    "largest_fanin_cone_output": {
        "func": lambda nl, _a: largest_fanin_cone_output(nl),
        "required_args": (),
        "category": "graph_analysis",
        "public": True,
        "description": "Return the primary output whose fanin cone contains the most gates.",
    },
    "build_fanin_fanout_index": {
        "func": lambda nl, _a: build_fanin_fanout_index(nl),
        "required_args": (),
        "category": "internal",
        "public": False,
        "description": "Internal helper to build fanin/fanout index.",
    },
    "get_driver": {
        "func": lambda nl, a: get_driver(build_fanin_fanout_index(nl), a["signal"]),
        "required_args": ("signal",),
        "category": "internal",
        "public": False,
        "description": "Internal helper to query the driver of a signal.",
    },
    "get_drivers": {
        "func": lambda nl, a: get_drivers(build_fanin_fanout_index(nl), a["signal"]),
        "required_args": ("signal",),
        "category": "internal",
        "public": False,
        "description": "Internal helper to query all drivers of a signal.",
    },
    "get_loads": {
        "func": lambda nl, a: get_loads(
            build_fanin_fanout_index(nl),
            a["signal"],
            a.get("load_filter", "all"),
        ),
        "required_args": ("signal",),
        "category": "internal",
        "public": False,
        "description": "Internal helper to query loads of a signal.",
    },
}

PUBLIC_OP_TABLE: dict[str, dict[str, Any]] = {
    "immediate_fanin_gates": OP_TABLE["immediate_fanin_gates"],
    "immediate_fanout_gates": OP_TABLE["immediate_fanout_gates"],
    "immediate_data_fanout_gates": OP_TABLE["immediate_data_fanout_gates"],
    "transitive_fanin_cone": OP_TABLE["transitive_fanin_cone"],
    "transitive_fanout_cone": OP_TABLE["transitive_fanout_cone"],
    "count_fanin_cone_gates": OP_TABLE["count_fanin_cone_gates"],
    "count_fanout_cone_gates": OP_TABLE["count_fanout_cone_gates"],
    "shared_fanin_cone_gates": OP_TABLE["shared_fanin_cone_gates"],
    "highest_fanout_signal": OP_TABLE["highest_fanout_signal"],
    "highest_data_fanout_signal": OP_TABLE["highest_data_fanout_signal"],
    "highest_fanout_primary_input": OP_TABLE["highest_fanout_primary_input"],
    "highest_data_fanout_primary_input": OP_TABLE["highest_data_fanout_primary_input"],
    "largest_fanin_cone_output": OP_TABLE["largest_fanin_cone_output"],
}


def get_public_op_catalog() -> list[dict[str, Any]]:
    """Return LLM-facing operation metadata (name, args, description)."""
    catalog = []
    for name, meta in PUBLIC_OP_TABLE.items():
        catalog.append({
            "op": name,
            "required_args": list(meta["required_args"]),
            "category": meta["category"],
            "description": meta["description"],
        })
    return catalog


def _normalize_args(op: str, args: dict[str, Any]) -> dict[str, Any]:
    """Accept alternate arg names used in prompts or docs."""
    args = dict(args)
    if op in ("immediate_fanin_gates", "immediate_fanout_gates", "immediate_data_fanout_gates"):
        args.setdefault("gate_or_signal", args.get("source") or args.get("target"))
    if op in ("transitive_fanin_cone", "count_fanin_cone_gates"):
        args.setdefault("target", args.get("gate_or_signal"))
    if op in ("transitive_fanout_cone", "count_fanout_cone_gates"):
        args.setdefault("source", args.get("gate_or_signal"))
    return args


def dispatch_fanin_fanout_op(
    netlist: Netlist,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> Any:
    """Execute a structured analysis request against a loaded netlist."""
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown analysis op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [k for k in meta["required_args"] if k not in args]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "result": meta["func"](netlist, args)}


def format_analysis_result(payload: dict[str, Any]) -> str:
    """Turn a dispatcher payload into grader-friendly text."""
    op = payload["op"]
    result = payload["result"]

    if op in ("highest_fanout_signal", "highest_data_fanout_signal"):
        signal, count = result
        return f"Highest fanout signal: {signal} (fanout={count})"
    if op in ("highest_fanout_primary_input", "highest_data_fanout_primary_input"):
        pi, count = result
        return f"Highest fanout primary input: {pi} (fanout={count})"
    if op == "largest_fanin_cone_output":
        po, size = result
        return f"Largest fanin cone output: {po} (cone_size={size})"
    if op in ("count_fanin_cone_gates", "count_fanout_cone_gates"):
        label = "fanin" if "fanin" in op else "fanout"
        return f"Count ({label} cone gates): {result}"
    if isinstance(result, list):
        return f"{op}: {result}"
    if isinstance(result, tuple) and result and isinstance(result[0], str):
        return f"{op}: {result}"
    if isinstance(result, dict):
        return f"{op}: built index with {len(result.get('wire_loads', {}))} loaded signals"
    return f"{op}: {result}"


_NAME = r"([\w\[\]\.]+)"

def try_parse_fanin_fanout_request(line: str) -> dict[str, Any] | None:
    """Rule-based mapping from natural-language prompts to structured ops."""
    low = line.lower()

    if re.search(r"highest fanout primary input", low) or re.search(
        r"which primary input has the highest fanout", low
    ):
        return {"op": "highest_data_fanout_primary_input", "args": {}}
    if m := re.search(rf"highest fanout signal", low):
        return {"op": "highest_fanout_signal", "args": {}}
    if m := re.search(rf"largest fanin cone output", low):
        return {"op": "largest_fanin_cone_output", "args": {}}

    if m := re.search(rf"shared fanin cone (?:of|between)\s+{_NAME}\s+and\s+{_NAME}", line, re.I):
        return {
            "op": "shared_fanin_cone_gates",
            "args": {"target1": m.group(1), "target2": m.group(2)},
        }

    if m := re.search(
        rf"how many gates are in the fanin cone of\s+{_NAME}", line, re.I
    ):
        return {"op": "count_fanin_cone_gates", "args": {"target": m.group(1)}}

    if m := re.search(
        rf"how many gates are in the fanout cone of\s+{_NAME}", line, re.I
    ):
        return {"op": "count_fanout_cone_gates", "args": {"source": m.group(1)}}

    if m := re.search(rf"fanin cone of\s+{_NAME}", line, re.I):
        return {"op": "transitive_fanin_cone", "args": {"target": m.group(1)}}

    if m := re.search(rf"fanout cone of\s+{_NAME}", line, re.I):
        return {"op": "transitive_fanout_cone", "args": {"source": m.group(1)}}

    if m := re.search(rf"immediate fanin of\s+{_NAME}", line, re.I):
        return {"op": "immediate_fanin_gates", "args": {"gate_or_signal": m.group(1)}}

    if m := re.search(rf"immediate fanout of\s+{_NAME}", line, re.I):
        return {"op": "immediate_fanout_gates", "args": {"gate_or_signal": m.group(1)}}

    # test05-style: "fanout of primary input n5" + "gates that n5 drives directly"
    if m := re.search(rf"fanout of primary input\s+({_NAME})", line, re.I):
        return {"op": "immediate_fanout_gates", "args": {"gate_or_signal": m.group(1)}}
    if m := re.search(rf"gates that\s+({_NAME})\s+drives?\s+directly", line, re.I):
        return {"op": "immediate_fanout_gates", "args": {"gate_or_signal": m.group(1)}}

    if re.search(r"\bfanout\b", low) and (m := re.search(_NAME, line)):
        return {"op": "immediate_fanout_gates", "args": {"gate_or_signal": m.group(1)}}

    return None
