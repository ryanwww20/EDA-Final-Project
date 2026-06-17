"""
Sequential / DFF analysis on top of the netlist_twoside IR.

Section 1.5 of tools/tool.md.  Follows the same shape as the other analysis
modules: pure query functions first, then an OP_TABLE dispatcher, formatter,
and a small rule-based prompt parser.

DFF model
---------
A flip-flop is ``g.type == "dff"`` with named ports
``{RN, SN, CK, D, Q}`` (RN/SN active-low async reset/set, CK clock, D/Q data).
Constants (1'b0/1'b1) are not nets.  An *enable / hold* register is detected
structurally: the flop's own Q feeds back into the combinational fanin cone of
its own D pin (the classic ``D = enable ? data : Q`` load-enable mux).
"""

from __future__ import annotations

import re
from typing import Any

from netlist_twoside import Gate, Netlist
from tools.analysis_fanin_fanout import transitive_fanin_cone

_CONST = re.compile(r"1'b[01]")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


def _dffs(netlist: Netlist) -> list[Gate]:
    return [g for g in netlist.gates.values() if g.type == "dff"]


# ---------------------------------------------------------------------------
# Clock -> flip-flop queries
# ---------------------------------------------------------------------------

def list_ff_driven_by_clock(netlist: Netlist, clock: str) -> list[str]:
    """Instance names of every flip-flop whose CK pin is driven by ``clock``."""
    return sorted(
        g.name for g in _dffs(netlist) if g.ports.get("CK") == clock
    )


# ---------------------------------------------------------------------------
# D-pin logic structure (enable / hold detection)
# ---------------------------------------------------------------------------

def _has_enable_hold(netlist: Netlist, dff: Gate) -> bool:
    """A flop has an enable/hold structure when its own Q feeds back into the
    combinational fanin cone of its D pin (i.e. it can hold its current value).
    """
    d_net = dff.ports.get("D")
    if not d_net or _is_const(d_net):
        return False
    # The fanin cone stops at sequential boundaries but *includes* the boundary
    # flop gate itself, so a Q->...->D feedback shows up as `dff.name` in the cone.
    return dff.name in transitive_fanin_cone(netlist, d_net)


def analyze_dff_d_input_logic(netlist: Netlist) -> list[dict[str, Any]]:
    """Per-flop analysis of the D-pin: clock, D net, and enable/hold presence."""
    result: list[dict[str, Any]] = []
    for g in sorted(_dffs(netlist), key=lambda x: x.name):
        d_net = g.ports.get("D")
        result.append({
            "name": g.name,
            "clock": g.ports.get("CK"),
            "d_net": d_net,
            "d_is_constant": _is_const(d_net),
            "has_enable_hold": _has_enable_hold(netlist, g),
        })
    return result


def count_ff_with_enable_hold(netlist: Netlist) -> dict[str, Any]:
    """Count flip-flops that have an enable/hold structure on their D input."""
    flops = _dffs(netlist)
    with_eh = [g.name for g in flops if _has_enable_hold(netlist, g)]
    return {
        "total_ff": len(flops),
        "with_enable_hold": len(with_eh),
        "flops": sorted(with_eh),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "list_ff_driven_by_clock": {
        "func": lambda nl, a: list_ff_driven_by_clock(nl, a["clock"]),
        "required_args": ("clock",),
        "category": "sequential_analysis",
        "public": True,
        "description": "List all flip-flops driven by a given clock net.",
    },
    "analyze_dff_d_input_logic": {
        "func": lambda nl, _a: analyze_dff_d_input_logic(nl),
        "required_args": (),
        "category": "sequential_analysis",
        "public": True,
        "description": "Analyze every flip-flop's D-pin logic for enable/hold structure.",
    },
    "count_ff_with_enable_hold": {
        "func": lambda nl, _a: count_ff_with_enable_hold(nl),
        "required_args": (),
        "category": "sequential_analysis",
        "public": True,
        "description": "Count flip-flops whose D input has an enable/hold structure.",
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
    if op == "list_ff_driven_by_clock":
        args.setdefault("clock", args.get("clk") or args.get("clock_net")
                        or args.get("signal") or args.get("net"))
    return args


def dispatch_dff_op(
    netlist: Netlist,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown sequential/DFF op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](netlist, args)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_dff_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "list_ff_driven_by_clock":
        listing = ", ".join(result) if result else "(none)"
        return f"Flip-flops driven by clock {args['clock']} ({len(result)}): {listing}"

    if op == "analyze_dff_d_input_logic":
        if not result:
            return "No flip-flops in the design."
        lines = [f"DFF D-input analysis ({len(result)} flops):"]
        for e in result:
            tag = "enable/hold" if e["has_enable_hold"] else "plain"
            lines.append(
                f"  {e['name']}: clock={e['clock']}, D={e['d_net']} [{tag}]"
            )
        return "\n".join(lines)

    if op == "count_ff_with_enable_hold":
        body = ", ".join(result["flops"]) if result["flops"] else "(none)"
        return (
            f"Flip-flops with enable/hold: {result['with_enable_hold']} "
            f"of {result['total_ff']}. Flops: {body}"
        )

    return f"{op}: {result}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"


def try_parse_dff_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    # flip-flops driven by a clock
    if m := re.search(
        rf"(?:flip[- ]?flops?|ffs?|registers?)\s+(?:driven|clocked) by\s+"
        rf"(?:clock\s+)?{_NAME}", line, re.I,
    ):
        return {"op": "list_ff_driven_by_clock", "args": {"clock": m.group(1)}}
    if m := re.search(rf"(?:clock|clk)\s+{_NAME}\s+drives?", line, re.I):
        return {"op": "list_ff_driven_by_clock", "args": {"clock": m.group(1)}}

    # count flops with enable/hold
    if re.search(r"how many.*(?:flip[- ]?flops?|ffs?|registers?).*"
                 r"(?:enable|hold)", low) or \
            re.search(r"count.*(?:enable|hold).*(?:flip[- ]?flops?|ffs?)", low):
        return {"op": "count_ff_with_enable_hold", "args": {}}

    # analyze D-pin logic
    if re.search(r"(?:analyze|analyse|describe).*d[- ]?(?:pin|input).*"
                 r"(?:logic|structure|enable|hold)", low) or \
            re.search(r"(?:enable|hold).*structure.*d[- ]?(?:pin|input)", low):
        return {"op": "analyze_dff_d_input_logic", "args": {}}

    return None
