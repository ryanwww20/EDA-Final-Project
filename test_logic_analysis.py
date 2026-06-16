#!/usr/bin/env python3
"""Smoke tests for tools.analysis_logic using netlist_twoside.parse()."""

from pathlib import Path

from netlist_twoside import parse
from tools.analysis_logic import (
    boolean_function_of_output,
    derive_boolean_equation,
    function_symmetric,
    output_always_constant,
    output_depends_on_input,
    signals_equivalent,
    try_parse_logic_request,
    write_logic_expression,
)

SIMPLE = Path(__file__).resolve().parent / "simple.v"

CASES = [
    ("derive_boolean_equation(y)", lambda nl: derive_boolean_equation(nl, "y"), "y = c | ~(a & b)"),
    ("write_logic_expression(n2)", lambda nl: write_logic_expression(nl, "n2"), "~(a & b)"),
    ("boolean_function_of_output(y)", lambda nl: boolean_function_of_output(nl, "y"), "y = c | ~(a & b)"),
    ("signals_equivalent(n1, n2)", lambda nl: signals_equivalent(nl, "n1", "n2"), False),
    ("output_always_constant(y, 0)", lambda nl: output_always_constant(nl, "y", 0), False),
    ("output_depends_on_input(y, a)", lambda nl: output_depends_on_input(nl, "y", "a"), True),
    ("function_symmetric(n1, a, b)", lambda nl: function_symmetric(nl, "n1", "a", "b"), True),
]

PARSE_CASES = [
    (
        "Verify that n1039 and n1046 produce identical logic values for all inputs.",
        {"op": "signals_equivalent", "args": {"sig_a": "n1039", "sig_b": "n1046"}},
    ),
    (
        "Check functional equivalence between internal signals n1035 and n1029.",
        {"op": "signals_equivalent", "args": {"sig_a": "n1035", "sig_b": "n1029"}},
    ),
    (
        "Check whether the function at n11 is symmetric with respect to inputs n3 and n9[0].",
        {"op": "function_symmetric", "args": {"node": "n11", "in_a": "n3", "in_b": "n9[0]"}},
    ),
]


def main() -> int:
    nl = parse(str(SIMPLE))
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

    for line, expected in PARSE_CASES:
        got = try_parse_logic_request(line)
        ok = got == expected
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] parse: {line}")
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
