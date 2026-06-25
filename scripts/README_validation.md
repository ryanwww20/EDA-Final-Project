# Validation Script

Run after executing public testcases:

```bash
python3 scripts/validate_all.py --run-dir output
```

The script accepts both the project output layout:

```text
output/log/test01.log
output/out_v/test01_out.v
```

and a flat run directory:

```text
run/test01.log
run/test01_out.v
```

Useful options:

```bash
python3 scripts/validate_all.py \
  --run-dir output \
  --expected scripts/expected_checks.example.json \
  --summary-csv validation_summary.csv \
  --summary-json validation_summary.json \
  --cases test01 test02 \
  --strict-output-required true \
  --verbose
```

The CSV contains one row per testcase with PASS/FAIL status, log protocol
status, Verilog parse status, undefined-signal count, gate counts, max fanout,
rough max combinational depth, CHECK_RESULT counts, and expected-check status.
