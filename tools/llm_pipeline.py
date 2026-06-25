"""
Higher-level LLM orchestration pipeline.

This module implements the state-file loop described in docs/llm_pipeline.md:

prompt -> Planner LLM -> plan.md
       -> Main LLM -> request_output or output_operation
       -> backend execution -> history.json -> plan.md update

The LLM still never executes Python.  Concrete operations are validated and
dispatched through tools.llm_planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import time
from typing import Any, Callable

from netlist_twoside import summary
from tools.history_compact import compact_history_entry, summarize_history_for_llm
from tools.llm_planner import (
    execute_plan,
    format_plan_results,
    normalize_plan,
    validate_plan,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PIPELINE_DIR_NAME = "llm_state"
DEBUG_LOG_NAME = "debug.log"
DOCS_EDA_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "docs", "EDA_skill.md")
DOCS_LOWER_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "docs", "eda_skill.md")
DOCS_EDA_TOOL_MD_PATH = os.path.join(PROJECT_ROOT, "docs", "EDA_tool.md")
DOCS_EDA_TOOLS_MD_PATH = os.path.join(PROJECT_ROOT, "docs", "EDA_tools.md")
TOOL_MD_PATH = os.path.join(PROJECT_ROOT, "tools", "tool.md")
ROOT_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "skill.md")
TOOLS_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "tools", "skill.md")

LLMCaller = Callable[[str, str, bool], str]

# How many compact history rows to embed in LLM prompts (full trail stays on disk).
LLM_HISTORY_MAX_ENTRIES = 8

# Disambiguation hints for Main LLM op selection (cone vs global, bulk vs per-gate).
_MAIN_OP_DISAMBIGUATION = (
    "Operation selection hints:\n"
    "- \"gate type IN THE CONE of X\" -> count_gates_by_type_in_cone(output=X), "
    "NOT count_gates_of_type.\n"
    "- \"how many gates eliminated by constant propagation\" -> "
    "count_eliminated_by_const_prop(type=...), NOT count_gates_of_type.\n"
    "- \"replace ALL xor ... nand\" / \"convert every XOR\" -> convert_xor_to_nand, "
    "NOT decompose_xor_in_cone or per-gate reconnect.\n"
    "- \"replace ALL xnor ... nor\" -> convert_xnor_to_nor.\n"
    "- \"list gates in cone\" / \"gates that contribute to output\" -> "
    "transitive_fanin_cone(output=X) and report the gate list.\n"
    "- After a tool call succeeds, prefer request_output; do not repeat the same op."
)


@dataclass
class PipelinePaths:
    root: str
    plan: str
    operation: str
    history: str
    debug: str


@dataclass
class PipelineRunResult:
    response: str
    stop_reason: str
    iterations: int
    paths: PipelinePaths
    history: list[dict[str, Any]] = field(default_factory=list)


def infer_case_name(prompt_text: str, default: str = "case") -> str:
    """Infer a testcase name from the natural-language request."""
    match = re.search(r"\b(\w*?\d+)\.log\b", prompt_text)
    if match:
        return match.group(1)
    match = re.search(r"\b((?:case|test)\w*\d+)\b", prompt_text)
    if match:
        return match.group(1)
    match = re.search(r"\b(testcase|case)\s+([A-Za-z_]*\d+)\b", prompt_text, re.I)
    if match:
        return match.group(2)
    return default


def get_pipeline_dir(state: Any, case_name: str | None = None) -> str:
    """Return the per-testcase pipeline workspace directory."""
    name = case_name or getattr(state, "case_name", None) or "case"
    testcase_dir = os.path.join(PROJECT_ROOT, "testcase", name)
    if os.path.isdir(testcase_dir):
        return os.path.join(testcase_dir, PIPELINE_DIR_NAME)
    return os.path.join(PROJECT_ROOT, "output", PIPELINE_DIR_NAME, name)


def get_pipeline_paths(state: Any, case_name: str | None = None) -> PipelinePaths:
    root = get_pipeline_dir(state, case_name=case_name)
    return PipelinePaths(
        root=root,
        plan=os.path.join(root, "plan.md"),
        operation=os.path.join(root, "operation.json"),
        history=os.path.join(root, "history.json"),
        debug=os.path.join(root, DEBUG_LOG_NAME),
    )


def read_text(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return default


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_history(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        write_text(path, "[]\n")
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"history.json must contain a JSON list: {path}")
    return data


def write_history(path: str, history: list[dict[str, Any]]) -> None:
    write_text(path, json.dumps(history, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def append_history(path: str, entry: dict[str, Any]) -> dict[str, Any]:
    history = read_history(path)
    item = dict(entry)
    item.setdefault("step", len(history) + 1)
    history.append(item)
    write_history(path, history)
    return item


def initialize_history(path: str) -> None:
    write_history(path, [])


def append_debug(path: str, message: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(message.rstrip() + "\n")


def _skill_text() -> str:
    for path in (
        DOCS_EDA_SKILL_MD_PATH,
        DOCS_LOWER_SKILL_MD_PATH,
        ROOT_SKILL_MD_PATH,
        TOOLS_SKILL_MD_PATH,
    ):
        text = read_text(path)
        if text:
            return text
    return "(No EDA_skill.md file was found in the project.)"


def _tool_text() -> str:
    for path in (DOCS_EDA_TOOL_MD_PATH, DOCS_EDA_TOOLS_MD_PATH, TOOL_MD_PATH):
        text = read_text(path)
        if text:
            return text
    return "(No EDA_tool.md file was found in the project.)"


def _tool_catalog_text() -> str:
    """Compact LLM command reference (prefer EDA_tools.md over the 54KB tool.md)."""
    text = read_text(DOCS_EDA_TOOLS_MD_PATH)
    if text:
        return text
    text = read_text(DOCS_EDA_TOOL_MD_PATH)
    if text:
        return text
    return _tool_text()


def _tool_brief_for_planner() -> str:
    """Category index for Planner LLM -- no per-op args, much smaller than full catalog."""
    text = read_text(DOCS_EDA_TOOLS_MD_PATH) or read_text(DOCS_EDA_TOOL_MD_PATH)
    if not text:
        return (
            "Operation categories: design_io, netlist_stats, fanin_fanout, path, "
            "logic, dff, structural_health, verification, transform_stats, "
            "fanout_buffer, depth_opt, cleanup, rewire, remap."
        )
    sections = [line.strip() for line in text.splitlines() if line.startswith("## ")]
    return (
        "Available operation categories (Main LLM picks the exact op later):\n"
        + "\n".join(sections)
    )


def _history_for_llm(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return summarize_history_for_llm(history, max_entries=LLM_HISTORY_MAX_ENTRIES)


def _design_context(state: Any) -> dict[str, Any]:
    if getattr(state, "netlist", None) is None:
        return {}
    return summary(state.netlist)


def _json_block(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)


def request_llm_plan(
    prompt_text: str,
    state: Any,
    llm_call: LLMCaller,
) -> str:
    """Ask Planner LLM to create plan.md as Markdown only."""
    system_prompt = (
        "You are the Planner LLM for an EDA task pipeline. "
        "Create a Markdown-only plan.md for the current prompt. "
        "Do not emit JSON. Do not request or execute tools."
    )
    user_content = (
        "# EDA_skill.md\n"
        f"{_skill_text()}\n\n"
        "# Operation categories (brief index only)\n"
        f"{_tool_brief_for_planner()}\n\n"
        "# Prompt\n"
        f"{prompt_text}\n\n"
        "# Runtime Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "Write a concise plan.md that records the task intent, needed information, "
        "candidate tool operations, dependencies, and expected final output."
    )
    return llm_call(system_prompt, user_content, False).strip()


def request_llm_main_decision(
    state: Any,
    prompt_text: str,
    plan_text: str,
    history: list[dict[str, Any]],
    llm_call: LLMCaller,
) -> str:
    """Ask Main LLM for one typed JSON decision."""
    system_prompt = (
        "You are the Main LLM for an EDA tool pipeline. Return JSON only. "
        "For each iteration, emit exactly one of these schemas:\n"
        '{"type":"request_output","output":"final answer text"}\n'
        '{"type":"output_operation","operation":{"op":"operation_name","args":{}}}\n'
        "Use request_output only when the current prompt is fully answered. "
        "Use output_operation when you need a real backend tool result.\n"
        "Critical rules:\n"
        "- Answer ONLY the current request. Do not perform work it did not ask for.\n"
        "- The design state PERSISTS across requests. history.json lists what is "
        "already done. NEVER re-run begin_testcase, load_design, or write_design "
        "if history shows it already succeeded and the current request does not "
        "ask for it again.\n"
        "- The current request maps to begin_testcase ONLY if it announces a new "
        "testcase; to load_design ONLY if it names a file to read; to write_design "
        "ONLY if it asks to write/output a file.\n"
        "- NEVER invent a file path, signal, or gate name. Use exact names from the "
        "current request. If a required argument is not present in the request, do "
        "not guess -- choose a different operation or emit request_output explaining "
        "what is missing.\n"
        f"{_MAIN_OP_DISAMBIGUATION}"
    )
    user_content = (
        "# EDA_skill.md\n"
        f"{_skill_text()}\n\n"
        "# EDA_tool.md\n"
        f"{_tool_catalog_text()}\n\n"
        "# Prompt\n"
        f"{prompt_text}\n\n"
        "# plan.md\n"
        f"{plan_text}\n\n"
        "# history.json (recent only; full trail is on disk; do not repeat)\n"
        f"{_json_block(_history_for_llm(history))}\n\n"
        "# Runtime Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "Return one JSON object only. Prefer one output_operation at a time. "
        "Use exact signal, gate, and file names from the prompt/history."
    )
    return llm_call(system_prompt, user_content, True).strip()


def request_llm_update_plan(
    state: Any,
    prompt_text: str,
    plan_text: str,
    latest_entries: list[dict[str, Any]],
    history: list[dict[str, Any]],
    llm_call: LLMCaller,
) -> str:
    """Ask Main LLM to update plan.md as Markdown only."""
    system_prompt = (
        "You are the Main LLM updating plan.md after a backend tool result. "
        "Return Markdown only. Do not emit JSON."
    )
    user_content = (
        "# Prompt\n"
        f"{prompt_text}\n\n"
        "# Previous plan.md\n"
        f"{plan_text}\n\n"
        "# Latest operation result\n"
        f"{_json_block(summarize_history_for_llm(latest_entries))}\n\n"
        "# Recent history.json\n"
        f"{_json_block(_history_for_llm(history))}\n\n"
        "# Runtime Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "Update plan.md with completed steps, pending steps, learned facts, "
        "and whether the current prompt is ready for request_output."
    )
    return llm_call(system_prompt, user_content, False).strip()


def _strip_json_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw


def parse_main_llm_decision(raw_decision: str) -> dict[str, Any]:
    """Parse and validate Main LLM typed decision JSON."""
    try:
        data = json.loads(_strip_json_fence(raw_decision))
    except json.JSONDecodeError as e:
        raise ValueError(f"Main LLM output is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Main LLM decision must be a JSON object.")

    decision_type = data.get("type")
    if decision_type == "request_output":
        output = data.get("output", "")
        return {"type": "request_output", "output": str(output)}

    if decision_type == "output_operation":
        operation = data.get("operation")
        if not isinstance(operation, dict):
            raise ValueError("output_operation decision must contain an operation object.")
        return {"type": "output_operation", "operation": operation}

    # Backward-compatible normalization for older JSON-only operation planners.
    if "op" in data or "operations" in data:
        plan = normalize_plan(data)
        operations = plan["operations"]
        if len(operations) != 1:
            raise ValueError("Main LLM must emit exactly one output_operation.")
        return {"type": "output_operation", "operation": operations[0]}

    raise ValueError("Main LLM decision type must be request_output or output_operation.")


def append_request_output_history(
    history_path: str,
    prompt_text: str,
    output: str,
) -> dict[str, Any]:
    return append_history(
        history_path,
        {
            "prompt": prompt_text,
            "main_llm_output_type": "request_output",
            "status": "success",
            "request_output": output,
        },
    )


def execute_output_operation(
    state: Any,
    operation: dict[str, Any],
    history_path: str,
    prompt_text: str,
) -> list[dict[str, Any]]:
    """Validate, execute, and append history for one output_operation."""
    entries: list[dict[str, Any]] = []
    try:
        plan = validate_plan({"operations": [operation]}, implemented_only=True)
    except Exception as e:
        entry = append_history(
            history_path,
            {
                "prompt": prompt_text,
                "main_llm_output_type": "output_operation",
                "operation": operation,
                "status": "error",
                "error": str(e),
            },
        )
        return [entry]

    for operation in plan["operations"]:
        try:
            results = execute_plan(
                state,
                {"operations": [operation]},
                implemented_only=True,
            )
            for result in results:
                entry = append_history(
                    history_path,
                    compact_history_entry({
                        "prompt": prompt_text,
                        "main_llm_output_type": "output_operation",
                        "operation": result["request"],
                        "status": "success",
                        "tool_output": result["payload"],
                        "text": result["text"],
                    }),
                )
                entries.append(entry)
        except Exception as e:
            entry = append_history(
                history_path,
                {
                    "prompt": prompt_text,
                    "main_llm_output_type": "output_operation",
                    "operation": operation,
                    "status": "error",
                    "error": str(e),
                },
            )
            entries.append(entry)
    return entries


def execute_operation_json(
    state: Any,
    raw_operation: Any,
    history_path: str,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for older tests and callers.

    New pipeline code should use execute_output_operation(), because history
    entries now record the prompt and Main LLM output type.
    """
    try:
        plan = validate_plan(raw_operation, implemented_only=True)
    except Exception as e:
        entry = append_history(
            history_path,
            {
                "main_llm_output_type": "output_operation",
                "operation": raw_operation,
                "status": "error",
                "error": str(e),
            },
        )
        return [entry]

    entries: list[dict[str, Any]] = []
    for operation in plan["operations"]:
        entries.extend(execute_output_operation(state, operation, history_path, ""))
    return entries


def _latest_response_text(history: list[dict[str, Any]]) -> str:
    for entry in reversed(history):
        if entry.get("status") == "success" and entry.get("request_output"):
            return str(entry["request_output"])
        if entry.get("status") == "success" and entry.get("text"):
            return str(entry["text"])
        if entry.get("status") == "error" and entry.get("error"):
            return f"Error: {entry['error']}"
    return "[pipeline produced no executable output]"


def run_llm_pipeline(
    prompt_text: str,
    state: Any,
    llm_call: LLMCaller,
    *,
    max_iterations: int = 10,
    max_repeated_errors: int = 3,
) -> PipelineRunResult:
    """Run the full state-file LLM pipeline for one natural-language request."""
    case_name = getattr(state, "case_name", None) or infer_case_name(prompt_text)
    paths = get_pipeline_paths(state, case_name=case_name)
    os.makedirs(paths.root, exist_ok=True)

    # Records persist across every request of a testcase and are reset only when
    # a new testcase begins (case_name changes) -- this keeps a full execution
    # trail in history.json / debug.log as docs/llm_pipeline.md intends, while
    # main() still answers one stdin line at a time per the PDF contract.
    prev_case = getattr(state, "_pipeline_case", None)
    new_testcase = prev_case != case_name
    state._pipeline_case = case_name
    if new_testcase or not os.path.exists(paths.history):
        write_text(paths.debug, "")
        initialize_history(paths.history)
        append_debug(paths.debug, f"pipeline_dir={paths.root}")
        append_debug(paths.debug, f"initialized history.json={paths.history}")
    append_debug(paths.debug, f"\n=== request: {prompt_text!r} (case={case_name}) ===")
    request_start = time.perf_counter()

    # Everything recorded by earlier requests in this testcase stays on disk.
    # The Main LLM sees a compact summary of history.json; base_len lets us
    # summarize only this prompt round if the loop stops without request_output.
    base_len = len(read_history(paths.history))

    plan = request_llm_plan(prompt_text, state, llm_call)
    write_text(paths.plan, plan + ("\n" if not plan.endswith("\n") else ""))
    append_debug(paths.debug, f"wrote plan.md={paths.plan}")

    response: str | None = None
    stop_reason = "max_iterations"
    repeated_error_iterations = 0
    iteration_count = 0

    for iteration in range(1, max(0, max_iterations) + 1):
        iteration_count = iteration
        history = read_history(paths.history)
        raw_decision = request_llm_main_decision(
            state,
            prompt_text,
            plan,
            history,
            llm_call,
        )
        write_text(paths.operation, raw_decision + ("\n" if not raw_decision.endswith("\n") else ""))
        append_debug(paths.debug, f"iteration={iteration} wrote main decision={paths.operation}")

        try:
            decision = parse_main_llm_decision(raw_decision)
        except Exception as e:
            append_history(
                paths.history,
                {
                    "prompt": prompt_text,
                    "main_llm_output_type": "parse_error",
                    "status": "error",
                    "raw_main_llm_output": raw_decision,
                    "error": str(e),
                },
            )
            append_debug(paths.debug, f"iteration={iteration} parse_error={e}")
            stop_reason = "parse_error"
            break

        if decision["type"] == "request_output":
            response = decision["output"]
            append_request_output_history(paths.history, prompt_text, response)
            append_debug(paths.debug, "stop_reason=request_output")
            stop_reason = "request_output"
            break

        entries = execute_output_operation(
            state,
            decision["operation"],
            paths.history,
            prompt_text,
        )
        for entry in entries:
            op = entry.get("operation", {})
            append_debug(paths.debug, f"iteration={iteration} executed={op} status={entry.get('status')}")

        if entries and all(entry.get("status") == "error" for entry in entries):
            repeated_error_iterations += 1
        else:
            repeated_error_iterations = 0

        history = read_history(paths.history)
        plan = request_llm_update_plan(
            state,
            prompt_text,
            plan,
            entries,
            history,
            llm_call,
        )
        write_text(paths.plan, plan + ("\n" if not plan.endswith("\n") else ""))
        append_debug(paths.debug, f"iteration={iteration} updated plan.md={paths.plan}")

        if repeated_error_iterations >= max_repeated_errors:
            append_debug(paths.debug, "stop_reason=repeated_errors")
            stop_reason = "repeated_errors"
            break
    else:
        append_debug(paths.debug, "stop_reason=max_iterations")

    history = read_history(paths.history)
    request_history = history[base_len:]
    if not response:
        response = format_plan_results([])
    if response == "[no operations]":
        response = _latest_response_text(request_history)
    request_elapsed = time.perf_counter() - request_start
    append_debug(paths.debug, f"request_elapsed={request_elapsed:.2f}s")
    return PipelineRunResult(
        response=response,
        stop_reason=stop_reason,
        iterations=iteration_count,
        paths=paths,
        history=history,
    )
