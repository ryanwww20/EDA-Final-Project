#!/usr/bin/env python3
"""Smoke tests for the file-backed LLM pipeline."""

from types import SimpleNamespace
import json
import os
import tempfile

from tools.llm_planner import normalize_plan, validate_plan
import tools.llm_pipeline as llm_pipeline


def check(cond, msg):
    print(f"{'ok  ' if cond else 'FAIL'} {msg}")
    assert cond, msg


def test_history_helpers(tmp):
    history_path = os.path.join(tmp, "history.json")

    llm_pipeline.initialize_history(history_path)
    check(llm_pipeline.read_history(history_path) == [], "history initializes as []")

    first = llm_pipeline.append_history(
        history_path,
        {
            "operation": {"op": "count_total_gates", "args": {}},
            "status": "success",
            "payload": {"op": "count_total_gates", "result": {}},
            "text": "TOTAL: 0",
        },
    )
    check(first["step"] == 1, "success history entry gets step 1")

    second = llm_pipeline.append_history(
        history_path,
        {
            "operation": {"op": "get_gate_info", "args": {"gate": "U999"}},
            "status": "error",
            "error": "Unknown gate: U999",
        },
    )
    check(second["step"] == 2, "error history entry gets step 2")
    check(len(llm_pipeline.read_history(history_path)) == 2, "history appends entries")


def test_operation_validation(tmp):
    history_path = os.path.join(tmp, "history.json")
    llm_pipeline.initialize_history(history_path)
    state = SimpleNamespace(netlist=None)

    single = normalize_plan('{"op":"count_total_gates","args":{}}')
    check(single == {"operations": [{"op": "count_total_gates", "args": {}}]},
          "single-operation JSON normalizes to operations list")

    try:
        validate_plan('{"op":"definitely_not_real","args":{}}', implemented_only=True)
    except ValueError as e:
        check("Unknown operation" in str(e), "invalid operation is rejected")
    else:
        raise AssertionError("invalid operation was not rejected")

    entries = llm_pipeline.execute_operation_json(
        state,
        '{"op":"definitely_not_real","args":{}}',
        history_path,
    )
    check(entries[0]["status"] == "error", "invalid operation is appended as error")


def test_run_pipeline_stops_at_max_iterations(tmp):
    old_root = llm_pipeline.PROJECT_ROOT
    old_tool = llm_pipeline.TOOL_MD_PATH
    old_root_skill = llm_pipeline.ROOT_SKILL_MD_PATH
    old_tools_skill = llm_pipeline.TOOLS_SKILL_MD_PATH
    try:
        llm_pipeline.PROJECT_ROOT = tmp
        llm_pipeline.TOOL_MD_PATH = os.path.join(tmp, "tools", "tool.md")
        llm_pipeline.ROOT_SKILL_MD_PATH = os.path.join(tmp, "skill.md")
        llm_pipeline.TOOLS_SKILL_MD_PATH = os.path.join(tmp, "tools", "skill.md")

        calls = {"json": 0, "markdown": 0}

        def fake_llm(_system, _user, json_response=False):
            if json_response:
                calls["json"] += 1
                return json.dumps({"op": "definitely_not_real", "args": {}})
            calls["markdown"] += 1
            return "Pipeline progress\n\nStatus: in_progress"

        state = SimpleNamespace(
            case_name="unitcase",
            netlist=None,
            log_file=None,
        )
        result = llm_pipeline.run_llm_pipeline(
            "Please do a unit test pipeline request.",
            state,
            fake_llm,
            max_iterations=2,
            max_repeated_errors=10,
        )

        check(result.stop_reason == "max_iterations", "pipeline stops at max iterations")
        check(result.iterations == 2, "pipeline reports iteration count")
        check(len(result.history) == 2, "pipeline records one failed op per iteration")
        check(os.path.exists(result.paths.plan), "plan.md is written")
        check(os.path.exists(result.paths.current_plan), "current-plan.md is written")
        check(os.path.exists(result.paths.operation), "operation.json is written")
        check(os.path.exists(result.paths.history), "history.json is written")
        check(os.path.exists(result.paths.debug), "debug.log is written")
    finally:
        llm_pipeline.PROJECT_ROOT = old_root
        llm_pipeline.TOOL_MD_PATH = old_tool
        llm_pipeline.ROOT_SKILL_MD_PATH = old_root_skill
        llm_pipeline.TOOLS_SKILL_MD_PATH = old_tools_skill


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_history_helpers(tmp)
        test_operation_validation(tmp)
        test_run_pipeline_stops_at_max_iterations(tmp)
    print("\nall llm-pipeline smoke tests passed")


if __name__ == "__main__":
    main()
