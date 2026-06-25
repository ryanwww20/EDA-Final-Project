"""
Naming / connection edits on the netlist_twoside IR.

Section 2.4 of tools/tool.md.

``rename_gate`` and ``rename_wire`` are pure renamings — structurally and
functionally identical, so they apply unconditionally.  ``reconnect_gate_pin``
is a deliberate connectivity change that may alter function; it applies as
requested and *reports* whether equivalence still holds (without rolling back —
the reconnection is the explicit intent).
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any

from netlist_twoside import Netlist
from tools.verify_equivalence import miter_equivalent

_CONST = re.compile(r"1'b[01]")
_DFF_PINS = ("D", "CK", "RN", "SN")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


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


# ---------------------------------------------------------------------------
# Renaming
# ---------------------------------------------------------------------------

def rename_gate(netlist: Netlist, old: str, new: str) -> dict[str, Any]:
    """Rename a gate instance.  Pure renaming (function unchanged)."""
    if old not in netlist.gates:
        raise ValueError(f"No gate named '{old}'.")
    if new in netlist.gates:
        raise ValueError(f"A gate named '{new}' already exists.")
    g = netlist.gates.pop(old)
    g.name = new
    netlist.gates[new] = g
    _reindex(netlist)
    return {"op": "rename_gate", "old": old, "new": new}


def rename_wire(netlist: Netlist, old: str, new: str) -> dict[str, Any]:
    """Rename a wire and update every reference.  Pure renaming."""
    if _is_const(old):
        raise ValueError("Cannot rename a constant.")
    if new in _all_nets(netlist):
        raise ValueError(f"Net '{new}' already exists.")

    refs = 0
    for g in netlist.gates.values():
        if g.out == old:
            g.out = new
            refs += 1
        if g.type == "dff":
            for pin in _DFF_PINS:
                if g.ports.get(pin) == old:
                    g.ports[pin] = new
                    refs += 1
        else:
            new_ins = []
            for s in g.ins:
                if s == old:
                    new_ins.append(new)
                    refs += 1
                else:
                    new_ins.append(s)
            g.ins = new_ins

    is_port = False
    for store in (netlist.inputs, netlist.outputs):
        if old in store:
            store.discard(old)
            store.add(new)
            is_port = True
    if old in netlist.bus_width:
        netlist.bus_width[new] = netlist.bus_width.pop(old)
    if old in netlist.port_order:
        netlist.port_order = [new if p == old else p for p in netlist.port_order]
        is_port = True

    _reindex(netlist)
    return {"op": "rename_wire", "old": old, "new": new,
            "references_updated": refs, "was_port": is_port}


# ---------------------------------------------------------------------------
# Reconnection (deliberate connectivity edit)
# ---------------------------------------------------------------------------

def _resolve_pin(netlist: Netlist, gate, pin: str) -> tuple[str, Any]:
    """Return ('in', index) or ('port', pin) for a pin spec."""
    if gate.type == "dff":
        p = pin.upper()
        if p not in _DFF_PINS:
            raise ValueError(f"DFF pin must be one of {_DFF_PINS}, got '{pin}'.")
        return ("port", p)
    m = re.fullmatch(r"(?:in)?(\d+)", pin.strip(), re.I)
    if m:
        idx = int(m.group(1))
        if idx >= len(gate.ins):
            raise ValueError(f"Gate '{gate.name}' has no input pin {idx}.")
        return ("in", idx)
    raise ValueError(f"Unrecognized pin '{pin}' for gate '{gate.name}'.")


def reconnect_gate_pin(netlist: Netlist, gate: str, pin: str, signal: str) -> dict[str, Any]:
    """Reconnect an input pin of a gate to a new signal."""
    g = netlist.gates.get(gate)
    if g is None:
        raise ValueError(f"No gate named '{gate}'.")
    kind, ref = _resolve_pin(netlist, g, pin)
    if kind == "in":
        old = g.ins[ref]
        g.ins[ref] = signal
    else:
        old = g.ports.get(ref)
        g.ports[ref] = signal
    _reindex(netlist)
    return {"op": "reconnect_gate_pin", "gate": gate, "pin": pin,
            "old_signal": old, "new_signal": signal}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "rename_gate": {
        "func": lambda nl, a: rename_gate(nl, a["old"], a["new"]),
        "required_args": ("old", "new"), "category": "transform", "public": True,
        "verify": False,
        "description": "Rename a gate instance (pure renaming).",
    },
    "rename_wire": {
        "func": lambda nl, a: rename_wire(nl, a["old"], a["new"]),
        "required_args": ("old", "new"), "category": "transform", "public": True,
        "verify": False,
        "description": "Rename an internal wire and update all references (pure renaming).",
    },
    "reconnect_gate_pin": {
        "func": lambda nl, a: reconnect_gate_pin(nl, a["gate"], a["pin"], a["signal"]),
        "required_args": ("gate", "pin", "signal"), "category": "transform",
        "public": True, "verify": True,
        "description": "Reconnect an input pin of a gate to a new signal (may change function).",
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
    if op in ("rename_gate", "rename_wire"):
        args.setdefault("old", args.get("from") or args.get("old_name")
                        or args.get("name"))
        args.setdefault("new", args.get("to") or args.get("new_name"))
    if op == "reconnect_gate_pin":
        args.setdefault("signal", args.get("net") or args.get("wire")
                        or args.get("to"))
        args.setdefault("pin", args.get("input") or args.get("port"))
    return args


def dispatch_transform_rewire_op(
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
        raise ValueError(f"Unknown rewire op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")

    state.pre_transform_netlist = copy.deepcopy(state.netlist)
    report = meta["func"](state.netlist, args)

    # Renames are equivalence-preserving by construction; reconnection may not be
    # (and is intentional), so we report equivalence but never roll it back.
    if meta.get("verify"):
        eq = miter_equivalent(state.pre_transform_netlist, state.netlist)
        report["equivalent"] = eq["equivalent"]
        report["verify_method"] = "sat"
    else:
        report["equivalent"] = True
        report["verify_method"] = "structural_rename"

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

def format_transform_rewire_result(payload: dict[str, Any]) -> str:
    r = payload["result"]
    op = r["op"]
    if op == "rename_gate":
        return f"Renamed gate {r['old']} -> {r['new']}."
    if op == "rename_wire":
        port = " (module port)" if r.get("was_port") else ""
        return (f"Renamed wire {r['old']} -> {r['new']}{port}; "
                f"{r['references_updated']} reference(s) updated.")
    if op == "reconnect_gate_pin":
        eq = "still equivalent" if r["equivalent"] else "FUNCTION CHANGED"
        return (f"Reconnected {r['gate']}.{r['pin']}: {r['old_signal']} -> "
                f"{r['new_signal']} ({eq}).")
    return f"{op}: {r}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"


def try_parse_transform_rewire_request(line: str) -> dict[str, Any] | None:
    # reconnect
    if m := re.search(
        rf"reconnect\s+(?:gate\s+)?{_NAME}\s+(?:pin\s+)?{_NAME}\s+to\s+{_NAME}",
        line, re.I,
    ):
        return {"op": "reconnect_gate_pin",
                "args": {"gate": m.group(1), "pin": m.group(2), "signal": m.group(3)}}
    if m := re.search(
        rf"(?:connect|reattach)\s+(?:input\s+)?(?:pin\s+)?{_NAME}\s+of\s+(?:gate\s+)?"
        rf"{_NAME}\s+to\s+{_NAME}", line, re.I,
    ):
        return {"op": "reconnect_gate_pin",
                "args": {"gate": m.group(2), "pin": m.group(1), "signal": m.group(3)}}

    # rename gate / wire
    if m := re.search(rf"rename\s+gate\s+{_NAME}\s+(?:to|->|as)\s+{_NAME}", line, re.I):
        return {"op": "rename_gate", "args": {"old": m.group(1), "new": m.group(2)}}
    if m := re.search(
        rf"rename\s+(?:wire|net|signal)\s+{_NAME}\s+(?:to|->|as)\s+{_NAME}", line, re.I,
    ):
        return {"op": "rename_wire", "args": {"old": m.group(1), "new": m.group(2)}}
    if m := re.search(rf"rename\s+{_NAME}\s+(?:to|->|as)\s+{_NAME}", line, re.I):
        # ambiguous: prefer wire unless the name is a known gate (resolved at dispatch)
        return {"op": "rename_wire", "args": {"old": m.group(1), "new": m.group(2)}}

    return None
