"""
Technology / logic remapping transformations on the netlist_twoside IR.

Section 2.5 of tools/tool.md.  Each op rewrites combinational gates into an
equivalent network expressed in a restricted gate basis (NAND+NOT, NOR+NOT,
AND+NOT, NAND-only, NOR-only, …) while preserving the design's function.

Every op preserves each rewritten gate's *output net* (so downstream wiring is
untouched) and is checked for functional equivalence with the SAT miter, rolling
back on any unintended change — these rewrites are equivalence-preserving by
construction, so the miter is a safety net rather than an accept criterion.

Rewrite scopes:
  - whole-design  (``reconstruct_netlist_and_not_only``, ``remap_netlist_nand_not_only``)
  - single gate type, whole design  (``convert_xnor_to_nor``, ``convert_xor_to_nand``,
    ``replace_nand_const1_with_inverter``)
  - fanin cone of an output  (``replace_or_with_nand_not_in_cone``,
    ``convert_cone_to_nand_not``, ``convert_cone_to_nor_not``, ``decompose_xor_in_cone``)
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Callable

from netlist_twoside import Gate, Netlist
from tools.verify_equivalence import miter_equivalent
from tools.analysis_fanin_fanout import transitive_fanin_cone

_CONST = re.compile(r"1'b[01]")
_DFF_PINS = ("D", "CK", "RN", "SN")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


# ---------------------------------------------------------------------------
# Shared IR-edit helpers (same shape as transform_cleanup / transform_depth)
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
            name = f"u_rm{self._gi}"
            if name not in self._gates:
                self._gates.add(name)
                return name

    def net(self) -> str:
        while True:
            self._ni += 1
            name = f"rw{self._ni}"
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


# ---------------------------------------------------------------------------
# Gate-network builder + basis decompositions
# ---------------------------------------------------------------------------

class _Builder:
    """Accumulates freshly-minted gates that implement a single rewrite.

    Each constructor emits one gate driving a fresh net and returns that net,
    so the *last* gate emitted always drives the returned (top-level) net.
    """

    def __init__(self, namer: _Namer) -> None:
        self._namer = namer
        self.gates: list[Gate] = []

    def _emit(self, gtype: str, ins: list[str]) -> str:
        out = self._namer.net()
        name = self._namer.gate()
        self.gates.append(Gate(name, gtype, out=out, ins=list(ins)))
        return out

    def NOT(self, a: str) -> str:
        return self._emit("not", [a])

    def AND(self, a: str, b: str) -> str:
        return self._emit("and", [a, b])

    def OR(self, a: str, b: str) -> str:
        return self._emit("or", [a, b])

    def NAND(self, a: str, b: str) -> str:
        return self._emit("nand", [a, b])

    def NOR(self, a: str, b: str) -> str:
        return self._emit("nor", [a, b])


# A decomposition fn takes (builder, gate_type, input_nets) and returns the net
# computing the gate's function in the target basis, or None to skip the gate.
Decomp = Callable[..., "str | None"]


def _to_nand_not(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """Express any primitive gate using only NAND and NOT."""
    if gtype == "not":
        return b.NOT(ins[0])
    if gtype == "buf":
        return b.NOT(b.NOT(ins[0]))
    a, c = ins[0], ins[1]
    if gtype == "nand":
        return b.NAND(a, c)
    if gtype == "and":                       # a&b = ~(a NAND b)
        return b.NOT(b.NAND(a, c))
    if gtype == "or":                        # a|b = (~a) NAND (~b)
        return b.NAND(b.NOT(a), b.NOT(c))
    if gtype == "nor":                       # ~(a|b)
        return b.NOT(b.NAND(b.NOT(a), b.NOT(c)))
    if gtype in ("xor", "xnor"):             # classic 4-NAND XOR
        t1 = b.NAND(a, c)
        t2 = b.NAND(a, t1)
        t3 = b.NAND(c, t1)
        xo = b.NAND(t2, t3)
        return b.NOT(xo) if gtype == "xnor" else xo
    return None


def _to_nor_not(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """Express any primitive gate using only NOR and NOT."""
    if gtype == "not":
        return b.NOT(ins[0])
    if gtype == "buf":
        return b.NOT(b.NOT(ins[0]))
    a, c = ins[0], ins[1]
    if gtype == "nor":
        return b.NOR(a, c)
    if gtype == "or":                        # a|b = ~(a NOR b)
        return b.NOT(b.NOR(a, c))
    if gtype == "and":                       # a&b = (~a) NOR (~b)
        return b.NOR(b.NOT(a), b.NOT(c))
    if gtype == "nand":                      # ~(a&b)
        return b.NOT(b.NOR(b.NOT(a), b.NOT(c)))
    if gtype in ("xor", "xnor"):
        # a^b = (a&~b) | (~a&b);  a&~b = NOR(~a,b), ~a&b = NOR(a,~b)
        t1 = b.NOR(b.NOT(a), c)
        t2 = b.NOR(a, b.NOT(c))
        xo = b.NOT(b.NOR(t1, t2))            # OR(t1,t2)
        return b.NOT(xo) if gtype == "xnor" else xo
    return None


def _to_and_not(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """Express any primitive gate using only AND and NOT."""
    if gtype == "not":
        return b.NOT(ins[0])
    if gtype == "buf":
        return b.NOT(b.NOT(ins[0]))
    a, c = ins[0], ins[1]
    if gtype == "and":
        return b.AND(a, c)
    if gtype == "nand":                      # ~(a&b)
        return b.NOT(b.AND(a, c))
    if gtype == "or":                        # a|b = ~(~a & ~b)
        return b.NOT(b.AND(b.NOT(a), b.NOT(c)))
    if gtype == "nor":                       # ~a & ~b
        return b.AND(b.NOT(a), b.NOT(c))
    if gtype in ("xor", "xnor"):
        t1 = b.AND(a, b.NOT(c))              # a & ~b
        t2 = b.AND(b.NOT(a), c)              # ~a & b
        xo = b.NOT(b.AND(b.NOT(t1), b.NOT(t2)))   # OR(t1,t2)
        return b.NOT(xo) if gtype == "xnor" else xo
    return None


def _xor_to_and_or_not(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """Decompose XOR/XNOR into AND/OR/NOT; pass other gate types through."""
    if gtype not in ("xor", "xnor"):
        return None
    a, c = ins[0], ins[1]
    t1 = b.AND(a, b.NOT(c))                   # a & ~b
    t2 = b.AND(b.NOT(a), c)                   # ~a & b
    o = b.OR(t1, t2)
    return b.NOT(o) if gtype == "xnor" else o


def _or_to_nand_not(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """Rewrite OR gates as NAND+NOT; leave everything else untouched."""
    if gtype != "or":
        return None
    return b.NAND(b.NOT(ins[0]), b.NOT(ins[1]))


def _xnor_to_nor_only(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """XNOR(a,b) using four NOR gates only (dual of the 4-NAND XOR)."""
    if gtype != "xnor":
        return None
    a, c = ins[0], ins[1]
    t1 = b.NOR(a, c)
    t2 = b.NOR(a, t1)
    t3 = b.NOR(c, t1)
    return b.NOR(t2, t3)


def _xor_to_nand_only(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """XOR(a,b) using four NAND gates only."""
    if gtype != "xor":
        return None
    a, c = ins[0], ins[1]
    t1 = b.NAND(a, c)
    t2 = b.NAND(a, t1)
    t3 = b.NAND(c, t1)
    return b.NAND(t2, t3)


def _nand_const1_to_inverter(b: _Builder, gtype: str, ins: list[str]) -> str | None:
    """NAND with a constant-1 input is an inverter of the other input."""
    if gtype != "nand" or "1'b1" not in ins:
        return None
    other = ins[1] if ins[0] == "1'b1" else ins[0]
    return b.NOT(other)


# ---------------------------------------------------------------------------
# Core rewrite driver
# ---------------------------------------------------------------------------

def _rewrite_gates(
    netlist: Netlist, gate_names: list[str], decomp: Decomp, namer: _Namer
) -> tuple[int, dict[str, int]]:
    """Replace each named combinational gate with ``decomp``'s network.

    The original gate's output net is preserved; only its implementation is
    swapped.  Returns (gates_rewritten, added_gates_by_type)."""
    rewritten = 0
    added: dict[str, int] = defaultdict(int)
    for name in list(gate_names):
        g = netlist.gates.get(name)
        if g is None or g.type == "dff":
            continue
        b = _Builder(namer)
        res = decomp(b, g.type, g.ins)
        if res is None or not b.gates:
            continue
        # Repoint the gate that drives the top-level result net to g.out.
        driver = next((x for x in b.gates if x.out == res), b.gates[-1])
        driver.out = g.out
        del netlist.gates[g.name]
        for ng in b.gates:
            netlist.gates[ng.name] = ng
            added[ng.type] += 1
        rewritten += 1
    _reindex(netlist)
    return rewritten, dict(added)


def _comb_gate_names(netlist: Netlist) -> list[str]:
    return [n for n, g in netlist.gates.items() if g.type != "dff"]


def _cone_gate_names(netlist: Netlist, output: str) -> list[str]:
    return [n for n in transitive_fanin_cone(netlist, output)
            if n in netlist.gates and netlist.gates[n].type != "dff"]


# ---------------------------------------------------------------------------
# Public transformations (pure netlist mutators)
# ---------------------------------------------------------------------------

def _report(op: str, rewritten: int, added: dict[str, int],
            extra: dict[str, Any] | None = None) -> dict[str, Any]:
    rep = {"op": op, "gates_rewritten": rewritten, "added_gates_by_type": added}
    if extra:
        rep.update(extra)
    return rep


# --- cone-scoped basis remapping -------------------------------------------

def replace_or_with_nand_not_in_cone(netlist: Netlist, output: str) -> dict[str, Any]:
    """Within ``output``'s fanin cone, rewrite OR gates as NAND+NOT."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _cone_gate_names(netlist, output),
                              _or_to_nand_not, namer)
    return _report("replace_or_with_nand_not_in_cone", n, added, {"output": output})


def convert_cone_to_nand_not(netlist: Netlist, output: str) -> dict[str, Any]:
    """Rewrite every combinational gate in ``output``'s cone using NAND+NOT."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _cone_gate_names(netlist, output),
                              _to_nand_not, namer)
    return _report("convert_cone_to_nand_not", n, added, {"output": output})


def convert_cone_to_nor_not(netlist: Netlist, output: str) -> dict[str, Any]:
    """Rewrite every combinational gate in ``output``'s cone using NOR+NOT."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _cone_gate_names(netlist, output),
                              _to_nor_not, namer)
    return _report("convert_cone_to_nor_not", n, added, {"output": output})


def decompose_xor_in_cone(netlist: Netlist, output: str) -> dict[str, Any]:
    """Decompose XOR/XNOR gates in ``output``'s cone into AND/OR/NOT."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _cone_gate_names(netlist, output),
                              _xor_to_and_or_not, namer)
    return _report("decompose_xor_in_cone", n, added, {"output": output})


# --- whole-design basis remapping ------------------------------------------

def reconstruct_netlist_and_not_only(netlist: Netlist) -> dict[str, Any]:
    """Rewrite the whole design into an AND+NOT-only network."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _comb_gate_names(netlist), _to_and_not, namer)
    return _report("reconstruct_netlist_and_not_only", n, added)


def remap_netlist_nand_not_only(netlist: Netlist) -> dict[str, Any]:
    """Rewrite the whole design into a NAND+NOT-only network."""
    namer = _Namer(netlist)
    n, added = _rewrite_gates(netlist, _comb_gate_names(netlist), _to_nand_not, namer)
    return _report("remap_netlist_nand_not_only", n, added)


# --- single gate-type conversions ------------------------------------------

def convert_xnor_to_nor(netlist: Netlist) -> dict[str, Any]:
    """Convert every XNOR gate into a NOR-only (four-NOR) network."""
    namer = _Namer(netlist)
    targets = [n for n, g in netlist.gates.items() if g.type == "xnor"]
    n, added = _rewrite_gates(netlist, targets, _xnor_to_nor_only, namer)
    return _report("convert_xnor_to_nor", n, added)


def convert_xor_to_nand(netlist: Netlist) -> dict[str, Any]:
    """Convert every XOR gate into a NAND-only (four-NAND) network."""
    namer = _Namer(netlist)
    targets = [n for n, g in netlist.gates.items() if g.type == "xor"]
    n, added = _rewrite_gates(netlist, targets, _xor_to_nand_only, namer)
    return _report("convert_xor_to_nand", n, added)


def replace_nand_const1_with_inverter(netlist: Netlist) -> dict[str, Any]:
    """Replace every NAND gate with a constant-1 input by an inverter."""
    namer = _Namer(netlist)
    targets = [n for n, g in netlist.gates.items()
               if g.type == "nand" and "1'b1" in g.ins]
    n, added = _rewrite_gates(netlist, targets, _nand_const1_to_inverter, namer)
    return _report("replace_nand_const1_with_inverter", n, added)


# ---------------------------------------------------------------------------
# State-aware dispatcher (snapshot -> mutate -> SAT self-check -> record)
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "replace_or_with_nand_not_in_cone": {
        "func": lambda nl, a: replace_or_with_nand_not_in_cone(nl, a["output"]),
        "required_args": ("output",), "category": "transform", "public": True,
        "description": "In an output's fanin cone, rewrite OR gates as NAND+NOT.",
    },
    "convert_cone_to_nand_not": {
        "func": lambda nl, a: convert_cone_to_nand_not(nl, a["output"]),
        "required_args": ("output",), "category": "transform", "public": True,
        "description": "Rewrite every gate in an output's cone using only NAND and NOT.",
    },
    "convert_cone_to_nor_not": {
        "func": lambda nl, a: convert_cone_to_nor_not(nl, a["output"]),
        "required_args": ("output",), "category": "transform", "public": True,
        "description": "Rewrite every gate in an output's cone using only NOR and NOT.",
    },
    "decompose_xor_in_cone": {
        "func": lambda nl, a: decompose_xor_in_cone(nl, a["output"]),
        "required_args": ("output",), "category": "transform", "public": True,
        "description": "Decompose XOR/XNOR gates in an output's cone into AND/OR/NOT.",
    },
    "reconstruct_netlist_and_not_only": {
        "func": lambda nl, _a: reconstruct_netlist_and_not_only(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Rewrite the whole design into an AND+NOT-only network.",
    },
    "remap_netlist_nand_not_only": {
        "func": lambda nl, _a: remap_netlist_nand_not_only(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Rewrite the whole design into a NAND+NOT-only network.",
    },
    "convert_xnor_to_nor": {
        "func": lambda nl, _a: convert_xnor_to_nor(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Convert every XNOR gate into a NOR-only network.",
    },
    "convert_xor_to_nand": {
        "func": lambda nl, _a: convert_xor_to_nand(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Convert every XOR gate into a NAND-only network.",
    },
    "replace_nand_const1_with_inverter": {
        "func": lambda nl, _a: replace_nand_const1_with_inverter(nl),
        "required_args": (), "category": "transform", "public": True,
        "description": "Replace NAND gates that have a constant-1 input with an inverter.",
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
    if "output" in {a for m in OP_TABLE.values() for a in m["required_args"]}:
        args.setdefault("output", args.get("out") or args.get("target_output")
                        or args.get("po") or args.get("signal"))
    return args


def dispatch_transform_remap_op(
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
        raise ValueError(f"Unknown remap transform op: {op}")

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

    # These rewrites are equivalence-preserving by construction; the miter is a
    # safety net.  Roll back on any unintended functional change.
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

def format_transform_remap_result(payload: dict[str, Any]) -> str:
    r = payload["result"]
    area = f"gates {r['gate_count_before']}->{r['gate_count_after']}"
    added = r.get("added_gates_by_type") or {}
    added_str = ", ".join(f"{v} {k}" for k, v in sorted(added.items())) or "none"
    scope = f" in cone of {r['output']}" if "output" in r else ""
    head = (f"{r['op']}{scope}: rewrote {r['gates_rewritten']} gate(s); "
            f"added {added_str}; {area}.")
    if r.get("rolled_back"):
        head += " WARNING: not equivalence-preserving, rolled back."
    else:
        head += " Functional equivalence verified."
    return head


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"


def try_parse_transform_remap_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    # --- cone-scoped ops (need an output name) ---
    if m := re.search(rf"\bor\b.*\bnand\b.*\bcone\b.*?(?:of|for)\s+{_NAME}", line, re.I) \
            or re.search(rf"replace.*\bor\b.*with\s+nand.*?{_NAME}", line, re.I):
        if "cone" in low or "or" in low:
            mm = re.search(rf"(?:cone\s+(?:of|for)|output)\s+{_NAME}", line, re.I)
            if mm:
                return {"op": "replace_or_with_nand_not_in_cone",
                        "args": {"output": mm.group(1)}}

    if m := re.search(
        rf"(?:cone\s+(?:of|for)|output)\s+{_NAME}.*?nand\s*(?:\+|/|,|\band\b)?\s*not", line, re.I,
    ):
        return {"op": "convert_cone_to_nand_not", "args": {"output": m.group(1)}}
    if m := re.search(
        rf"(?:cone\s+(?:of|for)|output)\s+{_NAME}.*?nor\s*(?:\+|/|,|\band\b)?\s*not", line, re.I,
    ):
        return {"op": "convert_cone_to_nor_not", "args": {"output": m.group(1)}}
    if m := re.search(
        rf"(?:decompose|break|split).*xor.*(?:cone\s+(?:of|for)|output)\s+{_NAME}", line, re.I,
    ):
        return {"op": "decompose_xor_in_cone", "args": {"output": m.group(1)}}

    # --- whole-design basis remapping ---
    if re.search(r"and\s*(?:\+|/|,|\band\b)?\s*not[- ]only|only\s+and\s+and\s+not|"
                 r"reconstruct.*and.*not", low):
        return {"op": "reconstruct_netlist_and_not_only", "args": {}}
    if re.search(r"nand\s*(?:\+|/|,|\band\b)?\s*not[- ]only|only\s+nand\s+and\s+not|"
                 r"remap.*nand.*not|nand[- ]?not only", low):
        return {"op": "remap_netlist_nand_not_only", "args": {}}

    # --- single gate-type conversions ---
    if re.search(r"xnor.*(?:to|into|->|as).*nor|convert.*xnor", low):
        return {"op": "convert_xnor_to_nor", "args": {}}
    if re.search(r"xor.*(?:to|into|->|as).*nand|convert.*xor.*nand", low):
        return {"op": "convert_xor_to_nand", "args": {}}
    if re.search(r"nand.*(?:1'b1|constant\s*1|tied\s*high|const.*1).*(?:invert|not)|"
                 r"replace.*nand.*invert", low):
        return {"op": "replace_nand_const1_with_inverter", "args": {}}

    return None
