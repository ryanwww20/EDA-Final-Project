from pathlib import Path
import re
from collections import Counter

GATE_TYPES = ["AND", "OR", "NOT", "NAND", "NOR", "XOR", "XNOR", "BUF", "DFF"]


def remove_comments(code: str) -> str:
    # remove /* ... */ comments
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    # remove // comments
    code = re.sub(r"//.*", "", code)
    return code


def count_gates(verilog_code: str) -> Counter:
    code = remove_comments(verilog_code)

    counts = Counter()
    for gate in GATE_TYPES:
        # Match patterns like: and g1 (...); or AND g1 (...);
        pattern = rf"(?i)\b{re.escape(gate)}\b\s+\w+\s*\("
        counts[gate] = len(re.findall(pattern, code))

    return counts


def format_gate_count_report(counts: Counter) -> str:
    lines = ["Gate count:"]
    total = 0
    for gate in GATE_TYPES:
        n = counts[gate]
        total += n
        lines.append(f"{gate}: {n}")
    lines.append(f"TOTAL: {total}")
    return "\n".join(lines)


def report_gate_counts(verilog_code: str) -> str:
    """Count gates and return a formatted report (for main.py / other callers)."""
    return format_gate_count_report(count_gates(verilog_code))


def report_gate_counts_from_file(path) -> str:
    """Read a Verilog file, count gates, and return a formatted report."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot find input file: {path}")
    return report_gate_counts(path.read_text())


def run_standalone(case_name: str = "test02") -> None:
    case_dir = Path("testcase") / case_name
    input_file = case_dir / f"{case_name}.v"
    output_file = case_dir / f"{case_name}_out.v"

    if not input_file.exists():
        raise FileNotFoundError(f"Cannot find input file: {input_file}")

    verilog_code = input_file.read_text()
    counts = count_gates(verilog_code)

    output_file.write_text(verilog_code)

    print(f"Case name: {case_name}")
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print()
    print(format_gate_count_report(counts))


if __name__ == "__main__":
    run_standalone()
