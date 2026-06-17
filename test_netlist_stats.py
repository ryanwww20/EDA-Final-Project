#!/usr/bin/env python3
"""Smoke test for tools.analysis_netlist_stats against real testcases."""

from netlist_twoside import parse
from tools.analysis_netlist_stats import (
    count_total_gates,
    count_gates_of_type,
    list_gates_of_type,
    count_gates_by_type_in_cone,
    max_fanin_cone_depth,
    count_primary_inputs_outputs,
    list_primary_inputs_with_widths,
    list_primary_outputs_with_widths,
    get_gate_info,
    list_nand_gates_with_pins,
    dispatch_netlist_stats_op,
    format_netlist_stats_result,
    try_parse_netlist_stats_request,
)


def check(cond, msg):
    print(f"{'ok  ' if cond else 'FAIL'} {msg}")
    assert cond, msg


def main():
    nl = parse("testcase/test39/test39.v")

    totals = count_total_gates(nl)
    check(totals["total"] == len(nl.gates), "count_total_gates total matches IR")
    check(sum(totals["by_type"].values()) == totals["total"], "by_type sums to total")

    # per-type consistency
    for disp, t in (("NOT", "not"), ("XOR", "xor"), ("NAND", "nand")):
        check(count_gates_of_type(nl, t) == totals["by_type"][disp],
              f"count_gates_of_type {t} matches breakdown")
        check(len(list_gates_of_type(nl, t)) == count_gates_of_type(nl, t),
              f"list_gates_of_type {t} length matches count")

    # PI/PO inventory: bit counts and port listings agree
    io = count_primary_inputs_outputs(nl)
    pis = list_primary_inputs_with_widths(nl)
    pos = list_primary_outputs_with_widths(nl)
    check(io["pi_ports"] == len(pis), "pi_ports matches PI listing length")
    check(io["po_ports"] == len(pos), "po_ports matches PO listing length")
    check(io["pi_bits"] == sum(w for _, w in pis), "pi_bits == sum of PI widths")
    check(io["po_bits"] == sum(w for _, w in pos), "po_bits == sum of PO widths")
    # test39 declares input [15:0] n9 etc -> at least one wide bus
    check(any(w > 1 for _, w in pis), "detects bussed primary inputs")

    # cone stats on an output with logic behind it
    out = next(p for p, w in pos if w == 1)
    cone = count_gates_by_type_in_cone(nl, out)
    check(cone["total"] >= 0, "count_gates_by_type_in_cone runs")
    depth = max_fanin_cone_depth(nl, out)
    check(depth >= 0, "max_fanin_cone_depth runs")

    # gate info
    g = next(iter(nl.gates))
    info = get_gate_info(nl, g)
    check(info["name"] == g, "get_gate_info returns the gate")

    nands = list_nand_gates_with_pins(nl)
    check(len(nands) == count_gates_of_type(nl, "nand"),
          "list_nand_gates_with_pins length matches NAND count")

    # dispatcher + formatter round trip
    payload = dispatch_netlist_stats_op(nl, {"op": "count_total_gates", "args": {}})
    text = format_netlist_stats_result(payload)
    check("TOTAL:" in text, "formatter renders total gate count")

    # prompt parsing for the exact testcase phrasings
    cases = [
        ("Please count all the gates in this design and report the total count broken down by gate type (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF).", "count_total_gates"),
        ("How many NOT gates are currently in the design?", "count_gates_of_type"),
        ("List all XOR gates in this design.", "list_gates_of_type"),
        ("Report the number of each gate type in the cone of n14.", "count_gates_by_type_in_cone"),
        ("Compute the maximum logic depth of the fanin cone of output n3.", "max_fanin_cone_depth"),
        ("Determine the number of primary inputs and outputs.", "count_primary_inputs_outputs"),
        ("How many primary inputs and primary outputs does this design have?", "count_primary_inputs_outputs"),
        ("Please list all the primary inputs of this design with their bit widths.", "list_primary_inputs_with_widths"),
        ("List all primary outputs of this design with their bit widths.", "list_primary_outputs_with_widths"),
        ("What type of gate is g0? Report its gate type and pin connections.", "get_gate_info"),
        ("List all NAND gates in this design with their input and output signals.", "list_nand_gates_with_pins"),
    ]
    for line, expected in cases:
        req = try_parse_netlist_stats_request(line)
        check(req is not None and req["op"] == expected,
              f"parse -> {expected}: {line[:48]!r}")

    print("\nall netlist-stats smoke tests passed")


if __name__ == "__main__":
    main()
