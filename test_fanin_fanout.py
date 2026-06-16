#!/usr/bin/env python3
"""Smoke tests for analysis_fanin_fanout.py using netlist_twoside.parse()."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from netlist_twoside import parse
from tools.analysis_fanin_fanout import (
    build_fanin_fanout_index,
    get_drivers,
    get_loads,
    highest_data_fanout_primary_input,
    highest_data_fanout_signal,
    count_fanin_cone_gates,
    count_fanout_cone_gates,
    highest_fanout_primary_input,
    highest_fanout_signal,
    immediate_data_fanout_gates,
    immediate_fanin_gates,
    immediate_fanout_gates,
    largest_fanin_cone_output,
    shared_fanin_cone_gates,
    transitive_fanin_cone,
    transitive_fanout_cone,
)

SIMPLE = Path(__file__).resolve().parent / "simple.v"

CASES = [
    ("immediate_fanin_gates(U3)", lambda nl: immediate_fanin_gates(nl, "U3"), ["U2"]),
    ("immediate_fanout_gates(U1)", lambda nl: immediate_fanout_gates(nl, "U1"), ["U2"]),
    ("transitive_fanin_cone(y)", lambda nl: transitive_fanin_cone(nl, "y"), ["U1", "U2", "U3"]),
    ("transitive_fanin_cone(n2)", lambda nl: transitive_fanin_cone(nl, "n2"), ["U1", "U2"]),
    ("transitive_fanout_cone(a)", lambda nl: transitive_fanout_cone(nl, "a"), ["U1", "U2", "U3"]),
    ("transitive_fanout_cone(U1)", lambda nl: transitive_fanout_cone(nl, "U1"), ["U2", "U3"]),
    ("count_fanin_cone_gates(y)", lambda nl: count_fanin_cone_gates(nl, "y"), 3),
    ("count_fanout_cone_gates(a)", lambda nl: count_fanout_cone_gates(nl, "a"), 3),
    (
        "shared_fanin_cone_gates(y, n2)",
        lambda nl: shared_fanin_cone_gates(nl, "y", "n2"),
        ["U1", "U2"],
    ),
    (
        "highest_fanout_signal()",
        lambda nl: highest_fanout_signal(nl),
        ("a", 1),
    ),
    (
        "highest_fanout_primary_input()",
        lambda nl: highest_fanout_primary_input(nl),
        ("", 0),
    ),
    (
        "largest_fanin_cone_output()",
        lambda nl: largest_fanin_cone_output(nl),
        ("", 0),
    ),
]

SEQUENTIAL_NETLIST = """
module top(a, b, mix, clk, rst, q, shared, out);
  input a, b, mix, clk, rst;
  output q, shared, out;
  wire n1, n2, q_unique, dummy_q;
  and U1(n1, a, b);
  dff FF0(.RN(rst), .SN(1'b1), .CK(clk), .D(n1), .Q(q));
  dff FF1(.RN(rst), .SN(1'b1), .CK(clk), .D(a), .Q(shared));
  dff FF2(.RN(1'b1), .SN(1'b1), .CK(clk), .D(b), .Q(shared));
  and U2(n2, shared, a);
  buf U3(out, n2);
  dff FF3(.RN(mix), .SN(1'b1), .CK(mix), .D(mix), .Q(q_unique));
  and U4(dummy_q, mix, b);
endmodule
"""


def parse_text(verilog: str):
    with NamedTemporaryFile("w", suffix=".v", delete=True) as f:
        f.write(verilog)
        f.flush()
        return parse(f.name)


def main() -> int:
    nl = parse(str(SIMPLE))
    index = build_fanin_fanout_index(nl)
    seq = parse_text(SEQUENTIAL_NETLIST)
    seq_index = build_fanin_fanout_index(seq)

    print(f"Loaded {SIMPLE.name}: {len(nl.gates)} gates")
    print(f"Index signals with loads: {len(index['wire_loads'])}")
    print()

    passed = 0
    failed = 0
    for label, fn, expected in CASES:
        got = fn(nl)
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        print(f"       output:   {got!r}")
        if not ok:
            print(f"       expected: {expected!r}")
            failed += 1
        else:
            passed += 1

    extra_cases = [
        (
            "get_drivers(shared)",
            lambda: get_drivers(seq_index, "shared"),
            [("GATE", "FF1"), ("GATE", "FF2")],
        ),
        (
            "transitive_fanout_cone(shared)",
            lambda: transitive_fanout_cone(seq, "shared"),
            ["U2", "U3"],
        ),
        (
            "transitive_fanin_cone(shared)",
            lambda: transitive_fanin_cone(seq, "shared"),
            ["FF1", "FF2"],
        ),
        (
            "immediate_fanin_gates(FF0)",
            lambda: immediate_fanin_gates(seq, "FF0"),
            ["U1"],
        ),
        (
            "transitive_fanin_cone(FF0)",
            lambda: transitive_fanin_cone(seq, "FF0"),
            ["FF0", "U1"],
        ),
        (
            "get_loads(mix, all)",
            lambda: get_loads(seq_index, "mix", "all"),
            [("FF3", "CK"), ("FF3", "D"), ("FF3", "RN"), ("U4", "in0")],
        ),
        (
            "get_loads(mix, data)",
            lambda: get_loads(seq_index, "mix", "data"),
            [("FF3", "D"), ("U4", "in0")],
        ),
        (
            "get_loads(mix, combinational)",
            lambda: get_loads(seq_index, "mix", "combinational"),
            [("U4", "in0")],
        ),
        (
            "immediate_data_fanout_gates(mix)",
            lambda: immediate_data_fanout_gates(seq, "mix"),
            ["FF3", "U4"],
        ),
        (
            "highest_data_fanout_signal()",
            lambda: highest_data_fanout_signal(seq),
            ("a", 3),
        ),
        (
            "highest_data_fanout_primary_input()",
            lambda: highest_data_fanout_primary_input(seq),
            ("a", 3),
        ),
    ]

    for label, fn, expected in extra_cases:
        got = fn()
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label}")
        print(f"       output:   {got!r}")
        if not ok:
            print(f"       expected: {expected!r}")
            failed += 1
        else:
            passed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
