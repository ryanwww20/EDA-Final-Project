"""
Higher-level LLM orchestration pipeline.

This module implements the state-file loop described in docs/llm_pipeline.md:

prompt -> plan.md -> operation.json -> backend execution -> history.json
       -> current-plan.md -> next operation

The LLM still never executes Python.  Concrete operations are validated and
dispatched through tools.llm_planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Callable

from netlist_twoside import summary
from tools.llm_planner import (
    execute_plan,
    format_plan_results,
    get_operation_catalog,
    normalize_plan,
    validate_plan,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
PIPELINE_DIR_NAME = "llm_state"
DEBUG_LOG_NAME = "debug.log"
TOOL_MD_PATH = os.path.join(PROJECT_ROOT, "tools", "tool.md")
ROOT_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "skill.md")
TOOLS_SKILL_MD_PATH = os.path.join(PROJECT_ROOT, "tools", "skill.md")

LLMCaller = Callable[[str, str, bool], str]


@dataclass
class PipelinePaths:
    root: str
    plan: str
    current_plan: str
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
        current_plan=os.path.join(root, "current-plan.md"),
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
    for path in (ROOT_SKILL_MD_PATH, TOOLS_SKILL_MD_PATH):
        text = read_text(path)
        if text:
            return text
    return "(No skill.md file was found in the project.)"


def _tool_text() -> str:
    return read_text(TOOL_MD_PATH, default="(tools/tool.md was not found.)")


def _catalog_json() -> str:
    catalog = get_operation_catalog(include_unimplemented=False)
    return json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=True)


def _design_context(state: Any) -> dict[str, Any]:
    if getattr(state, "netlist", None) is None:
        return {}
    return summary(state.netlist)


def _json_block(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)


def request_llm_high_level_plan(
    prompt_text: str,
    state: Any,
    llm_call: LLMCaller,
) -> str:
    """Ask the LLM to create plan.md as Markdown only."""
    system_prompt = (
        "You are an EDA task planner. Create a high-level Markdown plan. "
        "Do not emit JSON and do not request tool execution in this response."
    )
    user_content = (
        "# User Prompt\n"
        f"{prompt_text}\n\n"
        "# Case Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "# skill.md\n"
        f"{_skill_text()}\n\n"
        "# tool.md\n"
        f"{_tool_text()}\n\n"
        "# Implemented Backend Operation Catalog\n"
        f"{_catalog_json()}\n\n"
        "Write a concise Markdown plan covering the task intent, information needed, "
        "likely backend operations, dependencies, and expected final response. "
        "End with `Status: in_progress`."
    )
    return llm_call(system_prompt, user_content, False).strip()


def request_llm_next_operation(
    state: Any,
    current_plan: str,
    history: list[dict[str, Any]],
    llm_call: LLMCaller,
    *,
    request_text: str = "",
) -> str:
    """Ask the LLM to produce operation.json as JSON only."""
    system_prompt = (
        "You are an EDA operation selector. Return JSON only. "
        "Use only operations from the implemented backend catalog, or emit "
        '`{"op":"final_answer","args":{"answer":"..."}}` when THE CURRENT REQUEST '
        "is fully answered.\n"
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
        "not guess -- choose a different operation or emit final_answer."
    )
    user_content = (
        "# Current Request (answer ONLY this)\n"
        f"{request_text}\n\n"
        "# Current Plan\n"
        f"{current_plan}\n\n"
        "# history.json (already executed; do not repeat)\n"
        f"{_json_block(history)}\n\n"
        "# Case Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "# skill.md\n"
        f"{_skill_text()}\n\n"
        "# tool.md\n"
        f"{_tool_text()}\n\n"
        "# Implemented Backend Operation Catalog\n"
        f"{_catalog_json()}\n\n"
        "Return one concrete operation unless a small ordered batch is necessary. "
        "The normal schema is:\n"
        '{"operations":[{"op":"operation_name","args":{}}]}\n'
        "Use exact signal, gate, and file names from the current request/history."
    )
    return llm_call(system_prompt, user_content, True).strip()


def request_llm_update_current_plan(
    state: Any,
    current_plan: str,
    history: list[dict[str, Any]],
    llm_call: LLMCaller,
    *,
    original_plan: str,
    original_prompt: str,
) -> str:
    """Ask the LLM to update current-plan.md as Markdown only."""
    system_prompt = (
        "You update an EDA pipeline progress plan. Return Markdown only. "
        "Include exactly one status line: `Status: in_progress` or `Status: complete`."
    )
    user_content = (
        "# Original Prompt\n"
        f"{original_prompt}\n\n"
        "# Original plan.md\n"
        f"{original_plan}\n\n"
        "# Previous current-plan.md\n"
        f"{current_plan}\n\n"
        "# Latest history.json\n"
        f"{_json_block(history)}\n\n"
        "# Case Context\n"
        f"{_json_block({'case_name': getattr(state, 'case_name', None), 'design_summary': _design_context(state)})}\n\n"
        "Update the plan with completed steps, pending steps, learned facts, "
        "the likely next operation, and whether the final answer is ready."
    )
    return llm_call(system_prompt, user_content, False).strip()


def current_plan_is_complete(current_plan: str) -> bool:
    return re.search(r"^\s*Status\s*:\s*complete\s*$", current_plan, re.I | re.M) is not None


def _operation_for_error(raw_operation: str) -> Any:
    try:
        plan = normalize_plan(raw_operation)
    except Exception:
        return raw_operation
    operations = plan.get("operations", [])
    if len(operations) == 1:
        return operations[0]
    return {"operations": operations}


def _final_answer_from_operation(raw_operation: str) -> str | None:
    try:
        plan = normalize_plan(raw_operation)
    except Exception:
        return None
    operations = plan.get("operations", [])
    if len(operations) != 1:
        return None
    request = operations[0]
    if request.get("op") != "final_answer":
        return None
    args = request.get("args") or {}
    answer = args.get("answer")
    return str(answer) if answer is not None else ""


def execute_operation_json(
    state: Any,
    raw_operation: str,
    history_path: str,
) -> list[dict[str, Any]]:
    """Validate, execute, and append history entries for operation.json."""
    entries: list[dict[str, Any]] = []
    try:
        plan = validate_plan(raw_operation, implemented_only=True)
    except Exception as e:
        entry = append_history(
            history_path,
            {
                "operation": _operation_for_error(raw_operation),
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
                    {
                        "operation": result["request"],
                        "status": "success",
                        "payload": result["payload"],
                        "text": result["text"],
                    },
                )
                entries.append(entry)
        except Exception as e:
            entry = append_history(
                history_path,
                {
                    "operation": operation,
                    "status": "error",
                    "error": str(e),
                },
            )
            entries.append(entry)
    return entries


def _latest_response_text(history: list[dict[str, Any]]) -> str:
    for entry in reversed(history):
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

    # Everything recorded by earlier requests in this testcase stays on disk as
    # the record, but the LLM only sees this request's slice so prior requests
    # do not confuse planning or trip completion detection early.
    base_len = len(read_history(paths.history))

    plan = request_llm_high_level_plan(prompt_text, state, llm_call)
    write_text(paths.plan, plan + ("\n" if not plan.endswith("\n") else ""))
    write_text(paths.current_plan, plan + ("\n" if not plan.endswith("\n") else ""))
    append_debug(paths.debug, f"wrote plan.md={paths.plan}")
    append_debug(paths.debug, f"wrote current-plan.md={paths.current_plan}")

    current_plan = plan
    final_answer: str | None = None
    stop_reason = "max_iterations"
    repeated_error_iterations = 0
    iteration_count = 0

    for iteration in range(1, max(0, max_iterations) + 1):
        iteration_count = iteration
        history = read_history(paths.history)
        raw_operation = request_llm_next_operation(
            state, current_plan, history, llm_call, request_text=prompt_text
        )
        write_text(paths.operation, raw_operation + ("\n" if not raw_operation.endswith("\n") else ""))
        append_debug(paths.debug, f"iteration={iteration} wrote operation.json={paths.operation}")

        final_answer = _final_answer_from_operation(raw_operation)
        if final_answer is not None:
            append_history(
                paths.history,
                {
                    "operation": {"op": "final_answer", "args": {"answer": final_answer}},
                    "status": "success",
                    "payload": {"answer": final_answer},
                    "text": final_answer,
                },
            )
            history = read_history(paths.history)
            current_plan = request_llm_update_current_plan(
                state,
                current_plan,
                history,
                llm_call,
                original_plan=plan,
                original_prompt=prompt_text,
            )
            if not current_plan_is_complete(current_plan):
                current_plan += "\nStatus: complete\n"
            write_text(paths.current_plan, current_plan + ("\n" if not current_plan.endswith("\n") else ""))
            append_debug(paths.debug, "stop_reason=final_answer")
            stop_reason = "final_answer"
            break

        entries = execute_operation_json(state, raw_operation, paths.history)
        for entry in entries:
            op = entry.get("operation", {})
            append_debug(paths.debug, f"iteration={iteration} executed={op} status={entry.get('status')}")

        if entries and all(entry.get("status") == "error" for entry in entries):
            repeated_error_iterations += 1
        else:
            repeated_error_iterations = 0

        history = read_history(paths.history)
        current_plan = request_llm_update_current_plan(
            state,
            current_plan,
            history,
            llm_call,
            original_plan=plan,
            original_prompt=prompt_text,
        )
        write_text(paths.current_plan, current_plan + ("\n" if not current_plan.endswith("\n") else ""))
        append_debug(paths.debug, f"iteration={iteration} updated current-plan.md={paths.current_plan}")

        if current_plan_is_complete(current_plan):
            append_debug(paths.debug, "stop_reason=current_plan_complete")
            stop_reason = "current_plan_complete"
            break
        if repeated_error_iterations >= max_repeated_errors:
            append_debug(paths.debug, "stop_reason=repeated_errors")
            stop_reason = "repeated_errors"
            break
    else:
        append_debug(paths.debug, "stop_reason=max_iterations")

    history = read_history(paths.history)
    request_history = history[base_len:]
    response = final_answer if final_answer is not None else _latest_response_text(request_history)
    if not response:
        response = format_plan_results([])
    return PipelineRunResult(
        response=response,
        stop_reason=stop_reason,
        iterations=iteration_count,
        paths=paths,
        history=history,
    )
