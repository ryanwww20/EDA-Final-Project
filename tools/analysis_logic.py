"""
Functional / logic / formal-style analysis on top of netlist_twoside.

This mirrors tools.analysis_fanin_fanout: pure query functions first, then an
OP_TABLE dispatcher, formatter, and a small rule-based prompt parser.
"""

from __future__ import annotations

import itertools
import re
from typing import Any

from algorithm.boolean_logic import (
    BDDManager,
    BoolExpr,
    CONST0,
    CONST1,
    bdd_depends_on,
    bdd_equivalent,
    bdd_is_const,
    bdd_symmetric_in,
    expr_support,
    format_expr,
    gate_expr,
    var,
)
from netlist_twoside import Netlist

_CONST = re.compile(r"1'b[01]")
_SUPPORTED_GATES = {"and", "or", "nand", "nor", "xor", "xnor", "not", "buf"}


def _is_const(signal: str | None) -> bool:
    return bool(signal and _CONST.fullmatch(signal))


def _const_expr(signal: str) -> BoolExpr:
    return CONST1 if signal == "1'b1" else CONST0


def _all_signal_names(netlist: Netlist) -> set[str]:
    signals = set(netlist.inputs) | set(netlist.outputs)
    for gate in netlist.gates.values():
        if gate.out:
            signals.add(gate.out)
        for net in gate.ins:
            if net:
                signals.add(net)
        for net in gate.ports.values():
            if net:
                signals.add(net)
    return {s for s in signals if s and not _is_const(s)}


class LogicContext:
    """Build Boolean expressions from the netlist with DFFs as boundaries."""

    def __init__(self, netlist: Netlist):
        self.netlist = netlist
        self.memo: dict[str, BoolExpr] = {}
        self.stack: set[str] = set()

    def expr_for_signal(self, signal: str) -> BoolExpr:
        if _is_const(signal):
            return _const_expr(signal)
        if signal in self.memo:
            return self.memo[signal]
        if signal in self.stack:
            return var(signal)

        gate_name = self.netlist.unique_driver(signal)
        if not gate_name:
            result = var(signal)
            self.memo[signal] = result
            return result

        gate = self.netlist.gates.get(gate_name)
        if gate is None or gate.type == "dff" or gate.type not in _SUPPORTED_GATES:
            result = var(signal)
            self.memo[signal] = result
            return result

        self.stack.add(signal)
        inputs = [self.expr_for_signal(net) for net in gate.ins]
        result = gate_expr(gate.type, inputs)
        self.stack.remove(signal)
        self.memo[signal] = result
        return result


def build_logic_context(netlist: Netlist) -> LogicContext:
    return LogicContext(netlist)


def derive_boolean_equation(netlist: Netlist, output: str) -> str:
    expr = build_logic_context(netlist).expr_for_signal(output)
    return f"{output} = {format_expr(expr)}"


def write_logic_expression(netlist: Netlist, wire: str) -> str:
    expr = build_logic_context(netlist).expr_for_signal(wire)
    return format_expr(expr)


def boolean_function_of_output(netlist: Netlist, output: str) -> str:
    return derive_boolean_equation(netlist, output)


def signals_equivalent(netlist: Netlist, sig_a: str, sig_b: str) -> bool:
    ctx = build_logic_context(netlist)
    return bdd_equivalent(ctx.expr_for_signal(sig_a), ctx.expr_for_signal(sig_b))


def output_always_constant(netlist: Netlist, output: str, val: int | bool | str) -> bool:
    if isinstance(val, str):
        val_bool = val.strip() in ("1", "1'b1", "true", "True")
    else:
        val_bool = bool(val)
    expr = build_logic_context(netlist).expr_for_signal(output)
    return bdd_is_const(expr, val_bool)


def output_depends_on_input(netlist: Netlist, output: str, inp: str) -> bool:
    expr = build_logic_context(netlist).expr_for_signal(output)
    return bdd_depends_on(expr, inp)


def function_symmetric(netlist: Netlist, node: str, in_a: str, in_b: str) -> bool:
    expr = build_logic_context(netlist).expr_for_signal(node)
    return bdd_symmetric_in(expr, in_a, in_b)


def _fanin_signal_candidates(
    netlist: Netlist,
    target: str,
    *,
    max_candidates: int = 512,
) -> list[str]:
    """Return cone-local internal signals for expensive pair searches."""
    candidates: set[str] = set()
    visited_nets: set[str] = set()
    stack = [target]

    while stack:
        signal = stack.pop()
        if signal in visited_nets or _is_const(signal):
            continue
        visited_nets.add(signal)

        gate_name = netlist.unique_driver(signal)
        if not gate_name:
            continue
        gate = netlist.gates.get(gate_name)
        if gate is None or gate.type == "dff":
            continue
        if gate.out and gate.out not in netlist.inputs:
            candidates.add(gate.out)
        for net in gate.ins:
            if net and not _is_const(net):
                if net not in netlist.inputs and netlist.unique_driver(net):
                    candidates.add(net)
                stack.append(net)

    candidates.discard(target)
    return sorted(candidates)[:max_candidates]


def exists_nand_pair_equivalent_to(netlist: Netlist, wire: str) -> tuple[bool, str | None, str | None]:
    ctx = build_logic_context(netlist)
    target_expr = ctx.expr_for_signal(wire)
    candidates = _fanin_signal_candidates(netlist, wire)
    if not candidates:
        candidates = sorted(
            sig for sig in _all_signal_names(netlist)
            if sig != wire and sig not in netlist.inputs and netlist.unique_driver(sig)
        )[:256]

    expr_by_signal = {sig: ctx.expr_for_signal(sig) for sig in candidates}
    variables = set(expr_support(target_expr))
    for expr in expr_by_signal.values():
        variables |= expr_support(expr)

    manager = BDDManager(sorted(variables))
    target_node = manager.from_expr(target_expr)
    node_by_signal = {
        sig: manager.from_expr(expr)
        for sig, expr in expr_by_signal.items()
    }

    for sig_a, sig_b in itertools.combinations_with_replacement(candidates, 2):
        nand_node = manager.negate(
            manager.apply("and", node_by_signal[sig_a], node_by_signal[sig_b])
        )
        if nand_node == target_node:
            return (True, sig_a, sig_b)
    return (False, None, None)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "signals_equivalent": {
        "func": lambda nl, a: signals_equivalent(nl, a["sig_a"], a["sig_b"]),
        "required_args": ("sig_a", "sig_b"),
        "category": "logic_formal",
        "public": True,
        "description": "Check whether two signals are functionally equivalent.",
    },
    "output_always_constant": {
        "func": lambda nl, a: output_always_constant(nl, a["output"], a["val"]),
        "required_args": ("output", "val"),
        "category": "logic_formal",
        "public": True,
        "description": "Check whether an output is constant 0 or 1.",
    },
    "output_depends_on_input": {
        "func": lambda nl, a: output_depends_on_input(nl, a["output"], a["input"]),
        "required_args": ("output", "input"),
        "category": "logic_formal",
        "public": True,
        "description": "Check whether an output functionally depends on an input.",
    },
    "derive_boolean_equation": {
        "func": lambda nl, a: derive_boolean_equation(nl, a["output"]),
        "required_args": ("output",),
        "category": "logic_formal",
        "public": True,
        "description": "Derive a Boolean equation for an output.",
    },
    "write_logic_expression": {
        "func": lambda nl, a: write_logic_expression(nl, a["wire"]),
        "required_args": ("wire",),
        "category": "logic_formal",
        "public": True,
        "description": "Write a Boolean logic expression for a wire.",
    },
    "boolean_function_of_output": {
        "func": lambda nl, a: boolean_function_of_output(nl, a["output"]),
        "required_args": ("output",),
        "category": "logic_formal",
        "public": True,
        "description": "Return the Boolean function of an output.",
    },
    "function_symmetric": {
        "func": lambda nl, a: function_symmetric(nl, a["node"], a["in_a"], a["in_b"]),
        "required_args": ("node", "in_a", "in_b"),
        "category": "logic_formal",
        "public": True,
        "description": "Check whether a node function is symmetric in two inputs.",
    },
    "exists_nand_pair_equivalent_to": {
        "func": lambda nl, a: exists_nand_pair_equivalent_to(nl, a["wire"]),
        "required_args": ("wire",),
        "category": "logic_formal",
        "public": True,
        "description": "Find whether NAND(a,b) over existing internal signals equals a wire.",
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
    if op == "signals_equivalent":
        args.setdefault("sig_a", args.get("signal_a") or args.get("a"))
        args.setdefault("sig_b", args.get("signal_b") or args.get("b"))
    if op in ("derive_boolean_equation", "boolean_function_of_output"):
        args.setdefault("output", args.get("target") or args.get("wire"))
    if op == "write_logic_expression":
        args.setdefault("wire", args.get("target") or args.get("output"))
    if op == "output_depends_on_input":
        args.setdefault("output", args.get("out") or args.get("target"))
        args.setdefault("input", args.get("inp"))
    if op == "function_symmetric":
        args.setdefault("node", args.get("target") or args.get("wire"))
    if op == "exists_nand_pair_equivalent_to":
        args.setdefault("wire", args.get("target") or args.get("output"))
    return args


def dispatch_logic_op(
    netlist: Netlist,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown logic analysis op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [arg for arg in meta["required_args"] if arg not in args or args[arg] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](netlist, args)}


def format_logic_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "signals_equivalent":
        return (
            f"Signals {args['sig_a']} and {args['sig_b']} are "
            f"{'functionally equivalent' if result else 'not functionally equivalent'}."
        )
    if op == "output_always_constant":
        return (
            f"Output {args['output']} is "
            f"{'always' if result else 'not always'} {args['val']}."
        )
    if op == "output_depends_on_input":
        return (
            f"Output {args['output']} "
            f"{'depends' if result else 'does not depend'} on input {args['input']}."
        )
    if op in ("derive_boolean_equation", "boolean_function_of_output"):
        return f"Boolean equation: {result}"
    if op == "write_logic_expression":
        return f"Logic expression for {args['wire']}: {result}"
    if op == "function_symmetric":
        return (
            f"Function at {args['node']} is "
            f"{'symmetric' if result else 'not symmetric'} with respect to "
            f"{args['in_a']} and {args['in_b']}."
        )
    if op == "exists_nand_pair_equivalent_to":
        found, sig_a, sig_b = result
        if found:
            return f"Yes. NAND({sig_a}, {sig_b}) is equivalent to {args['wire']}."
        return f"No NAND pair equivalent to {args['wire']} was found."
    return f"{op}: {result}"


_NAME = r"([\w\[\]']+)"


def try_parse_logic_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    if m := re.search(rf"signals?\s+{_NAME}\s+and\s+{_NAME}.*functionally equivalent", line, re.I):
        return {"op": "signals_equivalent", "args": {"sig_a": m.group(1), "sig_b": m.group(2)}}
    if m := re.search(rf"that\s+{_NAME}\s+and\s+{_NAME}\s+produce identical", line, re.I):
        return {"op": "signals_equivalent", "args": {"sig_a": m.group(1), "sig_b": m.group(2)}}
    if m := re.search(rf"whether\s+{_NAME}\s+and\s+{_NAME}\s+(?:are|produce).*?(?:equivalent|identical)", line, re.I):
        return {"op": "signals_equivalent", "args": {"sig_a": m.group(1), "sig_b": m.group(2)}}
    if m := re.search(rf"(?:functional equivalence|equivalence) between internal signals?\s+{_NAME}\s+and\s+{_NAME}", line, re.I):
        return {"op": "signals_equivalent", "args": {"sig_a": m.group(1), "sig_b": m.group(2)}}

    if m := re.search(rf"output\s+{_NAME}\s+always\s+([01])", line, re.I):
        return {"op": "output_always_constant", "args": {"output": m.group(1), "val": m.group(2)}}

    if m := re.search(rf"output\s+{_NAME}\s+depend(?:s)?\s+on\s+input\s+{_NAME}", line, re.I):
        return {"op": "output_depends_on_input", "args": {"output": m.group(1), "input": m.group(2)}}

    if m := re.search(rf"derive the boolean equation for output\s+{_NAME}", line, re.I):
        return {"op": "derive_boolean_equation", "args": {"output": m.group(1)}}

    if m := re.search(rf"write the logic expression for\s+{_NAME}", line, re.I):
        return {"op": "write_logic_expression", "args": {"wire": m.group(1)}}

    if m := re.search(rf"what boolean function does output\s+{_NAME}\s+compute", line, re.I):
        return {"op": "boolean_function_of_output", "args": {"output": m.group(1)}}

    if m := re.search(rf"function at\s+{_NAME}\s+is symmetric with respect to inputs\s+{_NAME}\s+and\s+{_NAME}", line, re.I):
        return {
            "op": "function_symmetric",
            "args": {"node": m.group(1), "in_a": m.group(2), "in_b": m.group(3)},
        }
    if m := re.search(rf"function at\s+{_NAME}.*symmetric.*inputs\s+{_NAME}\s+and\s+{_NAME}", line, re.I):
        return {
            "op": "function_symmetric",
            "args": {"node": m.group(1), "in_a": m.group(2), "in_b": m.group(3)},
        }

    if "nand" in low and "equivalent" in low:
        if m := re.search(rf"equivalent to\s+{_NAME}", line, re.I):
            return {"op": "exists_nand_pair_equivalent_to", "args": {"wire": m.group(1)}}

    return None
