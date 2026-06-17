"""
And-Inverter Graph (AIG) engine for depth optimization and tech remapping.

An AIG represents combinational logic as 2-input AND nodes with inverters on
edges (literals).  All gate types (NAND/NOR/NOT/AND/OR/XOR/XNOR) reduce to
ANDs + inversions, which lets us balance AND-trees uniformly to cut logic
depth, then map back to real gates.

Literals
--------
A literal is ``node << 1 | inverted``.  Node 0 is the constant 0, so literal 0
is const-0 and literal 1 is const-1.  ``nodes[i]`` is ``(f0, f1)`` for an AND
node and ``None`` for a constant / structural leaf.

Balancing here is **sharing-aware**: a supergate stops at inverted edges, at
nodes with fanout > 1, and at leaves, so rebalancing never duplicates shared
logic (area-neutral) — it only re-associates fanout-1 AND chains into balanced
trees.
"""

from __future__ import annotations

import heapq
import re
from typing import Any

from netlist_twoside import Netlist

_CONST = re.compile(r"1'b[01]")
_PRIM = {"and", "or", "nand", "nor", "xor", "xnor", "not", "buf"}


def _is_const(net: str | None) -> bool:
    return bool(net and _CONST.fullmatch(net))


class Aig:
    def __init__(self) -> None:
        self.nodes: list[Any] = [None]          # node 0 = const0
        self.strash: dict[tuple[int, int], int] = {}
        self.leaf_net: dict[int, str] = {}       # leaf node id -> original net
        self.sink_lit: dict[str, int] = {}       # sink net -> literal

    # -- literal helpers --
    @staticmethod
    def lit(node: int, inv: int = 0) -> int:
        return (node << 1) | inv

    @staticmethod
    def node_of(lit: int) -> int:
        return lit >> 1

    @staticmethod
    def inv_of(lit: int) -> int:
        return lit & 1

    @staticmethod
    def neg(lit: int) -> int:
        return lit ^ 1

    def is_leaf(self, node: int) -> bool:
        return node != 0 and self.nodes[node] is None

    # -- construction with structural hashing + constant folding --
    def mk_and(self, a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        if a == 1:
            return b
        if b == 1:
            return a
        if a == b:
            return a
        if a == (b ^ 1):
            return 0
        key = (a, b) if a < b else (b, a)
        nid = self.strash.get(key)
        if nid is None:
            nid = len(self.nodes)
            self.nodes.append(key)
            self.strash[key] = nid
        return self.lit(nid, 0)

    def mk_or(self, a: int, b: int) -> int:
        return self.neg(self.mk_and(self.neg(a), self.neg(b)))

    def mk_xor(self, a: int, b: int) -> int:
        return self.mk_or(self.mk_and(a, self.neg(b)),
                          self.mk_and(self.neg(a), b))

    def new_leaf(self, net: str, cache: dict[str, int]) -> int:
        nid = cache.get(net)
        if nid is None:
            nid = len(self.nodes)
            self.nodes.append(None)
            self.leaf_net[nid] = net
            cache[net] = nid
        return self.lit(nid, 0)


# XOR / XNOR are kept atomic: decomposing them into AND/inverters explodes both
# depth and area (each becomes a 2-3 level sub-graph), which hurts XOR-heavy
# designs.  Treating their outputs as leaves preserves the native 2-input gates.
_ATOMIC = {"xor", "xnor"}


def _leaf_predicate(netlist: Netlist):
    """A net is an AIG leaf if it has no unique combinational driver (PI, DFF Q,
    constant, multi-driver, unsupported gate) or is driven by an atomic gate."""
    def is_leaf(net: str) -> bool:
        if _is_const(net):
            return False
        drv = netlist.unique_driver(net)
        g = netlist.gates.get(drv) if drv else None
        return (g is None or g.type == "dff" or g.type not in _PRIM
                or g.type in _ATOMIC)
    return is_leaf


def build_aig(netlist: Netlist, sinks: list[str]) -> Aig:
    """Build an AIG whose ``sink_lit`` maps each sink net to its literal.

    Iterative post-order build, safe on the largest designs."""
    aig = Aig()
    leaf_cache: dict[str, int] = {}
    memo: dict[str, int] = {}
    is_leaf = _leaf_predicate(netlist)

    def build(root: str) -> int:
        stack = [(root, False)]
        while stack:
            net, done = stack.pop()
            if net in memo:
                continue
            if _is_const(net):
                memo[net] = 1 if net == "1'b1" else 0
                continue
            if is_leaf(net):
                memo[net] = aig.new_leaf(net, leaf_cache)
                continue
            g = netlist.gates[netlist.unique_driver(net)]
            ins = g.ins
            if not done:
                stack.append((net, True))
                for s in ins:
                    if s not in memo:
                        stack.append((s, False))
                continue
            a = memo.get(ins[0])
            b = memo.get(ins[1]) if len(ins) > 1 else None
            if a is None or (len(ins) > 1 and b is None):
                memo[net] = aig.new_leaf(net, leaf_cache)   # loop guard
                continue
            t = g.type
            if t == "buf":
                r = a
            elif t == "not":
                r = aig.neg(a)
            elif t == "and":
                r = aig.mk_and(a, b)
            elif t == "nand":
                r = aig.neg(aig.mk_and(a, b))
            elif t == "or":
                r = aig.mk_or(a, b)
            elif t == "nor":
                r = aig.neg(aig.mk_or(a, b))
            elif t == "xor":
                r = aig.mk_xor(a, b)
            elif t == "xnor":
                r = aig.neg(aig.mk_xor(a, b))
            else:
                r = aig.new_leaf(net, leaf_cache)
            memo[net] = r
        return memo[root]

    for s in sinks:
        aig.sink_lit[s] = build(s)
    return aig


def _fanout_counts(aig: Aig) -> list[int]:
    fo = [0] * len(aig.nodes)
    for i in range(1, len(aig.nodes)):
        node = aig.nodes[i]
        if node is not None:
            f0, f1 = node
            fo[f0 >> 1] += 1
            fo[f1 >> 1] += 1
    for lit in aig.sink_lit.values():
        fo[lit >> 1] += 1
    return fo


def _supergate_leaves(aig: Aig, node: int, fo: list[int]) -> list[int]:
    """Boundary literals of the AND-supergate rooted at ``node``: stop at
    inverted edges, leaves, constants, or shared (fanout>1) nodes."""
    leaves: list[int] = []
    stack = list(aig.nodes[node])
    while stack:
        lit = stack.pop()
        n = lit >> 1
        if (lit & 1) or n == 0 or aig.nodes[n] is None or fo[n] > 1:
            leaves.append(lit)
        else:
            stack.extend(aig.nodes[n])
    return leaves


# ---------------------------------------------------------------------------
# Synthesis: balanced AIG -> gate specs (sharing-aware, area-neutral)
# ---------------------------------------------------------------------------

class GatePlan:
    """Result of synthesizing an AIG into 2-input gates."""

    def __init__(self) -> None:
        self.gates: list[tuple[str, str, str, list[str]]] = []  # (name,type,out,ins)
        self.sink_drivers: dict[str, str] = {}   # sink net -> net carrying its value

    def add(self, name: str, gtype: str, out: str, ins: list[str]) -> None:
        self.gates.append((name, gtype, out, ins))


class _Synth:
    """Inverter-absorbing technology mapping.

    Works on *items* ``(net, inv, depth)`` so that an inverted operand is not
    materialized as a NOT gate unless unavoidable.  Each 2-input combine picks
    the gate type that absorbs the operand/output inversions:

        a · b           -> and        ¬(a · b)         -> nand
        ¬a · ¬b         -> nor        ¬(¬a · ¬b)=a+b   -> or

    Only a *mixed*-polarity pair (one inverted, one not) needs a real inverter.
    """

    def __init__(self, aig: Aig, namer) -> None:
        self.aig = aig
        self.namer = namer
        self.fo = _fanout_counts(aig)
        self.plan = GatePlan()
        self.pos_net: dict[int, str] = {}     # AND node -> net with positive value
        self.not_net: dict[str, str] = {}     # net -> its inverted net
        self.depth: dict[str, int] = {}       # net -> logic depth

    def _d(self, net: str) -> int:
        return self.depth.get(net, 0)

    def _emit(self, gtype: str, ins: list[str], out: str | None = None) -> str:
        out = out or self.namer.net()
        name = self.namer.gate()
        self.plan.add(name, gtype, out, ins)
        self.depth[out] = 1 + max((self._d(i) for i in ins), default=0)
        return out

    def _invert(self, net: str) -> str:
        cached = self.not_net.get(net)
        if cached is None:
            cached = self._emit("not", [net])
            self.not_net[net] = cached
        return cached

    # -- items: (net, inv, depth) --
    def _item_of_lit(self, lit: int) -> tuple[str, int, int]:
        node = lit >> 1
        inv = lit & 1
        if node == 0:
            return ("1'b1" if inv else "1'b0", 0, 0)
        if self.aig.nodes[node] is None:               # leaf
            return (self.aig.leaf_net[node], inv, 0)
        net = self._pos_net(node)
        return (net, inv, self._d(net))

    def _combine(self, a, b, out: str | None = None, out_inv: bool = False):
        na, ia, _ = a
        nb, ib, _ = b
        if ia and ib:
            gtype = "or" if out_inv else "nor"
        elif not ia and not ib:
            gtype = "nand" if out_inv else "and"
        else:                                          # mixed -> one inverter
            if ia:
                na = self._invert(na)
            else:
                nb = self._invert(nb)
            gtype = "nand" if out_inv else "and"
        net = self._emit(gtype, [na, nb], out)
        return (net, 0, self._d(net))

    def _huffman(self, items, out: str | None = None, out_inv: bool = False):
        """Balanced AND-reduction of ``items`` (depth-Huffman), absorbing the
        final output inversion when ``out_inv``."""
        if len(items) == 1:
            net, inv, d = items[0]
            if not out and not out_inv:
                return items[0]
            # materialize to a definite net / polarity
            src = self._invert(net) if (inv ^ out_inv) else net
            res = self._emit("buf", [src], out)
            return (res, 0, self._d(res))
        heap = [(items[i][2], i, items[i]) for i in range(len(items))]
        heapq.heapify(heap)
        counter = len(items)
        while len(heap) > 1:
            _, _, A = heapq.heappop(heap)
            _, _, B = heapq.heappop(heap)
            if len(heap) == 0:
                C = self._combine(A, B, out=out, out_inv=out_inv)
            else:
                C = self._combine(A, B)
            heapq.heappush(heap, (C[2], counter, C))
            counter += 1
        return heap[0][2]

    def _pos_net(self, node: int) -> str:
        cached = self.pos_net.get(node)
        if cached is not None:
            return cached
        leaves = _supergate_leaves(self.aig, node, self.fo)
        items = [self._item_of_lit(l) for l in leaves]
        net = self._huffman(items)[0]
        self.pos_net[node] = net
        return net

    def _realize_to(self, sink: str, lit: int) -> None:
        node = lit >> 1
        inv = lit & 1
        if node == 0:
            self.plan.sink_drivers[sink] = "1'b1" if inv else "1'b0"
            return
        if self.aig.nodes[node] is None:               # leaf
            base = self.aig.leaf_net[node]
            if inv:
                self.plan.sink_drivers[sink] = self._emit("not", [base], sink)
            else:
                self.plan.sink_drivers[sink] = base
            return
        if self.fo[node] > 1 or node in self.pos_net:
            base = self._pos_net(node)
            if inv:
                self._emit("not", [base], sink)
                self.plan.sink_drivers[sink] = sink
            else:
                self.plan.sink_drivers[sink] = base
            return
        # exclusive AND node: build its tree with the root driving the sink,
        # absorbing the sink inversion into the final gate.
        leaves = _supergate_leaves(self.aig, node, self.fo)
        items = [self._item_of_lit(l) for l in leaves]
        self._huffman(items, out=sink, out_inv=bool(inv))
        self.plan.sink_drivers[sink] = sink

    def run(self) -> GatePlan:
        for sink, lit in self.aig.sink_lit.items():
            self._realize_to(sink, lit)
        return self.plan


def synthesize_balanced(aig: Aig, namer) -> GatePlan:
    """Balance the AIG (sharing-aware) and synthesize 2-input gates with
    inverter-absorbing technology mapping (and / nand / or / nor / not).

    ``namer`` must provide ``.gate()`` and ``.net()`` returning fresh names.
    Returns a GatePlan: new gates plus a sink-net -> driving-net map."""
    return _Synth(aig, namer).run()
