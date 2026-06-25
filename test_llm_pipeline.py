#!/usr/bin/env python3
"""Smoke tests for the file-backed LLM pipeline."""

from types import SimpleNamespace
import json
import os
import tempfile

from tools.llm_planner import normalize_plan, validate_plan
import tools.llm_pipeline as llm_pipeline
from tools.history_compact import (
    compact_history_entry,
    compact_tool_payload,
    summarize_history_for_llm,
)


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

    decision = llm_pipeline.parse_main_llm_decision(
        '{"type":"output_operation","operation":{"op":"count_total_gates","args":{}}}'
    )
    check(decision["type"] == "output_operation", "Main LLM operation decision parses")

    decision = llm_pipeline.parse_main_llm_decision(
        '{"type":"request_output","output":"done"}'
    )
    check(decision == {"type": "request_output", "output": "done"},
          "Main LLM request_output decision parses")


def test_run_pipeline_stops_at_max_iterations(tmp):
    old_root = llm_pipeline.PROJECT_ROOT
    old_docs_skill = llm_pipeline.DOCS_EDA_SKILL_MD_PATH
    old_docs_lower_skill = llm_pipeline.DOCS_LOWER_SKILL_MD_PATH
    old_docs_tool = llm_pipeline.DOCS_EDA_TOOL_MD_PATH
    old_docs_tools = llm_pipeline.DOCS_EDA_TOOLS_MD_PATH
    old_tool = llm_pipeline.TOOL_MD_PATH
    old_root_skill = llm_pipeline.ROOT_SKILL_MD_PATH
    old_tools_skill = llm_pipeline.TOOLS_SKILL_MD_PATH
    try:
        llm_pipeline.PROJECT_ROOT = tmp
        llm_pipeline.DOCS_EDA_SKILL_MD_PATH = os.path.join(tmp, "docs", "EDA_skill.md")
        llm_pipeline.DOCS_LOWER_SKILL_MD_PATH = os.path.join(tmp, "docs", "eda_skill.md")
        llm_pipeline.DOCS_EDA_TOOL_MD_PATH = os.path.join(tmp, "docs", "EDA_tool.md")
        llm_pipeline.DOCS_EDA_TOOLS_MD_PATH = os.path.join(tmp, "docs", "EDA_tools.md")
        llm_pipeline.TOOL_MD_PATH = os.path.join(tmp, "tools", "tool.md")
        llm_pipeline.ROOT_SKILL_MD_PATH = os.path.join(tmp, "skill.md")
        llm_pipeline.TOOLS_SKILL_MD_PATH = os.path.join(tmp, "tools", "skill.md")

        calls = {"json": 0, "markdown": 0}

        def fake_llm(_system, _user, json_response=False):
            if json_response:
                calls["json"] += 1
                return json.dumps({
                    "type": "output_operation",
                    "operation": {"op": "definitely_not_real", "args": {}},
                })
            calls["markdown"] += 1
            return f"Pipeline progress update {calls['markdown']}"

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
        check(result.history[0]["main_llm_output_type"] == "output_operation",
              "history records Main LLM operation type")
        check(os.path.exists(result.paths.plan), "plan.md is written")
        check(os.path.exists(result.paths.operation), "operation.json is written")
        check(os.path.exists(result.paths.history), "history.json is written")
        check(os.path.exists(result.paths.debug), "debug.log is written")
    finally:
        llm_pipeline.PROJECT_ROOT = old_root
        llm_pipeline.DOCS_EDA_SKILL_MD_PATH = old_docs_skill
        llm_pipeline.DOCS_LOWER_SKILL_MD_PATH = old_docs_lower_skill
        llm_pipeline.DOCS_EDA_TOOL_MD_PATH = old_docs_tool
        llm_pipeline.DOCS_EDA_TOOLS_MD_PATH = old_docs_tools
        llm_pipeline.TOOL_MD_PATH = old_tool
        llm_pipeline.ROOT_SKILL_MD_PATH = old_root_skill
        llm_pipeline.TOOLS_SKILL_MD_PATH = old_tools_skill


def test_run_pipeline_request_output(tmp):
    old_root = llm_pipeline.PROJECT_ROOT
    try:
        llm_pipeline.PROJECT_ROOT = tmp

        def fake_llm(_system, _user, json_response=False):
            if json_response:
                return json.dumps({
                    "type": "request_output",
                    "output": "final answer",
                })
            return "Plan for immediate answer"

        state = SimpleNamespace(
            case_name="unitcase",
            netlist=None,
            log_file=None,
        )
        result = llm_pipeline.run_llm_pipeline(
            "Please answer directly.",
            state,
            fake_llm,
            max_iterations=3,
        )

        check(result.stop_reason == "request_output", "pipeline stops at request_output")
        check(result.response == "final answer", "pipeline returns request output")
        check(result.history[-1]["request_output"] == "final answer",
              "history records final request output")
    finally:
        llm_pipeline.PROJECT_ROOT = old_root


def test_history_summarization(tmp):
    huge_paths = [
        {"nets": [f"n{i}", f"n{i + 1}"], "gates": [f"g{i}"]}
        for i in range(2000)
    ]
    bloated = {
        "step": 11,
        "prompt": "List every path originating at primary input n0[0] and terminating at primary output n63[1].",
        "main_llm_output_type": "output_operation",
        "operation": {"op": "enumerate_paths", "args": {"src": "n0[0]", "dst": "n63[1]"}},
        "status": "success",
        "text": "x" * 1_000_000,
        "tool_output": {
            "op": "enumerate_paths",
            "result": {
                "src": "n0[0]",
                "dst": "n63[1]",
                "count": 2000,
                "truncated": True,
                "paths": huge_paths,
            },
        },
    }

    compact = compact_history_entry(bloated)
    check(len(compact["text"]) <= 600, "compact history truncates text")
    check("sample_paths" in compact["tool_output"]["result"], "compact history keeps path sample")
    check(len(compact["tool_output"]["result"]["sample_paths"]) == 10, "compact history limits path sample")

    summary = summarize_history_for_llm([bloated])[0]
    summary_json = json.dumps(summary)
    check(len(summary_json) < 20_000, "summarized history stays small for LLM context")
    check(summary["operation"]["op"] == "enumerate_paths", "summary keeps operation metadata")


def test_history_summarization_fanout_cone(tmp):
    gates = [f"g{i}" for i in range(1000)]
    entry = {
        "step": 5,
        "status": "success",
        "operation": {"op": "transitive_fanout_cone", "args": {"source": "n13"}},
        "tool_output": {"op": "transitive_fanout_cone", "result": gates},
        "text": f"transitive_fanout_cone (1000): {', '.join(gates[:20])}, ...",
    }
    summary = summarize_history_for_llm([entry])[0]
    check(summary["tool_output"]["result"]["count"] == 1000, "fanout summary keeps count")
    check(len(summary["tool_output"]["result"]["sample"]) == 20, "fanout summary samples gates")
    check(len(json.dumps(summary)) < 5_000, "fanout summary stays small")


def test_history_truncation_for_llm(tmp):
    history = [
        {"step": i, "status": "success", "prompt": f"request {i}", "text": f"answer {i}"}
        for i in range(1, 21)
    ]
    trimmed = summarize_history_for_llm(history, max_entries=8)
    check(len(trimmed) == 8, "history truncation keeps last N entries")
    check(trimmed[0]["step"] == 13, "history truncation drops oldest rows")
    check(trimmed[-1]["step"] == 20, "history truncation keeps newest row")


def test_planner_uses_brief_tool_index(tmp):
    captured: list[str] = []

    def fake_llm(_system, user, json_response=False):
        captured.append(user)
        return json.dumps({"type": "request_output", "output": "ok"})

    state = SimpleNamespace(case_name="unitcase", netlist=None, log_file=None)
    llm_pipeline.run_llm_pipeline(
        "Count total gates.",
        state,
        fake_llm,
        max_iterations=1,
    )
    check(captured, "planner/main LLM was called")
    plan_user = captured[0]
    check("Operation categories (brief index only)" in plan_user, "plan prompt uses brief index")
    check("- `count_total_gates()`" not in plan_user,
          "plan prompt omits full per-op catalog entries")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_history_helpers(tmp)
        test_operation_validation(tmp)
        test_history_summarization(tmp)
        test_history_summarization_fanout_cone(tmp)
        test_history_truncation_for_llm(tmp)
        test_run_pipeline_stops_at_max_iterations(tmp)
        test_run_pipeline_request_output(tmp)
        test_planner_uses_brief_tool_index(tmp)
    print("\nall llm-pipeline smoke tests passed")


if __name__ == "__main__":
    main()
