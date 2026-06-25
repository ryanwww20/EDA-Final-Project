#!/usr/bin/env python3
"""Post-run validator for ICCAD Problem A public testcase outputs.

This script intentionally avoids touching the main EDA flow.  It scans logs and
generated Verilog files, checks contest-facing evidence, and writes compact CSV
and JSON summaries that are easy to include in final presentation material.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LEGAL_GATE_TYPES = ("and", "or", "nand", "nor", "not", "buf", "xor", "xnor", "dff")
COMB_GATE_TYPES = tuple(t for t in LEGAL_GATE_TYPES if t != "dff")
CONST_RE = re.compile(r"\s*1'b[01]\s*", re.I)
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*(?:\s*\[[^\]]+\])?")
DECL_KINDS = {"input", "output", "wire"}
NAMED_OUTPUT_PORTS = {"y", "z", "zn", "q", "out", "o"}
DFF_OUTPUT_PORTS = {"q", "qn"}


@dataclass
class Gate:
    gtype: str
    name: str
    out: str | None
    ins: list[str] = field(default_factory=list)
    ports: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedNetlist:
    module: str | None = None
    declared_bases: set[str] = field(default_factory=set)
    declared_signals: set[str] = field(default_factory=set)
    inputs: set[str] = field(default_factory=set)
    outputs: set[str] = field(default_factory=set)
    wires: set[str] = field(default_factory=set)
    gates: list[Gate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    undefined_signals: set[str] = field(default_factory=set)
    gate_counts: Counter[str] = field(default_factory=Counter)
    max_fanout: int = 0
    max_depth: int = 0


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {value!r}")


def strip_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def normalize_signal(signal: str | None) -> str:
    if not signal:
        return ""
    return re.sub(r"\s+", "", signal.strip())


def is_constant(signal: str | None) -> bool:
    return bool(signal and CONST_RE.fullmatch(signal))


def signal_base(signal: str) -> str:
    signal = normalize_signal(signal)
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_$]*)", signal)
    return match.group(1) if match else signal


def expand_bus(base: str, msb: int, lsb: int) -> list[str]:
    lo, hi = sorted((msb, lsb))
    return [f"{base}[{idx}]" for idx in range(lo, hi + 1)]


def split_csv_like(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(ch)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def parse_decl_statement(statement: str, netlist: ParsedNetlist) -> bool:
    match = re.match(r"^\s*(input|output|wire)\b\s*(.*)$", statement, re.S | re.I)
    if not match:
        return False

    kind = match.group(1).lower()
    rest = match.group(2).strip()
    rest = re.sub(r"\b(?:wire|reg|logic|signed)\b", " ", rest)
    range_match = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", rest)
    msb_lsb: tuple[int, int] | None = None
    if range_match:
        msb_lsb = (int(range_match.group(1)), int(range_match.group(2)))
        rest = rest[: range_match.start()] + " " + rest[range_match.end() :]

    store = {"input": netlist.inputs, "output": netlist.outputs, "wire": netlist.wires}[kind]
    for raw_name in split_csv_like(rest):
        raw_name = raw_name.split("=", 1)[0].strip()
        name_match = re.match(r"([A-Za-z_][A-Za-z0-9_$]*)", raw_name)
        if not name_match:
            continue
        base = name_match.group(1)
        netlist.declared_bases.add(base)
        netlist.declared_signals.add(base)
        if msb_lsb is None:
            store.add(base)
        else:
            for bit in expand_bus(base, msb_lsb[0], msb_lsb[1]):
                store.add(bit)
                netlist.declared_signals.add(bit)
    return True


def parse_named_ports(args: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    for port, signal in re.findall(r"\.(\w+)\s*\(\s*([^()]*?)\s*\)", args, flags=re.S):
        ports[port] = normalize_signal(signal)
    return ports


def parse_instance(statement: str, netlist: ParsedNetlist) -> None:
    match = re.match(
        r"^\s*([A-Za-z_][A-Za-z0-9_$]*)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*)\)\s*$",
        statement,
        flags=re.S,
    )
    if not match:
        if statement.strip():
            netlist.errors.append(f"malformed statement: {statement.strip()[:100]}")
        return

    gtype = match.group(1).lower()
    name = match.group(2)
    args = match.group(3).strip()
    if gtype not in LEGAL_GATE_TYPES:
        netlist.errors.append(f"illegal gate/module type {gtype!r} in instance {name}")
        return

    ports = parse_named_ports(args)
    out: str | None = None
    ins: list[str] = []
    if ports:
        lowered = {pin.lower(): sig for pin, sig in ports.items()}
        if gtype == "dff":
            for pin in DFF_OUTPUT_PORTS:
                if pin in lowered:
                    out = lowered[pin]
                    break
            ins = [sig for pin, sig in lowered.items() if pin not in DFF_OUTPUT_PORTS]
            if not out:
                netlist.errors.append(f"malformed dff {name}: missing Q output")
            if "d" not in lowered:
                netlist.warnings.append(f"dff {name}: missing D pin")
        else:
            for pin in NAMED_OUTPUT_PORTS:
                if pin in lowered:
                    out = lowered[pin]
                    break
            ins = [sig for pin, sig in lowered.items() if pin not in NAMED_OUTPUT_PORTS]
            if not out:
                netlist.errors.append(f"malformed {gtype} {name}: missing output port")
    else:
        nets = [normalize_signal(part) for part in split_csv_like(args)]
        if nets:
            out = nets[0]
            ins = nets[1:]
        min_args = 2 if gtype in {"not", "buf"} else 3
        if gtype == "dff":
            min_args = 2
        if len(nets) < min_args:
            netlist.errors.append(
                f"malformed {gtype} {name}: expected at least {min_args} positional args"
            )

    if gtype in {"not", "buf"} and len(ins) != 1:
        netlist.errors.append(f"malformed {gtype} {name}: expected exactly one input")
    if gtype in {"and", "or", "nand", "nor", "xor", "xnor"} and len(ins) < 2:
        netlist.errors.append(f"malformed {gtype} {name}: expected at least two inputs")
    if not out:
        netlist.errors.append(f"malformed {gtype} {name}: missing output signal")

    netlist.gates.append(Gate(gtype=gtype, name=name, out=out, ins=ins, ports=ports))


def is_declared(signal: str, netlist: ParsedNetlist) -> bool:
    if signal in netlist.declared_signals:
        return True
    return signal_base(signal) in netlist.declared_bases


def compute_netlist_checks(netlist: ParsedNetlist, allow_implicit_wires: bool) -> None:
    netlist.gate_counts = Counter(g.gtype for g in netlist.gates)
    input_signals = set(netlist.inputs)
    input_bases = {signal_base(sig) for sig in netlist.inputs}

    drivers: dict[str, list[str]] = defaultdict(list)
    fanout: dict[str, list[str]] = defaultdict(list)
    for gate in netlist.gates:
        if gate.out and not is_constant(gate.out):
            drivers[gate.out].append(gate.name)
        for signal in gate.ins:
            if signal and not is_constant(signal):
                fanout[signal].append(gate.name)

    for signal, gate_names in drivers.items():
        if len(gate_names) > 1:
            netlist.warnings.append(
                f"multiple drivers for {signal}: {', '.join(gate_names[:5])}"
            )

    undefined: set[str] = set()
    for gate in netlist.gates:
        gate_signals = ([gate.out] if gate.out else []) + gate.ins
        for signal in gate_signals:
            if not signal or is_constant(signal):
                continue
            if not is_declared(signal, netlist):
                undefined.add(signal)

    for signal in sorted(undefined):
        driven = signal in drivers
        if allow_implicit_wires and driven:
            netlist.warnings.append(f"implicit wire inferred for {signal}")
        else:
            netlist.errors.append(f"undefined signal {signal}")
            netlist.undefined_signals.add(signal)

    netlist.max_fanout = max((len(loads) for loads in fanout.values()), default=0)

    driver_gate = {
        signal: netlist.gates_by_name[name]
        for signal, names in drivers.items()
        if len(names) == 1
        for name in names
        if name in netlist.gates_by_name
    }

    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(signal: str | None) -> int:
        if not signal or is_constant(signal):
            return 0
        if signal in input_signals or signal_base(signal) in input_bases:
            return 0
        if signal in memo:
            return memo[signal]
        if signal in visiting:
            netlist.warnings.append(f"combinational loop guard hit at {signal}")
            return 0
        gate = driver_gate.get(signal)
        if gate is None or gate.gtype == "dff":
            memo[signal] = 0
            return 0
        visiting.add(signal)
        value = 1 + max((depth(src) for src in gate.ins), default=0)
        visiting.discard(signal)
        memo[signal] = value
        return value

    outputs = sorted(netlist.outputs) if netlist.outputs else [g.out for g in netlist.gates if g.out]
    netlist.max_depth = max((depth(out) for out in outputs), default=0)
def parse_verilog(path: Path, allow_implicit_wires: bool) -> ParsedNetlist:
    netlist = ParsedNetlist()
    text = path.read_text()
    cleaned = strip_comments(text)

    module_match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;", cleaned, re.S)
    if not module_match:
        netlist.errors.append("missing module header")
        return netlist
    if not re.search(r"\bendmodule\b", cleaned):
        netlist.errors.append("missing endmodule")
        return netlist

    netlist.module = module_match.group(1)
    body = cleaned[module_match.end() : re.search(r"\bendmodule\b", cleaned).start()]

    statements = [stmt.strip() for stmt in body.split(";") if stmt.strip()]
    for statement in statements:
        first = statement.split(None, 1)[0].lower() if statement.split(None, 1) else ""
        if first in DECL_KINDS:
            parse_decl_statement(statement, netlist)
        else:
            parse_instance(statement, netlist)

    netlist.gates_by_name = {gate.name: gate for gate in netlist.gates}  # type: ignore[attr-defined]
    compute_netlist_checks(netlist, allow_implicit_wires)
    return netlist


def check_log_protocol(text: str) -> tuple[bool, int, list[str]]:
    tag_re = re.compile(r"^#(RESPONSE|END)\s+(\d+)\s*$", re.M)
    open_id: int | None = None
    response_ids: list[int] = []
    end_ids: list[int] = []
    errors: list[str] = []

    for match in tag_re.finditer(text):
        tag = match.group(1)
        idx = int(match.group(2))
        if tag == "RESPONSE":
            if open_id is not None:
                errors.append(f"#RESPONSE {idx} opened before #END {open_id}")
            open_id = idx
            response_ids.append(idx)
        else:
            if open_id is None:
                errors.append(f"#END {idx} without matching #RESPONSE")
            elif idx != open_id:
                errors.append(f"#END {idx} does not match #RESPONSE {open_id}")
            open_id = None
            end_ids.append(idx)

    if open_id is not None:
        errors.append(f"#RESPONSE {open_id} missing #END")

    expected = list(range(1, len(response_ids) + 1))
    if response_ids != expected:
        errors.append(f"response ids are not continuous from 1: {response_ids[:10]}")
    if end_ids != response_ids:
        errors.append("response/end id sequence mismatch")
    return not errors, len(response_ids), errors


def parse_check_results(log_text: str) -> tuple[int, int, int, list[str]]:
    total = pass_count = fail_count = 0
    warnings: list[str] = []
    for line in log_text.splitlines():
        if not line.startswith("CHECK_RESULT:"):
            continue
        total += 1
        payload = line.split(":", 1)[1].strip()
        status = ""
        if payload.startswith("{"):
            try:
                data = json.loads(payload)
                status = str(data.get("status", "")).upper()
            except json.JSONDecodeError:
                warnings.append(f"malformed CHECK_RESULT JSON: {payload[:80]}")
        else:
            if re.search(r"\bPASS\b", payload, re.I):
                status = "PASS"
            elif re.search(r"\bFAIL\b", payload, re.I):
                status = "FAIL"

        if status == "PASS":
            pass_count += 1
        elif status == "FAIL":
            fail_count += 1
        else:
            warnings.append(f"unknown CHECK_RESULT status: {payload[:80]}")
    return total, pass_count, fail_count, warnings


def candidate_log_paths(run_dir: Path, case: str) -> list[Path]:
    return [
        run_dir / f"{case}.log",
        run_dir / "log" / f"{case}.log",
        run_dir / "output" / "log" / f"{case}.log",
    ]


def candidate_out_paths(run_dir: Path, case: str) -> list[Path]:
    return [
        run_dir / f"{case}_out.v",
        run_dir / "out_v" / f"{case}_out.v",
        run_dir / "output" / "out_v" / f"{case}_out.v",
        run_dir / case / f"{case}_out.v",
    ]


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def infer_cases(run_dir: Path) -> list[str]:
    cases: set[str] = set()
    search_dirs = [
        run_dir,
        run_dir / "log",
        run_dir / "out_v",
        run_dir / "output" / "log",
        run_dir / "output" / "out_v",
    ]
    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in directory.glob("*.log"):
            cases.add(path.stem)
        for path in directory.glob("*_out.v"):
            cases.add(path.name[: -len("_out.v")])
    return sorted(cases, key=case_sort_key)


def case_sort_key(case: str) -> tuple[str, int, str]:
    match = re.search(r"(\d+)$", case)
    if not match:
        return (case, -1, case)
    return (case[: match.start()], int(match.group(1)), case)


def run_expected_checks(row: dict[str, Any], checks: list[dict[str, Any]], log_text: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for check in checks:
        ctype = check.get("type")
        if ctype == "output_parse_ok":
            ok = bool(row["out_v_parse_ok"])
        elif ctype == "no_undefined_signals":
            ok = int(row["undefined_signal_count"]) == 0
        elif ctype == "gate_type_absent":
            ok = int(row.get(f"{check.get('gate_type', '').lower()}_count", 0)) == 0
        elif ctype == "gate_type_count_eq":
            ok = int(row.get(f"{check.get('gate_type', '').lower()}_count", 0)) == int(check["value"])
        elif ctype == "gate_type_count_le":
            ok = int(row.get(f"{check.get('gate_type', '').lower()}_count", 0)) <= int(check["value"])
        elif ctype == "gate_type_count_ge":
            ok = int(row.get(f"{check.get('gate_type', '').lower()}_count", 0)) >= int(check["value"])
        elif ctype == "max_fanout_le":
            ok = int(row["max_fanout"]) <= int(check["value"])
        elif ctype == "max_depth_le":
            ok = int(row["max_depth"]) <= int(check["value"])
        elif ctype == "log_contains":
            ok = str(check.get("text", "")) in log_text
        elif ctype == "log_regex":
            ok = re.search(str(check.get("pattern", "")), log_text, re.M) is not None
        elif ctype == "check_result_pass":
            ok = int(row["check_result_count"]) > 0 and int(row["check_result_fail_count"]) == 0
        else:
            ok = False
            failures.append(f"unknown expected check type {ctype!r}")
            continue

        if not ok:
            failures.append(f"expected check failed: {check}")
    return not failures, failures


CSV_COLUMNS = [
    "case",
    "final_status",
    "log_exists",
    "tags_ok",
    "response_count",
    "out_v_exists",
    "out_v_parse_ok",
    "undefined_signal_count",
    "warning_count",
    "error_count",
    "gate_total",
    "and_count",
    "or_count",
    "nand_count",
    "nor_count",
    "not_count",
    "buf_count",
    "xor_count",
    "xnor_count",
    "dff_count",
    "max_fanout",
    "max_depth",
    "check_result_count",
    "check_result_pass_count",
    "check_result_fail_count",
    "expected_checks_ok",
    "note",
]


def validate_case(
    run_dir: Path,
    case: str,
    *,
    strict_output_required: bool,
    allow_implicit_wires: bool,
    expected: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    row: dict[str, Any] = {column: "" for column in CSV_COLUMNS}
    row["case"] = case
    row["final_status"] = "FAIL"
    for key in ("log_exists", "tags_ok", "out_v_exists", "out_v_parse_ok", "expected_checks_ok"):
        row[key] = False
    for key in (
        "response_count",
        "undefined_signal_count",
        "warning_count",
        "error_count",
        "gate_total",
        "max_fanout",
        "max_depth",
        "check_result_count",
        "check_result_pass_count",
        "check_result_fail_count",
    ):
        row[key] = 0
    for gate_type in LEGAL_GATE_TYPES:
        row[f"{gate_type}_count"] = 0

    notes: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    log_text = ""
    log_path = first_existing(candidate_log_paths(run_dir, case))
    if log_path is not None:
        row["log_exists"] = True
        log_text = log_path.read_text(errors="replace")
        tags_ok, response_count, protocol_errors = check_log_protocol(log_text)
        row["tags_ok"] = tags_ok
        row["response_count"] = response_count
        errors.extend(protocol_errors)
        cr_count, cr_pass, cr_fail, cr_warnings = parse_check_results(log_text)
        row["check_result_count"] = cr_count
        row["check_result_pass_count"] = cr_pass
        row["check_result_fail_count"] = cr_fail
        warnings.extend(cr_warnings)
        if cr_fail:
            errors.append(f"{cr_fail} CHECK_RESULT failure(s)")
    else:
        errors.append("missing log")

    out_path = first_existing(candidate_out_paths(run_dir, case))
    if out_path is not None:
        row["out_v_exists"] = True
        try:
            parsed = parse_verilog(out_path, allow_implicit_wires=allow_implicit_wires)
            row["out_v_parse_ok"] = not parsed.errors
            row["undefined_signal_count"] = len(parsed.undefined_signals)
            row["gate_total"] = len(parsed.gates)
            for gate_type in LEGAL_GATE_TYPES:
                row[f"{gate_type}_count"] = parsed.gate_counts.get(gate_type, 0)
            row["max_fanout"] = parsed.max_fanout
            row["max_depth"] = parsed.max_depth
            errors.extend(parsed.errors)
            warnings.extend(parsed.warnings)
        except Exception as exc:  # noqa: BLE001 - validator should record and continue.
            errors.append(f"Verilog parse exception: {exc}")
    elif strict_output_required:
        errors.append("missing output Verilog")
    else:
        notes.append("output Verilog not required")

    expected_checks = expected.get(case, [])
    expected_ok, expected_failures = run_expected_checks(row, expected_checks, log_text)
    row["expected_checks_ok"] = expected_ok
    errors.extend(expected_failures)

    row["warning_count"] = len(warnings)
    row["error_count"] = len(errors)
    if not errors:
        row["final_status"] = "PASS"
    note_parts = notes + errors[:5]
    if len(errors) > 5:
        note_parts.append(f"... {len(errors) - 5} more error(s)")
    if warnings and not errors:
        note_parts.append(f"{len(warnings)} warning(s)")
    row["note"] = " | ".join(note_parts)
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_json_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "total_cases": total,
        "final_pass": sum(1 for row in rows if row["final_status"] == "PASS"),
        "protocol_pass": sum(1 for row in rows if row["log_exists"] and row["tags_ok"]),
        "output_parse_pass": sum(1 for row in rows if row["out_v_parse_ok"]),
        "expected_checks_pass": sum(1 for row in rows if row["expected_checks_ok"]),
        "check_result_failures": sum(int(row["check_result_fail_count"]) for row in rows),
        "cases": rows,
    }


def print_terminal_summary(summary: dict[str, Any], csv_path: Path, json_path: Path, rows: list[dict[str, Any]]) -> None:
    total = summary["total_cases"]
    print("# Validation summary")
    print()
    print(f"Cases:                    {total}")
    print(f"Final PASS:               {summary['final_pass']}/{total}")
    print(f"Protocol PASS:            {summary['protocol_pass']}/{total}")
    print(f"Output parse PASS:        {summary['output_parse_pass']}/{total}")
    print(f"Expected checks PASS:     {summary['expected_checks_pass']}/{total}")
    print(f"CHECK_RESULT failures:    {summary['check_result_failures']}")
    print(f"Wrote CSV:                {csv_path}")
    print(f"Wrote JSON:               {json_path}")

    failed = [row for row in rows if row["final_status"] != "PASS"]
    if failed:
        print()
        print("Failed cases:")
        print()
        for row in failed:
            note = row["note"] or "validation failed"
            print(f"* {row['case']}: {note}")


def load_expected(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if path is None:
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("expected checks file must contain a JSON object")
    result: dict[str, list[dict[str, Any]]] = {}
    for case, checks in data.items():
        if not isinstance(checks, list):
            raise ValueError(f"expected checks for {case} must be a list")
        result[case] = checks
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate post-run EDA testcase outputs.")
    parser.add_argument("--run-dir", default=".", help="Directory containing logs/out_v files.")
    parser.add_argument("--expected", help="Optional expected_checks.json path.")
    parser.add_argument("--summary-csv", default="validation_summary.csv")
    parser.add_argument("--summary-json", default="validation_summary.json")
    parser.add_argument("--cases", nargs="+", help="Explicit testcase names to validate.")
    parser.add_argument("--strict-output-required", type=parse_bool, default=True)
    parser.add_argument(
        "--allow-implicit-wires",
        type=parse_bool,
        default=False,
        help="Treat undeclared driven nets as warnings instead of hard errors.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-case PASS/FAIL lines.")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    expected = load_expected(Path(args.expected) if args.expected else None)
    cases = args.cases if args.cases else infer_cases(run_dir)
    if not cases:
        print(f"No cases found under {run_dir}", file=sys.stderr)
        return 2

    rows = [
        validate_case(
            run_dir,
            case,
            strict_output_required=args.strict_output_required,
            allow_implicit_wires=args.allow_implicit_wires,
            expected=expected,
        )
        for case in cases
    ]

    if args.verbose:
        for row in rows:
            suffix = f" - {row['note']}" if row["note"] else ""
            print(f"[{row['final_status']}] {row['case']}{suffix}")

    csv_path = Path(args.summary_csv)
    json_path = Path(args.summary_json)
    write_csv(csv_path, rows)
    summary = build_json_summary(rows)
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    print_terminal_summary(summary, csv_path, json_path, rows)
    return 0 if summary["final_pass"] == summary["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
