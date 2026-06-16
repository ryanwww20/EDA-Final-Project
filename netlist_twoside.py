"""
Gate-level Verilog netlist parser + data structure.
Validated against ICCAD Contest Problem A testcases.
"""
import re
from collections import defaultdict

# 1-input gates (output, input). Everything else is 2-input (output, in0, in1).
ONE_INPUT = {"not", "buf"}
PRIM_GATES = {"and", "or", "nand", "nor", "xor", "xnor", "not", "buf"}


class Gate:
    __slots__ = ("name", "type", "out", "ins", "ports")

    def __init__(self, name, gtype, out=None, ins=None, ports=None):
        self.name = name          # instance name, e.g. "g0"
        self.type = gtype         # "and", "dff", ...
        self.out = out            # driven net (for prim gates / dff Q)
        self.ins = ins or []      # input nets (combinational fanin)
        self.ports = ports or {}  # for dff: {"RN":.., "SN":.., "CK":.., "D":.., "Q":..}

    def __repr__(self):
        return f"Gate({self.name} {self.type} out={self.out} ins={self.ins})"


class Netlist:
    def __init__(self):
        self.module = None
        self.port_order = []          # module port list order
        self.inputs = set()           # primary input nets (bit-level expanded)
        self.outputs = set()          # primary output nets (bit-level expanded)
        self.bus_width = {}           # base name -> (msb, lsb) for inputs/outputs
        self.gates = {}               # name -> Gate
        self.driver = {}              # net -> unique gate_name that drives it (PI nets absent)
        self.drivers = defaultdict(list)  # net -> all gate_names driving it
        self.fanout = defaultdict(list)  # net -> list of gate_names consuming it

    # ---- queries built on top of the core structure ----
    def add_driver(self, net, gate_name):
        if not net:
            return
        self.drivers[net].append(gate_name)
        if len(self.drivers[net]) == 1:
            self.driver[net] = gate_name
        else:
            self.driver.pop(net, None)

    def drivers_of(self, net):
        return list(self.drivers.get(net, []))

    def unique_driver(self, net):
        drivers = self.drivers_of(net)
        return drivers[0] if len(drivers) == 1 else None

    def has_multiple_drivers(self, net):
        return len(self.drivers.get(net, [])) > 1

    def is_pi(self, net):
        return net in self.inputs

    def is_po(self, net):
        return net in self.outputs

    def driving_gate(self, net):
        return self.gates.get(self.unique_driver(net))

    def combinational_fanins(self, gate):
        """Nets feeding this gate combinationally (dff: only D... but dff is a
        sequential boundary, so for combinational traversal treat Q as a PI-like
        startpoint and D as a PO-like endpoint)."""
        if gate.type == "dff":
            return [gate.ports.get("D")]
        return gate.ins


def _expand_bus(base, msb, lsb):
    lo, hi = sorted((msb, lsb))
    return [f"{base}[{i}]" for i in range(lo, hi + 1)]


def parse(path):
    nl = Netlist()
    text = open(path).read()
    # strip comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    # module header
    m = re.search(r"\bmodule\s+(\w+)\s*\(([^)]*)\)\s*;", text, re.S)
    nl.module = m.group(1)
    nl.port_order = [p.strip() for p in m.group(2).split(",") if p.strip()]

    body = text[m.end():]

    # input / output declarations (may carry bus range)
    for kind, store in (("input", nl.inputs), ("output", nl.outputs)):
        for dm in re.finditer(rf"\b{kind}\b\s*(\[(\d+):(\d+)\])?\s*([^;]+);", body):
            rng, msb, lsb, names = dm.groups()
            for nm in (x.strip() for x in names.split(",") if x.strip()):
                if rng:
                    msb_i, lsb_i = int(msb), int(lsb)
                    nl.bus_width[nm] = (msb_i, lsb_i)
                    for bit in _expand_bus(nm, msb_i, lsb_i):
                        store.add(bit)
                else:
                    store.add(nm)

    # gate / dff instantiations
    # primitive: <type> <inst>(net, net[, net]);
    for gm in re.finditer(
        r"\b(and|or|nand|nor|xor|xnor|not|buf)\s+(\w+)\s*\(([^;]*?)\)\s*;", body, re.S
    ):
        gtype, inst, args = gm.group(1), gm.group(2), gm.group(3)
        nets = [a.strip() for a in args.split(",")]
        out, ins = nets[0], nets[1:]
        g = Gate(inst, gtype, out=out, ins=ins)
        nl.gates[inst] = g
        nl.add_driver(out, inst)
        for s in ins:
            nl.fanout[s].append(inst)

    # dff: dff <inst>(.RN(..), .SN(..), .CK(..), .D(..), .Q(..));
    for dm in re.finditer(r"\bdff\s+(\w+)\s*\(([^;]*?)\)\s*;", body, re.S):
        inst, args = dm.group(1), dm.group(2)
        ports = dict(re.findall(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)", args))
        g = Gate(inst, "dff", out=ports.get("Q"), ins=[], ports=ports)
        nl.gates[inst] = g
        if g.out:
            nl.add_driver(g.out, inst)
        for pin in ("D", "CK", "RN", "SN"):
            net = ports.get(pin)
            if net and not re.fullmatch(r"1'b[01]", net or ""):
                nl.fanout[net].append(inst)

    return nl


_CONST = re.compile(r"1'b[01]")


def _collect_internal_buses(nl):
    """Find bracketed nets (e.g. n199[0]) whose base is NOT a declared PI/PO,
    and infer their bus range so we can emit a valid `wire [msb:lsb] base;`."""
    bracket = re.compile(r"^(\w+)\[(\d+)\]$")
    ranges = {}                      # base -> (min_idx, max_idx)
    declared = set(nl.bus_width)     # bases already declared as PI/PO buses

    def note(net):
        if not net or _CONST.fullmatch(net):
            return
        m = bracket.match(net)
        if not m:
            return
        base, idx = m.group(1), int(m.group(2))
        if base in declared:
            return
        lo, hi = ranges.get(base, (idx, idx))
        ranges[base] = (min(lo, idx), max(hi, idx))

    for g in nl.gates.values():
        note(g.out)
        for s in g.ins:
            note(s)
        for v in g.ports.values():
            note(v)
    return ranges


def dump(nl, path):
    """Write the Netlist back out as a gate-level Verilog file.

    The output re-parses to a structurally identical Netlist (round-trip safe)
    and is valid Verilog (every net is declared)."""
    lines = []
    lines.append(f"module {nl.module}({', '.join(nl.port_order)});")

    # --- input / output declarations, in module port order ---
    for p in nl.port_order:
        if p in nl.bus_width:                     # bussed PI/PO
            msb, lsb = nl.bus_width[p]
            lo = min(msb, lsb)
            kind = "input" if f"{p}[{lo}]" in nl.inputs else "output"
            lines.append(f"  {kind} [{msb}:{lsb}] {p};")
        else:                                     # scalar PI/PO
            kind = "input" if p in nl.inputs else "output"
            lines.append(f"  {kind} {p};")

    # --- wire declarations (for valid Verilog; parser ignores these) ---
    pi_po = nl.inputs | nl.outputs
    bus_bases = set(nl.bus_width)
    internal_buses = _collect_internal_buses(nl)

    # bussed internal wires
    for base, (lo, hi) in sorted(internal_buses.items()):
        lines.append(f"  wire [{hi}:{lo}] {base};")

    # scalar internal wires: every referenced net that's not PI/PO,
    # not a bus bit, and not a constant
    bracket = re.compile(r"^\w+\[\d+\]$")
    scalar_wires = set()

    def consider(net):
        if not net or _CONST.fullmatch(net):
            return
        if net in pi_po or bracket.match(net):
            return
        if net in bus_bases:
            return
        scalar_wires.add(net)

    for g in nl.gates.values():
        consider(g.out)
        for s in g.ins:
            consider(s)
        for v in g.ports.values():
            consider(v)

    for w in sorted(scalar_wires):
        lines.append(f"  wire {w};")

    # --- gate / dff instantiations ---
    for g in nl.gates.values():
        if g.type == "dff":
            p = g.ports
            inner = ", ".join(f".{pin}({p[pin]})" for pin in
                              ("RN", "SN", "CK", "D", "Q") if pin in p)
            lines.append(f"  dff {g.name}({inner});")
        else:
            args = ", ".join([g.out] + g.ins)
            lines.append(f"  {g.type} {g.name}({args});")

    lines.append("endmodule")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def summary(nl):
    """Human/agent-friendly stats about a Netlist."""
    num_dff = sum(1 for g in nl.gates.values() if g.type == "dff")
    num_combinational = len(nl.gates) - num_dff
    clock_nets = sorted({
        g.ports["CK"]
        for g in nl.gates.values()
        if g.type == "dff" and g.ports.get("CK")
        and not _CONST.fullmatch(g.ports["CK"])
    })
    return {
        "module": nl.module,
        "num_gates_total": len(nl.gates),
        "num_combinational": num_combinational,
        "num_dff": num_dff,
        "num_inputs": len(nl.inputs),
        "num_outputs": len(nl.outputs),
        "is_sequential": num_dff > 0,
        "clock_nets": clock_nets,
    }


def signature(nl):
    """Canonical, comparable fingerprint of a Netlist's logical content.
    Two netlists with the same signature are structurally identical."""
    gate_sig = set()
    for g in nl.gates.values():
        if g.type == "dff":
            ports = tuple(sorted(g.ports.items()))
            gate_sig.add((g.name, g.type, ports))
        else:
            # gate input order matters for non-symmetric reasoning, keep it
            gate_sig.add((g.name, g.type, g.out, tuple(g.ins)))
    return {
        "module": nl.module,
        "ports": tuple(nl.port_order),
        "inputs": frozenset(nl.inputs),
        "outputs": frozenset(nl.outputs),
        "bus_width": frozenset(nl.bus_width.items()),
        "gates": frozenset(gate_sig),
    }


if __name__ == "__main__":
    import sys, glob, os, tempfile

    # Single-file CLI mode:  python3 netlist.py in.v out.v
    if len(sys.argv) == 3:
        nl = parse(sys.argv[1])
        dump(nl, sys.argv[2])
        print(f"parsed {sys.argv[1]} ({len(nl.gates)} gates) -> {sys.argv[2]}")
        sys.exit(0)

    # Round-trip validation mode (no args): parse -> dump -> parse, compare.
    pattern = (sys.argv[1] if len(sys.argv) == 2
               else "/tmp/testcase_extracted/testcase/test*/test*.v")
    files = sorted(glob.glob(pattern))
    ok = fail = 0
    for f in files:
        name = os.path.basename(f)
        try:
            nl1 = parse(f)
            with tempfile.NamedTemporaryFile("w", suffix=".v", delete=False) as tmp:
                tmp_path = tmp.name
            dump(nl1, tmp_path)
            nl2 = parse(tmp_path)
            os.unlink(tmp_path)
            if signature(nl1) == signature(nl2):
                print(f"{name:14s} OK   gates={len(nl1.gates)}")
                ok += 1
            else:
                s1, s2 = signature(nl1), signature(nl2)
                diffs = [k for k in s1 if s1[k] != s2[k]]
                print(f"{name:14s} MISMATCH in {diffs}")
                fail += 1
        except Exception as e:
            print(f"{name:14s} ERROR: {e}")
            fail += 1
    print(f"\nround-trip: {ok} OK, {fail} FAIL  (out of {len(files)})")
