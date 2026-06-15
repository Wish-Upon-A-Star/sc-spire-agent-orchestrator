"""Optional OpenAI Agents SDK adapter for SC Spire orchestration.

This adapter is deliberately safe-by-default: importing it and building
manifests never calls a model. Live Runner calls must be added behind a budget
gate and transcript logging gate.
"""

from __future__ import annotations

from typing import Any

from agents_sdk_pattern import probe_agents_sdk


def build_agent_manifest(personas: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    for role_id, persona in sorted(personas.items()):
        agents.append(
            {
                "role_id": role_id,
                "sdk_equivalent": "Agent",
                "name": persona.get("name") or role_id,
                "instructions_source": persona.get("responsibility") or persona.get("description") or "",
                "handoff_description": persona.get("route") or persona.get("provider") or "",
                "review_only": bool(persona.get("review_only")),
                "must_read": persona.get("must_read", []),
                "permissions": persona.get("permissions", []),
            }
        )
    return agents


def build_handoff_manifest(personas: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    for role_id, persona in sorted(personas.items()):
        route = persona.get("route") or persona.get("provider") or "manual"
        handoffs.append(
            {
                "from": "main-orchestrator",
                "to": role_id,
                "sdk_equivalent": "handoff",
                "route": route,
                "record_required": True,
                "trace_event": "handoff",
            }
        )
    return handoffs


def build_guardrail_manifest() -> list[dict[str, Any]]:
    return [
        {
            "id": "prompt_preflight",
            "sdk_equivalent": "input_guardrail",
            "owner": "prompt-preflight-agent",
            "checks": [
                "scope ambiguity",
                "missing acceptance criteria",
                "API budget risk",
                "missing evidence requirement",
                "worker/reviewer routing gaps",
            ],
        },
        {
            "id": "issue_memory_preflight",
            "sdk_equivalent": "input_guardrail",
            "owner": "issue-memory-agent",
            "checks": [
                "recent repeated failures",
                "open unresolved issues",
                "countermeasure injection",
            ],
        },
        {
            "id": "closure_review_gate",
            "sdk_equivalent": "output_guardrail",
            "owner": "validator-ovv-product-level",
            "checks": [
                "evidence exists",
                "review lanes inspected",
                "known issues resolved or explicitly limited",
                "final report contract satisfied",
            ],
        },
    ]


def build_tool_manifest() -> list[dict[str, Any]]:
    return [
        {"id": "codex_subscription_worker", "sdk_equivalent": "agent_as_tool", "api_call": False},
        {"id": "claude_collaborator", "sdk_equivalent": "external_tool_or_agent", "api_call": False},
        {"id": "openai_agents_sdk", "sdk_equivalent": "live_runner_optional", "api_call": True},
        {"id": "issue_memory_scan", "sdk_equivalent": "function_tool", "api_call": False},
        {"id": "browser_verification", "sdk_equivalent": "local_tool", "api_call": False},
        {"id": "queue_controls", "sdk_equivalent": "function_tool", "api_call": False},
    ]


def build_trace_manifest() -> dict[str, Any]:
    return {
        "sdk_equivalent": "trace",
        "local_trace_files": [
            "output/agent_orchestrator_runs/operator_message_events.jsonl",
            "output/agent_orchestrator_runs/<run_id>/transcript.jsonl",
            "output/agent_orchestrator_runs/<run_id>/transcript.md",
        ],
        "required_event_fields": ["timestamp", "actor", "type", "status", "target", "artifact"],
    }


def build_sdk_style_manifest(personas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "api_call_performed": False,
        "sdk_import": probe_agents_sdk(),
        "agents": build_agent_manifest(personas),
        "handoffs": build_handoff_manifest(personas),
        "guardrails": build_guardrail_manifest(),
        "tools": build_tool_manifest(),
        "trace": build_trace_manifest(),
        "runner_policy": {
            "default": "do_not_call",
            "allowed_after": [
                "operator approval",
                "budget guard pass",
                "small structured task classification",
                "transcript logging active",
            ],
        },
    }

