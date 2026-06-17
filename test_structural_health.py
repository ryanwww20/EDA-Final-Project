#!/usr/bin/env python3
"""Smoke tests for tools.analysis_structural_health."""

from tempfile import NamedTemporaryFile

from netlist_twoside import parse
from tools.analysis_structural_health import (
    dispatch_structural_health_op,
    find_floating_signals,
    format_structural_health_result,
    has_dangling_gates,
    has_redundant_gates,
    list_gates_with_constant_input,
    list_gates_with_tied_high,
    try_parse_structural_health_request,
)


STRUCTURAL_NETLIST = """
module top(a, b, c, y, z);
  input a, b, c;
  output y, z;
  wire n0, n1, n2, dead;
  and g0(n0, a, 1'b1);
  and g1(n1, a, b);
  and g2(n2, b, a);
  or g3(dead, n1, c);
  nand g4(y, n0, missing);
endmodule
"""


def parse_text(verilog: str):
    with NamedTemporaryFile("w", suffix=".v", delete=True) as f:
        f.write(verilog)
        f.flush()
        return parse(f.name)


def check(cond, msg):
    print(f"{'ok  ' if cond else 'FAIL'} {msg}")
    assert cond, msg


def main():
    nl = parse_text(STRUCTURAL_NETLIST)

    const_all = list_gates_with_constant_input(nl)
    check([g["name"] for g in const_all] == ["g0"], "finds all constant-input gates")

    const_and_one = list_gates_with_constant_input(nl, "AND", "1")
    check([g["name"] for g in const_and_one] == ["g0"], "filters constant inputs by type and value")

    tied_high = list_gates_with_tied_high(nl)
    check([g["name"] for g in tied_high] == ["g0"], "finds tied-high gates")

    dangling = has_dangling_gates(nl)
    check(dangling["has_dangling"], "reports dangling gates present")
    check(dangling["gates"] == ["g1", "g2", "g3"], "lists gates outside observable cone")

    redundant = has_redundant_gates(nl)
    check(redundant["has_redundant"], "reports redundant gates present")
    check(redundant["gates"][0]["name"] == "g2", "finds structural duplicate")
    check(redundant["gates"][0]["equivalent_to"] == "g1", "points duplicate to canonical gate")

    floating = find_floating_signals(nl)
    check(floating["signals"] == ["missing", "z"], "finds floating input and unconnected output")
    check(floating["floating_inputs"][0]["gate"] == "g4", "records floating input load")

    payload = dispatch_structural_health_op(
        nl,
        {"op": "list_gates_with_constant_input", "args": {"type": "NAND"}},
    )
    text = format_structural_health_result(payload)
    check("NAND with inputs tied to constants" in text, "dispatcher + formatter run")

    parser_cases = [
        ("Report any NAND gates with constant inputs (0 or 1) in this design.", "list_gates_with_constant_input"),
        ("List all gates with one or more inputs tied to 1'b1.", "list_gates_with_tied_high"),
        ("Check if there are any dangling gates in this design.", "has_dangling_gates"),
        ("Are there any redundant gates in this design?", "has_redundant_gates"),
        ("Check if there are any floating inputs or unconnected output ports in this design.", "find_floating_signals"),
    ]
    for line, expected in parser_cases:
        req = try_parse_structural_health_request(line)
        check(req is not None and req["op"] == expected, f"parse -> {expected}")

    print("\nall structural-health smoke tests passed")


if __name__ == "__main__":
    main()
