"""Compact and summarize pipeline history for LLM context and on-disk storage."""

from __future__ import annotations

from typing import Any

# Limits for text sent to / stored for the LLM. Full tool results may be larger
# when emitted to stdout via request_output; these caps prevent context blow-up.
MAX_PROMPT_CHARS = 120
MAX_TEXT_CHARS = 500
MAX_ERROR_CHARS = 200
MAX_LIST_PREVIEW = 20
MAX_PATH_PREVIEW = 10

_LARGE_LIST_OPS = frozenset({
    "transitive_fanout_cone",
    "transitive_fanin_cone",
    "shared_fanin_cone_gates",
    "immediate_fanout_gates",
    "immediate_fanin_gates",
    "gates_reachable_from",
    "gates_connected_to_output",
    "gates_driven_by_signal",
    "query_input_fanout",
    "list_immediate_successors",
    "outputs_with_depth_gt",
    "articulation_points_between",
})


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... ({len(text) - max_chars} chars truncated)"


def format_list_preview(items: list[Any], max_items: int = MAX_LIST_PREVIEW) -> str:
    if not items:
        return "(none)"
    preview = ", ".join(str(item) for item in items[:max_items])
    if len(items) > max_items:
        preview += f", ... ({len(items) - max_items} more)"
    return preview


def compact_enumerate_paths_result(result: dict[str, Any]) -> dict[str, Any]:
    paths = result.get("paths", [])
    compact = {
        "src": result.get("src"),
        "dst": result.get("dst"),
        "count": result.get("count", len(paths)),
        "truncated": result.get("truncated", False),
    }
    if paths:
        compact["sample_paths"] = paths[:MAX_PATH_PREVIEW]
    return compact


def compact_list_result(items: list[Any], max_items: int = MAX_LIST_PREVIEW) -> dict[str, Any]:
    return {
        "count": len(items),
        "sample": items[:max_items],
    }


def compact_tool_payload(payload: Any) -> Any:
    """Return a compact copy of a tool payload suitable for history / LLM context."""
    if not isinstance(payload, dict):
        return payload

    op = payload.get("op")
    result = payload.get("result")

    if op == "enumerate_paths" and isinstance(result, dict):
        return {
            "op": op,
            "args": payload.get("args"),
            "result": compact_enumerate_paths_result(result),
        }

    if op in _LARGE_LIST_OPS and isinstance(result, list):
        return {
            "op": op,
            "args": payload.get("args"),
            "result": compact_list_result(result),
        }

    if isinstance(result, list) and len(result) > MAX_LIST_PREVIEW:
        return {
            "op": op,
            "args": payload.get("args"),
            "result": compact_list_result(result),
        }

    if isinstance(result, dict):
        paths = result.get("paths")
        if isinstance(paths, list) and len(paths) > MAX_PATH_PREVIEW:
            compact_result = dict(result)
            compact_result["paths"] = paths[:MAX_PATH_PREVIEW]
            compact_result["paths_preview_only"] = True
            compact_result["path_count"] = result.get("count", len(paths))
            return {"op": op, "args": payload.get("args"), "result": compact_result}

    return payload


def compact_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a disk-friendly history entry with bulky fields compacted."""
    compact = dict(entry)

    if compact.get("tool_output") is not None:
        compact["tool_output"] = compact_tool_payload(compact["tool_output"])

    if compact.get("text"):
        compact["text"] = truncate_text(str(compact["text"]), MAX_TEXT_CHARS)

    if compact.get("raw_main_llm_output"):
        compact["raw_main_llm_output"] = truncate_text(
            str(compact["raw_main_llm_output"]), MAX_TEXT_CHARS
        )

    if compact.get("request_output"):
        compact["request_output"] = truncate_text(
            str(compact["request_output"]), MAX_TEXT_CHARS
        )

    return compact


def summarize_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return one history row for LLM prompts (always compact)."""
    summary: dict[str, Any] = {
        "step": entry.get("step"),
        "status": entry.get("status"),
    }

    prompt = entry.get("prompt", "")
    if prompt:
        summary["prompt"] = truncate_text(str(prompt), MAX_PROMPT_CHARS)

    if entry.get("main_llm_output_type"):
        summary["main_llm_output_type"] = entry["main_llm_output_type"]

    operation = entry.get("operation")
    if operation:
        summary["operation"] = operation

    if entry.get("status") == "error":
        if entry.get("error"):
            summary["error"] = truncate_text(str(entry["error"]), MAX_ERROR_CHARS)
        return summary

    if entry.get("request_output"):
        summary["request_output"] = truncate_text(
            str(entry["request_output"]), MAX_TEXT_CHARS
        )

    if entry.get("text"):
        summary["text"] = truncate_text(str(entry["text"]), MAX_TEXT_CHARS)

    if entry.get("tool_output") is not None:
        summary["tool_output"] = compact_tool_payload(entry["tool_output"])

    return summary


def summarize_history_for_llm(
    history: list[dict[str, Any]],
    *,
    max_entries: int | None = None,
) -> list[dict[str, Any]]:
    """Build the history block embedded in Main LLM prompts.

    When *max_entries* is set, only the most recent rows are included so
    late-testcase prompts do not re-send the entire testcase trail.
    """
    if max_entries is not None and len(history) > max_entries:
        history = history[-max_entries:]
    return [summarize_history_entry(entry) for entry in history]
