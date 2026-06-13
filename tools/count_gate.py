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


def main():
    case_name = "test02"
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
    print("Gate count:")
    total = 0
    for gate in GATE_TYPES:
        n = counts[gate]
        total += n
        print(f"{gate}: {n}")

    print(f"TOTAL: {total}")


if __name__ == "__main__":
    main()
