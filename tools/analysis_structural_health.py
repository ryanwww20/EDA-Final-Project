"""
Structural health checks on top of the netlist_twoside IR.

Section 1.6 of tools/tool.md.  This module follows the same shape as the
other analysis modules: pure query functions first, then an OP_TABLE
dispatcher, formatter, and a small rule-based prompt parser.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from netlist_twoside import Gate, Netlist

_CONST = re.compile(r"1'b[01]")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


def _norm_type(gtype: str | None) -> str | None:
    if gtype is None:
        return None
    gtype = gtype.strip().lower()
    if gtype in ("all", "any", "*"):
        return None
    return gtype if gtype else None


def _norm_const(val: int | bool | str | None) -> str | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return "1'b1" if val else "1'b0"
    if isinstance(val, int):
        return "1'b1" if val else "1'b0"
    text = str(val).strip().lower()
    if text in ("1", "true", "high", "1'b1"):
        return "1'b1"
    if text in ("0", "false", "low", "1'b0"):
        return "1'b0"
    return str(val).strip()


def _gate_input_items(gate: Gate) -> list[tuple[str, str]]:
    if gate.type == "dff":
        items: list[tuple[str, str]] = []
        for pin in ("D", "CK", "RN", "SN"):
            if pin in gate.ports:
                items.append((pin, gate.ports[pin]))
        return items
    return [(f"in{idx}", net) for idx, net in enumerate(gate.ins)]


def list_gates_with_constant_input(
    netlist: Netlist,
    gtype: str | None = None,
    val: int | bool | str | None = None,
) -> list[dict[str, Any]]:
    """List gates of a type whose input pins are tied to a constant.

    ``gtype=None`` means all gate types; ``val=None`` means either 0 or 1.
    """
    target_type = _norm_type(gtype)
    target_const = _norm_const(val)
    result: list[dict[str, Any]] = []

    for gate in sorted(netlist.gates.values(), key=lambda g: g.name):
        if target_type and gate.type != target_type:
            continue
        const_inputs = [
            {"pin": pin, "value": net}
            for pin, net in _gate_input_items(gate)
            if _is_const(net) and (target_const is None or net == target_const)
        ]
        if const_inputs:
            result.append({
                "name": gate.name,
                "type": gate.type,
                "output": gate.out,
                "constant_inputs": const_inputs,
            })
    return result


def list_gates_with_tied_high(netlist: Netlist) -> list[dict[str, Any]]:
    return list_gates_with_constant_input(netlist, None, "1'b1")


def _observable_sink_nets(netlist: Netlist) -> set[str]:
    sinks = set(netlist.outputs)
    for gate in netlist.gates.values():
        if gate.type == "dff":
            d = gate.ports.get("D")
            if d and not _is_const(d):
                sinks.add(d)
    return sinks


def _live_gates(netlist: Netlist) -> set[str]:
    """Gates that affect a primary output or a DFF D pin."""
    live: set[str] = set()
    seen_nets: set[str] = set()
    stack = list(_observable_sink_nets(netlist))

    while stack:
        net = stack.pop()
        if not net or _is_const(net) or net in netlist.inputs or net in seen_nets:
            continue
        seen_nets.add(net)
        for gate_name in netlist.drivers_of(net):
            gate = netlist.gates.get(gate_name)
            if gate is None:
                continue
            live.add(gate_name)
            for _pin, in_net in _gate_input_items(gate):
                if in_net and not _is_const(in_net):
                    stack.append(in_net)
    return live


def dangling_gates(netlist: Netlist) -> list[str]:
    live = _live_gates(netlist)
    return sorted(name for name in netlist.gates if name not in live)


def has_dangling_gates(netlist: Netlist) -> dict[str, Any]:
    gates = dangling_gates(netlist)
    return {"has_dangling": bool(gates), "gates": gates, "count": len(gates)}


def redundant_gates(netlist: Netlist) -> list[dict[str, Any]]:
    """Conservative structural redundancy detector.

    A gate is reported as redundant if another gate computes the same structural
    expression over the same inputs.  Inputs of commutative gates are sorted.
    """
    signatures: dict[tuple[Any, ...], list[Gate]] = defaultdict(list)
    commutative = {"and", "or", "nand", "nor", "xor", "xnor"}

    for gate in netlist.gates.values():
        if gate.type == "dff":
            continue
        inputs = tuple(gate.ins)
        if gate.type in commutative:
            inputs = tuple(sorted(inputs))
        signatures[(gate.type, inputs)].append(gate)

    result: list[dict[str, Any]] = []
    for gates in signatures.values():
        if len(gates) < 2:
            continue
        gates = sorted(gates, key=lambda g: g.name)
        keeper = gates[0]
        for duplicate in gates[1:]:
            result.append({
                "name": duplicate.name,
                "type": duplicate.type,
                "output": duplicate.out,
                "equivalent_to": keeper.name,
                "reason": "structural_duplicate",
            })
    return result


def has_redundant_gates(netlist: Netlist) -> dict[str, Any]:
    gates = redundant_gates(netlist)
    return {"has_redundant": bool(gates), "gates": gates, "count": len(gates)}


def find_floating_signals(netlist: Netlist) -> dict[str, Any]:
    """Find used-but-undriven input nets and output ports without a driver."""
    floating_inputs: list[dict[str, str]] = []
    for gate in sorted(netlist.gates.values(), key=lambda g: g.name):
        for pin, net in _gate_input_items(gate):
            if not net or _is_const(net) or net in netlist.inputs:
                continue
            if not netlist.drivers_of(net):
                floating_inputs.append({"gate": gate.name, "pin": pin, "signal": net})

    unconnected_outputs = sorted(
        out for out in netlist.outputs
        if out not in netlist.inputs and not netlist.drivers_of(out)
    )
    signals = sorted(
        {item["signal"] for item in floating_inputs} | set(unconnected_outputs)
    )
    return {
        "floating_inputs": floating_inputs,
        "unconnected_outputs": unconnected_outputs,
        "signals": signals,
        "count": len(signals),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "list_gates_with_constant_input": {
        "func": lambda nl, a: list_gates_with_constant_input(
            nl,
            a.get("type"),
            a.get("val"),
        ),
        "required_args": ("type",),
        "optional_args": ("val",),
        "category": "structural_health",
        "public": True,
        "description": "List gates with one or more inputs tied to a constant value.",
    },
    "list_gates_with_tied_high": {
        "func": lambda nl, _a: list_gates_with_tied_high(nl),
        "required_args": (),
        "category": "structural_health",
        "public": True,
        "description": "List gates with one or more input pins tied to 1'b1.",
    },
    "has_dangling_gates": {
        "func": lambda nl, _a: has_dangling_gates(nl),
        "required_args": (),
        "category": "structural_health",
        "public": True,
        "description": "Check whether the design contains gates that do not contribute to observable outputs.",
    },
    "has_redundant_gates": {
        "func": lambda nl, _a: has_redundant_gates(nl),
        "required_args": (),
        "category": "structural_health",
        "public": True,
        "description": "Check whether the design contains structurally redundant gates.",
    },
    "find_floating_signals": {
        "func": lambda nl, _a: find_floating_signals(nl),
        "required_args": (),
        "category": "structural_health",
        "public": True,
        "description": "Find floating gate inputs and unconnected output ports.",
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
    if op == "list_gates_with_constant_input":
        args.setdefault("type", args.get("gate_type") or args.get("gtype"))
        args.setdefault("val", args.get("value") or args.get("constant"))
    return args


def dispatch_structural_health_op(
    netlist: Netlist,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown structural health op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](netlist, args)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_gate_constant_entry(entry: dict[str, Any]) -> str:
    consts = ", ".join(
        f"{item['pin']}={item['value']}" for item in entry["constant_inputs"]
    )
    out = entry.get("output") or "(none)"
    return f"  {entry['name']} ({entry['type'].upper()}): output={out}, {consts}"


def format_structural_health_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "list_gates_with_constant_input":
        gtype = args.get("type")
        val = _norm_const(args.get("val"))
        label = (gtype.upper() if isinstance(gtype, str) else "Gates")
        suffix = f" tied to {val}" if val else " tied to constants"
        if not result:
            return f"{label} with inputs{suffix} (0): (none)"
        lines = [f"{label} with inputs{suffix} ({len(result)}):"]
        lines.extend(_format_gate_constant_entry(entry) for entry in result)
        return "\n".join(lines)

    if op == "list_gates_with_tied_high":
        if not result:
            return "Gates with inputs tied to 1'b1 (0): (none)"
        lines = [f"Gates with inputs tied to 1'b1 ({len(result)}):"]
        lines.extend(_format_gate_constant_entry(entry) for entry in result)
        return "\n".join(lines)

    if op == "has_dangling_gates":
        ans = "Yes" if result["has_dangling"] else "No"
        listing = ", ".join(result["gates"]) if result["gates"] else "(none)"
        return f"Dangling gates present: {ans} (count={result['count']}): {listing}"

    if op == "has_redundant_gates":
        ans = "Yes" if result["has_redundant"] else "No"
        if not result["gates"]:
            return "Redundant gates present: No (count=0): (none)"
        lines = [f"Redundant gates present: {ans} (count={result['count']}):"]
        for item in result["gates"]:
            lines.append(
                f"  {item['name']} ({item['type'].upper()}) duplicates "
                f"{item['equivalent_to']} via {item['reason']}"
            )
        return "\n".join(lines)

    if op == "find_floating_signals":
        if result["count"] == 0:
            return "Floating signals (0): (none)"
        lines = [f"Floating signals ({result['count']}): {', '.join(result['signals'])}"]
        if result["floating_inputs"]:
            lines.append("Floating gate inputs:")
            for item in result["floating_inputs"]:
                lines.append(f"  {item['gate']}.{item['pin']} <- {item['signal']}")
        if result["unconnected_outputs"]:
            lines.append(
                "Unconnected output ports: "
                + ", ".join(result["unconnected_outputs"])
            )
        return "\n".join(lines)

    return f"{op}: {result}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_GATE_WORD = r"(AND|OR|NOT|NAND|NOR|XOR|XNOR|BUF|DFF)"


def try_parse_structural_health_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    if "floating" in low or "unconnected output" in low:
        return {"op": "find_floating_signals", "args": {}}

    if "dangling gates" in low or "dangling gate" in low:
        return {"op": "has_dangling_gates", "args": {}}

    if "redundant gates" in low or "redundant gate" in low:
        return {"op": "has_redundant_gates", "args": {}}

    if "tied to 1'b1" in low or "tied high" in low:
        return {"op": "list_gates_with_tied_high", "args": {}}

    if "constant input" in low or "constant inputs" in low:
        args: dict[str, Any] = {"type": "all"}
        if m := re.search(_GATE_WORD, line, re.I):
            args["type"] = m.group(1)
        vals = []
        if "1'b0" in low or re.search(r"\b0\b", line):
            vals.append("0")
        if "1'b1" in low or re.search(r"\b1\b", line):
            vals.append("1")
        if len(vals) == 1:
            args["val"] = vals[0]
        return {"op": "list_gates_with_constant_input", "args": args}

    if m := re.search(rf"all\s+{_GATE_WORD}\s+gates?.*tied to constant\s+([01])", line, re.I):
        return {
            "op": "list_gates_with_constant_input",
            "args": {"type": m.group(1), "val": m.group(2)},
        }

    if m := re.search(rf"{_GATE_WORD}\s+gates?.*constant\s+([01])", line, re.I):
        return {
            "op": "list_gates_with_constant_input",
            "args": {"type": m.group(1), "val": m.group(2)},
        }

    return None
