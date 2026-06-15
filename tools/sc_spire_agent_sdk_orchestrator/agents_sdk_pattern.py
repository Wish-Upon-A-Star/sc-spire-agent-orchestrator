"""Agents SDK pattern contract for the local SC Spire orchestrator.

This module intentionally does not call OpenAI models. It maps the useful
Agents SDK concepts into the local subscription-first orchestration state:
agent identity, handoffs, guardrails, tools, trace events, sessions, and
review-only lanes.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import subprocess
import sys
from functools import lru_cache
from typing import Any


SDK_PATTERN_CONTRACT: dict[str, Any] = {
    "runtime_policy": {
        "default_execution": "codex_subscription_and_claude_subscription",
        "live_openai_agents_sdk": "optional_for_small_structured_orchestration_or_trace_runs",
        "model_call_rule": "Do not use API model calls for broad work unless the operator explicitly allows it or subscription routes are unavailable.",
        "pattern_first_rule": "Use Agents SDK concepts locally first; constructing live SDK Agent/Runner objects is allowed, but Runner/model calls remain opt-in.",
    },
    "concepts": [
        {
            "id": "agent_identity",
            "sdk_concept": "Agent instructions and handoff_description",
            "local_mapping": "AGENT_PERSONAS entries define identity, route, permissions, review_only, and must_read context.",
            "required_for": ["all_targets"],
        },
        {
            "id": "handoffs",
            "sdk_concept": "Handoffs between specialized agents",
            "local_mapping": "Every route from prompt-preflight to main/reviewer/worker is recorded as a transcript event and queue control event.",
            "required_for": ["main-orchestrator", "supervisor-agent", "review_lanes"],
        },
        {
            "id": "guardrails",
            "sdk_concept": "Input/output guardrails",
            "local_mapping": "Preflight risk flags, AGENTS.md rules, issue-memory countermeasures, and review gate checks are stored as guardrail inputs.",
            "required_for": ["prompt-preflight-agent", "main-orchestrator", "validator-ovv-product-level"],
        },
        {
            "id": "tools_and_agents_as_tools",
            "sdk_concept": "Function tools, local tools, and agents-as-tools",
            "local_mapping": "Codex worker, Claude reviewer, Gemini reviewer, issue-memory scan, browser verification, and queue controls are represented as callable routes/tools in the registry.",
            "required_for": ["codex-worker", "claude-reviewer", "gemini-reviewer"],
        },
        {
            "id": "tracing",
            "sdk_concept": "Trace spans for model calls, tools, handoffs, guardrails, and custom events",
            "local_mapping": "operator_message_events.jsonl and transcript.jsonl are the local trace log; each event must include actor, status/type, target, artifact, and timestamp.",
            "required_for": ["all_runs"],
        },
        {
            "id": "sessions_results",
            "sdk_concept": "Runner sessions and result items",
            "local_mapping": "A run directory under output/agent_orchestrator_runs is the session; transcript.jsonl, chatkit-thread.json, and orchestration-plan.json are result items.",
            "required_for": ["viewer", "review_lanes"],
        },
    ],
    "minimum_run_contract": [
        "agent identity selected",
        "shared context loaded",
        "guardrails evaluated",
        "handoff target recorded",
        "trace event appended",
        "review lane selected when closure or quality claim exists",
        "result artifact written",
    ],
    "local_first_adapter": {
        "agent_manifest": "Role personas are treated like SDK Agent definitions even when no API call is made.",
        "handoff_manifest": "Queue/transcript route changes are treated like SDK handoffs.",
        "guardrail_manifest": "Prompt preflight, issue-memory, AGENTS.md, and review gates are treated like SDK guardrails.",
        "trace_manifest": "operator_message_events.jsonl and run transcript files are treated like SDK traces.",
        "result_manifest": "Run directories and plan/transcript/chatkit artifacts are treated like SDK result items.",
    },
}


@lru_cache(maxsize=1)
def probe_agents_sdk() -> dict[str, Any]:
    status: dict[str, Any] = {
        "installed": False,
        "importable": False,
        "version": None,
        "module_file": None,
        "import_error": None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "symbols": {},
    }
    try:
        status["version"] = importlib.metadata.version("openai-agents")
        status["installed"] = True
    except importlib.metadata.PackageNotFoundError:
        return status

    if os.environ.get("SC_SPIRE_PROBE_LIVE_AGENTS_SDK") != "1":
        status["import_error"] = "deferred_until_main_orchestrator_live_sdk_gate"
        status["deferred"] = True
        return status

    try:
        agents_module = importlib.import_module("agents")
    except Exception as exc:  # pragma: no cover - depends on local runtime/package compatibility.
        status["import_error"] = f"{type(exc).__name__}: {exc}"
        return status

    status["importable"] = True
    status["module_file"] = getattr(agents_module, "__file__", None)
    for name in [
        "Agent",
        "Runner",
        "handoff",
        "GuardrailFunctionOutput",
        "input_guardrail",
        "output_guardrail",
        "function_tool",
    ]:
        status["symbols"][name] = hasattr(agents_module, name)
    return status


@lru_cache(maxsize=1)
def probe_python_launcher_agents_sdk(version: str = "3.13") -> dict[str, Any]:
    script = (
        "import agents, json, sys; "
        "print(json.dumps({"
        "'python': sys.version.split()[0], "
        "'module_file': getattr(agents, '__file__', None), "
        "'version': getattr(agents, '__version__', 'unknown'), "
        "'symbols': {name: hasattr(agents, name) for name in "
        "['Agent','Runner','handoff','GuardrailFunctionOutput','input_guardrail','output_guardrail','function_tool']}"
        "}, ensure_ascii=False))"
    )
    try:
        completed = subprocess.run(
            ["py", f"-{version}", "-c", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - depends on local launcher.
        return {
            "runtime": f"py -{version}",
            "available": False,
            "importable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if completed.returncode != 0:
        return {
            "runtime": f"py -{version}",
            "available": True,
            "importable": False,
            "error": (completed.stderr or completed.stdout).strip(),
        }
    try:
        import json

        payload = json.loads(completed.stdout)
    except Exception as exc:
        return {
            "runtime": f"py -{version}",
            "available": True,
            "importable": False,
            "error": f"probe parse failed: {type(exc).__name__}: {exc}",
        }
    return {
        "runtime": f"py -{version}",
        "available": True,
        "importable": True,
        "error": None,
        **payload,
    }


def build_live_sdk_adapter_manifest() -> dict[str, Any]:
    sdk_status = probe_agents_sdk()
    return {
        "api_call_performed": False,
        "runner_call_default": False,
        "can_construct_live_objects": bool(
            sdk_status.get("importable")
            and sdk_status.get("symbols", {}).get("Agent")
            and sdk_status.get("symbols", {}).get("Runner")
        ),
        "construction_allowed_for": [
            "agent identity validation",
            "handoff shape validation",
            "guardrail experiments",
            "trace/eval dry-run packet generation",
        ],
        "runner_allowed_only_when": [
            "operator explicitly approves API use",
            "task is small and structured",
            "budget guard permits the call",
            "transcript logging is already active",
        ],
        "sdk_status": sdk_status,
    }


def build_agents_sdk_pattern_status() -> dict[str, Any]:
    sdk_status = probe_agents_sdk()
    return {
        "installed": sdk_status["installed"],
        "importable": sdk_status["importable"],
        "import_error": sdk_status["import_error"],
        "version": sdk_status["version"],
        "runtime": {
            "python": sdk_status["python"],
            "platform": sdk_status["platform"],
        },
        "contract": SDK_PATTERN_CONTRACT,
        "live_call_default": False,
        "safe_to_use_without_api_call": True,
        "live_adapter": build_live_sdk_adapter_manifest(),
        "alternative_runtimes": [],
        "orchestrator_usage_contract": {
            "owner": "main-orchestrator",
            "must_use_for": [
                "agent identity selection",
                "handoff target selection",
                "input guardrail construction",
                "output guardrail/review gate construction",
                "trace/eval-ready event shape",
                "deciding whether a small live SDK call is justified",
            ],
            "live_runner_policy": "optional_after_budget_and_logging_gate",
            "status_probe_policy": "do_not_spawn_external_python_from_http_status",
        },
        "external_probe_available_on_demand": [
            "probe_python_launcher_agents_sdk('3.13')",
        ],
        "optional_live_adapter": {
            "package": "openai-agents",
            "import": "agents",
            "use_only_for": [
                "small structured orchestration",
                "guardrail experiments",
                "trace/eval-ready records",
                "explicit operator-approved live SDK run",
            ],
        },
    }
