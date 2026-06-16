"""
LLM-facing structured-operation layer.

The LLM is expected to return JSON, not free-form Python calls.  This module
owns the operation catalog, validates the JSON, and dispatches each operation
to the existing backend functions.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from netlist_twoside import dump, parse, summary
from tools.analysis_fanin_fanout import (
    dispatch_fanin_fanout_op,
    format_analysis_result,
    get_public_op_catalog as get_fanin_fanout_catalog,
)
from tools.analysis_logic import (
    dispatch_logic_op,
    format_logic_result,
    get_public_op_catalog as get_logic_catalog,
)


OperationHandler = Callable[[Any, dict[str, Any]], dict[str, Any]]
OperationFormatter = Callable[[dict[str, Any]], str]


def _handle_begin(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    args = request.get("args", {})
    case_name = args.get("case_name") or "case"
    state.case_name = case_name
    if state.log_file:
        state.log_file.close()
    state.log_file = open(f"{case_name}.log", "w")
    return {
        "op": "begin_testcase",
        "result": (
            f'Acknowledged. Initialized testcase "{case_name}". '
            f"All subsequent responses will be recorded to {case_name}.log. "
            f"Design state is empty and ready for commands."
        ),
    }


def _handle_load_design(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    args = request.get("args", {})
    path = args["path"]
    if not os.path.exists(path) and state.case_name:
        candidate = os.path.join("testcase", state.case_name, os.path.basename(path))
        if os.path.exists(candidate):
            path = candidate
    state.netlist = parse(path)
    s = summary(state.netlist)
    return {
        "op": "load_design",
        "result": (
            f"Loaded gate-level Verilog from {path} successfully.\n"
            f"- module: {s['module']}, single top module (flat netlist)\n"
            f"- gates: {s['num_gates_total']} "
            f"({s['num_combinational']} combinational, {s['num_dff']} DFF)\n"
            f"- PI: {s['num_inputs']}, PO: {s['num_outputs']}\n"
            f"- sequential: {s['is_sequential']}, clocks: {s['clock_nets']}"
        ),
    }


def _handle_write_design(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    args = request.get("args", {})
    if state.netlist is None:
        raise ValueError("No design loaded.")
    path = args["path"]
    dump(state.netlist, path)
    return {
        "op": "write_design",
        "result": f'Wrote the current design to "{path}" successfully.',
    }


def _handle_fanin_fanout(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_fanin_fanout_op(state.netlist, request, public_only=True)


def _handle_logic(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_logic_op(state.netlist, request, public_only=True)


def _format_passthrough(payload: dict[str, Any]) -> str:
    return str(payload["result"])


def _format_unimplemented(payload: dict[str, Any]) -> str:
    op = payload["op"]
    return f"[{op} not implemented yet]"


def _unimplemented_handler(_state: Any, request: dict[str, Any]) -> dict[str, Any]:
    return {"op": request["op"], "result": None}


BASE_OP_TABLE: dict[str, dict[str, Any]] = {
    "begin_testcase": {
        "required_args": ("case_name",),
        "category": "design_io",
        "description": "Initialize testcase state and open the testcase log file.",
        "handler": _handle_begin,
        "formatter": _format_passthrough,
    },
    "load_design": {
        "required_args": ("path",),
        "category": "design_io",
        "description": "Parse a gate-level Verilog file into the current design state.",
        "handler": _handle_load_design,
        "formatter": _format_passthrough,
    },
    "write_design": {
        "required_args": ("path",),
        "category": "design_io",
        "description": "Write the current design state to a gate-level Verilog file.",
        "handler": _handle_write_design,
        "formatter": _format_passthrough,
    },
}


UNIMPLEMENTED_OPS: dict[str, dict[str, Any]] = {
    "count_total_gates": {
        "required_args": (),
        "category": "netlist_stats",
        "description": "Count all gates by type and total count.",
    },
    "path_exists": {
        "required_args": ("src", "dst"),
        "optional_args": ("avoid",),
        "category": "path_depth_query",
        "description": "Check whether a combinational path exists, optionally avoiding a node.",
    },
    "enumerate_paths": {
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "description": "Enumerate combinational paths between two nodes.",
    },
    "max_logic_depth": {
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "description": "Compute maximum logic depth between two nodes.",
    },
    "longest_comb_path_depth": {
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "description": "Compute longest combinational path depth between two nodes.",
    },
    "critical_path_depth": {
        "required_args": ("src", "dst"),
        "category": "path_depth_query",
        "description": "Compute critical path depth between two nodes.",
    },
    "count_gates_driven_by": {
        "required_args": ("gate",),
        "category": "graph_query",
        "description": "Count gates driven by a gate output.",
    },
    "list_immediate_successors": {
        "required_args": ("gate",),
        "category": "graph_query",
        "description": "List immediate successor gates of a gate.",
    },
    "gates_reachable_from": {
        "required_args": ("source",),
        "category": "graph_query",
        "description": "List all gates reachable from a node.",
    },
    "gates_connected_to_output": {
        "required_args": ("gate",),
        "category": "graph_query",
        "description": "List gates connected to a gate output.",
    },
    "gates_driven_by_signal": {
        "required_args": ("wire",),
        "category": "graph_query",
        "description": "List gates driven by a signal.",
    },
    "insert_buffers_max_fanout": {
        "required_args": (),
        "optional_args": ("max",),
        "category": "transform",
        "description": "Insert buffers so no gate drives more than max loads.",
    },
    "insert_buffer_per_load": {
        "required_args": ("signal",),
        "category": "transform",
        "description": "Insert one buffer per load on a signal.",
    },
    "rename_wire": {
        "required_args": ("old", "new"),
        "category": "transform",
        "description": "Rename an internal wire and update all references.",
    },
    "verify_equivalent_to_original": {
        "required_args": (),
        "category": "verification",
        "description": "Verify current design against the originally loaded design.",
    },
    "verify_equivalent_to_pre_transform": {
        "required_args": (),
        "category": "verification",
        "description": "Verify current design against the previous transform snapshot.",
    },
    "count_added_buffers": {
        "required_args": (),
        "category": "transform_stats",
        "description": "Count BUF gates added by the last buffer insertion.",
    },
    "max_pi_to_dff_d_depth": {
        "required_args": (),
        "category": "path_depth_query",
        "description": "Compute maximum logic depth from any PI to any DFF D pin.",
    },
    "outputs_with_depth_gt": {
        "required_args": ("n",),
        "category": "path_depth_query",
        "description": "List outputs whose logic depth is greater than n.",
    },
    "get_gate_info": {
        "required_args": ("gate",),
        "category": "netlist_stats",
        "description": "Report a gate type and pin connections.",
    },
}


def _catalog_entry(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": name,
        "required_args": list(meta.get("required_args", ())),
        "optional_args": list(meta.get("optional_args", ())),
        "category": meta["category"],
        "description": meta["description"],
    }


def get_operation_catalog(*, include_unimplemented: bool = False) -> list[dict[str, Any]]:
    """Return the full operation catalog to show the LLM."""
    catalog = [_catalog_entry(name, meta) for name, meta in BASE_OP_TABLE.items()]
    catalog.extend(get_fanin_fanout_catalog())
    catalog.extend(get_logic_catalog())
    if include_unimplemented:
        catalog.extend(
            _catalog_entry(name, meta)
            for name, meta in UNIMPLEMENTED_OPS.items()
        )
    return sorted(catalog, key=lambda item: (item["category"], item["op"]))


def get_llm_system_prompt() -> str:
    """Prompt text for a JSON-only planner."""
    catalog = json.dumps(get_operation_catalog(), indent=2, sort_keys=True)
    return (
        "You are an EDA operation planner. Read the user request and return only "
        "valid JSON. Do not include markdown or explanatory text.\n\n"
        "JSON schema:\n"
        "{\n"
        '  "operations": [\n'
        '    {"op": "operation_name", "args": {"arg_name": "value"}}\n'
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Split multi-line prompts into ordered atomic operations.\n"
        "- Use only operation names from the catalog.\n"
        "- Include all required args. Omit unknown args instead of inventing values.\n"
        "- Use signal, gate, and file names exactly as written in the request.\n"
        "- Return JSON only.\n\n"
        f"Operation catalog:\n{catalog}"
    )


def normalize_plan(raw: Any) -> dict[str, Any]:
    """Accept common LLM JSON shapes and normalize to {'operations': [...]}."""
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        raw = json.loads(raw)

    if isinstance(raw, list):
        raw = {"operations": raw}
    if not isinstance(raw, dict):
        raise ValueError("LLM plan must be a JSON object or list.")

    if "operations" not in raw:
        if "op" in raw:
            raw = {"operations": [raw]}
        else:
            raise ValueError("LLM plan must contain an 'operations' array.")

    operations = raw["operations"]
    if not isinstance(operations, list):
        raise ValueError("'operations' must be an array.")
    return {"operations": operations}


def _implemented_tables() -> dict[str, dict[str, Any]]:
    table = dict(BASE_OP_TABLE)
    for meta in get_fanin_fanout_catalog():
        table[meta["op"]] = {
            "required_args": tuple(meta["required_args"]),
            "category": meta["category"],
            "description": meta["description"],
            "handler": _handle_fanin_fanout,
            "formatter": format_analysis_result,
        }
    for meta in get_logic_catalog():
        table[meta["op"]] = {
            "required_args": tuple(meta["required_args"]),
            "category": meta["category"],
            "description": meta["description"],
            "handler": _handle_logic,
            "formatter": format_logic_result,
        }
    return table


def _all_tables() -> dict[str, dict[str, Any]]:
    table = _implemented_tables()
    for name, meta in UNIMPLEMENTED_OPS.items():
        table[name] = {
            **meta,
            "handler": _unimplemented_handler,
            "formatter": _format_unimplemented,
        }
    return table


def validate_plan(
    raw_plan: Any,
    *,
    implemented_only: bool = True,
) -> dict[str, Any]:
    """Validate op names and required args before any backend function is called."""
    plan = normalize_plan(raw_plan)
    table = _implemented_tables() if implemented_only else _all_tables()
    validated: list[dict[str, Any]] = []

    for idx, op_request in enumerate(plan["operations"]):
        if not isinstance(op_request, dict):
            raise ValueError(f"Operation #{idx + 1} must be an object.")
        op = op_request.get("op")
        if not isinstance(op, str) or not op:
            raise ValueError(f"Operation #{idx + 1} is missing a string 'op'.")
        if op not in table:
            raise ValueError(f"Unknown operation: {op}")

        args = op_request.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValueError(f"Args for {op} must be an object.")

        missing = [
            name
            for name in table[op].get("required_args", ())
            if name not in args or args[name] is None
        ]
        if missing:
            raise ValueError(f"Missing args for {op}: {missing}")

        validated.append({"op": op, "args": args})

    return {"operations": validated}


def execute_plan(
    state: Any,
    raw_plan: Any,
    *,
    implemented_only: bool = True,
) -> list[dict[str, Any]]:
    """Validate and execute a structured LLM plan."""
    plan = validate_plan(raw_plan, implemented_only=implemented_only)
    table = _implemented_tables() if implemented_only else _all_tables()
    results: list[dict[str, Any]] = []

    for request in plan["operations"]:
        meta = table[request["op"]]
        payload = meta["handler"](state, request)
        results.append({
            "request": request,
            "payload": payload,
            "text": meta["formatter"](payload),
        })

    return results


def format_plan_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "[no operations]"
    return "\n".join(item["text"] for item in results)
