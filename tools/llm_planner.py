"""
LLM-facing structured-operation layer.

The LLM is expected to return JSON, not free-form Python calls.  This module
owns the operation catalog, validates the JSON, and dispatches each operation
to the existing backend functions.
"""

from __future__ import annotations

import copy
import json
import importlib
import inspect
import os
import pkgutil
import re
from typing import Any, Callable

from netlist_twoside import dump, parse, summary
import tools as tools_pkg
from tools.analysis_fanin_fanout import (
    build_fanin_fanout_index,
    dispatch_fanin_fanout_op,
    format_analysis_result,
    get_loads,
    get_public_op_catalog as get_fanin_fanout_catalog,
    immediate_fanout_gates,
    transitive_fanout_cone,
)
from tools.analysis_logic import (
    dispatch_logic_op,
    format_logic_result,
    get_public_op_catalog as get_logic_catalog,
)
from tools.analysis_netlist_stats import (
    dispatch_netlist_stats_op,
    format_netlist_stats_result,
    get_public_op_catalog as get_netlist_stats_catalog,
    max_fanin_cone_depth,
)
from tools.analysis_path import (
    dispatch_path_op,
    format_path_result,
    get_public_op_catalog as get_path_catalog,
)
from tools.analysis_structural_health import (
    dispatch_structural_health_op,
    format_structural_health_result,
    get_public_op_catalog as get_structural_health_catalog,
)
from tools.analysis_transform_stats import (
    dispatch_transform_stats_op,
    format_transform_stats_result,
    get_public_op_catalog as get_transform_stats_catalog,
)
from tools.analysis_dff import (
    dispatch_dff_op,
    format_dff_result,
    get_public_op_catalog as get_dff_catalog,
)
from tools.verify_equivalence import (
    dispatch_verify_op,
    format_verify_result,
    get_public_op_catalog as get_verify_catalog,
)


OperationHandler = Callable[[Any, "dict[str, Any]"], "dict[str, Any]"]
OperationFormatter = Callable[["dict[str, Any]"], str]

OUTPUT_ROOT = "/raid4/courses/eda2026s/eda26s19/EDA-Final-Project/output"
OUTPUT_LOG_DIR = os.path.join(OUTPUT_ROOT, "log")
OUTPUT_V_DIR = os.path.join(OUTPUT_ROOT, "out_v")
TOOL_MD_PATH = os.path.join(os.path.dirname(__file__), "tool.md")


def ensure_output_dirs() -> None:
    os.makedirs(OUTPUT_LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_V_DIR, exist_ok=True)


def resolve_log_path(case_name: str) -> str:
    ensure_output_dirs()
    return os.path.join(OUTPUT_LOG_DIR, f"{case_name}.log")


def resolve_out_v_path(path: str) -> str:
    ensure_output_dirs()
    basename = os.path.basename(path)
    abs_path = os.path.abspath(path)
    if abs_path.startswith(os.path.abspath(OUTPUT_ROOT) + os.sep):
        return abs_path
    return os.path.join(OUTPUT_V_DIR, basename)


def _handle_begin(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    args = request.get("args", {})
    case_name = args.get("case_name") or "case"
    log_path = resolve_log_path(case_name)
    # If the same testcase is already initialized with an open log, keep it open
    # so we never truncate responses already written for this testcase. Only
    # (re)open with "w" when starting a different/new testcase.
    already_open = (
        state.log_file is not None
        and not state.log_file.closed
        and state.case_name == case_name
    )
    state.case_name = case_name
    if not already_open:
        if state.log_file:
            state.log_file.close()
        state.log_file = open(log_path, "w")
    return {
        "op": "begin_testcase",
        "result": (
            f'Acknowledged. Initialized testcase "{case_name}". '
            f"All subsequent responses will be recorded to {log_path}. "
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
    state.original_netlist = copy.deepcopy(state.netlist)
    state.pre_transform_netlist = None
    state.last_transform_report = None
    state.transform_history = []
    state.loaded_path = path
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
    path = resolve_out_v_path(args["path"])
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


def _handle_netlist_stats(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_netlist_stats_op(state.netlist, request, public_only=True)


def _handle_path(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_path_op(state.netlist, request, public_only=True)


def _handle_structural_health(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_structural_health_op(state.netlist, request, public_only=True)


def _handle_transform_stats(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_transform_stats_op(state, request, public_only=True)


def _handle_dff(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return dispatch_dff_op(state.netlist, request, public_only=True)


def _handle_verify(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    return dispatch_verify_op(state, request, public_only=True)


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


def _require_netlist(state: Any) -> Any:
    if state.netlist is None:
        raise ValueError("No design loaded.")
    return state.netlist


def _handle_graph_alias(state: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Implement documented tool.md names that are thin wrappers over analysis ops."""
    netlist = _require_netlist(state)
    op = request["op"]
    args = request.get("args", {})

    if op == "query_input_fanout":
        result = immediate_fanout_gates(netlist, args["input"])
    elif op == "count_gates_driven_by":
        result = len(immediate_fanout_gates(netlist, args["gate"]))
    elif op in ("list_immediate_successors", "gates_connected_to_output"):
        result = immediate_fanout_gates(netlist, args["gate"])
    elif op == "gates_reachable_from":
        result = transitive_fanout_cone(netlist, args["node"])
    elif op == "gates_driven_by_signal":
        result = immediate_fanout_gates(netlist, args["wire"])
    elif op == "deepest_fanin_cone_output":
        best_output = ""
        best_depth = -1
        for output in sorted(netlist.outputs):
            depth = max_fanin_cone_depth(netlist, output)
            if depth > best_depth:
                best_output = output
                best_depth = depth
        result = (best_output, max(best_depth, 0))
    elif op == "max_fanout_of_signal":
        index = build_fanin_fanout_index(netlist)
        result = len(get_loads(index, args["wire"]))
    else:
        raise ValueError(f"Unknown graph alias op: {op}")

    return {"op": op, "args": args, "result": result}


def _format_graph_alias(payload: dict[str, Any]) -> str:
    op = payload["op"]
    args = payload.get("args", {})
    result = payload["result"]

    from tools.history_compact import format_list_preview

    if op == "query_input_fanout":
        return (
            f"Fanout of input {args['input']} ({len(result)}): "
            f"{format_list_preview(result)}"
        )
    if op == "count_gates_driven_by":
        return f"Gate {args['gate']} directly drives {result} gate(s)."
    if op == "list_immediate_successors":
        return (
            f"Immediate successors of {args['gate']} ({len(result)}): "
            f"{format_list_preview(result)}"
        )
    if op == "gates_reachable_from":
        return (
            f"Gates reachable from {args['node']} ({len(result)}): "
            f"{format_list_preview(result)}"
        )
    if op == "gates_connected_to_output":
        return (
            f"Gates connected to output of {args['gate']} ({len(result)}): "
            f"{format_list_preview(result)}"
        )
    if op == "gates_driven_by_signal":
        return (
            f"Gates driven by signal {args['wire']} ({len(result)}): "
            f"{format_list_preview(result)}"
        )
    if op == "deepest_fanin_cone_output":
        output, depth = result
        return f"Deepest fanin cone output: {output} (depth={depth})"
    if op == "max_fanout_of_signal":
        return f"Fanout of signal {args['wire']}: {result}"
    return f"{op}: {result}"


ALIAS_OP_TABLE: dict[str, dict[str, Any]] = {
    "query_input_fanout": {
        "required_args": ("input",),
        "category": "graph_analysis",
        "description": "Return the direct fanout gates driven by a primary input or signal.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "count_gates_driven_by": {
        "required_args": ("gate",),
        "category": "graph_analysis",
        "description": "Count gates directly driven by a gate output.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "list_immediate_successors": {
        "required_args": ("gate",),
        "category": "graph_analysis",
        "description": "List immediate successor gates of a gate.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "gates_reachable_from": {
        "required_args": ("node",),
        "category": "graph_analysis",
        "description": "List gates reachable from a node along fanout edges.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "gates_connected_to_output": {
        "required_args": ("gate",),
        "category": "graph_analysis",
        "description": "List gates connected to a gate output.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "gates_driven_by_signal": {
        "required_args": ("wire",),
        "category": "graph_analysis",
        "description": "List gates directly driven by a signal.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "deepest_fanin_cone_output": {
        "required_args": (),
        "category": "graph_analysis",
        "description": "Return the primary output whose fanin cone has the greatest logic depth.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
    "max_fanout_of_signal": {
        "required_args": ("wire",),
        "category": "graph_analysis",
        "description": "Return the direct fanout load count of a signal.",
        "handler": _handle_graph_alias,
        "formatter": _format_graph_alias,
    },
}


UNIMPLEMENTED_OPS: dict[str, dict[str, Any]] = {
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
}


def _catalog_entry(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "op": name,
        "required_args": list(meta.get("required_args", ())),
        "optional_args": list(meta.get("optional_args", ())),
        "category": meta["category"],
        "description": meta["description"],
    }


def _parse_signature_args(signature: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required: list[str] = []
    optional: list[str] = []
    for raw_arg in signature.split(","):
        arg = raw_arg.strip()
        if not arg:
            continue
        name = arg.split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_]\w*", name) is None:
            continue
        if "=" in arg:
            optional.append(name)
        else:
            required.append(name)
    return tuple(required), tuple(optional)


def _slug_category(text: str) -> str:
    text = re.sub(r"^\d+(?:\.\d+)?\s*", "", text).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug or "tool_md"


def _tool_md_catalog() -> list[dict[str, Any]]:
    if not os.path.exists(TOOL_MD_PATH):
        return []

    catalog: dict[str, dict[str, Any]] = {}
    category = "tool_md"
    table_row = re.compile(
        r"^\|\s*`([A-Za-z_]\w*)\(([^`]*)\)`\s*\|\s*([^|]+?)\s*\|"
    )
    function_ref = re.compile(r"`([A-Za-z_]\w*)\(([^`]*)\)`")

    with open(TOOL_MD_PATH, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("### "):
                category = _slug_category(line.lstrip("#").strip())

            row = table_row.match(line)
            if row:
                name, signature, description = row.groups()
                required, optional = _parse_signature_args(signature)
                catalog[name] = {
                    "op": name,
                    "required_args": list(required),
                    "optional_args": list(optional),
                    "category": category,
                    "description": description.strip(),
                }
                continue

            if line.startswith("#### "):
                match = function_ref.search(line)
                if match and match.group(1) not in catalog:
                    name, signature = match.groups()
                    required, optional = _parse_signature_args(signature)
                    catalog[name] = {
                        "op": name,
                        "required_args": list(required),
                        "optional_args": list(optional),
                        "category": category,
                        "description": f"Declared in tools/tool.md: {name}.",
                    }

    return list(catalog.values())


def _first_callable(module: Any, prefix: str, suffix: str) -> Callable[..., Any] | None:
    names = sorted(
        name
        for name in dir(module)
        if name.startswith(prefix) and name.endswith(suffix)
    )
    for name in names:
        value = getattr(module, name)
        if callable(value):
            return value
    return None


def _dispatch_uses_state(dispatcher: Callable[..., Any]) -> bool:
    params = list(inspect.signature(dispatcher).parameters.values())
    return bool(params and params[0].name == "state")


def _make_backend_handler(
    dispatcher: Callable[..., Any],
    *,
    state_aware: bool,
) -> OperationHandler:
    accepts_public_only = "public_only" in inspect.signature(dispatcher).parameters

    def handler(state: Any, request: dict[str, Any]) -> dict[str, Any]:
        kwargs = {"public_only": True} if accepts_public_only else {}
        if state_aware:
            return dispatcher(state, request, **kwargs)
        netlist = _require_netlist(state)
        return dispatcher(netlist, request, **kwargs)

    return handler


def _discover_tool_backends() -> list[dict[str, Any]]:
    backends: list[dict[str, Any]] = []
    for module_info in pkgutil.iter_modules(tools_pkg.__path__, tools_pkg.__name__ + "."):
        module_name = module_info.name.rsplit(".", 1)[-1]
        if module_name in {"llm_planner", "__init__"} or module_name.startswith("_"):
            continue
        module = importlib.import_module(module_info.name)
        catalog_fn = getattr(module, "get_public_op_catalog", None)
        dispatcher = _first_callable(module, "dispatch_", "_op")
        formatter = _first_callable(module, "format_", "_result")
        if not callable(catalog_fn) or dispatcher is None or formatter is None:
            continue
        parsers = [
            getattr(module, name)
            for name in sorted(dir(module))
            if name.startswith("try_parse_")
            and name.endswith("_request")
            and callable(getattr(module, name))
        ]
        backends.append({
            "module": module,
            "catalog": catalog_fn,
            "handler": _make_backend_handler(
                dispatcher,
                state_aware=_dispatch_uses_state(dispatcher),
            ),
            "formatter": formatter,
            "parsers": parsers,
        })
    return backends


def get_rule_based_parsers() -> list[Callable[[str], dict[str, Any] | None]]:
    parsers: list[Callable[[str], dict[str, Any] | None]] = []
    for backend in _discover_tool_backends():
        parsers.extend(backend["parsers"])
    return parsers


def try_parse_tool_request(line: str) -> dict[str, Any] | None:
    for parser in get_rule_based_parsers():
        request = parser(line)
        if request is not None:
            return request
    return None


def _implemented_catalog_entries() -> list[dict[str, Any]]:
    entries = [_catalog_entry(name, meta) for name, meta in BASE_OP_TABLE.items()]
    entries.extend(_catalog_entry(name, meta) for name, meta in ALIAS_OP_TABLE.items())
    for backend in _discover_tool_backends():
        entries.extend(backend["catalog"]())
    return entries


def _declared_tool_md_ops() -> dict[str, dict[str, Any]]:
    declared = {
        meta["op"]: {
            "required_args": tuple(meta.get("required_args", ())),
            "optional_args": tuple(meta.get("optional_args", ())),
            "category": meta.get("category", "tool_md"),
            "description": meta.get("description", f"Declared tool {meta['op']}."),
        }
        for meta in _tool_md_catalog()
    }
    for name, meta in UNIMPLEMENTED_OPS.items():
        declared.setdefault(name, meta)
    return declared


def get_operation_catalog(*, include_unimplemented: bool = True) -> list[dict[str, Any]]:
    """Return the operation catalog to show the LLM."""
    catalog_by_op = {
        meta["op"]: meta
        for meta in _implemented_catalog_entries()
    }
    if include_unimplemented:
        for name, meta in _declared_tool_md_ops().items():
            catalog_by_op.setdefault(name, _catalog_entry(name, meta))
    return sorted(catalog_by_op.values(), key=lambda item: (item["category"], item["op"]))


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
    table.update(ALIAS_OP_TABLE)
    for backend in _discover_tool_backends():
        for meta in backend["catalog"]():
            table[meta["op"]] = {
                "required_args": tuple(meta.get("required_args", ())),
                "optional_args": tuple(meta.get("optional_args", ())),
                "category": meta["category"],
                "description": meta["description"],
                "handler": backend["handler"],
                "formatter": backend["formatter"],
            }
    return table


def _all_tables() -> dict[str, dict[str, Any]]:
    table = _implemented_tables()
    for name, meta in _declared_tool_md_ops().items():
        table.setdefault(name, {
            **meta,
            "handler": _unimplemented_handler,
            "formatter": _format_unimplemented,
        })
    return table


ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "target": ("output", "out", "node", "wire", "signal", "gate", "gate_or_signal"),
    "source": ("input", "inp", "node", "wire", "signal", "gate", "gate_or_signal"),
    "gate_or_signal": ("gate", "node", "wire", "signal", "input", "source", "target"),
    "output": ("out", "target", "node", "wire", "signal"),
    "input": ("inp", "in", "source", "signal", "wire"),
    "wire": ("signal", "net", "target", "output", "node"),
    "signal": ("wire", "net", "source", "target", "node"),
    "node": ("target", "source", "gate", "wire", "signal"),
    "gate": ("name", "target", "node", "gate_or_signal"),
    "type": ("gate_type", "gtype"),
    "val": ("value", "constant"),
    "clock": ("clk", "clock_net", "signal", "net"),
    "n": ("threshold", "depth"),
    "max": ("limit",),
    "target1": ("out1", "output1", "a", "sig_a"),
    "target2": ("out2", "output2", "b", "sig_b"),
    "sig_a": ("signal_a", "a"),
    "sig_b": ("signal_b", "b"),
    "src": ("source", "from", "start"),
    "dst": ("dest", "target", "to", "end"),
}


def _normalize_args_for_validation(
    meta: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(args)
    for required in meta.get("required_args", ()):
        if required in normalized and normalized[required] is not None:
            continue
        for alias in ARG_ALIASES.get(required, ()):
            if alias in normalized and normalized[alias] is not None:
                normalized[required] = normalized[alias]
                break
    return normalized


def validate_plan(
    raw_plan: Any,
    *,
    implemented_only: bool = False,
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
        args = _normalize_args_for_validation(table[op], args)

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
    implemented_only: bool = False,
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
