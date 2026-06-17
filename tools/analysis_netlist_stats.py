"""
Gate / netlist statistics on top of the netlist_twoside IR.

Section 1.1 of tools/tool.md.  Mirrors the structure of
tools.analysis_fanin_fanout: pure query functions first, then an OP_TABLE
dispatcher, a formatter, and a small rule-based prompt parser.

DFF instances are sequential boundaries: their Q acts as a PI-like source and
their D as a PO-like sink, so combinational depth never crosses a flop.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from netlist_twoside import Gate, Netlist
from tools.analysis_fanin_fanout import transitive_fanin_cone

_CONST = re.compile(r"1'b[01]")

# IR gate-type tokens are lowercase; the contest reports use these display names
# and this fixed ordering (see every testcase's "broken down by gate type" line).
_TYPE_ORDER = ["and", "or", "not", "nand", "nor", "xor", "xnor", "buf", "dff"]
_DISPLAY = {t: t.upper() for t in _TYPE_ORDER}


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


def _norm_type(gtype: str) -> str:
    return gtype.strip().lower()


# ---------------------------------------------------------------------------
# Whole-design gate counts
# ---------------------------------------------------------------------------

def count_total_gates(netlist: Netlist) -> dict[str, Any]:
    """Count gates by type and overall, using the parsed IR (not regex)."""
    counts = Counter(g.type for g in netlist.gates.values())
    by_type = {_DISPLAY[t]: counts.get(t, 0) for t in _TYPE_ORDER}
    return {"by_type": by_type, "total": len(netlist.gates)}


def count_gates_of_type(netlist: Netlist, gtype: str) -> int:
    t = _norm_type(gtype)
    return sum(1 for g in netlist.gates.values() if g.type == t)


def list_gates_of_type(netlist: Netlist, gtype: str) -> list[str]:
    t = _norm_type(gtype)
    return sorted(g.name for g in netlist.gates.values() if g.type == t)


# ---------------------------------------------------------------------------
# Cone-local gate counts / depth
# ---------------------------------------------------------------------------

def count_gates_by_type_in_cone(netlist: Netlist, output: str) -> dict[str, Any]:
    """Count gates by type within the transitive fanin cone of an output."""
    cone = transitive_fanin_cone(netlist, output)
    counts = Counter(
        netlist.gates[name].type for name in cone if name in netlist.gates
    )
    by_type = {_DISPLAY[t]: counts.get(t, 0) for t in _TYPE_ORDER}
    return {"output": output, "by_type": by_type, "total": len(cone)}


def max_fanin_cone_depth(netlist: Netlist, output: str) -> int:
    """Maximum combinational logic depth (gate levels) of an output's fanin cone.

    Depth of a PI / constant / DFF-Q source is 0; depth of a gate output is
    1 + max depth over its combinational inputs.  DFFs are boundaries.
    """
    memo: dict[str, int] = {}
    stack: set[str] = set()

    def depth(net: str | None) -> int:
        if not net or _is_const(net) or net in netlist.inputs:
            return 0
        if net in memo:
            return memo[net]
        if net in stack:               # combinational loop guard
            return 0
        gate_name = netlist.unique_driver(net)
        gate = netlist.gates.get(gate_name) if gate_name else None
        if gate is None or gate.type == "dff":
            memo[net] = 0
            return 0
        stack.add(net)
        d = 1 + max((depth(n) for n in gate.ins), default=0)
        stack.discard(net)
        memo[net] = d
        return d

    return depth(output)


# ---------------------------------------------------------------------------
# Primary input / output inventory
# ---------------------------------------------------------------------------

def _port_kind_width(netlist: Netlist, port: str) -> tuple[str | None, int]:
    """Return ("input"/"output"/None, bit_width) for a declared module port."""
    if port in netlist.bus_width:
        msb, lsb = netlist.bus_width[port]
        lo = min(msb, lsb)
        kind = "input" if f"{port}[{lo}]" in netlist.inputs else "output"
        return kind, abs(msb - lsb) + 1
    if port in netlist.inputs:
        return "input", 1
    if port in netlist.outputs:
        return "output", 1
    return None, 0


def count_primary_inputs_outputs(netlist: Netlist) -> dict[str, int]:
    """Count primary inputs/outputs at both the port and the bit level."""
    pi_ports = po_ports = 0
    for port in netlist.port_order:
        kind, _ = _port_kind_width(netlist, port)
        if kind == "input":
            pi_ports += 1
        elif kind == "output":
            po_ports += 1
    return {
        "pi_ports": pi_ports,
        "po_ports": po_ports,
        "pi_bits": len(netlist.inputs),
        "po_bits": len(netlist.outputs),
    }


def _list_ports_with_widths(netlist: Netlist, want: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for port in netlist.port_order:
        kind, width = _port_kind_width(netlist, port)
        if kind == want:
            result.append((port, width))
    return result


def list_primary_inputs_with_widths(netlist: Netlist) -> list[tuple[str, int]]:
    return _list_ports_with_widths(netlist, "input")


def list_primary_outputs_with_widths(netlist: Netlist) -> list[tuple[str, int]]:
    return _list_ports_with_widths(netlist, "output")


# ---------------------------------------------------------------------------
# Per-gate info
# ---------------------------------------------------------------------------

def get_gate_info(netlist: Netlist, gate: str) -> dict[str, Any]:
    """Report a gate's type and pin connections."""
    g = netlist.gates.get(gate)
    if g is None:
        raise ValueError(f"No gate named '{gate}' in the design.")
    if g.type == "dff":
        return {"name": g.name, "type": "dff", "ports": dict(g.ports)}
    return {"name": g.name, "type": g.type, "output": g.out, "inputs": list(g.ins)}


def list_nand_gates_with_pins(netlist: Netlist) -> list[dict[str, Any]]:
    """List every NAND gate with its input and output signals."""
    return [
        {"name": g.name, "inputs": list(g.ins), "output": g.out}
        for g in sorted(netlist.gates.values(), key=lambda x: x.name)
        if g.type == "nand"
    ]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "count_total_gates": {
        "func": lambda nl, _a: count_total_gates(nl),
        "required_args": (),
        "category": "netlist_stats",
        "public": True,
        "description": "Count all gates broken down by type (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF) plus the total.",
    },
    "count_gates_of_type": {
        "func": lambda nl, a: count_gates_of_type(nl, a["type"]),
        "required_args": ("type",),
        "category": "netlist_stats",
        "public": True,
        "description": "Count gates of a single given type (e.g. NOT, NAND, XOR).",
    },
    "list_gates_of_type": {
        "func": lambda nl, a: list_gates_of_type(nl, a["type"]),
        "required_args": ("type",),
        "category": "netlist_stats",
        "public": True,
        "description": "List the instance names of all gates of a given type.",
    },
    "count_gates_by_type_in_cone": {
        "func": lambda nl, a: count_gates_by_type_in_cone(nl, a["output"]),
        "required_args": ("output",),
        "category": "netlist_stats",
        "public": True,
        "description": "Count gates by type within the fanin cone of an output.",
    },
    "max_fanin_cone_depth": {
        "func": lambda nl, a: max_fanin_cone_depth(nl, a["output"]),
        "required_args": ("output",),
        "category": "netlist_stats",
        "public": True,
        "description": "Maximum combinational logic depth (gate levels) of an output's fanin cone.",
    },
    "count_primary_inputs_outputs": {
        "func": lambda nl, _a: count_primary_inputs_outputs(nl),
        "required_args": (),
        "category": "netlist_stats",
        "public": True,
        "description": "Report the number of primary inputs and primary outputs.",
    },
    "list_primary_inputs_with_widths": {
        "func": lambda nl, _a: list_primary_inputs_with_widths(nl),
        "required_args": (),
        "category": "netlist_stats",
        "public": True,
        "description": "List all primary inputs with their bit widths.",
    },
    "list_primary_outputs_with_widths": {
        "func": lambda nl, _a: list_primary_outputs_with_widths(nl),
        "required_args": (),
        "category": "netlist_stats",
        "public": True,
        "description": "List all primary outputs with their bit widths.",
    },
    "get_gate_info": {
        "func": lambda nl, a: get_gate_info(nl, a["gate"]),
        "required_args": ("gate",),
        "category": "netlist_stats",
        "public": True,
        "description": "Report a gate's type and pin connections.",
    },
    "list_nand_gates_with_pins": {
        "func": lambda nl, _a: list_nand_gates_with_pins(nl),
        "required_args": (),
        "category": "netlist_stats",
        "public": True,
        "description": "List all NAND gates with their input and output signals.",
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
    if op in ("count_gates_of_type", "list_gates_of_type"):
        args.setdefault("type", args.get("gate_type") or args.get("gtype"))
    if op in ("count_gates_by_type_in_cone", "max_fanin_cone_depth"):
        args.setdefault("output", args.get("target") or args.get("out"))
    if op == "get_gate_info":
        args.setdefault("gate", args.get("name") or args.get("target"))
    return args


def dispatch_netlist_stats_op(
    netlist: Netlist,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown netlist stats op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](netlist, args)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_by_type(by_type: dict[str, int], total: int) -> str:
    parts = [f"{name}: {by_type[name]}" for name in (_DISPLAY[t] for t in _TYPE_ORDER)]
    return "\n".join(parts + [f"TOTAL: {total}"])


def _format_widths(label: str, items: list[tuple[str, int]]) -> str:
    if not items:
        return f"{label}: (none)"
    body = ", ".join(f"{name} [{width}]" for name, width in items)
    return f"{label} ({len(items)}): {body}"


def format_netlist_stats_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "count_total_gates":
        return "Gate count:\n" + _format_by_type(result["by_type"], result["total"])
    if op == "count_gates_of_type":
        return f"{args['type'].upper()} gate count: {result}"
    if op == "list_gates_of_type":
        listing = ", ".join(result) if result else "(none)"
        return f"{args['type'].upper()} gates ({len(result)}): {listing}"
    if op == "count_gates_by_type_in_cone":
        return (
            f"Gate types in fanin cone of {result['output']}:\n"
            + _format_by_type(result["by_type"], result["total"])
        )
    if op == "max_fanin_cone_depth":
        return f"Maximum logic depth of fanin cone of {args['output']}: {result}"
    if op == "count_primary_inputs_outputs":
        return (
            f"Primary inputs: {result['pi_ports']} ports ({result['pi_bits']} bits); "
            f"Primary outputs: {result['po_ports']} ports ({result['po_bits']} bits)."
        )
    if op == "list_primary_inputs_with_widths":
        return _format_widths("Primary inputs", result)
    if op == "list_primary_outputs_with_widths":
        return _format_widths("Primary outputs", result)
    if op == "get_gate_info":
        if result["type"] == "dff":
            pins = ", ".join(f".{p}({v})" for p, v in result["ports"].items())
            return f"Gate {result['name']} is type DFF with pins: {pins}"
        ins = ", ".join(result["inputs"])
        return (
            f"Gate {result['name']} is type {result['type'].upper()}; "
            f"output={result['output']}, inputs=[{ins}]"
        )
    if op == "list_nand_gates_with_pins":
        if not result:
            return "NAND gates (0): (none)"
        lines = [f"NAND gates ({len(result)}):"]
        for g in result:
            ins = ", ".join(g["inputs"])
            lines.append(f"  {g['name']}: inputs=[{ins}], output={g['output']}")
        return "\n".join(lines)
    return f"{op}: {result}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"
_GATE_WORD = r"(AND|OR|NOT|NAND|NOR|XOR|XNOR|BUF|DFF)"


def try_parse_netlist_stats_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    # total gate count broken down by type
    if "count all the gates" in low or re.search(r"broken down by gate type", low):
        return {"op": "count_total_gates", "args": {}}

    # per-type counts: "how many NOT gates are currently in the design?"
    if m := re.search(rf"how many\s+{_GATE_WORD}\s+gates", line, re.I):
        return {"op": "count_gates_of_type", "args": {"type": m.group(1)}}
    if m := re.search(rf"(?:total\s+)?{_GATE_WORD}\s+gate count", line, re.I):
        return {"op": "count_gates_of_type", "args": {"type": m.group(1)}}

    # gate-type counts in a cone
    if m := re.search(rf"number of each gate type in the cone of\s+{_NAME}", line, re.I):
        return {"op": "count_gates_by_type_in_cone", "args": {"output": m.group(1)}}

    # list NAND gates with pins (check before generic list-of-type)
    if re.search(r"list all nand gates.*input and output", low) or re.search(
        r"nand gates.*with their input and output", low
    ):
        return {"op": "list_nand_gates_with_pins", "args": {}}

    # list gates of a type: "List all XOR gates in this design."
    if m := re.search(rf"list all\s+{_GATE_WORD}\s+gates", line, re.I):
        return {"op": "list_gates_of_type", "args": {"type": m.group(1)}}

    # max fanin cone depth
    if m := re.search(rf"maximum logic depth of the fanin cone of (?:output\s+)?{_NAME}", line, re.I):
        return {"op": "max_fanin_cone_depth", "args": {"output": m.group(1)}}

    # PI/PO counts
    if re.search(r"number of primary inputs and outputs", low) or re.search(
        r"how many primary inputs and primary outputs", low
    ):
        return {"op": "count_primary_inputs_outputs", "args": {}}

    # PI/PO listings with widths
    if re.search(r"primary inputs.*bit widths", low):
        return {"op": "list_primary_inputs_with_widths", "args": {}}
    if re.search(r"primary outputs.*bit widths", low):
        return {"op": "list_primary_outputs_with_widths", "args": {}}

    # gate info: "What type of gate is g0? Report its gate type and pin connections."
    if m := re.search(rf"what type of gate is\s+{_NAME}", line, re.I):
        return {"op": "get_gate_info", "args": {"gate": m.group(1)}}

    return None
