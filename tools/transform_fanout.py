"""
Fanout / buffer-insertion transformations on the netlist_twoside IR.

Section 2.1 of tools/tool.md.  These ops *mutate* the design, so unlike the
analysis modules:
  * dispatch is state-aware (it snapshots, mutates ``state.netlist``, and
    self-checks functional equivalence with the miter+SAT engine, rolling back
    on any unintended change);
  * each op returns a transform report (``added_gates_by_type`` etc.) recorded
    in ``state.last_transform_report`` / ``state.transform_history`` so the
    Section 1.8 transform-stats queries can read it.

IR invariants (driver / drivers / fanout) are rebuilt wholesale via
``_reindex`` after each mutation rather than patched in place, which keeps the
indexes provably consistent.
"""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from typing import Any

from netlist_twoside import Gate, Netlist
from tools.verify_equivalence import miter_equivalent

_CONST = re.compile(r"1'b[01]")
_DFF_PINS = ("D", "CK", "RN", "SN")


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


# ---------------------------------------------------------------------------
# IR helpers
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
    """Hands out gate-instance / wire names guaranteed not to collide."""

    def __init__(self, netlist: Netlist) -> None:
        self._gates = set(netlist.gates)
        self._nets = _all_nets(netlist)
        self._gi = 0
        self._ni = 0

    def gate(self) -> str:
        while True:
            self._gi += 1
            name = f"u_buf{self._gi}"
            if name not in self._gates:
                self._gates.add(name)
                return name

    def net(self) -> str:
        while True:
            self._ni += 1
            name = f"bw{self._ni}"
            if name not in self._nets:
                self._nets.add(name)
                return name


def _build_load_index(netlist: Netlist) -> dict[str, list[tuple[str, str]]]:
    """One pass: net -> sorted list of (gate, pin) consumers.

    Avoids the O(N^2) cost of scanning every gate once per net.
    """
    idx: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for g in netlist.gates.values():
        if g.type == "dff":
            for pin in _DFF_PINS:
                n = g.ports.get(pin)
                if n and not _is_const(n):
                    idx[n].append((g.name, pin))
        else:
            for i, n in enumerate(g.ins):
                if n and not _is_const(n):
                    idx[n].append((g.name, f"in{i}"))
    for n in idx:
        idx[n].sort()
    return idx


def _loads_of(netlist: Netlist, net: str) -> list[tuple[str, str]]:
    """Every (gate, pin) that consumes ``net`` — pins are 'in{idx}' or DFF ports."""
    loads: list[tuple[str, str]] = []
    for g in netlist.gates.values():
        if g.type == "dff":
            for pin in _DFF_PINS:
                if g.ports.get(pin) == net:
                    loads.append((g.name, pin))
        else:
            for i, n in enumerate(g.ins):
                if n == net:
                    loads.append((g.name, f"in{i}"))
    return sorted(loads)


def _set_pin(netlist: Netlist, gate_name: str, pin: str, new_net: str) -> None:
    g = netlist.gates[gate_name]
    if pin.startswith("in"):
        g.ins[int(pin[2:])] = new_net
    else:
        g.ports[pin] = new_net


def _candidate_nets(netlist: Netlist) -> set[str]:
    """Nets that can be a fanout source: primary inputs and gate outputs."""
    nets = {n for n in netlist.inputs if not _is_const(n)}
    for g in netlist.gates.values():
        if g.out and not _is_const(g.out):
            nets.add(g.out)
    return nets


def _fanout_counts(netlist: Netlist) -> Counter:
    counts: Counter = Counter()
    for g in netlist.gates.values():
        if g.type == "dff":
            for pin in _DFF_PINS:
                n = g.ports.get(pin)
                if n and not _is_const(n):
                    counts[n] += 1
        else:
            for n in g.ins:
                if n and not _is_const(n):
                    counts[n] += 1
    return counts


def _max_fanout(netlist: Netlist) -> int:
    counts = _fanout_counts(netlist)
    return max(counts.values()) if counts else 0


def _reindex(netlist: Netlist) -> None:
    """Rebuild driver / drivers / fanout from gates + connectivity."""
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
# Core buffer-tree construction
# ---------------------------------------------------------------------------

def _limit_fanout_for_net(
    netlist: Netlist, source: str, max_fanout: int, namer: _Namer,
    loads: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Insert a balanced buffer tree so ``source`` and every inserted buffer
    each drive at most ``max_fanout`` loads.  Returns the new buffer names.

    ``loads`` may be supplied from a prebuilt index to avoid a re-scan."""
    sinks = list(loads) if loads is not None else _loads_of(netlist, source)
    if len(sinks) <= max_fanout:
        return []

    added: list[str] = []
    while len(sinks) > max_fanout:
        next_sinks: list[tuple[str, str]] = []
        for i in range(0, len(sinks), max_fanout):
            group = sinks[i:i + max_fanout]
            bname = namer.gate()
            bnet = namer.net()
            # placeholder input; set when this buffer becomes a sink (next level
            # or the final assignment to `source`)
            netlist.gates[bname] = Gate(bname, "buf", out=bnet, ins=[None])
            added.append(bname)
            for gname, pin in group:
                _set_pin(netlist, gname, pin, bnet)
            next_sinks.append((bname, "in0"))
        sinks = next_sinks

    for gname, pin in sinks:           # remaining (<= max) read the source
        _set_pin(netlist, gname, pin, source)
    return added


def _resolve_through_buffers(netlist: Netlist, net: str) -> str:
    """Follow buf gates back to the first non-buf driver net (or a leaf)."""
    seen: set[str] = set()
    while net is not None and net not in seen:
        seen.add(net)
        drv = netlist.unique_driver(net)
        g = netlist.gates.get(drv) if drv else None
        if g is not None and g.type == "buf":
            net = g.ins[0]
        else:
            return net
    return net


def _buffer_insertion_equivalent(pre: Netlist, post: Netlist) -> bool:
    """Structural, O(N) proof that ``post`` differs from ``pre`` only by
    transparent buffer insertion (every original gate still sees the same
    logical signals once buffers are resolved away).  Sound for this transform
    class; far cheaper than a SAT miter on large designs.

    Buffers are resolved away on *both* sides, so any buffers already present in
    the original design cancel out and only the inserted ones matter."""
    if set(pre.inputs) != set(post.inputs) or set(pre.outputs) != set(post.outputs):
        return False

    def same(pre_net: str | None, post_net: str | None) -> bool:
        if pre_net is None or post_net is None:
            return pre_net == post_net
        return _resolve_through_buffers(pre, pre_net) == \
            _resolve_through_buffers(post, post_net)

    for name, pg in pre.gates.items():
        qg = post.gates.get(name)
        if qg is None or qg.type != pg.type or qg.out != pg.out:
            return False
        if pg.type == "dff":
            for pin in _DFF_PINS:
                if not same(pg.ports.get(pin), qg.ports.get(pin)):
                    return False
        else:
            if len(qg.ins) != len(pg.ins):
                return False
            if any(not same(a, b) for a, b in zip(pg.ins, qg.ins)):
                return False
    return True


def _report(
    op: str,
    added: list[str],
    buffered: list[str],
    limit: int | None,
    before: int,
    after: int,
) -> dict[str, Any]:
    return {
        "op": op,
        "added_buffers": added,
        "added_gates_by_type": {"buf": len(added)},
        "buffered_signals": buffered,
        "limit": limit,
        "max_fanout_before": before,
        "max_fanout_after": after,
    }


# ---------------------------------------------------------------------------
# Public transformations (pure netlist mutators)
# ---------------------------------------------------------------------------

def _optimize_all_fanout(netlist: Netlist, op: str, max_fanout: int) -> dict[str, Any]:
    namer = _Namer(netlist)
    load_index = _build_load_index(netlist)         # single pass, O(N)
    before = max((len(v) for v in load_index.values()), default=0)
    candidates = _candidate_nets(netlist)
    targets = sorted(
        s for s in candidates
        if len(load_index.get(s, ())) > max_fanout
    )
    added: list[str] = []
    buffered: list[str] = []
    for s in targets:
        new = _limit_fanout_for_net(netlist, s, max_fanout, namer, load_index[s])
        if new:
            added.extend(new)
            buffered.append(s)
    _reindex(netlist)
    return _report(op, added, buffered, max_fanout, before, _max_fanout(netlist))


def insert_buffers_max_fanout(netlist: Netlist, max: int = 4) -> dict[str, Any]:
    """Insert buffers design-wide so no net drives more than ``max`` loads."""
    return _optimize_all_fanout(netlist, "insert_buffers_max_fanout", max)


def fanout_optimization(netlist: Netlist, max: int = 4) -> dict[str, Any]:
    """Optimize fanout across the whole netlist to the ``max`` bound."""
    return _optimize_all_fanout(netlist, "fanout_optimization", max)


def insert_buffer_per_load(netlist: Netlist, signal: str) -> dict[str, Any]:
    """Insert one dedicated buffer per load on ``signal`` (load isolation)."""
    namer = _Namer(netlist)
    before = _max_fanout(netlist)
    added: list[str] = []
    for gname, pin in _loads_of(netlist, signal):
        bname = namer.gate()
        bnet = namer.net()
        netlist.gates[bname] = Gate(bname, "buf", out=bnet, ins=[signal])
        _set_pin(netlist, gname, pin, bnet)
        added.append(bname)
    _reindex(netlist)
    buffered = [signal] if added else []
    return _report("insert_buffer_per_load", added, buffered, None,
                   before, _max_fanout(netlist))


def insert_buffers_on_signal(
    netlist: Netlist, signal: str, max: int = 4
) -> dict[str, Any]:
    """Insert a balanced buffer tree on a single ``signal`` (e.g. clock/reset)."""
    namer = _Namer(netlist)
    before = _max_fanout(netlist)
    added = _limit_fanout_for_net(netlist, signal, max, namer)
    _reindex(netlist)
    buffered = [signal] if added else []
    return _report("insert_buffers_on_signal", added, buffered, max,
                   before, _max_fanout(netlist))


# ---------------------------------------------------------------------------
# State-aware dispatcher (snapshot -> mutate -> self-check -> record)
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "insert_buffers_max_fanout": {
        "func": lambda nl, a: insert_buffers_max_fanout(nl, int(a.get("max", 4))),
        "required_args": (),
        "optional_args": ("max",),
        "category": "transform",
        "public": True,
        "description": "Insert buffers design-wide so no net drives more than `max` loads (default 4).",
    },
    "fanout_optimization": {
        "func": lambda nl, a: fanout_optimization(nl, int(a.get("max", 4))),
        "required_args": (),
        "optional_args": ("max",),
        "category": "transform",
        "public": True,
        "description": "Optimize fanout across the whole netlist down to the `max` bound (default 4).",
    },
    "insert_buffer_per_load": {
        "func": lambda nl, a: insert_buffer_per_load(nl, a["signal"]),
        "required_args": ("signal",),
        "category": "transform",
        "public": True,
        "description": "Insert one dedicated buffer per load on a signal.",
    },
    "insert_buffers_on_signal": {
        "func": lambda nl, a: insert_buffers_on_signal(nl, a["signal"], int(a.get("max", 4))),
        "required_args": ("signal",),
        "optional_args": ("max",),
        "category": "transform",
        "public": True,
        "description": "Insert a balanced buffer tree on a specific signal (e.g. clock/reset) to the `max` bound.",
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
    if "max" not in args:
        for alt in ("max_fanout", "limit", "n", "k"):
            if alt in args:
                args["max"] = args[alt]
                break
    if op in ("insert_buffer_per_load", "insert_buffers_on_signal"):
        args.setdefault("signal", args.get("net") or args.get("wire")
                        or args.get("clock") or args.get("target"))
    return args


def dispatch_transform_fanout_op(
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
        raise ValueError(f"Unknown fanout transform op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")

    # snapshot -> mutate -> self-check -> record
    state.pre_transform_netlist = copy.deepcopy(state.netlist)
    report = meta["func"](state.netlist, args)

    # Fast O(N) structural proof (buffers are transparent); fall back to the
    # SAT miter only if the cheap proof is inconclusive.
    equivalent = _buffer_insertion_equivalent(state.pre_transform_netlist,
                                              state.netlist)
    report["verify_method"] = "structural"
    if not equivalent:
        sat = miter_equivalent(state.pre_transform_netlist, state.netlist)
        equivalent = sat["equivalent"]
        report["verify_method"] = "sat_fallback"
    report["equivalent"] = equivalent
    if not equivalent:
        state.netlist = state.pre_transform_netlist
        report["rolled_back"] = True

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

def format_transform_fanout_result(payload: dict[str, Any]) -> str:
    result = payload["result"]
    n = len(result["added_buffers"])
    limit = result.get("limit")
    bound = f" (limit {limit})" if limit is not None else ""
    head = (f"Inserted {n} buffer(s){bound}: max fanout "
            f"{result['max_fanout_before']} -> {result['max_fanout_after']}.")
    if result.get("buffered_signals"):
        sig = result["buffered_signals"]
        shown = ", ".join(sig[:8]) + (" ..." if len(sig) > 8 else "")
        head += f" Buffered nets ({len(sig)}): {shown}."
    if result.get("rolled_back"):
        head += " WARNING: change was not equivalence-preserving and was rolled back."
    else:
        head += " Functional equivalence verified."
    return head


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.]+)"


def try_parse_transform_fanout_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    # one buffer per load on a signal
    if m := re.search(rf"(?:one\s+)?buffer per load (?:on|of|for)\s+{_NAME}", line, re.I):
        return {"op": "insert_buffer_per_load", "args": {"signal": m.group(1)}}

    # buffers on a specific signal (clock / reset / named net) with a bound
    if m := re.search(
        rf"(?:insert|add)\s+buffers?\s+(?:on|to|for)\s+(?:the\s+)?"
        rf"(?:clock|reset|signal|net|wire)?\s*{_NAME}.*?(?:more than|max(?:imum)?|up to|of)\s+(\d+)",
        line, re.I,
    ):
        return {"op": "insert_buffers_on_signal",
                "args": {"signal": m.group(1), "max": int(m.group(2))}}
    if m := re.search(
        rf"(?:insert|add|buffer)\s+(?:buffers?\s+)?(?:on|to|for)?\s*"
        rf"(?:the\s+)?(?:clock|reset)\s+(?:signal\s+|net\s+)?{_NAME}", line, re.I,
    ):
        return {"op": "insert_buffers_on_signal", "args": {"signal": m.group(1)}}

    # design-wide max-fanout bound
    if m := re.search(r"(?:no|each|every).*(?:gate|signal|net).*drives?.*?(?:more than|at most)\s+(\d+)", line, re.I):
        return {"op": "insert_buffers_max_fanout", "args": {"max": int(m.group(1))}}
    if m := re.search(r"(?:limit|cap|reduce).*fanout.*?(?:to|of|below|under)\s+(\d+)", line, re.I):
        return {"op": "insert_buffers_max_fanout", "args": {"max": int(m.group(1))}}
    if m := re.search(r"max(?:imum)?\s+fanout\s+(?:of|to)\s+(\d+)", line, re.I):
        return {"op": "insert_buffers_max_fanout", "args": {"max": int(m.group(1))}}
    if re.search(r"fanout optimization|optimize.*fanout", low):
        return {"op": "fanout_optimization", "args": {}}

    return None
