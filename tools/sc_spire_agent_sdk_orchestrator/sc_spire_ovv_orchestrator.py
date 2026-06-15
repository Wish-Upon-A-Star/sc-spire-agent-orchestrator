"""SC Spire Agent SDK OVV orchestrator MVP.

This file intentionally starts with a deterministic dry-run contract. Live
Agents SDK execution should be added only after the project-specific gates are
stable and auditable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


UNITY_PLAYER_FACING_HINTS = (
    "Unity/",
    "Assets/",
    ".uxml",
    ".uss",
    ".prefab",
    ".unity",
)

WEB_PLAYER_FACING_HINTS = (
    "static/css/",
    "templates/",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUES_DIR = REPO_ROOT / "memory" / "issues_log"
RUNS_DIR = REPO_ROOT / "output" / "agent_orchestrator_runs"
DEFAULT_CLAUDE_SHIM = Path.home() / ".codex-node-global" / "claude.ps1"
DESKTOP_OPENAI_KEY_FILE = Path.home() / "Desktop" / "openai.txt"
PROVIDER_ROUTING_PATH = Path(__file__).resolve().parent / "provider_routing.json"
ISSUE_HEADER_RE = re.compile(
    r"^###\s+.*?\[(?P<date>\d{4}-\d{2}-\d{2})\]\s+\[(?P<phase>[a-z]+)\]\s+(?P<title>.+?)\s*$"
)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def load_provider_routing_config(path: Path = PROVIDER_ROUTING_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"version": 0, "routes": {}, "role_defaults": {}, "decision_rules": []}
    config = json.loads(path.read_text(encoding="utf-8"))
    routes = config.get("routes", {})
    for route_name, route in routes.items():
        if not isinstance(route, dict):
            continue
        override_env = route.get("override_env", {})
        if isinstance(override_env, dict):
            model_env = override_env.get("model")
            if model_env and os.environ.get(str(model_env)):
                route["effective_model"] = os.environ[str(model_env)]
            else:
                route["effective_model"] = route.get("default_model")
            enabled_env = override_env.get("enabled")
            route["effective_enabled"] = env_bool(str(enabled_env), bool(route.get("enabled", True))) if enabled_env else bool(route.get("enabled", True))
            timeout_env = override_env.get("timeout_seconds")
            if timeout_env and os.environ.get(str(timeout_env)):
                try:
                    route["effective_timeout_seconds"] = int(os.environ[str(timeout_env)])
                except ValueError:
                    route["effective_timeout_seconds"] = route.get("timeout_seconds")
            elif "timeout_seconds" in route:
                route["effective_timeout_seconds"] = route.get("timeout_seconds")
        else:
            route["effective_model"] = route.get("default_model")
            route["effective_enabled"] = bool(route.get("enabled", True))
    return config


def route_for_role(role: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    routing = config or load_provider_routing_config()
    route_name = routing.get("role_defaults", {}).get(role, routing.get("default_route", "openai_agents_sdk"))
    route = routing.get("routes", {}).get(route_name, {})
    return {
        "role": role,
        "route": route_name,
        "surface": route.get("surface", ""),
        "provider": route.get("provider", ""),
        "model": route.get("effective_model", route.get("default_model", "")),
        "enabled": route.get("effective_enabled", route.get("enabled", False)),
    }


@dataclass(frozen=True)
class Goal:
    goal_id: str
    user_request: str
    blocker_id: str | None
    work_type: str
    affected_surfaces: list[str]
    planned_files: list[str]
    acceptance_criteria: list[str]
    non_goals: list[str]


@dataclass(frozen=True)
class GateRequirements:
    classification: str
    can_edit_without_rendered_evidence: bool
    required_pre_edit_commands: list[str]
    required_evidence: list[str]
    human_review_required_for: list[str]


@dataclass(frozen=True)
class IssueMemoryEntry:
    section_file: str
    phase: str
    title: str
    date: str
    body: str
    resolved: str


@dataclass(frozen=True)
class IssueMemoryPreflight:
    issues_dir: str
    entries_scanned: int
    matching_open_issues: list[IssueMemoryEntry]
    matching_resolved_countermeasures: list[IssueMemoryEntry]
    required_actions: list[str]


@dataclass(frozen=True)
class DialogueEvent:
    timestamp: str
    speaker: str
    recipient: str
    event_type: str
    message: str
    artifact: str | None = None


@dataclass(frozen=True)
class AgentPersona:
    agent_id: str
    role: str
    perspective: str
    must_challenge: str
    success_signal: str


PERSONAS = [
    AgentPersona(
        agent_id="supervisor-agent",
        role="main orchestrator",
        perspective="Owns routing, gate order, and final decision integrity.",
        must_challenge="Any worker action that starts before PRD, issue-memory preflight, and Review Gate.",
        success_signal="A bounded plan with named owners, evidence, and no silent scope expansion.",
    ),
    AgentPersona(
        agent_id="product-critic-agent",
        role="player/product critic",
        perspective="Looks for player-facing weakness, sellability overclaims, and design drift.",
        must_challenge="Claims that code success or source prep equals product-quality closure.",
        success_signal="The plan names the player evidence needed before any product claim.",
    ),
    AgentPersona(
        agent_id="codex-worker",
        role="implementation worker",
        perspective="Owns local files, commands, builds, and evidence packaging.",
        must_challenge="Ambiguous file ownership or mixed safe-process and player-facing closure scope.",
        success_signal="The worker can execute a narrow task without guessing scope.",
    ),
    AgentPersona(
        agent_id="validator-code-level",
        role="code and contract validator",
        perspective="Checks syntax, contract shape, regressions, state transitions, and fragile logic.",
        must_challenge="Missing command evidence, untested branches, or stale generated artifacts.",
        success_signal="Fresh verification commands and contract outputs support the implementation.",
    ),
    AgentPersona(
        agent_id="validator-ovv-product-level",
        role="OVV and evidence validator",
        perspective="Checks rendered-evidence boundaries, issue-memory use, and closure honesty.",
        must_challenge="Any final status that ignores open issue-memory entries or lacks independent evidence.",
        success_signal="Every closure claim is mapped to evidence and unresolved issues are explicit.",
    ),
    AgentPersona(
        agent_id="claude-reviewer",
        role="external critique collaborator",
        perspective="Reviews architecture, routing, and product judgment from a separate model perspective.",
        must_challenge="Overconfident local consensus and missing alternative interpretations.",
        success_signal="A concise critique with blockers, routing corrections, and missing evidence.",
    ),
]


def load_goal(path: Path) -> Goal:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = ["goal_id", "user_request", "work_type", "affected_surfaces", "planned_files", "acceptance_criteria"]
    missing = [field for field in required if field not in raw]
    if missing:
        raise ValueError(f"Goal file missing required fields: {', '.join(missing)}")
    return Goal(
        goal_id=str(raw["goal_id"]),
        user_request=str(raw["user_request"]),
        blocker_id=raw.get("blocker_id"),
        work_type=str(raw["work_type"]),
        affected_surfaces=list(raw["affected_surfaces"]),
        planned_files=list(raw["planned_files"]),
        acceptance_criteria=list(raw["acceptance_criteria"]),
        non_goals=list(raw.get("non_goals", [])),
    )


def normalize_words(text: str) -> set[str]:
    words = {
        word
        for word in re.findall(r"[A-Za-z0-9가-힣_-]{3,}", text.lower())
        if word
        not in {
            "the",
            "and",
            "with",
            "for",
            "this",
            "that",
            "from",
            "agent",
            "sdk",
            "sc",
            "spire",
            "work",
            "file",
            "files",
            "goal",
            "sample",
            "evidence",
            "rendered",
            "player",
            "facing",
        }
    }
    return words


def canonical_title(title: str) -> str:
    value = " ".join(title.lower().split())
    value = re.sub(r"\b\d{4,}\b", "<num>", value)
    return value


def split_issue_payload(lines: list[str]) -> tuple[str, str]:
    body_lines: list[str] = []
    resolved_lines: list[str] = []
    target = body_lines
    for line in lines:
        if line.startswith("**Resolution / Method**:"):
            target = resolved_lines
            first = line.split(":", 1)[1].strip()
            if first:
                resolved_lines.append(first)
            continue
        target.append(line)
    return "\n".join(body_lines).strip(), "\n".join(resolved_lines).strip()


def parse_issue_memory(issues_dir: Path = ISSUES_DIR) -> list[IssueMemoryEntry]:
    if not issues_dir.exists():
        return []
    entries: list[IssueMemoryEntry] = []
    for path in sorted(issues_dir.glob("[0-9][0-9]-*.md")):
        current: dict[str, str] | None = None
        payload_lines: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = ISSUE_HEADER_RE.match(line)
            if match:
                if current is not None:
                    body, resolved = split_issue_payload(payload_lines)
                    entries.append(
                        IssueMemoryEntry(
                            section_file=path.name,
                            phase=current["phase"],
                            title=current["title"],
                            date=current["date"],
                            body=body,
                            resolved=resolved,
                        )
                    )
                current = {
                    "phase": match.group("phase"),
                    "title": " ".join(match.group("title").split()),
                    "date": match.group("date"),
                }
                payload_lines = []
            elif current is not None:
                payload_lines.append(line)
        if current is not None:
            body, resolved = split_issue_payload(payload_lines)
            entries.append(
                IssueMemoryEntry(
                    section_file=path.name,
                    phase=current["phase"],
                    title=current["title"],
                    date=current["date"],
                    body=body,
                    resolved=resolved,
                )
            )
    return entries


def build_goal_term_weights(goal: Goal) -> dict[str, int]:
    weighted: dict[str, int] = {}

    def add(text: str, weight: int) -> None:
        for term in normalize_words(text):
            weighted[term] = max(weighted.get(term, 0), weight)

    add(goal.user_request, 2)
    add(" ".join(goal.acceptance_criteria), 2)
    add(" ".join(goal.affected_surfaces), 3)
    add(goal.work_type, 3)
    if goal.blocker_id:
        add(goal.blocker_id, 5)
    for file_name in goal.planned_files:
        add(file_name.replace("\\", "/"), 4)
        add(Path(file_name).name, 4)
    return weighted


def issue_match_score(entry: IssueMemoryEntry, goal_term_weights: dict[str, int]) -> int:
    if not goal_term_weights:
        return 0
    entry_terms = normalize_words(f"{entry.title} {entry.body} {entry.resolved}")
    return sum(weight for term, weight in goal_term_weights.items() if term in entry_terms)


def dedupe_ranked(entries: list[tuple[int, IssueMemoryEntry]], limit: int) -> list[IssueMemoryEntry]:
    selected: list[IssueMemoryEntry] = []
    seen: set[tuple[str, str]] = set()
    for _score, entry in sorted(entries, key=lambda item: (item[0], item[1].date), reverse=True):
        key = (entry.section_file, canonical_title(entry.title))
        if key in seen:
            continue
        seen.add(key)
        selected.append(entry)
        if len(selected) >= limit:
            break
    return selected


def collapse_issue_lifecycle(entries: list[IssueMemoryEntry]) -> list[IssueMemoryEntry]:
    latest: dict[tuple[str, str], IssueMemoryEntry] = {}
    for entry in entries:
        key = (entry.section_file, canonical_title(entry.title))
        latest[key] = entry
    return list(latest.values())


def build_issue_memory_preflight(goal: Goal, limit: int = 8) -> IssueMemoryPreflight:
    raw_entries = parse_issue_memory()
    entries = collapse_issue_lifecycle(raw_entries)
    weights = build_goal_term_weights(goal)
    scored = [(issue_match_score(entry, weights), entry) for entry in entries]
    matched = [(score, entry) for score, entry in scored if score >= 5]
    open_entries = [(score, entry) for score, entry in matched if entry.phase in {"discovered", "updated"}]
    resolved_entries = [(score, entry) for score, entry in matched if entry.phase == "resolved" and entry.resolved]
    return IssueMemoryPreflight(
        issues_dir=str(ISSUES_DIR),
        entries_scanned=len(raw_entries),
        matching_open_issues=dedupe_ranked(open_entries, limit),
        matching_resolved_countermeasures=dedupe_ranked(resolved_entries, limit),
        required_actions=[
            "Treat matching open issues as Review Gate inputs, not passive notes.",
            "Convert any repeated open issue into an acceptance criterion or explicit blocker before worker execution.",
            "Reuse matching resolved countermeasures as candidate guardrails and verification steps.",
            "If a new issue is found, log discovered before fixing and resolved after verification.",
        ],
    )


def has_hint(goal: Goal, hints: tuple[str, ...]) -> bool:
    return any(any(hint in file_name for hint in hints) for file_name in goal.planned_files)


def classify_gate_requirements(goal: Goal) -> GateRequirements:
    unity_player_facing = goal.work_type == "player_facing_unity" or has_hint(goal, UNITY_PLAYER_FACING_HINTS)
    web_player_facing = goal.work_type == "player_facing_web" or has_hint(goal, WEB_PLAYER_FACING_HINTS)
    if unity_player_facing:
        return GateRequirements(
            classification="unity_player_facing_requires_ovv_and_rendered_evidence",
            can_edit_without_rendered_evidence=False,
            required_pre_edit_commands=[
                ".venv\\Scripts\\python.exe scripts\\validate_operating_state.py",
                ".venv\\Scripts\\python.exe scripts\\build_sc_spire_ovv_decision_packet.py",
                ".venv\\Scripts\\python.exe scripts\\unity_batch_preflight.py --require-license",
            ],
            required_evidence=[
                "PRD packet",
                "Task breakdown",
                "Review Gate",
                "OVV decision packet",
                "Claude or peer plan review result",
                "Rendered screenshot or player evidence for each changed surface",
                "Structural checklist validation",
                "Blind holistic visual/product review",
            ],
            human_review_required_for=[
                "score changes",
                "workaround acceptance",
                "closure with incomplete baseline",
                "destructive git or evidence cleanup",
            ],
        )
    if web_player_facing:
        return GateRequirements(
            classification="web_player_facing_requires_browser_evidence",
            can_edit_without_rendered_evidence=False,
            required_pre_edit_commands=[],
            required_evidence=[
                "PRD packet",
                "Task breakdown",
                "Review Gate",
                "Browser screenshot or Playwright evidence for each changed surface",
                "Responsive layout inspection",
                "Structural checklist validation",
                "Holistic visual/product review",
            ],
            human_review_required_for=[
                "score changes",
                "workaround acceptance",
                "destructive git or evidence cleanup",
            ],
        )
    return GateRequirements(
        classification="safe_source_or_process_prep",
        can_edit_without_rendered_evidence=True,
        required_pre_edit_commands=[],
        required_evidence=[
            "PRD packet",
            "Task breakdown",
            "Review Gate",
            "py_compile or equivalent syntax validation for changed scripts",
            "dry-run output for orchestration contract changes",
        ],
        human_review_required_for=[
            "destructive git operations",
            "scope expansion into player-facing files",
            "product quality score changes",
        ],
    )


def build_prd_packet(goal: Goal) -> dict[str, Any]:
    return {
        "problem": "SC Spire worker sessions can drift from OVV and project-specific closure gates when the control plane lives only in chat history.",
        "user_outcome": "A reusable Agent SDK orchestrator contract controls Codex execution from intake through final validation.",
        "explicit_requirements": goal.acceptance_criteria,
        "implied_requirements": [
            "Do not start implementation from a raw prompt.",
            "Keep Codex as the execution worker, not the final judge.",
            "Make OVV and rendered evidence hard gates for player-facing work.",
            "Promote matching issue logs into gate inputs and acceptance criteria.",
            "Make the contract runnable locally before adding live model calls.",
        ],
        "non_goals": goal.non_goals,
        "affected_surfaces": goal.affected_surfaces,
        "risks": [
            "Overbuilding a multi-agent stack before the project contract is stable.",
            "Treating dry-run output as product evidence.",
            "Accidentally routing player-facing Unity edits through the safe source/process lane.",
        ],
    }


def build_task_breakdown(goal: Goal, gates: GateRequirements) -> list[dict[str, Any]]:
    return [
        {
            "role": "intake-agent",
            "work_level": "planning",
            "owned_output": "PRD packet",
            "forbidden_scope": "file edits and closure claims",
        },
        {
            "role": "orchestration-agent",
            "work_level": "routing",
            "owned_output": "worker and validator plan",
            "forbidden_scope": "bypassing gate requirements",
        },
        {
            "role": "codex-worker",
            "work_level": "source_process" if gates.can_edit_without_rendered_evidence else "player_facing_work",
            "owned_files": goal.planned_files,
            "forbidden_scope": "changing files outside the assigned plan without regenerating gates",
        },
        {
            "role": "product-critic-agent",
            "validation_level": "product",
            "required_evidence": "player-facing risk review and sellability-claim challenge",
        },
        {
            "role": "validator-code-level",
            "validation_level": "code",
            "required_evidence": "syntax, contract, and regression command results",
        },
        {
            "role": "validator-ovv-product-level",
            "validation_level": "product_process",
            "required_evidence": gates.required_evidence,
        },
    ]


def build_review_gate(goal: Goal, gates: GateRequirements) -> dict[str, Any]:
    return {
        "pass_criteria": [
            "Every acceptance criterion has matching evidence.",
            "No known unresolved process or implementation issue remains.",
            "No player-facing closure is claimed without rendered evidence.",
            "No score movement is claimed from source/process work.",
        ],
        "fail_criteria": [
            "Worker starts from raw prompt without PRD and Review Gate.",
            "OVV decision packet is skipped for player-facing Unity work.",
            "Validation relies only on one passing test when UI/product evidence is required.",
            "A validator identifies a blocker and the orchestrator suppresses it.",
        ],
        "commands": gates.required_pre_edit_commands,
        "evidence_required": gates.required_evidence,
        "localhost_browser_target": "http://localhost:5050",
    }


def build_orchestration_plan(goal: Goal) -> dict[str, Any]:
    gates = classify_gate_requirements(goal)
    issue_memory = build_issue_memory_preflight(goal)
    provider_routing = load_provider_routing_config()
    return {
        "goal": asdict(goal),
        "agent_personas": [asdict(persona) for persona in PERSONAS],
        "provider_routing": {
            "config_path": str(PROVIDER_ROUTING_PATH.relative_to(REPO_ROOT)),
            "default_route": provider_routing.get("default_route"),
            "role_defaults": provider_routing.get("role_defaults", {}),
            "routes": provider_routing.get("routes", {}),
            "decision_rules": provider_routing.get("decision_rules", []),
            "persona_routes": [route_for_role(persona.agent_id, provider_routing) for persona in PERSONAS],
        },
        "gate_requirements": asdict(gates),
        "issue_memory_preflight": asdict(issue_memory),
        "prd_packet": build_prd_packet(goal),
        "task_breakdown": build_task_breakdown(goal, gates),
        "review_gate": build_review_gate(goal, gates),
        "final_report_contract": {
            "format": "SC Spire numbered Problem -> Method -> Final Result report",
            "must_include": [
                "review rounds actually performed",
                "round-by-round summary",
                "bugs found at completion time",
                "issues found and how they were resolved",
                "final implemented features",
                "regressions checked",
                "remaining limitations",
                "usage instructions",
            ],
        },
    }


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip()).strip("-")
    return value[:80] or "run"


def make_run_dir(goal: Goal) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / f"{stamp}-{safe_slug(goal.goal_id)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def append_event(events: list[DialogueEvent], speaker: str, recipient: str, event_type: str, message: str, artifact: str | None = None) -> None:
    events.append(
        DialogueEvent(
            timestamp=utc_timestamp(),
            speaker=speaker,
            recipient=recipient,
            event_type=event_type,
            message=message,
            artifact=artifact,
        )
    )


def summarize_issue_titles(entries: list[dict[str, Any]], limit: int = 5) -> str:
    if not entries:
        return "No matching entries."
    return "\n".join(f"- [{entry['section_file']}] {entry['title']}" for entry in entries[:limit])


def run_claude_review(prompt: str, timeout_seconds: int) -> tuple[bool, str]:
    claude_cmd = shutil.which("claude") or str(DEFAULT_CLAUDE_SHIM)
    if not Path(claude_cmd).exists() and shutil.which(claude_cmd) is None:
        return False, f"Claude CLI was not found. Tried PATH and {DEFAULT_CLAUDE_SHIM}."

    if claude_cmd.lower().endswith(".ps1"):
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            claude_cmd,
        ]
    else:
        command = [claude_cmd]
    command += [
        "-p",
        "--permission-mode",
        "default",
        "--disable-slash-commands",
        "--output-format",
        "text",
        "--system-prompt",
        "You are a concise SC Spire orchestration reviewer. Review the packet and return blockers, routing corrections, and missing evidence only.",
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("NO_COLOR", "1")
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return False, f"Claude execution failed: {exc}"
    output = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        return False, f"Claude exited with code {completed.returncode}.\nSTDOUT:\n{output}\nSTDERR:\n{stderr}"
    if stderr:
        output = f"{output}\n\n[stderr]\n{stderr}" if output else f"[stderr]\n{stderr}"
    return True, output or "Claude returned an empty response."


def build_claude_prompt(plan: dict[str, Any]) -> str:
    return (
        "Review this SC Spire Agent SDK orchestrator packet.\n"
        "Focus on role routing, persona quality, issue-memory usefulness, missing gates, and whether worker/validator handoffs are safe.\n"
        "This should be collaborative critique, not a command-only review.\n"
        "Do not claim product completion.\n\n"
        + json.dumps(plan, ensure_ascii=False, indent=2)
    )


def add_collaboration_round(events: list[DialogueEvent], plan: dict[str, Any]) -> None:
    gates = plan["gate_requirements"]
    issue_memory = plan["issue_memory_preflight"]
    append_event(
        events,
        "supervisor-agent",
        "product-critic-agent",
        "question",
        "From a player/product perspective, what would make this plan unsafe to close?",
    )
    append_event(
        events,
        "product-critic-agent",
        "supervisor-agent",
        "answer",
        "Closure is unsafe if the worker treats "
        + gates["classification"]
        + " as product completion. The plan must preserve rendered-evidence and sellability boundaries.",
    )
    append_event(
        events,
        "validator-ovv-product-level",
        "codex-worker",
        "challenge",
        "Before implementation, explain how matching open issue-memory entries will change your acceptance criteria.",
    )
    append_event(
        events,
        "codex-worker",
        "validator-ovv-product-level",
        "answer",
        "I will treat the top open issue-memory entries as active risks. If they overlap my files or evidence path, I must add verification or escalate instead of ignoring them.\n\n"
        + summarize_issue_titles(issue_memory["matching_open_issues"], limit=4),
    )
    append_event(
        events,
        "validator-code-level",
        "orchestration-agent",
        "challenge",
        "The plan needs concrete command evidence. Which verification commands are mandatory for this classification?",
    )
    commands = plan["review_gate"]["commands"] or [
        "No pre-edit command is required, but changed scripts still need syntax and dry-run verification."
    ]
    append_event(
        events,
        "orchestration-agent",
        "validator-code-level",
        "answer",
        "\n".join(f"- {command}" for command in commands),
    )
    append_event(
        events,
        "supervisor-agent",
        "all-agents",
        "consensus",
        "Consensus: proceed only as a bounded orchestration contract unless the required evidence gates are satisfied. Product-quality or closure claims remain blocked until validators agree with evidence.",
    )


def run_local_dialogue(
    goal: Goal,
    plan: dict[str, Any],
    *,
    ask_claude: bool,
    execute_claude: bool,
    claude_timeout: int,
) -> Path:
    run_dir = make_run_dir(goal)
    events: list[DialogueEvent] = []
    plan_path = run_dir / "orchestration-plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    append_event(
        events,
        "supervisor-agent",
        "intake-agent",
        "handoff",
        "Convert the user request into a PRD packet. Do not authorize file edits.",
        str(plan_path.relative_to(REPO_ROOT)),
    )
    append_event(
        events,
        "intake-agent",
        "orchestration-agent",
        "response",
        "PRD packet ready. Explicit requirements, implied requirements, non-goals, affected surfaces, and risks are in the orchestration plan.",
        str(plan_path.relative_to(REPO_ROOT)),
    )

    issue_memory = plan["issue_memory_preflight"]
    append_event(
        events,
        "orchestration-agent",
        "issue-memory-agent",
        "handoff",
        "Scan issue memory and promote relevant open issues/countermeasures into gate inputs.",
    )
    append_event(
        events,
        "issue-memory-agent",
        "orchestration-agent",
        "response",
        "Open issue inputs:\n"
        + summarize_issue_titles(issue_memory["matching_open_issues"])
        + "\n\nResolved countermeasure candidates:\n"
        + summarize_issue_titles(issue_memory["matching_resolved_countermeasures"]),
    )

    gates = plan["gate_requirements"]
    append_event(
        events,
        "orchestration-agent",
        "codex-worker",
        "assignment",
        "Assigned work classification: "
        + gates["classification"]
        + ". Owned files are limited to the planned files in the contract. Worker must not expand scope without regenerating gates.",
    )
    append_event(
        events,
        "orchestration-agent",
        "product-critic-agent",
        "assignment",
        "Challenge player-facing claims, weak visual/product assumptions, and any attempt to treat dry-run or source-prep evidence as product closure.",
    )
    append_event(
        events,
        "orchestration-agent",
        "validator-code-level",
        "assignment",
        "Validate syntax, contract shape, command results, and regressions for changed orchestration files.",
    )
    append_event(
        events,
        "orchestration-agent",
        "validator-ovv-product-level",
        "assignment",
        "Validate OVV/process gates, issue-memory use, rendered-evidence boundary, and final report contract.",
    )
    add_collaboration_round(events, plan)

    if ask_claude:
        claude_prompt_path = run_dir / "claude-review-prompt.md"
        claude_prompt_path.write_text(build_claude_prompt(plan), encoding="utf-8")
        append_event(
            events,
            "orchestration-agent",
            "claude-reviewer",
            "review_request",
            "Prepared external Claude review request for routing/gate packet.",
            str(claude_prompt_path.relative_to(REPO_ROOT)),
        )
        if execute_claude:
            ok, response = run_claude_review(claude_prompt_path.read_text(encoding="utf-8"), claude_timeout)
            append_event(
                events,
                "claude-reviewer",
                "orchestration-agent",
                "review_response" if ok else "review_blocked",
                response,
            )
        else:
            append_event(
                events,
                "claude-reviewer",
                "orchestration-agent",
                "review_queued",
                "Claude prompt artifact was written but not executed. Use --execute-claude only when a slow local Claude subprocess is acceptable.",
                str(claude_prompt_path.relative_to(REPO_ROOT)),
            )
    else:
        append_event(
            events,
            "orchestration-agent",
            "claude-reviewer",
            "review_skipped",
            "Claude review was not requested for this local run. Use --ask-claude to attempt the local Claude CLI adapter.",
        )

    append_event(
        events,
        "final-reporter-agent",
        "user",
        "summary",
        "Local multi-agent dialogue run complete. Transcript and plan artifacts were written for audit and future improvement.",
    )

    transcript_jsonl = run_dir / "transcript.jsonl"
    transcript_md = run_dir / "transcript.md"
    chatkit_thread = run_dir / "chatkit-thread.json"
    transcript_jsonl.write_text(
        "\n".join(json.dumps(asdict(event), ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )
    transcript_md.write_text(render_transcript_markdown(goal, events, plan_path), encoding="utf-8")
    chatkit_thread.write_text(json.dumps(render_chatkit_thread(goal, events), ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def render_transcript_markdown(goal: Goal, events: list[DialogueEvent], plan_path: Path) -> str:
    lines = [
        f"# Agent Orchestrator Transcript - {goal.goal_id}",
        "",
        f"- Generated: {utc_timestamp()}",
        f"- Plan: `{plan_path.relative_to(REPO_ROOT)}`",
        "",
    ]
    for index, event in enumerate(events, start=1):
        lines.extend(
            [
                f"## {index}. {event.speaker} -> {event.recipient} [{event.event_type}]",
                "",
                f"- time: `{event.timestamp}`",
            ]
        )
        if event.artifact:
            lines.append(f"- artifact: `{event.artifact}`")
        lines.extend(["", event.message, ""])
    return "\n".join(lines)


def render_chatkit_thread(goal: Goal, events: list[DialogueEvent]) -> dict[str, Any]:
    return {
        "thread_id": goal.goal_id,
        "title": f"SC Spire orchestrator run: {goal.goal_id}",
        "metadata": {
            "source": "sc_spire_agent_sdk_orchestrator",
            "intended_ui": "ChatKit or any operator dashboard that can render role-tagged messages",
        },
        "items": [
            {
                "id": f"event-{index:03d}",
                "role": "assistant" if event.speaker != "user" else "user",
                "speaker": event.speaker,
                "recipient": event.recipient,
                "type": event.event_type,
                "created_at": event.timestamp,
                "content": event.message,
                "artifact": event.artifact,
            }
            for index, event in enumerate(events, start=1)
        ],
    }


def check_live_sdk_ready() -> dict[str, Any]:
    desktop_key_file_present = DESKTOP_OPENAI_KEY_FILE.exists() and DESKTOP_OPENAI_KEY_FILE.stat().st_size > 0
    routing = load_provider_routing_config()
    claude_cmd = shutil.which("claude") or str(DEFAULT_CLAUDE_SHIM)
    claude_available = bool(shutil.which("claude")) or Path(claude_cmd).exists()
    return {
        "openai_agents_installed": importlib.util.find_spec("agents") is not None,
        "openai_api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "desktop_openai_key_file_present": desktop_key_file_present,
        "provider_routing_path": str(PROVIDER_ROUTING_PATH.relative_to(REPO_ROOT)),
        "provider_routes": routing.get("routes", {}),
        "role_defaults": routing.get("role_defaults", {}),
        "decision_rules": routing.get("decision_rules", []),
        "claude_cli_or_shim_available": claude_available,
        "codex_subscription_worker_available": True,
        "codex_mcp_next_step": "Run `codex mcp-server` and connect it as an MCP tool from Agents SDK live mode.",
        "chatkit_next_step": "Use ChatKit as the operator UI after the server-side Agents SDK workflow and transcript API are wired.",
    }


def render_text(plan: dict[str, Any]) -> str:
    goal = plan["goal"]
    gates = plan["gate_requirements"]
    lines = [
        f"SC Spire Agent SDK OVV Orchestrator Dry Run: {goal['goal_id']}",
        "",
        f"Classification: {gates['classification']}",
        f"Can edit without rendered evidence: {gates['can_edit_without_rendered_evidence']}",
        "",
        "PRD:",
        f"- Problem: {plan['prd_packet']['problem']}",
        f"- User outcome: {plan['prd_packet']['user_outcome']}",
        "",
        "Task Breakdown:",
    ]
    for task in plan["task_breakdown"]:
        lines.append(f"- {task['role']}: {task.get('work_level') or task.get('validation_level')}")
    lines.extend(["", "Provider Routing:"])
    for route in plan.get("provider_routing", {}).get("persona_routes", []):
        lines.append(f"- {route['role']}: {route['route']} / {route['model']} / enabled={route['enabled']}")
    lines.extend(["", "Review Gate Commands:"])
    commands = plan["review_gate"]["commands"] or ["No pre-edit command required for this classification."]
    lines.extend(f"- {command}" for command in commands)
    lines.extend(["", "Evidence Required:"])
    lines.extend(f"- {item}" for item in plan["review_gate"]["evidence_required"])
    issue_memory = plan["issue_memory_preflight"]
    lines.extend(
        [
            "",
            "Issue Memory Preflight:",
            f"- entries scanned: {issue_memory['entries_scanned']}",
            f"- matching open issues: {len(issue_memory['matching_open_issues'])}",
            f"- matching resolved countermeasures: {len(issue_memory['matching_resolved_countermeasures'])}",
        ]
    )
    for item in issue_memory["matching_open_issues"][:3]:
        lines.append(f"- open: [{item['section_file']}] {item['title']}")
    for item in issue_memory["matching_resolved_countermeasures"][:3]:
        lines.append(f"- countermeasure: [{item['section_file']}] {item['title']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a SC Spire Agent SDK OVV orchestration contract.")
    parser.add_argument("--goal", required=True, type=Path, help="Path to goal JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Build the deterministic orchestration contract.")
    parser.add_argument("--run-sdk", action="store_true", help="Check live Agents SDK readiness. Full live mode is not wired yet.")
    parser.add_argument("--run-local-dialogue", action="store_true", help="Run a deterministic local multi-agent dialogue and write transcript artifacts.")
    parser.add_argument("--ask-claude", action="store_true", help="During --run-local-dialogue, write a Claude review prompt artifact and record the request.")
    parser.add_argument("--execute-claude", action="store_true", help="Actually execute the local Claude CLI during --ask-claude. This may be slow or unavailable.")
    parser.add_argument("--claude-timeout", type=int, default=300, help="Seconds to wait for optional Claude review when --execute-claude is used.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    if not args.dry_run and not args.run_sdk and not args.run_local_dialogue:
        parser.error("Choose --dry-run, --run-sdk, or --run-local-dialogue.")

    goal = load_goal(args.goal)
    plan = build_orchestration_plan(goal)

    if args.run_sdk:
        plan["live_sdk_readiness"] = check_live_sdk_ready()
    if args.run_local_dialogue:
        run_dir = run_local_dialogue(
            goal,
            plan,
            ask_claude=args.ask_claude,
            execute_claude=args.execute_claude,
            claude_timeout=args.claude_timeout,
        )
        plan["local_dialogue_run"] = str(run_dir)

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(render_text(plan))
        if args.run_local_dialogue:
            print("")
            print(f"Local dialogue run: {plan['local_dialogue_run']}")
        if args.run_sdk:
            readiness = plan["live_sdk_readiness"]
            print("")
            print("Live SDK readiness:")
            for key, value in readiness.items():
                print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
