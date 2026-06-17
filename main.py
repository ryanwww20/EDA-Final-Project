#!/usr/bin/env python3
"""
ICCAD Contest Problem A - main pipeline / orchestrator.

This file owns the I/O contract with the grading environment:
  - read natural-language requests from stdin, one per line
  - print a #RESPONSE <id> ... #END <id> block to stdout for each
  - mirror every response into output/log/<case_name>.log
  - flush after every #END (the grader waits for it before sending the next line)

EDA operations and the LLM agent are stubbed out below; fill them in later.
Run:  ./cada0001_alpha -config <config_file_path>
"""

import sys
import re
import argparse
import copy
import json
import os
import urllib.error
import urllib.request

from netlist_twoside import parse, dump, summary   # our data-structure module
from tools.llm_planner import (
    execute_plan,
    format_plan_results,
    get_llm_system_prompt,
    resolve_log_path,
    resolve_out_v_path,
    try_parse_tool_request,
)
from tools.llm_pipeline import run_llm_pipeline
from tools.analysis_fanin_fanout import (
    dispatch_fanin_fanout_op,
    format_analysis_result,
    try_parse_fanin_fanout_request,
)
from tools.analysis_logic import (
    dispatch_logic_op,
    format_logic_result,
    try_parse_logic_request,
)
from tools.analysis_netlist_stats import (
    dispatch_netlist_stats_op,
    format_netlist_stats_result,
    try_parse_netlist_stats_request,
)
from tools.analysis_path import (
    dispatch_path_op,
    format_path_result,
    try_parse_path_request,
)
from tools.analysis_structural_health import (
    dispatch_structural_health_op,
    format_structural_health_result,
    try_parse_structural_health_request,
)
from tools.analysis_transform_stats import (
    dispatch_transform_stats_op,
    format_transform_stats_result,
    try_parse_transform_stats_request,
)
from tools.analysis_dff import (
    dispatch_dff_op,
    format_dff_result,
    try_parse_dff_request,
)
from tools.verify_equivalence import (
    dispatch_verify_op,
    format_verify_result,
    try_parse_verify_request,
)
from tools.transform_fanout import (
    dispatch_transform_fanout_op,
    format_transform_fanout_result,
    try_parse_transform_fanout_request,
)
from tools.transform_depth import (
    dispatch_transform_depth_op,
    format_transform_depth_result,
    try_parse_transform_depth_request,
)
from tools.transform_cleanup import (
    dispatch_transform_cleanup_op,
    format_transform_cleanup_result,
    try_parse_transform_cleanup_request,
)


# ---------------------------------------------------------------------------
# Design state: everything that persists across requests within one testcase.
# ---------------------------------------------------------------------------
class State:
    def __init__(self):
        self.netlist = None        # current Netlist object (the "design state")
        self.original_netlist = None   # snapshot of the design as first loaded
        self.pre_transform_netlist = None  # snapshot before the last transform
        self.last_transform_report = None  # report emitted by the last transform
        self.transform_history = []    # ordered list of transform reports
        self.loaded_path = None    # path the current design was parsed from
        self.case_name = None      # e.g. "test01"
        self.log_file = None       # open file handle for <case_name>.log
        self.config = None         # LLM config (api key, model, ...)


# ---------------------------------------------------------------------------
# Config loading (the -config file). Stub: parse the YAML when you wire up LLM.
# ---------------------------------------------------------------------------
def _parse_config_value(value):
    value = value.strip().strip("\"'")
    if value.lower() in ("true", "yes", "on"):
        return True
    if value.lower() in ("false", "no", "off"):
        return False
    if value.lower() in ("null", "none"):
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_config(path):
    """Load a small JSON/YAML-style config without adding dependencies.

    Supported flat or nested keys:
      model, api_key, api_key_env, base_url, temperature, timeout, enabled, strict
      llm.model, llm.api_key, ...
    """
    with open(path) as f:
        text = f.read()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {}
        stack = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if ":" not in line:
                continue

            indent = len(line) - len(line.lstrip())
            key, value = line.strip().split(":", 1)
            while stack and stack[-1][0] >= indent:
                stack.pop()

            prefix = ".".join(item[1] for item in stack)
            full_key = f"{prefix}.{key}" if prefix else key

            if value.strip():
                data[full_key] = _parse_config_value(value)
            else:
                stack.append((indent, key))

    data["config_path"] = path
    return data


def _cfg(config, key, default=None):
    if not config:
        return default
    if key in config:
        return config[key]

    namespaces = ["llm"]
    provider = config.get("provider")
    if provider:
        namespaces.append(str(provider))
    namespaces.append("generation")

    for namespace in namespaces:
        nested = config.get(namespace)
        if isinstance(nested, dict) and key in nested:
            return nested[key]
        dotted = f"{namespace}.{key}"
        if dotted in config:
            return config[dotted]
    return default


def _cfg_bool(config, key, default=False):
    value = _cfg(config, key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _llm_api_key(config):
    api_key = _cfg(config, "api_key")
    if isinstance(api_key, str) and api_key.startswith("$"):
        api_key = os.getenv(api_key[1:])
    if api_key:
        return api_key

    env_name = _cfg(config, "api_key_env", "OPENAI_API_KEY")
    if env_name:
        return os.getenv(str(env_name))
    return None


def _llm_is_configured(config):
    if not config or _cfg_bool(config, "enabled", True) is False:
        return False
    return bool(_cfg(config, "model") and _llm_api_key(config))


def request_llm_text(state, system_prompt, user_content, json_response=False):
    """Ask a configured cloud LLM for text."""
    config = state.config or {}
    provider = str(_cfg(config, "provider", "openai")).lower()
    model = _cfg(config, "model")
    api_key = _llm_api_key(config)
    if not model or not api_key:
        raise ValueError("LLM config must include model and api_key/api_key_env.")

    temperature = _cfg(config, "temperature", 0)
    timeout = _cfg(config, "timeout", 30)
    max_output_tokens = _cfg(config, "max_output_tokens")

    if provider == "anthropic":
        base_url = _cfg(config, "base_url", "https://api.anthropic.com/v1/messages")
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": int(max_output_tokens or 4096),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }
        request = urllib.request.Request(
            str(base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": str(_cfg(config, "anthropic_version", "2023-06-01")),
                "Content-Type": "application/json",
            },
            method="POST",
        )
    else:
        base_url = _cfg(config, "base_url", "https://api.openai.com/v1/chat/completions")
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if json_response:
            payload["response_format"] = {"type": "json_object"}
        if max_output_tokens is not None:
            payload["max_tokens"] = int(max_output_tokens)

        request = urllib.request.Request(
            str(base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e

    data = json.loads(body)
    if provider == "anthropic":
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        raise RuntimeError("Anthropic response did not contain text content.")
    return data["choices"][0]["message"]["content"]


def request_llm_plan(line, state):
    """Ask a configured cloud LLM for a JSON plan."""
    design_context = {}
    if state.netlist is not None:
        design_context = summary(state.netlist)
    user_content = json.dumps(
        {
            "request": line,
            "case_name": state.case_name,
            "design_summary": design_context,
        },
        ensure_ascii=True,
    )
    return request_llm_text(state, get_llm_system_prompt(), user_content, json_response=True)


def _llm_pipeline_enabled(config):
    return _cfg_bool(config, "pipeline_mode", False)


def _max_pipeline_iterations(config):
    return int(_cfg(config, "max_pipeline_iterations", 10))


def _max_pipeline_repeated_errors(config):
    return int(_cfg(config, "max_pipeline_repeated_errors", 3))


# ---------------------------------------------------------------------------
# Request handlers.  Right now we do crude keyword routing so the loop runs.
# Later, replace `route_request` with the LLM agent (tool calling).
# ---------------------------------------------------------------------------
def handle_begin(line, state):
    """'This is the beginning of testcase caseXX. ... caseXX.log'"""
    # grab the case id (e.g. test04 / case23). Avoid matching the bare word
    # "testcase" by requiring a trailing digit, and prefer a name that also
    # appears as "<name>.log" if present.
    m = re.search(r"\b(\w*?\d+)\.log\b", line)         # name from the .log target
    if not m:
        m = re.search(r"\b((?:case|test)\w*\d+)\b", line)
    state.case_name = m.group(1) if m else "case"
    log_path = resolve_log_path(state.case_name)
    if state.log_file:
        state.log_file.close()
    state.log_file = open(log_path, "w")
    return (f'Acknowledged. Initialized testcase "{state.case_name}". '
            f"All subsequent responses will be recorded to {log_path}. "
            f"Design state is empty and ready for commands.")


def handle_load(line, state):
    """'Load test1.v from design/' -> parse a .v into state.netlist"""
    m = re.search(r"([^\s'\"]+\.v)", line)
    if not m:
        return "Error: could not find a .v filename in the request."
    path = m.group(1)
    # try to honour an explicit directory if one is mentioned
    dm = re.search(r"(?:from|in)\s+['\"]?([^\s'\"]+/)['\"]?", line)
    if dm and "/" not in path:
        path = dm.group(1) + path
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
    return (f"Loaded gate-level Verilog from {path} successfully.\n"
            f"- module: {s['module']}, single top module (flat netlist)\n"
            f"- gates: {s['num_gates_total']} "
            f"({s['num_combinational']} combinational, {s['num_dff']} DFF)\n"
            f"- PI: {s['num_inputs']}, PO: {s['num_outputs']}\n"
            f"- sequential: {s['is_sequential']}, clocks: {s['clock_nets']}")


def handle_write(line, state):
    """'Write out the design to result.v' -> dump state.netlist"""
    m = re.search(r"([^\s'\"]+\.v)", line)
    if not m:
        return "Error: could not find an output .v filename in the request."
    if state.netlist is None:
        return "Error: no design loaded."
    path = resolve_out_v_path(m.group(1))
    dump(state.netlist, path)
    return f'Wrote the current design to "{path}" successfully.'


# -------- analysis (fanin / fanout / cone) --------
def handle_analysis(line, state):
    if state.netlist is None:
        return "Error: no design loaded."

    request = try_parse_transform_stats_request(line)
    if request is not None:
        payload = dispatch_transform_stats_op(state, request)
        return format_transform_stats_result(payload)

    request = try_parse_tool_request(line)
    if request is not None:
        results = execute_plan(state, request)
        return format_plan_results(results)

    request = try_parse_netlist_stats_request(line)
    if request is not None:
        payload = dispatch_netlist_stats_op(state.netlist, request)
        return format_netlist_stats_result(payload)

    request = try_parse_fanin_fanout_request(line)
    if request is not None:
        payload = dispatch_fanin_fanout_op(state.netlist, request)
        return format_analysis_result(payload)

    request = try_parse_logic_request(line)
    if request is not None:
        payload = dispatch_logic_op(state.netlist, request)
        return format_logic_result(payload)

    request = try_parse_structural_health_request(line)
    if request is not None:
        payload = dispatch_structural_health_op(state.netlist, request)
        return format_structural_health_result(payload)

    request = try_parse_path_request(line)
    if request is not None:
        payload = dispatch_path_op(state.netlist, request)
        return format_path_result(payload)

    request = try_parse_dff_request(line)
    if request is not None:
        payload = dispatch_dff_op(state.netlist, request)
        return format_dff_result(payload)

    request = try_parse_verify_request(line)
    if request is not None:
        payload = dispatch_verify_op(state, request)
        return format_verify_result(payload)

    return "[analysis not implemented yet]"


def handle_transform(line, state):
    if state.netlist is None:
        return "Error: no design loaded."

    request = try_parse_transform_fanout_request(line)
    if request is not None:
        payload = dispatch_transform_fanout_op(state, request)
        return format_transform_fanout_result(payload)

    request = try_parse_transform_depth_request(line)
    if request is not None:
        payload = dispatch_transform_depth_op(state, request)
        return format_transform_depth_result(payload)

    request = try_parse_transform_cleanup_request(line)
    if request is not None:
        payload = dispatch_transform_cleanup_op(state, request)
        return format_transform_cleanup_result(payload)

    request = try_parse_tool_request(line)
    if request is not None:
        results = execute_plan(state, request)
        return format_plan_results(results)
    # TODO: remaining transform families (cleanup, remap, depth opt).
    return "[transformation not implemented yet]"


def route_request(line, state):
    """Crude keyword router. REPLACE with the LLM agent later.

    The real version: send `line` + tool schema + summary(state.netlist)
    to the LLM, let it pick a tool + args, execute the matching eda_ops
    function, feed the result back, return the LLM's natural-language answer.
    """
    stripped = line.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        results = execute_plan(state, stripped)
        return format_plan_results(results)

    if _llm_is_configured(state.config):
        try:
            if _llm_pipeline_enabled(state.config):
                result = run_llm_pipeline(
                    line,
                    state,
                    lambda system, user, json_response=False: request_llm_text(
                        state,
                        system,
                        user,
                        json_response=json_response,
                    ),
                    max_iterations=_max_pipeline_iterations(state.config),
                    max_repeated_errors=_max_pipeline_repeated_errors(state.config),
                )
                return result.response
            else:
                plan_json = request_llm_plan(line, state)
                results = execute_plan(state, plan_json)
                return format_plan_results(results)
        except Exception as e:
            if _cfg_bool(state.config, "strict", False):
                return f"LLM routing failed: {e}"

    low = line.lower()
    if "beginning of" in low or "begin" in low and "testcase" in low:
        return handle_begin(line, state)
    if re.search(r"\b(load|read)\b", low):
        return handle_load(line, state)
    if re.search(r"\bwrite\b|\boutput the design\b", low):
        return handle_write(line, state)
    if re.search(
        r"\b(depth|paths?|equivalent|equivalence|identical|constant|boolean|logic|"
        r"symmetric|depend|always|cone|fanout|verify|exists?|count|gates?|primary|"
        r"width|widths|type|reachable|driven|successors|dangling|floating|"
        r"unconnected|redundant|tied|tie|traverse|enumerat\w*|articulation|"
        r"connect\w*|reach\w*|levels?)\b",
        low,
    ):
        return handle_analysis(line, state)
    if re.search(r"\b(insert|replace|remove|optimize|balance|reduce|add)\b", low):
        return handle_transform(line, state)
    return "[unrecognized request]"


# ---------------------------------------------------------------------------
# Main loop: the I/O contract. This part is done and should not need changes.
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-config", dest="config", required=False)
    args = ap.parse_args()

    state = State()
    state.config = load_config(args.config) if args.config else None

    # PDF section 3.3 contract: read ONE request per stdin line, answer it with
    # its own #RESPONSE <id> ... #END <id> block, and flush so the grader sends
    # the next line. route_request() decides per line whether to run the LLM
    # pipeline (which keeps its own plan/history records) or the keyword
    # fallback; either way each line produces exactly one numbered response.
    rid = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid += 1

        try:
            response = route_request(line, state)
        except Exception as e:
            response = f"Error while processing request: {e}"

        # write to stdout
        sys.stdout.write(f"#RESPONSE {rid}\n{response}\n#END {rid}\n")
        sys.stdout.flush()                       # <-- critical: grader waits on this

        # mirror to log
        if state.log_file:
            state.log_file.write(f"#RESPONSE {rid}\n{response}\n#END {rid}\n")
            state.log_file.flush()

    if state.log_file:
        state.log_file.close()


if __name__ == "__main__":
    main()
