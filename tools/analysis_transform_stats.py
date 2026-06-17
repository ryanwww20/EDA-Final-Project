"""
Transformation-result statistics.

Section 1.8 of tools/tool.md.  Unlike the pure netlist analyses in sections
1.1-1.6, these queries may need persistent transformation reports from State:
"how many gates were added/removed/eliminated" is a delta, not just a property
of the current netlist.

The module still follows the normal backend shape: pure-ish query helpers first,
then OP_TABLE, dispatcher, formatter, and a small rule-based prompt parser.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from netlist_twoside import Netlist
from tools.analysis_netlist_stats import (
    count_gates_by_type_in_cone,
    max_fanin_cone_depth,
)
from tools.analysis_structural_health import dangling_gates

_GATE_TYPES = {"and", "or", "not", "nand", "nor", "xor", "xnor", "buf", "dff"}


def _norm_type(gtype: str | None) -> str | None:
    if gtype is None:
        return None
    text = str(gtype).strip().lower()
    return text if text else None


def _state_netlist(state: Any) -> Netlist:
    netlist = getattr(state, "netlist", None)
    if netlist is None:
        raise ValueError("No design loaded.")
    return netlist


def _history(state: Any) -> list[dict[str, Any]]:
    hist = getattr(state, "transform_history", None)
    if isinstance(hist, list):
        return [r for r in hist if isinstance(r, dict)]
    return []


def _latest_report(state: Any) -> dict[str, Any]:
    report = getattr(state, "last_transform_report", None)
    if isinstance(report, dict):
        return report
    hist = _history(state)
    return hist[-1] if hist else {}


def _latest_report_with_any(state: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    report = _latest_report(state)
    if any(k in report for k in keys):
        return report
    for item in reversed(_history(state)):
        if any(k in item for k in keys):
            return item
    return report


def _gate_type_counts(netlist: Netlist) -> Counter[str]:
    return Counter(g.type for g in netlist.gates.values())


def _previous_netlist(state: Any) -> Netlist | None:
    prev = getattr(state, "pre_transform_netlist", None)
    return prev if isinstance(prev, Netlist) else None


def _type_count_from_mapping(value: Any, gtype: str) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in (gtype, gtype.upper()):
        if key in value:
            try:
                return int(value[key])
            except (TypeError, ValueError):
                return None
    return None


def _count_typed_items(value: Any, gtype: str | None = None) -> int | None:
    """Count report payloads shaped as int, list, or type->count dict."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        if gtype is not None:
            typed = _type_count_from_mapping(value, gtype)
            if typed is not None:
                return typed
        if "count" in value:
            try:
                return int(value["count"])
            except (TypeError, ValueError):
                return None
        return None
    if isinstance(value, (list, tuple, set)):
        if gtype is None:
            return len(value)
        count = 0
        saw_type = False
        for item in value:
            item_type = None
            if isinstance(item, dict):
                item_type = item.get("type") or item.get("gate_type")
            elif hasattr(item, "type"):
                item_type = getattr(item, "type")
            if item_type is not None:
                saw_type = True
                if _norm_type(item_type) == gtype:
                    count += 1
        return count if saw_type else None
    return None


def _first_count(report: dict[str, Any], keys: tuple[str, ...], gtype: str | None = None) -> int | None:
    for key in keys:
        if key not in report:
            continue
        count = _count_typed_items(report[key], gtype)
        if count is not None:
            return count
    return None


def _count_added_by_type_from_diff(state: Any, gtype: str) -> int | None:
    prev = _previous_netlist(state)
    if prev is None:
        return None
    current = _state_netlist(state)
    return max(0, _gate_type_counts(current)[gtype] - _gate_type_counts(prev)[gtype])


def _count_removed_by_type_from_diff(state: Any, gtype: str | None = None) -> int | None:
    prev = _previous_netlist(state)
    if prev is None:
        return None
    current = _state_netlist(state)
    if gtype is not None:
        return max(0, _gate_type_counts(prev)[gtype] - _gate_type_counts(current)[gtype])
    return max(0, len(prev.gates) - len(current.gates))


def _with_source(count: int | None, source: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"count": 0 if count is None else count, "source": source, "detail": detail or {}}


def count_added_gates_of_type(state: Any, gtype: str) -> dict[str, Any]:
    """Count gates of a given type added by the latest relevant transform."""
    t = _norm_type(gtype)
    if t not in _GATE_TYPES:
        raise ValueError(f"Unsupported gate type: {gtype}")

    keys = (
        "added_gates_by_type",
        "added_by_type",
        "added_gate_count_by_type",
        "added_gates",
    )
    report = _latest_report_with_any(state, keys)
    count = _first_count(report, keys, t)
    if count is not None:
        return _with_source(count, "last_transform_report", detail={"report_op": report.get("op")})

    diff = _count_added_by_type_from_diff(state, t)
    if diff is not None:
        return _with_source(diff, "pre_transform_diff")
    return _with_source(None, "unavailable")


def count_added_buffers(state: Any) -> dict[str, Any]:
    return count_added_gates_of_type(state, "buf")


def count_removed_dangling(state: Any) -> dict[str, Any]:
    keys = (
        "removed_dangling",
        "removed_dangling_gates",
        "dangling_gates_removed",
        "removed_gates",
    )
    report = _latest_report_with_any(state, keys)
    count = _first_count(report, keys)
    if count is not None:
        return _with_source(count, "last_transform_report", detail={"report_op": report.get("op")})

    prev = _previous_netlist(state)
    if prev is not None:
        current_names = set(_state_netlist(state).gates)
        removed = [name for name in dangling_gates(prev) if name not in current_names]
        return _with_source(len(removed), "pre_transform_diff", detail={"removed": removed})
    return _with_source(None, "unavailable")


def count_removed_redundant(state: Any) -> dict[str, Any]:
    keys = (
        "removed_redundant",
        "removed_redundant_gates",
        "redundant_gates_removed",
        "removed_gates",
    )
    report = _latest_report_with_any(state, keys)
    count = _first_count(report, keys)
    if count is not None:
        return _with_source(count, "last_transform_report", detail={"report_op": report.get("op")})

    diff = _count_removed_by_type_from_diff(state)
    if diff is not None:
        return _with_source(diff, "pre_transform_diff")
    return _with_source(None, "unavailable")


def count_merged_gates(state: Any) -> dict[str, Any]:
    keys = (
        "merged_gates",
        "merge_count",
        "merged_count",
        "removed_duplicate_gates",
        "removed_gates",
    )
    report = _latest_report_with_any(state, keys)
    count = _first_count(report, keys)
    if count is not None:
        return _with_source(count, "last_transform_report", detail={"report_op": report.get("op")})

    diff = _count_removed_by_type_from_diff(state)
    if diff is not None:
        return _with_source(diff, "pre_transform_diff")
    return _with_source(None, "unavailable")


def count_eliminated_by_const_prop(state: Any, gtype: str) -> dict[str, Any]:
    t = _norm_type(gtype)
    if t not in _GATE_TYPES:
        raise ValueError(f"Unsupported gate type: {gtype}")

    keys = (
        "const_prop_eliminated_by_type",
        "constant_propagation_eliminated_by_type",
        "eliminated_gates_by_type",
        "removed_gates_by_type",
        "eliminated_gates",
        "removed_gates",
    )
    report = _latest_report_with_any(state, keys)
    count = _first_count(report, keys, t)
    if count is not None:
        return _with_source(count, "last_transform_report", detail={"report_op": report.get("op")})

    diff = _count_removed_by_type_from_diff(state, t)
    if diff is not None:
        return _with_source(diff, "pre_transform_diff")
    return _with_source(None, "unavailable")


def count_gates_in_cone_after_restructure(
    state: Any,
    output: str,
    gtype: str,
) -> dict[str, Any]:
    t = _norm_type(gtype)
    if t not in _GATE_TYPES:
        raise ValueError(f"Unsupported gate type: {gtype}")
    result = count_gates_by_type_in_cone(_state_netlist(state), output)
    return {
        "output": output,
        "type": t,
        "count": result["by_type"].get(t.upper(), 0),
        "by_type": result["by_type"],
        "total": result["total"],
    }


def cone_depth_after_opt(state: Any, output: str) -> dict[str, Any]:
    return {
        "output": output,
        "depth": max_fanin_cone_depth(_state_netlist(state), output),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

OP_TABLE: dict[str, dict[str, Any]] = {
    "count_added_buffers": {
        "func": lambda st, _a: count_added_buffers(st),
        "required_args": (),
        "category": "transform_stats",
        "public": True,
        "description": "Count BUF gates added by the latest buffer insertion transform.",
    },
    "count_added_gates_of_type": {
        "func": lambda st, a: count_added_gates_of_type(st, a["type"]),
        "required_args": ("type",),
        "category": "transform_stats",
        "public": True,
        "description": "Count gates of a given type added by the latest relevant transform.",
    },
    "count_removed_dangling": {
        "func": lambda st, _a: count_removed_dangling(st),
        "required_args": (),
        "category": "transform_stats",
        "public": True,
        "description": "Count dangling gates removed by the latest cleanup transform.",
    },
    "count_removed_redundant": {
        "func": lambda st, _a: count_removed_redundant(st),
        "required_args": (),
        "category": "transform_stats",
        "public": True,
        "description": "Count redundant gates removed by the latest redundancy cleanup transform.",
    },
    "count_merged_gates": {
        "func": lambda st, _a: count_merged_gates(st),
        "required_args": (),
        "category": "transform_stats",
        "public": True,
        "description": "Count gates merged by the latest merge transform.",
    },
    "count_eliminated_by_const_prop": {
        "func": lambda st, a: count_eliminated_by_const_prop(st, a["type"]),
        "required_args": ("type",),
        "category": "transform_stats",
        "public": True,
        "description": "Count gates of a given type eliminated by constant propagation.",
    },
    "count_gates_in_cone_after_restructure": {
        "func": lambda st, a: count_gates_in_cone_after_restructure(
            st,
            a["output"],
            a["type"],
        ),
        "required_args": ("output", "type"),
        "category": "transform_stats",
        "public": True,
        "description": "Count gates of a given type in an output cone after restructure.",
    },
    "cone_depth_after_opt": {
        "func": lambda st, a: cone_depth_after_opt(st, a["output"]),
        "required_args": ("output",),
        "category": "transform_stats",
        "public": True,
        "description": "Report an output cone depth after optimization.",
    },
}

PUBLIC_OP_TABLE = {name: meta for name, meta in OP_TABLE.items() if meta.get("public")}


def get_public_op_catalog() -> list[dict[str, Any]]:
    return [
        {
            "op": name,
            "required_args": list(meta["required_args"]),
            "optional_args": list(meta.get("optional_args", ())),
            "category": meta["category"],
            "description": meta["description"],
        }
        for name, meta in PUBLIC_OP_TABLE.items()
    ]


def _normalize_args(op: str, args: dict[str, Any]) -> dict[str, Any]:
    args = dict(args)
    if op in ("count_added_gates_of_type", "count_eliminated_by_const_prop"):
        args.setdefault("type", args.get("gate_type") or args.get("gtype"))
    if op == "count_gates_in_cone_after_restructure":
        args.setdefault("output", args.get("target") or args.get("out"))
        args.setdefault("type", args.get("gate_type") or args.get("gtype"))
    if op == "cone_depth_after_opt":
        args.setdefault("output", args.get("target") or args.get("out"))
    return args


def dispatch_transform_stats_op(
    state: Any,
    request: dict[str, Any],
    *,
    public_only: bool = False,
) -> dict[str, Any]:
    op = request["op"]
    table = PUBLIC_OP_TABLE if public_only else OP_TABLE
    if op not in table:
        raise ValueError(f"Unknown transform stats op: {op}")

    meta = table[op]
    args = _normalize_args(op, request.get("args", {}))
    missing = [a for a in meta["required_args"] if a not in args or args[a] is None]
    if missing:
        raise ValueError(f"Missing args for {op}: {missing}")
    return {"op": op, "args": args, "result": meta["func"](state, args)}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _source_note(result: dict[str, Any]) -> str:
    source = result.get("source")
    if source == "unavailable":
        return " No transformation report was available, so the count defaults to 0."
    return ""


def format_transform_stats_result(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    if op == "count_added_buffers":
        return f"BUF gates added by the last buffer insertion: {result['count']}." + _source_note(result)
    if op == "count_added_gates_of_type":
        return (
            f"{args['type'].upper()} gates added by the latest relevant transform: "
            f"{result['count']}."
        ) + _source_note(result)
    if op == "count_removed_dangling":
        return f"Dangling gates removed: {result['count']}." + _source_note(result)
    if op == "count_removed_redundant":
        return f"Redundant gates removed: {result['count']}." + _source_note(result)
    if op == "count_merged_gates":
        return f"Gates merged: {result['count']}." + _source_note(result)
    if op == "count_eliminated_by_const_prop":
        return (
            f"{args['type'].upper()} gates eliminated by constant propagation: "
            f"{result['count']}."
        ) + _source_note(result)
    if op == "count_gates_in_cone_after_restructure":
        return (
            f"{result['type'].upper()} gates in the fanin cone of {result['output']} "
            f"now: {result['count']}."
        )
    if op == "cone_depth_after_opt":
        return f"Depth of the fanin cone of {result['output']} now: {result['depth']}."
    return f"{op}: {result}"


# ---------------------------------------------------------------------------
# Rule-based prompt parser
# ---------------------------------------------------------------------------

_NAME = r"([\w\[\]\.']+)"
_GATE_WORD = r"(AND|OR|NOT|NAND|NOR|XOR|XNOR|BUF|DFF)"


def try_parse_transform_stats_request(line: str) -> dict[str, Any] | None:
    low = line.lower()

    if re.search(r"buf gates?.*added", low) or re.search(r"buffers?.*were added", low):
        return {"op": "count_added_buffers", "args": {}}

    if m := re.search(rf"how many\s+{_GATE_WORD}\s+gates?\s+were added", line, re.I):
        gtype = m.group(1)
        if gtype.lower() == "buf":
            return {"op": "count_added_buffers", "args": {}}
        return {"op": "count_added_gates_of_type", "args": {"type": gtype}}

    if re.search(r"dangling gates?.*removed", low):
        return {"op": "count_removed_dangling", "args": {}}

    if re.search(r"redundant gates?.*removed", low):
        return {"op": "count_removed_redundant", "args": {}}

    if re.search(r"gates?.*merged", low) or re.search(r"merged.*structural duplicates", low):
        return {"op": "count_merged_gates", "args": {}}

    if m := re.search(rf"how many\s+{_GATE_WORD}\s+gates?\s+were eliminated by constant", line, re.I):
        return {"op": "count_eliminated_by_const_prop", "args": {"type": m.group(1)}}

    if m := re.search(
        rf"how many\s+{_GATE_WORD}\s+gates?.*restructured cone of output\s+{_NAME}",
        line,
        re.I,
    ):
        return {
            "op": "count_gates_in_cone_after_restructure",
            "args": {"type": m.group(1), "output": m.group(2)},
        }

    if m := re.search(
        rf"how many\s+{_GATE_WORD}\s+gates?.*cone of output\s+{_NAME}.*now",
        line,
        re.I,
    ):
        return {
            "op": "count_gates_in_cone_after_restructure",
            "args": {"type": m.group(1), "output": m.group(2)},
        }

    if m := re.search(rf"depth of the cone of\s+{_NAME}\s+now", line, re.I):
        return {"op": "cone_depth_after_opt", "args": {"output": m.group(1)}}

    if m := re.search(rf"cone of\s+{_NAME}.*depth.*now", line, re.I):
        return {"op": "cone_depth_after_opt", "args": {"output": m.group(1)}}

    return None
