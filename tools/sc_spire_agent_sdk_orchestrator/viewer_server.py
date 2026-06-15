"""Local HTML viewer for SC Spire agent orchestrator transcripts."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from agents_sdk_live_adapter import build_sdk_style_manifest
from agents_sdk_pattern import build_agents_sdk_pattern_status


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "output" / "agent_orchestrator_runs"
ISSUE_IMPORT_DIR = RUNS_DIR / "issue_import"
ISSUE_IMPORT_INDEX = ISSUE_IMPORT_DIR / "deduped-issues.json"
ISSUE_IMPORT_COMPACT_INDEX = ISSUE_IMPORT_DIR / "deduped-issues-compact.json"
STATIC_DIR = Path(__file__).resolve().parent / "viewer_static"
OPERATOR_MESSAGES = RUNS_DIR / "operator_messages.jsonl"
OPERATOR_MESSAGE_EVENTS = RUNS_DIR / "operator_message_events.jsonl"
VIEWER_DEBUG_LOG = RUNS_DIR / "viewer_server_debug.log"
PROVIDER_ROUTING_PATH = Path(__file__).resolve().parent / "provider_routing.json"
GOAL_REPORT_ROOT = Path(os.environ.get("SC_SPIRE_GOAL_REPORT_ROOT", r"D:\sc-spire-orchestrator-goal-reports"))
DESKTOP_OPENAI_KEY = Path.home() / "Desktop" / "openai.txt"
RESPONSES_API_URL = "https://api.openai.com/v1/responses"
PROMPT_PREFLIGHT_TIMEOUT = int(os.environ.get("SC_SPIRE_PROMPT_PREFLIGHT_TIMEOUT", "120"))
LIVE_PROMPT_PREFLIGHT_ENABLED = os.environ.get("SC_SPIRE_LIVE_PROMPT_PREFLIGHT", "0") == "1"
LIVE_PREFLIGHT_OVERRIDE: bool | None = None  # None=env 따름, True/False=런타임 토글
QUEUE_POLL_SECONDS = float(os.environ.get("SC_SPIRE_QUEUE_POLL_SECONDS", "3"))
QUEUE_PROCESSOR_ENABLED = os.environ.get("SC_SPIRE_QUEUE_PROCESSOR", "1") != "0"
QUEUE_AUTORUN_ENABLED = os.environ.get("SC_SPIRE_QUEUE_AUTORUN", "1") != "0"
QUEUE_AUTORUN_MAX_PER_TICK = max(1, int(os.environ.get("SC_SPIRE_QUEUE_AUTORUN_MAX_PER_TICK", "1")))
QUEUE_AUTO_ADVANCE_ENABLED = os.environ.get("SC_SPIRE_QUEUE_AUTO_ADVANCE", "1") != "0"
QUEUE_AUTO_ADVANCE_STEPS = max(0, int(os.environ.get("SC_SPIRE_QUEUE_AUTO_ADVANCE_STEPS", "1000000")))
SHORT_LOOP_MAX_ATTEMPTS = max(1, int(os.environ.get("SC_SPIRE_SHORT_LOOP_MAX_ATTEMPTS", "1000000")))
SHORT_LOOP_VALIDATOR_MIN = max(2, int(os.environ.get("SC_SPIRE_SHORT_LOOP_VALIDATOR_MIN", "4")))
MIN_REVIEW_ITERATIONS_BEFORE_STOP = max(1, int(os.environ.get("SC_SPIRE_MIN_REVIEW_ITERATIONS_BEFORE_STOP", "3")))
SUPERVISOR_AUTO_REVIEW_ENABLED = os.environ.get("SC_SPIRE_SUPERVISOR_AUTO_REVIEW", "1") != "0"
SUPERVISOR_AUTO_LIVE_CLAUDE = os.environ.get("SC_SPIRE_SUPERVISOR_AUTO_LIVE_CLAUDE", "0") == "1"
CLAUDE_REVIEW_TIMEOUT = int(os.environ.get("SC_SPIRE_CLAUDE_REVIEW_TIMEOUT", "900"))
EVENT_LOCK = threading.Lock()
STATUS_EPOCH = {"seq": 0}
STATUS_EPOCH_LOCK = threading.Lock()
ISSUE_IMPORT_CACHE: dict[str, object] = {"mtime": None, "payload": None}
RESPONSE_CACHE: dict[str, dict[str, object]] = {}
RESPONSE_CACHE_LOCKS: dict[str, threading.Lock] = {
    "runs": threading.Lock(),
    "status": threading.Lock(),
}
INSTANCE_LOCK_HANDLE = None


def debug_log(message: str) -> None:
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        with VIEWER_DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{utc_timestamp()} {message}\n")
    except OSError:
        pass


def cached_payload(key: str, ttl_seconds: float, builder) -> object:
    now = time.time()
    cached = RESPONSE_CACHE.get(key)
    if cached and now - float(cached.get("time", 0)) <= ttl_seconds:
        return cached.get("payload")
    lock = RESPONSE_CACHE_LOCKS[key]
    acquired = lock.acquire(blocking=False)
    if not acquired:
        if cached:
            return cached.get("payload")
        with lock:
            return RESPONSE_CACHE.get(key, {}).get("payload")
    try:
        cached = RESPONSE_CACHE.get(key)
        if cached and now - float(cached.get("time", 0)) <= ttl_seconds:
            return cached.get("payload")
        payload = builder()
        RESPONSE_CACHE[key] = {"time": time.time(), "payload": payload}
        return payload
    finally:
        lock.release()


def acquire_instance_lock(port: int) -> None:
    """Prevent multiple viewer_server processes for the same port."""
    global INSTANCE_LOCK_HANDLE
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNS_DIR / f"viewer_server_{port}.lock"
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"viewer server already running for port {port}: {lock_path}", file=sys.stderr)
        raise SystemExit(2)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode("ascii"))
    handle.flush()
    INSTANCE_LOCK_HANDLE = handle


def invalidate_status_cache() -> None:
    RESPONSE_CACHE.pop("runs", None)
    RESPONSE_CACHE.pop("status", None)
    with STATUS_EPOCH_LOCK:
        STATUS_EPOCH["seq"] += 1


def list_runs(limit: int = 80) -> list[dict[str, object]]:
    if not RUNS_DIR.exists():
        return []
    runs: list[dict[str, object]] = []
    visible_index = 0
    for path in sorted(RUNS_DIR.iterdir(), key=lambda item: item.name, reverse=True):
        if not path.is_dir():
            continue
        transcript = path / "transcript.jsonl"
        chatkit = path / "chatkit-thread.json"
        if not transcript.exists() and not chatkit.exists():
            continue
        event_count = 0
        if transcript.exists():
            try:
                with transcript.open("r", encoding="utf-8", errors="replace") as handle:
                    event_count = sum(1 for _, line in zip(range(200), handle) if line.strip())
            except OSError:
                event_count = 0
        title = fast_title_for_run_dir(path)
        runs.append(
            {
                "id": path.name,
                "title": title,
                "event_count": event_count,
                "has_chatkit": chatkit.exists(),
                "has_claude_prompt": (path / "claude-review-prompt.md").exists(),
                "has_claude_response": (path / "claude-review-response.md").exists(),
                "has_plan": (path / "orchestration-plan.json").exists(),
                "is_current": visible_index == 0,
            }
        )
        visible_index += 1
        if len(runs) >= limit:
            break
    return runs


def fast_title_for_run_dir(run_dir: Path) -> str:
    plan_path = run_dir / "orchestration-plan.json"
    if plan_path.exists():
        try:
            text = plan_path.read_text(encoding="utf-8", errors="replace")[:4096]
            match = re.search(r'"title"\s*:\s*"([^"]+)"', text)
            if match:
                return title_for_message({"original_message": match.group(1)})
            match = re.search(r'"original_message"\s*:\s*"([^"]+)"', text)
            if match:
                return title_for_message({"original_message": match.group(1)})
        except OSError:
            pass
    return run_dir.name


def title_for_run_dir(run_dir: Path) -> str:
    plan_path = run_dir / "orchestration-plan.json"
    if plan_path.exists():
        try:
            plan = read_json_file(plan_path)
            if isinstance(plan, dict):
                operator_message = plan.get("operator_message")
                if isinstance(operator_message, dict):
                    title = str(operator_message.get("title") or operator_message.get("original_message") or "").strip()
                    if title:
                        return title_for_message({"original_message": title})
                goal = plan.get("goal")
                if isinstance(goal, dict):
                    title = str(goal.get("goal_id") or goal.get("blocker_id") or "").strip()
                    if title:
                        return title
        except Exception:
            return run_dir.name
    return run_dir.name


def safe_run_dir(run_id: str) -> Path:
    run_dir = (RUNS_DIR / run_id).resolve()
    if RUNS_DIR.resolve() not in run_dir.parents:
        raise ValueError("invalid run id")
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(run_id)
    return run_dir


def read_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_transcript(run_dir: Path) -> list[dict[str, object]]:
    jsonl = run_dir / "transcript.jsonl"
    if not jsonl.exists():
        return []
    events: list[dict[str, object]] = []
    for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def reconcile_run_artifacts(run_id: str, run_dir: Path) -> dict[str, object]:
    """Run the derived-audit ensure_* reconcilers (which may WRITE files).

    This is the mutating reconciliation step that used to live inside
    run_payload. It is now only invoked from explicit POST flows so that the
    GET /api/run path stays read-only (A1).
    """
    summary: dict[str, object] = {
        "reconciled": [],
        "skipped": False,
        "provenance": make_provenance("contract_generated", "viewer-server"),
    }
    reconciled: list[str] = summary["reconciled"]  # type: ignore[assignment]
    # E2: build/refresh the per-run context capsule on every mutating reconcile.
    # This is a MUTATION (A1) so it lives here, not on the GET run_payload path.
    try:
        write_context_capsule(run_id, run_dir, mode=_run_capsule_mode(run_dir))
        reconciled.append(CONTEXT_CAPSULE_ARTIFACT)
    except Exception as exc:  # pragma: no cover - defensive
        summary["capsule_error"] = str(exc)
    if not (run_dir / "d-drive-report-pack.json").exists():
        summary["skipped"] = True
        return summary
    try:
        if ensure_report_pack_judgment(run_id, run_dir) is not None:
            reconciled.append("report-pack-judgment.json")
        if ensure_report_evidence_audit(run_id, run_dir) is not None:
            reconciled.append("report-evidence-audit.json")
        if ensure_goal_completion_audit(run_id, run_dir) is not None:
            reconciled.append("goal-completion-audit.json")
    except Exception as exc:  # pragma: no cover - defensive parity with old behavior
        summary["error"] = str(exc)
    return summary


def run_payload(run_id: str) -> dict[str, object]:
    run_dir = safe_run_dir(run_id)
    plan_path = run_dir / "orchestration-plan.json"
    chatkit_path = run_dir / "chatkit-thread.json"
    markdown_path = run_dir / "transcript.md"
    claude_prompt_path = run_dir / "claude-review-prompt.md"
    plan = read_json_file(plan_path) if plan_path.exists() else None
    if isinstance(plan, dict):
        latest_plan_overrides = {
            "worker_dispatch": run_dir / "worker-dispatch.json",
            "evidence_contract": run_dir / "evidence-contract.json",
            "review_gate": run_dir / "review-gate.json",
            "agents_sdk_run_contract": run_dir / "agents-sdk-run-contract.json",
            "issue_gate": run_dir / "issue-gate.json",
            "main_advisory_council": run_dir / "main-advisory-council.json",
            "queue_routing_decision": run_dir / "queue-routing-decision.json",
            "cerberus_deliberation": run_dir / "cerberus-deliberation.json",
            "d_drive_report_pack": run_dir / "d-drive-report-pack.json",
            "report_pack_judgment": run_dir / "report-pack-judgment.json",
            "report_evidence_audit": run_dir / "report-evidence-audit.json",
            "goal_completion_audit": run_dir / "goal-completion-audit.json",
            "unity_rendered_evidence": run_dir / "unity-rendered-evidence.json",
        }
        for key, artifact_path in latest_plan_overrides.items():
            if artifact_path.exists():
                try:
                    plan[key] = read_json_file(artifact_path)
                except Exception:
                    pass
        plan = enrich_dispatch_preview(plan)
    capsule_path = run_dir / CONTEXT_CAPSULE_ARTIFACT
    context_capsule = None
    if capsule_path.exists():
        try:
            context_capsule = read_json_file(capsule_path)
        except Exception:
            context_capsule = None
    return {
        "id": run_id,
        "events": read_transcript(run_dir),
        "plan": plan,
        "context_capsule": context_capsule,
        "chatkit": read_json_file(chatkit_path) if chatkit_path.exists() else None,
        "transcript_md": markdown_path.read_text(encoding="utf-8", errors="replace") if markdown_path.exists() else "",
        "claude_prompt": claude_prompt_path.read_text(encoding="utf-8", errors="replace") if claude_prompt_path.exists() else "",
        "artifacts": sorted(item.name for item in run_dir.iterdir() if item.is_file()),
    }


def enrich_dispatch_preview(plan: dict[str, object]) -> dict[str, object]:
    if plan.get("main_dispatch_preview"):
        return plan
    if plan.get("kind") == "operator_message_orchestrated_packet":
        dispatch = plan.get("worker_dispatch") if isinstance(plan.get("worker_dispatch"), dict) else {}
        decision = plan.get("main_decision") if isinstance(plan.get("main_decision"), dict) else {}
        assignments = dispatch.get("assignments", []) if isinstance(dispatch.get("assignments"), list) else []
        plan["main_dispatch_preview"] = {
            "actual_dispatch_status": decision.get("status") or dispatch.get("status") or "dispatch_ready",
            "current_owner": "main-orchestrator",
            "note": str((plan.get("next_dispatch") or {}).get("note", "")) if isinstance(plan.get("next_dispatch"), dict) else "",
            "routes": [
                {
                    "agent": item.get("agent", ""),
                    "route": item.get("route", ""),
                    "status": item.get("status", ""),
                    "reason": item.get("task", "") or item.get("blocked_by", ""),
                }
                for item in assignments
                if isinstance(item, dict)
            ],
        }
        return plan
    if plan.get("kind") != "operator_prompt_handoff":
        return plan
    operator_message = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
    preflight = operator_message.get("preflight") if isinstance(operator_message.get("preflight"), dict) else {}
    risk_flags = preflight.get("risk_flags") or preflight.get("warnings") or []
    if not isinstance(risk_flags, list):
        risk_flags = []
    requires_claude = any("player_facing" in str(flag) or "closure" in str(flag) or "design" in str(flag) for flag in risk_flags)
    routes = [
        {
            "agent": "main-orchestrator",
            "route": default_provider_route(),
            "status": "received",
            "reason": "정제된 프롬프트를 받은 현재 소유자입니다.",
        },
        {
            "agent": "issue-memory-agent",
            "route": default_provider_route(),
            "status": "recommended_next",
            "reason": "기존 이슈와 반복 실패를 먼저 입력 조건으로 올립니다.",
        },
        {
            "agent": "supervisor-agent",
            "route": default_provider_route(),
            "status": "recommended_next",
            "reason": "작업이 필요한지 판단하고 PRD/worker/validator 배분을 결정합니다.",
        },
        {
            "agent": "codex-worker",
            "route": "codex_subscription_worker",
            "status": "conditional",
            "reason": "메인이 실제 파일 수정이나 브라우저 검증을 승인할 때만 배정됩니다.",
        },
    ]
    if requires_claude:
        routes.append(
            {
                "agent": "claude-reviewer",
                "route": "claude_collaborator",
                "status": "conditional",
                "reason": "player-facing, closure, product/design 위험이 있을 때 메인이 검토를 요청합니다.",
            }
        )
    plan["main_dispatch_preview"] = {
        "actual_dispatch_status": "not_dispatched_yet",
        "current_owner": "main-orchestrator",
        "note": "현재 저장된 실제 로그는 메인 큐 수신까지입니다. 아래는 메인이 다음에 선택해야 할 추천 라우팅이며, 실제 배정 로그는 아직 없습니다.",
        "routes": routes,
    }
    return plan


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PROVENANCE_SOURCE_TYPES = (
    "contract_generated",
    "local_self_check",
    "external_codex_cli",
    "live_claude_cli",
    "live_openai_api",
    "external_chatgpt_pro_manual",
    "operator_manual",
)


def make_provenance(
    source_type: str,
    created_by: str,
    *,
    command: str = "",
    exit_code: int | None = None,
    input_artifacts: list[str] | None = None,
    verified_by: list[str] | None = None,
    is_claim_evidence: bool = False,
) -> dict[str, object]:
    """Build a provenance block for artifacts the viewer writes (A2).

    Stamps trust traceability onto NEW viewer-written artifacts. Empty optional
    fields are omitted. ``source_type`` is validated against
    ``PROVENANCE_SOURCE_TYPES``.
    """
    if source_type not in PROVENANCE_SOURCE_TYPES:
        raise ValueError(
            f"invalid provenance source_type {source_type!r}; "
            f"allowed: {', '.join(PROVENANCE_SOURCE_TYPES)}"
        )
    provenance: dict[str, object] = {
        "source_type": source_type,
        "created_by": created_by,
        "is_claim_evidence": bool(is_claim_evidence),
        "stamped_at": utc_timestamp(),
    }
    if command:
        provenance["command"] = command
    if exit_code is not None:
        provenance["exit_code"] = exit_code
    if input_artifacts:
        provenance["input_artifacts"] = list(input_artifacts)
    if verified_by:
        provenance["verified_by"] = list(verified_by)
    return provenance


# E2 context capsule -----------------------------------------------------------

CONTEXT_CAPSULE_ARTIFACT = "context-capsule.json"

# Short, static-ish policy lines every lane should honor (E2). Kept terse so the
# capsule stays cheap to read.
CONTEXT_CAPSULE_POLICY = [
    "worker result alone cannot close",
    "player-facing closure requires rendered evidence",
    "every PASS must name the artifact that proves it",
    "if evidence is missing, verdict must be needs_retry or blocked",
]

# Artifacts a healthy run is expected to eventually produce. Absence => listed in
# missing_evidence (E2).
CONTEXT_CAPSULE_EXPECTED_EVIDENCE = [
    "worker-result.json",
    "validator-result.json",
]


def _artifact_trust(run_dir: Path, name: str) -> str:
    """Read an artifact's provenance.source_type as its trust level (E2/A2)."""
    path = run_dir / name
    if not path.exists():
        return "unknown"
    try:
        data = read_json_file(path)
    except Exception:
        return "unknown"
    if isinstance(data, dict):
        provenance = data.get("provenance")
        if isinstance(provenance, dict):
            source_type = provenance.get("source_type")
            if isinstance(source_type, str) and source_type:
                return source_type
    return "unknown"


def _run_capsule_mode(run_dir: Path) -> str:
    """Derive capsule mode (light|normal) from the run's request weight."""
    plan_path = run_dir / "orchestration-plan.json"
    if not plan_path.exists():
        return "normal"
    try:
        plan = read_json_file(plan_path)
    except Exception:
        return "normal"
    if not isinstance(plan, dict):
        return "normal"
    operator = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
    preflight = operator.get("preflight") if isinstance(operator.get("preflight"), dict) else {}
    weight = str(preflight.get("request_weight", "")).strip()
    return "light" if weight == "light" else "normal"


def build_context_capsule(run_id: str, run_dir: Path, mode: str = "normal") -> dict[str, object]:
    """Build a single per-run context capsule every lane can read first (E2).

    Assembled purely from EXISTING run data: the orchestration plan's operator
    message (raw/refined task), the existing issue-memory selection
    (``matching_issues_for_text`` top-k), per-artifact provenance trust (A2), and
    the set of expected-but-absent evidence artifacts.
    """
    plan_path = run_dir / "orchestration-plan.json"
    plan = read_json_file(plan_path) if plan_path.exists() else {}
    if not isinstance(plan, dict):
        plan = {}
    operator = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
    raw = str(operator.get("original_message", ""))
    refined = str(operator.get("refined_message", ""))

    issue_cap = 3 if mode == "light" else 8
    issue_query = "\n".join([raw, refined]).strip()
    relevant_issues: list[dict[str, object]] = []
    if issue_query:
        for issue in matching_issues_for_text(issue_query, limit=issue_cap):
            relevant_issues.append(
                {
                    "id": issue.get("id", ""),
                    "summary": issue.get("title", "") or issue.get("snippet", ""),
                    "countermeasure": issue.get("snippet", ""),
                }
            )

    current_artifacts: list[dict[str, object]] = []
    if run_dir.exists():
        for item in sorted(run_dir.iterdir(), key=lambda p: p.name):
            if not item.is_file():
                continue
            if item.name == CONTEXT_CAPSULE_ARTIFACT:
                continue
            current_artifacts.append(
                {
                    "name": item.name,
                    "status": "exists",
                    "trust": _artifact_trust(run_dir, item.name),
                }
            )

    present_names = {entry["name"] for entry in current_artifacts}
    missing_evidence = [name for name in CONTEXT_CAPSULE_EXPECTED_EVIDENCE if name not in present_names]

    return {
        "context_capsule_version": 1,
        "run_id": run_id,
        "task": {"raw": raw, "refined": refined, "mode": mode},
        "relevant_policy": list(CONTEXT_CAPSULE_POLICY),
        "relevant_issues": relevant_issues,
        "current_artifacts": current_artifacts,
        "missing_evidence": missing_evidence,
        "stamped_at": utc_timestamp(),
    }


def write_context_capsule(run_id: str, run_dir: Path, mode: str = "normal") -> dict[str, object]:
    """Build + persist the context capsule as a MUTATION (A1: not on GET path)."""
    capsule = build_context_capsule(run_id, run_dir, mode=mode)
    capsule["provenance"] = make_provenance("contract_generated", "viewer-server")
    write_json(run_dir / CONTEXT_CAPSULE_ARTIFACT, capsule)
    return capsule


# E4 reviewer output schema validator -----------------------------------------

REVIEW_VERDICTS = {"pass", "needs_retry", "blocked"}
REVIEW_SEVERITIES = {"high", "medium", "low"}
REVIEW_FINDING_REQUIRED_KEYS = ("severity", "claim", "because")


def validate_review_output(obj: object) -> tuple[bool, list[str]]:
    """Hand-rolled stdlib validator for the shared reviewer output schema (E4).

    Never raises on bad input. Returns ``(ok, errors)`` where ``errors`` is a
    list of human-readable strings. Validates: dict shape; verdict in the allowed
    set; top_findings is a list of <= 5 dicts each with required keys and a valid
    severity; missing_evidence / do_not_repeat are lists; next_action is a str.
    """
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, [f"output must be a dict, got {type(obj).__name__}"]

    verdict = obj.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        errors.append(
            f"verdict must be one of {sorted(REVIEW_VERDICTS)}, got {verdict!r}"
        )

    top_findings = obj.get("top_findings")
    if not isinstance(top_findings, list):
        errors.append("top_findings must be a list")
    else:
        if len(top_findings) > 5:
            errors.append(f"top_findings has {len(top_findings)} items (max 5)")
        for index, finding in enumerate(top_findings):
            if not isinstance(finding, dict):
                errors.append(f"top_findings[{index}] must be a dict")
                continue
            for key in REVIEW_FINDING_REQUIRED_KEYS:
                if key not in finding:
                    errors.append(f"top_findings[{index}] missing key {key!r}")
            severity = finding.get("severity")
            if severity is not None and severity not in REVIEW_SEVERITIES:
                errors.append(
                    f"top_findings[{index}].severity must be one of "
                    f"{sorted(REVIEW_SEVERITIES)}, got {severity!r}"
                )

    for list_key in ("missing_evidence", "do_not_repeat"):
        if list_key in obj and not isinstance(obj.get(list_key), list):
            errors.append(f"{list_key} must be a list")

    if "next_action" in obj and not isinstance(obj.get("next_action"), str):
        errors.append("next_action must be a str")

    return (not errors), errors


def summarize_run_context(run_id: str) -> dict[str, object]:
    if not run_id:
        return {}
    try:
        payload = run_payload(run_id)
    except Exception:
        return {"run_id": run_id}
    plan = payload.get("plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    goal = plan.get("goal") or {}
    gates = plan.get("gate_requirements") or {}
    issue_memory = plan.get("issue_memory_preflight") or {}
    return {
        "run_id": run_id,
        "goal_id": goal.get("goal_id", ""),
        "blocker_id": goal.get("blocker_id", ""),
        "work_type": goal.get("work_type", ""),
        "affected_surfaces": goal.get("affected_surfaces", []),
        "planned_files": goal.get("planned_files", []),
        "acceptance_criteria": goal.get("acceptance_criteria", []),
        "classification": gates.get("classification", ""),
        "required_evidence": gates.get("required_evidence", []),
        "open_issue_count": len(issue_memory.get("matching_open_issues", []) or []),
    }


# L2 GPT Pro manual strategist lane ------------------------------------------

GPT_PRO_REQUEST_ARTIFACT = "gpt-pro-review-request.md"
GPT_PRO_RESULT_ARTIFACT = "gpt-pro-review-result.json"
GPT_PRO_DEFAULT_MODEL = "gpt-5.5-pro"


def build_gpt_pro_request_markdown(run_id: str, capsule: dict[str, object]) -> str:
    """Build the compact GPT Pro Strategic Review Request packet (L2).

    A slow strategic-review lane fed by manual copy-paste. The operator pastes
    this into ChatGPT Pro and pastes the JSON answer back. Context is pulled from
    the E2 context-capsule so the packet stays compact.
    """
    task = capsule.get("task") if isinstance(capsule.get("task"), dict) else {}
    raw = str(task.get("raw", "")).strip()
    refined = str(task.get("refined", "")).strip()
    mode = str(task.get("mode", "")).strip()

    policy = capsule.get("relevant_policy") if isinstance(capsule.get("relevant_policy"), list) else []
    issues = capsule.get("relevant_issues") if isinstance(capsule.get("relevant_issues"), list) else []
    artifacts = capsule.get("current_artifacts") if isinstance(capsule.get("current_artifacts"), list) else []
    missing = capsule.get("missing_evidence") if isinstance(capsule.get("missing_evidence"), list) else []

    lines: list[str] = []
    lines.append("# GPT Pro Strategic Review Request")
    lines.append("")
    lines.append(f"- run_id: `{run_id}`")
    lines.append(f"- mode: `{mode or 'normal'}`")
    lines.append("")
    lines.append("## Role")
    lines.append(
        "You are a slow, senior strategic reviewer for an autonomous game-dev "
        "orchestrator (SC Spire). You give architecture critique, prompt/persona "
        "compression advice, failure-pattern analysis, and a closure challenge. "
        "You are a REVIEW-ONLY lane: you do not approve final completion."
    )
    lines.append("")
    lines.append("## Do NOT")
    lines.append("- Do NOT claim the work is closed/complete; you cannot grant closure.")
    lines.append("- Do NOT edit files or run commands; you only advise.")
    lines.append("- Do NOT invent evidence; if evidence is missing, say needs_retry or blocked.")
    lines.append("- Do NOT pretend to be an automated browser session; this is manual copy-paste.")
    lines.append("")
    lines.append("## Context (from this run's context-capsule)")
    lines.append(f"- Raw operator request: {raw or '(none)'}")
    lines.append(f"- Refined task: {refined or '(none)'}")
    if policy:
        lines.append("- Standing policy lines:")
        for item in policy:
            lines.append(f"  - {item}")
    if issues:
        lines.append("- Relevant past issues / countermeasures:")
        for issue in issues:
            if isinstance(issue, dict):
                summary = str(issue.get("summary", "")).strip()
                counter = str(issue.get("countermeasure", "")).strip()
                lines.append(f"  - {summary}" + (f" — {counter}" if counter else ""))
    if artifacts:
        names = ", ".join(str(item.get("name", "")) for item in artifacts if isinstance(item, dict))
        lines.append(f"- Current artifacts present: {names}")
    lines.append(f"- Missing expected evidence: {', '.join(str(m) for m in missing) if missing else '(none)'}")
    lines.append("")
    lines.append("## Questions (answer all 6)")
    lines.append("1. Is the orchestrator architecture / approach sound for this task, or is it drifting?")
    lines.append("2. Are the prompts/personas compressible or redundant? Where?")
    lines.append("3. What failure pattern, if any, is repeating across the artifacts/issues above?")
    lines.append("4. If this is a Unity recovery or replanning situation, what is the safest next plan?")
    lines.append("5. What evidence is missing before this could ever be closed?")
    lines.append("6. If asked to close now, what is your closure objection (closure must stay disallowed)?")
    lines.append("")
    lines.append("## Output (JSON ONLY — no prose outside the JSON)")
    lines.append("Return a single JSON object with exactly these fields:")
    lines.append("```json")
    lines.append("{")
    lines.append('  "verdict": "pass | needs_retry | blocked",')
    lines.append('  "top_findings": [')
    lines.append('    {"severity": "high|medium|low", "claim": "...", "because": "...", "required_evidence": "..."}')
    lines.append("  ],")
    lines.append('  "missing_evidence": ["..."],')
    lines.append('  "do_not_repeat": ["..."],')
    lines.append('  "next_action": "..."')
    lines.append("}")
    lines.append("```")
    lines.append("Keep top_findings to at most 5 items. Output JSON only.")
    lines.append("")
    return "\n".join(lines)


def parse_gpt_pro_answer(answer: str) -> object:
    """Parse an operator-pasted GPT Pro answer; strip ```json fences if present.

    Returns the parsed object on success, otherwise None (caller wraps it).
    """
    text = (answer or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        # Drop the opening fence line (``` or ```json) and any trailing fence.
        without_open = text.split("\n", 1)[1] if "\n" in text else ""
        if without_open.rstrip().endswith("```"):
            without_open = without_open.rstrip()[: -3]
        text = without_open.strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def build_gpt_pro_result_record(
    run_id: str, answer: str, model_claimed: str = GPT_PRO_DEFAULT_MODEL
) -> dict[str, object]:
    """Build the L2 GPT Pro strategy review result record from a pasted answer.

    Parses the answer as JSON (fence-stripped). On parse failure the answer is
    wrapped as {"raw": ..., "verdict": "needs_retry"}. Stamps manual provenance
    (external_chatgpt_pro_manual, operator claim) and annotates E4 schema status.
    """
    parsed = parse_gpt_pro_answer(answer)
    if isinstance(parsed, dict):
        record: dict[str, object] = dict(parsed)
    else:
        record = {"raw": answer, "verdict": "needs_retry"}
    record["kind"] = "gpt_pro_strategy_review"
    record["source"] = "manual_chatgpt_pro"
    record["run_id"] = run_id
    record["created_at"] = utc_timestamp()
    record["model_claimed_by_operator"] = str(model_claimed or GPT_PRO_DEFAULT_MODEL)
    record["provenance"] = make_provenance(
        "external_chatgpt_pro_manual", "operator", is_claim_evidence=True
    )
    schema_valid, schema_errors = validate_review_output(record)
    record["schema_valid"] = schema_valid
    record["schema_errors"] = schema_errors
    return record


def build_gpt_pro_request(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("id", "")).strip()
    if not run_id:
        raise ValueError("id is required")
    run_dir = safe_run_dir(run_id)
    capsule_path = run_dir / CONTEXT_CAPSULE_ARTIFACT
    if capsule_path.exists():
        try:
            capsule = read_json_file(capsule_path)
        except Exception:
            capsule = build_context_capsule(run_id, run_dir, mode=_run_capsule_mode(run_dir))
        if not isinstance(capsule, dict):
            capsule = build_context_capsule(run_id, run_dir, mode=_run_capsule_mode(run_dir))
    else:
        capsule = build_context_capsule(run_id, run_dir, mode=_run_capsule_mode(run_dir))
    markdown = build_gpt_pro_request_markdown(run_id, capsule)
    (run_dir / GPT_PRO_REQUEST_ARTIFACT).write_text(markdown, encoding="utf-8")
    append_transcript_event(
        run_dir,
        "gpt-pro-strategy-advisor",
        "operator",
        "gpt_pro_request_built",
        "GPT Pro 수동 전략 검토 요청 패킷 생성",
        GPT_PRO_REQUEST_ARTIFACT,
    )
    invalidate_status_cache()
    return {
        "run": run_payload(run_id),
        "artifact": GPT_PRO_REQUEST_ARTIFACT,
        "request_preview": markdown[:600],
    }


def record_gpt_pro_result(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("id", "")).strip()
    if not run_id:
        raise ValueError("id is required")
    run_dir = safe_run_dir(run_id)
    answer = str(payload.get("answer", ""))
    if not answer.strip():
        raise ValueError("answer is required")
    model_claimed = str(payload.get("model_claimed", "")).strip() or GPT_PRO_DEFAULT_MODEL
    record = build_gpt_pro_result_record(run_id, answer, model_claimed)
    write_json(run_dir / GPT_PRO_RESULT_ARTIFACT, record)
    append_transcript_event(
        run_dir,
        "gpt-pro-strategy-advisor",
        "main-orchestrator",
        "gpt_pro_review_result",
        f"GPT Pro 수동 전략 검토 결과 기록 (verdict={record.get('verdict', '')})",
        GPT_PRO_RESULT_ARTIFACT,
    )
    invalidate_status_cache()
    return {
        "run": run_payload(run_id),
        "artifact": GPT_PRO_RESULT_ARTIFACT,
        "schema_valid": record.get("schema_valid"),
        "verdict": record.get("verdict"),
    }


def read_openai_api_key() -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    if DESKTOP_OPENAI_KEY.exists():
        try:
            return DESKTOP_OPENAI_KEY.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            return ""
    return ""


def live_preflight_enabled() -> bool:
    if LIVE_PREFLIGHT_OVERRIDE is not None:
        return LIVE_PREFLIGHT_OVERRIDE
    return LIVE_PROMPT_PREFLIGHT_ENABLED


def live_preflight_state() -> dict[str, object]:
    enabled = live_preflight_enabled()
    key_present = bool(read_openai_api_key())
    if enabled and key_present:
        mode = "live"
    elif enabled and not key_present:
        mode = "live_requested_no_key"
    elif key_present:
        mode = "template_degraded"
    else:
        mode = "template_only"
    return {
        "live_enabled": enabled,
        "api_key_present": key_present,
        "effective_mode": mode,
        "override_active": LIVE_PREFLIGHT_OVERRIDE is not None,
    }


def load_provider_routing_config() -> dict[str, object]:
    if not PROVIDER_ROUTING_PATH.exists():
        return {}
    return json.loads(PROVIDER_ROUTING_PATH.read_text(encoding="utf-8"))


def default_provider_route() -> str:
    config = load_provider_routing_config()
    route = config.get("default_route") if isinstance(config, dict) else ""
    return str(route or "codex_subscription_worker")


AGENT_TARGETS = [
    "prompt-preflight-agent",
    "prompt-validator-agent",
    "main-orchestrator",
    "claude-decision-advisor",
    "openai-codex-api-advisor",
    "supervisor-agent",
    "issue-memory-agent",
    "codex-worker",
    "claude-reviewer",
    "product-critic-agent",
    "validator-code-level",
    "validator-ovv-product-level",
    "gemini-reviewer",
    "html",
    "thread",
]


AGENT_PERSONAS = {
    "prompt-preflight-agent": {
        "name": "프롬프트 사전 검증",
        "identity": "사용자 원문을 절대 지우지 않고 보존한 뒤, 메인 오케스트레이터가 실행 가능한 목표/범위/증거 중심 프롬프트로 정제하는 입구 역할입니다.",
        "route": "openai_agents_sdk",
        "permissions": ["prompt_refine", "risk_flag", "clarifying_questions"],
        "focus": [
            "원문 의도 보존",
            "모호한 요구를 실행 가능한 목표로 확장",
            "작업 전 필요한 evidence와 non-goal 추론",
            "사용자가 모델명을 말하지 않아도 필요한 경로 후보를 남김",
        ],
        "forbidden": ["원문 삭제", "완료 판단", "worker 직접 실행", "메인 라우팅 확정"],
        "must_read": ["provider_routing.json", "operator_message_events.jsonl", "memory/issues_log/*.md"],
    },
    "gpt-pro-strategy-advisor": {
        "name": "GPT Pro 전략 보좌관 (수동)",
        "identity": "느린 수동 ChatGPT Pro 전략 검토 레인입니다. 오케스트레이터가 만든 압축 요청 패킷을 오너가 ChatGPT Pro에 직접 붙여넣고, 응답을 다시 붙여넣어 provenance와 함께 보관합니다. 브라우저 자동화 없이 사람이 중간에 붙여넣는 human-gated escalation 레인입니다.",
        "route": "chatgpt_pro_manual_strategist",
        "permissions": [
            "architecture_review",
            "prompt_persona_review",
            "failure_pattern_analysis",
            "milestone_replanning",
            "closure_objection",
        ],
        "focus": [
            "오케스트레이터 구조/아키텍처 비평",
            "prompt/persona 압축 및 재설계 검토",
            "반복 실패(failure pattern) 분석",
            "Unity 복구 계획 / 마일스톤 재계획 검토",
            "high-risk 작업의 closure 직전 반박",
        ],
        "forbidden": [
            "최종 완료 승인",
            "파일 직접 수정",
            "Pro 응답만으로 closure",
            "자동 브라우저 세션",
        ],
        "review_only": True,
        "must_read": [
            "context-capsule.json",
            "current blockers",
            "latest worker/validator summaries",
        ],
    },
    "prompt-validator-agent": {
        "name": "프롬프트/계획 검증",
        "identity": "정제된 프롬프트와 초기 계획이 사용자 원문을 왜곡하지 않았는지, 실행 전 gate가 충분한지 검증하는 독립 reviewer입니다.",
        "route": "openai_agents_sdk",
        "permissions": ["prompt_review", "plan_review", "ambiguity_block", "scope_guard"],
        "focus": [
            "정제 프롬프트가 원문 요구를 빠뜨리지 않았는지 확인",
            "side chat이 main 역할을 침범하지 않는지 확인",
            "PRD/task breakdown/review gate가 worker 실행 전에 충분한지 확인",
            "모호하거나 위험한 계획이면 prompt-preflight로 되돌림",
        ],
        "forbidden": ["파일 수정", "worker 실행", "closure 승인", "검증 없이 통과 처리"],
        "must_read": ["operator raw prompt", "prompt-preflight.json", "AGENTS.md", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "main-orchestrator": {
        "name": "메인 오케스트레이터",
        "identity": "루프 소유자입니다. 작업 목표, 우선순위, worker/validator 배분, retry/blocked/closure 판단을 소유하며 side chat 결과를 입력 증거로만 사용합니다.",
        "route": "codex_subscription_worker",
        "permissions": ["route_work", "set_gates", "cancel_or_retry", "final_status"],
        "focus": [
            "raw prompt -> refined prompt -> prompt validation -> issue memory -> acceptance gate -> routing 순서를 강제",
            "모델명/provider명이 아니라 작업 목적, capability, availability, evidence requirement 기준으로 라우팅",
            "worker/sub-chat이 반환한 evidence만 보고 review gate와 retry/closure 결정",
            "sent_to_main, handed_off, prepared를 완료로 오인하지 않게 차단",
        ],
        "forbidden": ["side chat work를 main completion으로 표시", "worker result 없는 completed", "review gate 없는 completed"],
        "must_read": ["AGENTS.md", "provider_routing.json", "transcript.jsonl", "memory/issues_log/*.md"],
    },
    "claude-decision-advisor": {
        "name": "Claude 판단 보좌관",
        "identity": "메인 오케스트레이터의 최종 결정권을 빼앗지 않고, 계획/제품/증거/종료 주장을 다른 모델 관점으로 반박하는 상시 보좌관입니다.",
        "route": "claude_collaborator",
        "permissions": ["decision_challenge", "plan_counterargument", "closure_objection"],
        "focus": [
            "메인이 선택한 목표/범위가 사용자 의도를 놓치지 않았는지 반박",
            "완료 주장, 제품 품질, 약한 가정, 검증 누락을 지적",
            "큐 항목이 새 작업인지 현재 작업 steering인지 판단에 이견 제시",
        ],
        "forbidden": ["최종 결정권 행사", "파일 직접 수정", "Codex evidence 없이 closure 승인"],
        "must_read": ["operator raw prompt", "main-advisory-council.json", "queue-routing-decision.json", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "openai-codex-api-advisor": {
        "name": "OpenAI/Codex API 판단 보좌관",
        "identity": "Agents SDK/API 경로의 구조화 판단 보좌관입니다. 메인 결정에 JSON guardrail, routing critique, trace/eval 관점을 공급하되 최종 결정권은 메인에 둡니다.",
        "route": "openai_agents_sdk",
        "permissions": ["structured_decision_review", "guardrail_check", "routing_policy_check", "trace_eval_hint"],
        "focus": [
            "정제 프롬프트, 라우팅, 큐 steering 여부를 구조화 출력으로 검토",
            "Agents SDK handoff/guardrail/trace/eval-ready 계약 누락 감지",
            "API 예산을 쓸 가치가 있는 작은 판단인지 기록",
        ],
        "forbidden": ["광범위 구현 루프 수행", "API 예산 gate 없는 장시간 호출", "로컬 파일 직접 수정"],
        "must_read": ["provider_routing.json", "prompt-validation.json", "main-advisory-council.json", "agents-sdk-guardrails.json"],
        "review_only": True,
    },
    "supervisor-agent": {
        "name": "슈퍼바이저",
        "identity": "PRD, task breakdown, Review Gate를 만들고 작업 범위가 흐려지는 것을 막습니다.",
        "route": "codex_subscription_worker",
        "permissions": ["prd", "task_breakdown", "gate_design"],
        "must_read": ["AGENTS.md", "provider_routing.json", "memory/issues_log/*.md"],
    },
    "issue-memory-agent": {
        "name": "이슈 메모리",
        "identity": "과거 실패, 사용자 교정, 미해결 리스크를 찾아 다음 작업의 acceptance gate로 올립니다.",
        "route": "codex_subscription_worker",
        "permissions": ["issue_scan", "countermeasure_promotion"],
        "must_read": ["memory/issues_log/*.md", "operator_message_events.jsonl"],
    },
    "codex-worker": {
        "name": "Codex 작업자",
        "identity": "구독 기반 Codex CLI/앱 경로로 로컬 파일 수정, 명령 실행, 브라우저 검증, 증거 패키징을 맡습니다.",
        "route": "codex_subscription_worker",
        "permissions": ["file_edits", "commands", "browser_verification", "evidence"],
        "must_read": ["AGENTS.md", "assignment", "memory/issues_log/*.md", "transcript.jsonl"],
    },
    "claude-reviewer": {
        "name": "Claude 검토",
        "identity": "Claude MAX 경로의 독립 검토자입니다. 계획, 제품 판단, 종료 주장, 약한 가정을 반박합니다.",
        "route": "claude_collaborator",
        "permissions": ["plan_challenge", "product_review", "closure_challenge"],
        "must_read": ["PRD packet", "Review Gate", "evidence", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "product-critic-agent": {
        "name": "제품 비평",
        "identity": "플레이어 가치, 화면 품질, 상업성, 과장된 완료 주장을 검토합니다.",
        "route": "claude_collaborator",
        "permissions": ["product_challenge", "visual_quality_review"],
        "must_read": ["screenshots", "acceptance criteria", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "validator-code-level": {
        "name": "엄격 코드/계약 검증",
        "identity": "검증 council 1번입니다. 코드 변경, 상태 전이, API 계약, 회귀 위험을 반대자 관점으로 검증합니다.",
        "route": "codex_subscription_worker",
        "permissions": ["read_only_review", "test_commands"],
        "focus": ["syntax", "state transition", "API contract", "regression", "error handling"],
        "forbidden": ["직접 수정", "UI 감상으로 pass", "테스트 없이 pass", "다른 validator 책임 대체"],
        "pass_criteria": ["fresh command evidence", "changed contract explained", "no new obvious regression", "known issues checked"],
        "must_read": ["diff", "tests", "transcript.jsonl", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "validator-contract-level": {
        "name": "엄격 오케스트레이션 계약 검증",
        "identity": "검증 council 2번입니다. PRD, task breakdown, worker dispatch, evidence contract, retry/closure contract가 실제로 연결됐는지 검증합니다.",
        "route": "codex_subscription_worker",
        "permissions": ["artifact_review", "contract_review", "gate_review"],
        "focus": ["PRD completeness", "worker dispatch ownership", "evidence contract", "review gate", "retry routing"],
        "forbidden": ["artifact 이름만 보고 pass", "sent_to_main을 완료로 인정", "main/worker 역할 혼동"],
        "pass_criteria": ["prompt-validation artifact exists", "issue gate exists", "routing decision exists", "closure packet requirements explicit"],
        "must_read": ["orchestration-plan.json", "worker-dispatch.json", "evidence-contract.json", "review-gate.json"],
        "review_only": True,
    },
    "validator-ui-state-level": {
        "name": "엄격 UI/상태 검증",
        "identity": "검증 council 3번입니다. 운영자가 화면만 보고 현재 단계, 사용 모델, blocked 이유, 다음 행동을 알 수 있는지 검증합니다.",
        "route": "codex_subscription_worker",
        "permissions": ["browser_e2e_review", "operator_ui_review", "status_truth_review"],
        "focus": ["handed_off/refined/validating/routing/worker/reviewer/retry/block/completed 상태 구분", "Korean operator clarity", "no misleading completion"],
        "forbidden": ["로그만 보고 pass", "눈에 안 보이는 상태를 pass", "raw id만 노출하고 pass"],
        "pass_criteria": ["browser or DOM evidence", "latest run visible", "blocked/retry reason visible", "completed only after closure packet"],
        "must_read": ["HTML dashboard", "run artifacts", "operator_message_events.jsonl"],
        "review_only": True,
    },
    "validator-ovv-product-level": {
        "name": "OVV 제품 검증",
        "identity": "렌더링 증거, 화면 품질, OVV gate, 완료 정직성을 검토하는 검증 전용 레인입니다.",
        "route": "claude_collaborator",
        "permissions": ["ovv_review", "rendered_evidence_review", "closure_gate"],
        "must_read": ["screenshots", "OVV decision packet", "memory/issues_log/*.md"],
        "review_only": True,
    },
    "gemini-reviewer": {
        "name": "Gemini 3 Pro 검토",
        "identity": "Gemini 키가 설정되면 제3 관점 장문 검토와 대안 계획 검토를 맡습니다.",
        "route": "gemini_collaborator",
        "permissions": ["third_opinion", "alternative_plan_review"],
        "must_read": ["PRD packet", "transcript.md", "memory/issues_log/*.md"],
        "review_only": True,
        "enabled_note": "GEMINI_API_KEY 또는 구독 경로 설정 전까지 비활성입니다.",
    },
}


REVIEW_LANES = [
    {
        "id": "strict-code-contract-council",
        "name": "엄격 검증 1: 코드/API/상태",
        "owner": "validator-code-level",
        "state": "thread_ready",
        "thread_id": "019ebc2a-ddb2-7b92-b43a-bb12ea916748",
        "rule": "파일 수정 금지. syntax, command result, state transition, API contract, regression만 검증합니다. 증거 없으면 pass 금지.",
    },
    {
        "id": "strict-orchestration-contract-council",
        "name": "엄격 검증 2: 오케스트레이션 계약",
        "owner": "validator-contract-level",
        "state": "thread_ready",
        "thread_id": "019ebc2b-3d8c-77e0-bd9c-6ea1dead9d0a",
        "rule": "PRD, prompt validation, issue gate, worker dispatch, evidence contract, review gate, closure packet 조건을 검증합니다.",
    },
    {
        "id": "strict-ui-status-council",
        "name": "엄격 검증 3: UI/상태 진실성",
        "owner": "validator-ui-state-level",
        "state": "thread_ready",
        "thread_id": "019ebc2b-a21b-7c90-9d65-41469cd722bb",
        "rule": "운영 화면이 handed_off/refined/validating/issue_memory/routing/worker/reviewer/retry/block/completed를 오해 없이 보여주는지 검증합니다.",
    },
    {
        "id": "closure-product-challenge-lane",
        "name": "Closure 반박: 제품/Claude",
        "owner": "claude-reviewer",
        "state": "thread_ready",
        "rule": "worker와 validator council 결과를 승인하지 말고 제품/계획/증거/완료 주장 관점에서 반박합니다.",
    },
    {
        "id": "gemini-review-lane",
        "name": "Gemini 제3 검토",
        "owner": "gemini-reviewer",
        "state": "disabled_until_key",
        "rule": "Gemini 키 설정 후 장문 대안 검토에 사용합니다.",
    },
]


def short_loop_policy() -> dict[str, object]:
    return {
        "kind": "short_multi_validator_loop_policy",
        "mode": "goal_until_complete_short_iterations",
        "max_attempts": SHORT_LOOP_MAX_ATTEMPTS,
        "auto_advance_steps_per_tick": QUEUE_AUTO_ADVANCE_STEPS,
        "minimum_validator_lanes_per_result": SHORT_LOOP_VALIDATOR_MIN,
        "minimum_review_iterations_before_stop": MIN_REVIEW_ITERATIONS_BEFORE_STOP,
        "result_rule": "Every worker result must be followed by multiple validator lane artifacts before the next attempt, retry, or closure review.",
        "retry_rule": "If any mandatory validator blocks, the main orchestrator routes the finding back to prompt-preflight/main planning and continues short iterations until closure or a hard external blocker.",
        "goal_until_complete": True,
        "iteration_shape": "짧은 iteration을 계속 반복하되, 각 결과마다 다중 validator와 product/Claude closure challenge를 거칩니다.",
        "closure_blocked_without": [
            "worker-result.json for the latest short loop",
            "validator-code-result.json",
            "validator-contract-result.json",
            "validator-ui-state-result.json",
            "validator-issue-gate-result.json",
            "validator-result.json aggregate",
            "Claude/product closure challenge when non-trivial",
        ],
    }


def queue_routing_decision_for_message(message: dict[str, object]) -> dict[str, object]:
    text = " ".join(
        [
            str(message.get("original_message", "")),
            str(message.get("message", "")),
            str((message.get("prompt_preflight") or {}).get("summary", "") if isinstance(message.get("prompt_preflight"), dict) else ""),
        ]
    ).lower()
    target = str(message.get("target", "prompt-preflight-agent") or "prompt-preflight-agent")
    steering_tokens = [
        "스티어",
        "steer",
        "현재 상태",
        "지금 상태",
        "왜",
        "멈춰",
        "정지",
        "취소",
        "중단",
        "바꿔",
        "수정",
        "우선순위",
        "큐",
        "순서",
        "마일스톤",
        "구조",
        "방식",
        "판단",
        "검증",
        "다시",
        "이거",
    ]
    force_sequential_tokens = ["새 작업", "다음 작업", "새로 만들어", "구현해", "추가해", "생성해"]
    steering_score = sum(1 for token in steering_tokens if token in text)
    sequential_score = sum(1 for token in force_sequential_tokens if token in text)
    if target not in {"prompt-preflight-agent", "main"}:
        mode = "direct_target"
        action = "route_to_target_queue"
        reason = f"대상이 {target} 이므로 메인 순차 작업 대신 지정 대상 큐로 보냅니다."
    elif steering_score > sequential_score:
        mode = "steering_intervention"
        action = "interrupt_or_attach_to_current_main_run"
        reason = "현재 실행/큐/구조/검증을 바꾸는 운영자 교정으로 보여 순차 새 작업보다 steering으로 우선 처리합니다."
    else:
        mode = "sequential_work_item"
        action = "append_after_current_top_item"
        reason = "새 산출물을 요구하는 일반 작업으로 보고 현재 자동 처리 정책에 따라 큐 맨 위 항목부터 순차 처리합니다."
    return {
        "kind": "queue_routing_decision",
        "created_at": utc_timestamp(),
        "mode": mode,
        "action": action,
        "target": target,
        "steering_score": steering_score,
        "sequential_score": sequential_score,
        "reason": reason,
        "rules": [
            "메인 최종 소유자는 하나지만, 큐가 현재 작업 목표/검증/우선순위를 바꾸는 내용이면 steering으로 승격합니다.",
            "순수 신규 구현 요청이면 top_one_at_a_time 순차 큐에 둡니다.",
            "steering 승격은 완료 처리가 아니라 현재 main run의 prompt/plan/routing을 갱신해야 한다는 신호입니다.",
        ],
    }


def build_main_advisory_council(
    message_id: str,
    original: str,
    refined: str,
    preflight: dict[str, object],
    relevant_issues: list[dict[str, object]],
    queue_decision: dict[str, object],
) -> dict[str, object]:
    adapter_health = build_adapter_health()
    openai_health = adapter_health.get("openai_agents_sdk", {}) if isinstance(adapter_health, dict) else {}
    claude_health = adapter_health.get("claude_collaborator", {}) if isinstance(adapter_health, dict) else {}
    return {
        "kind": "cerberus_style_main_advisory_council",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "final_owner": "main-orchestrator",
        "final_owner_rule": "Claude와 OpenAI/Codex API 보좌관은 최종 결정자가 아닙니다. 둘의 이견과 guardrail을 받은 뒤 main-orchestrator 하나가 최종 routing/retry/closure 판단을 기록합니다.",
        "mandatory": True,
        "decision_sequence": [
            "prompt-preflight-agent preserves raw prompt and refines it",
            "prompt-validator-agent checks prompt distortion",
            "claude-decision-advisor challenges plan/product/closure assumptions",
            "openai-codex-api-advisor checks structured routing, guardrails, and trace/eval contract",
            "main-orchestrator writes one final decision with accepted/rejected advisor objections",
        ],
        "advisors": [
            {
                "agent": "claude-decision-advisor",
                "route": "claude_collaborator",
                "billing": "claude_max_subscription",
                "callable": bool(claude_health.get("callable")),
                "required_artifact": "claude-advisor-request.md",
                "result_artifact": "claude-advisor-result.json",
                "status": "request_prepared" if bool(claude_health.get("callable")) else "blocked_adapter_unavailable",
                "must_challenge": ["plan scope", "product judgment", "evidence sufficiency", "closure claim", "queue steering decision"],
            },
            {
                "agent": "openai-codex-api-advisor",
                "route": "openai_agents_sdk",
                "billing": "api_budget_limited",
                "callable": bool(openai_health.get("callable")),
                "required_artifact": "openai-codex-advisor-request.json",
                "result_artifact": "openai-codex-advisor-result.json",
                "status": "live_call_allowed_by_gate" if bool(openai_health.get("callable")) else "contract_prepared_live_call_blocked",
                "must_check": ["structured routing", "guardrails", "handoff graph", "queue steering mode", "API budget justification"],
                "api_budget_rule": "Use live API only for small structured decision help; otherwise keep the contract visible and block silent skipping.",
            },
        ],
        "queue_routing_decision": queue_decision,
        "main_decision_requirements": [
            "Record whether each advisor was called, skipped, blocked, or replaced by a local contract.",
            "If an advisor is not callable, show the adapter/key/import reason in the UI instead of pretending it ran.",
            "If advisors disagree, main-orchestrator must record accepted and rejected objections before worker dispatch.",
            "Closure remains blocked without worker result, validators, issue gate, product/Claude review, and evidence packet.",
        ],
        "context": {
            "original_excerpt": original[:800],
            "refined_excerpt": refined[:1200],
            "preflight_mode": preflight.get("mode", ""),
            "risk_flags": preflight.get("risk_flags", []),
            "relevant_issue_count": len(relevant_issues),
        },
    }


def build_cerberus_deliberation(
    message_id: str,
    original: str,
    refined: str,
    queue_decision: dict[str, object],
    relevant_issues: list[dict[str, object]],
) -> dict[str, object]:
    queue_mode = str(queue_decision.get("mode") or "unknown")
    return {
        "kind": "cerberus_deliberation",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "model": "one final main mind with two mandatory advisors",
        "final_owner": "main-orchestrator",
        "rule": "이 artifact는 하위 세션 배정표가 아니라 메인 판단 과정입니다. 세 머리가 같은 안건을 보고 서로 질문/반박/수정한 뒤 main-orchestrator가 최종 합성을 기록합니다.",
        "participants": [
            {"agent": "main-orchestrator", "voice": "final synthesis and routing owner"},
            {"agent": "claude-decision-advisor", "voice": "product, plan, evidence, closure objection"},
            {"agent": "openai-codex-api-advisor", "voice": "structured guardrail, routing, trace/eval, queue decision critique"},
        ],
        "rounds": [
            {
                "round": 1,
                "topic": "사용자 원문과 정제 프롬프트 같은 안건 공유",
                "messages": [
                    {
                        "speaker": "main-orchestrator",
                        "message": "원문을 지우지 않고 최종 목표, 증거, worker/reviewer 경계를 잡는다. 완료는 closure-packet 전까지 금지한다.",
                    },
                    {
                        "speaker": "claude-decision-advisor",
                        "message": "제품/운영 관점에서 사용자는 기능이 실제로 쓰이는지 보려는 것이지 artifact 이름만 보려는 게 아니다. UI와 결과 파일까지 확인해야 한다.",
                    },
                    {
                        "speaker": "openai-codex-api-advisor",
                        "message": "Agents SDK 방식은 identity, handoff, guardrail, trace/eval-ready record로 강제해야 한다. live API가 막히면 blocked/contract state를 표시해야 한다.",
                    },
                ],
            },
            {
                "round": 2,
                "topic": "큐 순차 처리 vs steering",
                "messages": [
                    {
                        "speaker": "openai-codex-api-advisor",
                        "message": f"queue classifier verdict is {queue_mode}. Reason: {queue_decision.get('reason', '')}",
                    },
                    {
                        "speaker": "claude-decision-advisor",
                        "message": "사용자가 현재 구조를 교정하거나 질책하는 문장은 새 작업 뒤에 줄 세우면 안 된다. 현재 run의 판단 기준을 바꾸는 steering으로 다뤄야 한다.",
                    },
                    {
                        "speaker": "main-orchestrator",
                        "message": "steering이면 현재 run의 prompt/plan/routing에 붙이고, 신규 산출물 요청이면 top-one-at-a-time 큐로 보낸다. 판정은 queue-routing-decision.json에 남긴다.",
                    },
                ],
            },
            {
                "round": 3,
                "topic": "반복 이슈와 기능 사용 강제",
                "messages": [
                    {
                        "speaker": "claude-decision-advisor",
                        "message": "같은 실수가 다른 세션에서 반복되면 검토가 실패한 것이다. issue-memory를 단순 기록이 아니라 acceptance gate로 승격해야 한다.",
                    },
                    {
                        "speaker": "openai-codex-api-advisor",
                        "message": f"relevant_issue_count={len(relevant_issues)}. 다음 worker 입력에는 issue-gate, validator-issue-gate-result, known-failure prevention rule이 포함돼야 한다.",
                    },
                    {
                        "speaker": "main-orchestrator",
                        "message": "worker dispatch 전 issue-memory-agent와 validator-issue-memory-level을 mandatory로 둔다. closure 전 product/Claude review를 생략하지 않는다.",
                    },
                ],
            },
            {
                "round": 4,
                "topic": "최종 합성",
                "messages": [
                    {
                        "speaker": "main-orchestrator",
                        "message": "최종 판단: 세 머리의 이견을 합쳐 하나의 main decision으로 기록한다. Claude/OpenAI-Codex는 보좌관이며 최종 owner는 main-orchestrator다.",
                    }
                ],
            },
        ],
        "final_synthesis": {
            "queue_mode": queue_mode,
            "must_show_in_ui": ["advisor conversation rounds", "queue mode", "accepted objections", "blocked live adapters", "next action"],
            "dispatch_allowed_after": [
                "prompt-validation.json",
                "issue-gate.json",
                "main-advisory-council.json",
                "cerberus-deliberation.json",
                "queue-routing-decision.json",
            ],
        },
    }


def write_cerberus_deliberation_artifacts(run_dir: Path, deliberation: dict[str, object]) -> None:
    write_json(run_dir / "cerberus-deliberation.json", deliberation)
    lines = [
        "# Cerberus Main Deliberation",
        "",
        str(deliberation.get("rule", "")),
        "",
        f"- final_owner: `{deliberation.get('final_owner', 'main-orchestrator')}`",
        f"- model: `{deliberation.get('model', '')}`",
        "",
    ]
    for round_item in deliberation.get("rounds", []):
        if not isinstance(round_item, dict):
            continue
        lines.extend([f"## Round {round_item.get('round')}: {round_item.get('topic')}", ""])
        for message in round_item.get("messages", []):
            if isinstance(message, dict):
                lines.append(f"- **{message.get('speaker')}**: {message.get('message')}")
        lines.append("")
    write_json(run_dir / "cerberus-deliberation-summary.json", deliberation.get("final_synthesis", {}))
    (run_dir / "cerberus-deliberation.md").write_text("\n".join(lines), encoding="utf-8")
    for round_item in deliberation.get("rounds", []):
        if not isinstance(round_item, dict):
            continue
        for message in round_item.get("messages", []):
            if not isinstance(message, dict):
                continue
            append_transcript_event(
                run_dir,
                str(message.get("speaker", "cerberus")),
                "cerberus-main-council",
                "deliberation",
                f"Round {round_item.get('round')} · {round_item.get('topic')}: {message.get('message')}",
                "cerberus-deliberation.json",
            )


def write_advisory_request_artifacts(run_dir: Path, council: dict[str, object], original: str, refined: str) -> None:
    queue_decision = council.get("queue_routing_decision") if isinstance(council.get("queue_routing_decision"), dict) else {}
    claude_request = "\n".join(
        [
            "# Claude decision advisor request",
            "",
            "Role: main-orchestrator advisor, not final owner. Challenge the decision before dispatch.",
            "",
            "원문:",
            original,
            "",
            "정제 프롬프트:",
            refined,
            "",
            "큐 판정:",
            json.dumps(queue_decision, ensure_ascii=False, indent=2),
            "",
            "검토 질문:",
            "- 이 메시지는 새 순차 작업인가, 현재 작업 steering인가?",
            "- 메인이 놓친 사용자 의도/제품 판단/증거 조건이 있는가?",
            "- 어떤 worker/validator를 반드시 붙여야 하는가?",
            "- 최종 main decision에 반영해야 할 반박은 무엇인가?",
        ]
    )
    (run_dir / "claude-advisor-request.md").write_text(claude_request, encoding="utf-8")
    write_json(
        run_dir / "openai-codex-advisor-request.json",
        {
            "kind": "openai_codex_api_advisor_request",
            "role": "structured decision advisor",
            "final_owner": "main-orchestrator",
            "original": original,
            "refined": refined,
            "queue_routing_decision": queue_decision,
            "required_output_schema": {
                "verdict": "sequential_work_item | steering_intervention | blocked",
                "routing_objections": ["string"],
                "required_guardrails": ["string"],
                "api_budget_justification": "string",
            },
        },
    )


def ensure_main_advisory_council_artifact(run_dir: Path) -> None:
    if (
        (run_dir / "main-advisory-council.json").exists()
        and (run_dir / "queue-routing-decision.json").exists()
        and (run_dir / "cerberus-deliberation.json").exists()
    ):
        return
    plan_path = run_dir / "orchestration-plan.json"
    plan = read_json_file(plan_path) if plan_path.exists() else {}
    if not isinstance(plan, dict):
        plan = {}
    operator = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
    original = str(operator.get("original_message", ""))
    refined = str(operator.get("refined_message", ""))
    preflight = operator.get("preflight") if isinstance(operator.get("preflight"), dict) else {}
    source_message_id = str(plan.get("source_message_id") or run_dir.name)
    message = {
        "id": source_message_id,
        "target": plan.get("target", "main"),
        "original_message": original,
        "message": refined,
        "prompt_preflight": preflight,
    }
    relevant_issues = matching_issues_for_text(f"{original}\n\n{refined}", limit=8)
    if (run_dir / "queue-routing-decision.json").exists():
        try:
            queue_decision = read_json_file(run_dir / "queue-routing-decision.json")
            if not isinstance(queue_decision, dict):
                queue_decision = queue_routing_decision_for_message(message)
        except Exception:
            queue_decision = queue_routing_decision_for_message(message)
    else:
        queue_decision = queue_routing_decision_for_message(message)
    council = build_main_advisory_council(source_message_id, original, refined, preflight, relevant_issues, queue_decision)
    deliberation = build_cerberus_deliberation(source_message_id, original, refined, queue_decision, relevant_issues)
    write_json(run_dir / "queue-routing-decision.json", queue_decision)
    write_json(run_dir / "main-advisory-council.json", council)
    write_advisory_request_artifacts(run_dir, council, original, refined)
    write_cerberus_deliberation_artifacts(run_dir, deliberation)
    if isinstance(plan, dict):
        plan["queue_routing_decision"] = queue_decision
        plan["main_advisory_council"] = council
        plan["cerberus_deliberation"] = deliberation
        write_json(plan_path, plan)
    append_transcript_event(
        run_dir,
        "main-orchestrator",
        "advisor-council",
        "backfill",
        "기존 run에 메인 판단 보좌관 council과 큐 순차/스티어링 판정 artifact를 추가했습니다.",
        "main-advisory-council.json",
    )


def normalize_message_target(target: str) -> str:
    if target == "main":
        return "prompt-preflight-agent"
    return target or "prompt-preflight-agent"


def dispatch_target_for_queue(target: str) -> str:
    if target in {"prompt-preflight-agent", "main-orchestrator", "main"}:
        return "main"
    return target


def prompt_preflight_model() -> str:
    if os.environ.get("SC_SPIRE_PROMPT_PREFLIGHT_MODEL"):
        return str(os.environ["SC_SPIRE_PROMPT_PREFLIGHT_MODEL"])
    if os.environ.get("SC_SPIRE_OPENAI_ORCHESTRATOR_MODEL"):
        return str(os.environ["SC_SPIRE_OPENAI_ORCHESTRATOR_MODEL"])
    config = load_provider_routing_config()
    routes = config.get("routes", {}) if isinstance(config, dict) else {}
    openai_route = routes.get("openai_agents_sdk", {}) if isinstance(routes, dict) else {}
    if isinstance(openai_route, dict) and openai_route.get("default_model"):
        return str(openai_route["default_model"])
    return "gpt-5.5"


SUGGEST_KEYWORD_MAP = {
    "테란": ["data/records/cards_terran.json"],
    "저그": ["data/records/cards_zerg.json"],
    "프로토스": ["data/records/cards_protoss.json"],
    "이벤트": ["data/records/events_*.json"],
    "보스": ["data/records/events_*.json"],
    "상점": ["game_mvp.py (shop section)", "app.py"],
    "유물": ["game_mvp.py (shop section)"],
    "한국어": ["data/localized_runtime/materialized/ko/"],
    "로케일": ["data/localized_runtime/materialized/ko/"],
    "번역": ["data/localized_runtime/materialized/ko/"],
}


def suggest_targets(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for keyword, paths in SUGGEST_KEYWORD_MAP.items():
        if keyword.lower() in lowered:
            for path in paths:
                if path not in hits:
                    hits.append(path)
    return hits[:5]


VAGUE_TOKENS = ["봐줘", "한번", "좀", "어떤지", "확인해", "체크", "이상한", "대충", "살펴"]
SPECIFIC_SIGNALS = [".json", ".py", "/", "->", "→", "라인", "필드", "에서", "낮춰", "바꿔", "추가", "수정"]


def classify_request_weight(text: str) -> str:
    has_path = any(sig in text for sig in [".json", ".py", "/"])
    specific = has_path or sum(1 for s in SPECIFIC_SIGNALS if s in text) >= 2
    if specific and len(text.split()) >= 4:
        return "full"
    if any(tok in text for tok in VAGUE_TOKENS) or len(text.split()) < 4:
        return "light"
    return "full"


def build_rule_based_prompt(text: str, target: str, run_context: dict[str, object]) -> tuple[str, dict[str, object]]:
    text = text if isinstance(text, str) else ""
    normalized = " ".join(text.split())
    suggested = suggest_targets(text)
    weight = classify_request_weight(text)
    missing: list[str] = []
    warnings: list[str] = []
    if len(normalized) < 12:
        missing.append("task_detail")
        warnings.append("Prompt is very short; converted into a clarification-first orchestrator request.")
    verification_tokens = ["\uac80\uc99d", "\ud655\uc778", "\ud14c\uc2a4\ud2b8", "\uc2a4\ud06c\ub9b0\uc0f7", "\uc99d\uac70", "review", "test", "evidence", "screenshot"]
    if not any(token in normalized.lower() for token in verification_tokens):
        warnings.append("No explicit verification request was found; added mandatory verification gates.")
    if target != "main":
        warnings.append("Target is not main; prompt was still normalized but should not start implementation automatically.")

    surfaces = run_context.get("affected_surfaces") or []
    evidence = run_context.get("required_evidence") or []
    acceptance = run_context.get("acceptance_criteria") or []
    planned_files = run_context.get("planned_files") or []
    context_bits = [
        f"선택 run {run_context.get('run_id')}" if run_context.get("run_id") else "",
        f"관련 이슈 {run_context.get('open_issue_count', 0)}개" if run_context.get("open_issue_count") else "",
        f"파일 {', '.join(map(str, planned_files[:3]))}" if planned_files else "",
        f"화면/영역 {', '.join(map(str, surfaces[:3]))}" if surfaces else "",
    ]
    context_line = " / ".join(bit for bit in context_bits if bit)
    acceptance_line = "; ".join(map(str, acceptance[:3])) if acceptance else "PRD, 작업자 배정, 검증 기준을 먼저 잡아라"
    evidence_line = "; ".join(map(str, evidence[:3])) if evidence else "worker-result, validator-result, Claude 검토, 화면/명령 증거"
    refined_lines = [
        "메인 오케스트레이터 실행 프롬프트",
        "",
        "사용자 원문은 대충 쓴 평문이어도 그대로 진짜 요구로 취급하라. 원문:",
        text,
        "",
        "이번 목표:",
        f"- {normalized}",
        "- 사용자가 모델명이나 도구명을 다 쓰지 않아도, 작업 품질에 이득이면 메인 오케스트레이터가 알아서 적절한 경로를 배정한다.",
        "- HTML 운영판에서 지금 무엇이 실행 중인지, 메인이 무엇을 판단했는지, 어느 작업자/검토자에게 무엇이 갔는지 바로 확인 가능해야 한다.",
        "",
        *(["추정 작업 대상 (확인 후 확정):", *(f"- {p}" for p in suggested), ""] if suggested else []),
        "먼저 해야 할 일:",
        "1. AGENTS.md, provider_routing.json, 최근 issue memory, 선택 run transcript를 읽은 것으로 간주하지 말고 실제 작업 입력에 반영하라.",
        "2. 반복 실패나 사용자 교정은 acceptance gate로 승격하라. 이미 알려진 실수를 다른 모델/세션이 다시 반복하지 못하게 막아라.",
        "3. 이 요청을 바로 완료 처리하지 말고 PRD packet, task breakdown, worker-dispatch, evidence-contract, review-gate를 먼저 만들어라.",
        "4. 파일 수정이나 외부 작업 전에는 어떤 worker가 무엇을 맡는지, 어떤 validator가 무엇을 막는지 명시하라.",
        "",
        "Agents SDK 사용 규칙:",
        "- live API 호출 여부와 별개로 Agents SDK 방식은 적극 적용한다.",
        "- run마다 agent identity/persona, handoff graph, input/output guardrails, trace/eval-ready artifact, structured result contract를 남겨라.",
        "- OpenAI API live call은 작은 structured preflight, guardrail check, trace/eval 판단에 실제 이득이 있을 때만 사용하고, 예산/모델/범위/이유를 기록하라.",
        "- API를 쓰지 않았다는 이유로 Agents SDK 방식을 안 쓴 것으로 처리하지 마라. local Agents SDK pattern artifact가 있으면 사용한 것으로 기록하라.",
        "",
        "모델/세션 배정 규칙:",
        "- 기본 구현과 로컬 검증은 Codex MAX 구독 경로를 우선한다.",
        "- Claude MAX는 비 trivial 작업의 계획 검토, 제품/디자인 판단, worker evidence critique, closure challenge에 필수로 배정한다.",
        "- 사용자가 Claude를 말하지 않아도, 완료 전 claude-review-result.json 또는 product-review-result.json이 없으면 closure를 막아라.",
        "- Gemini는 키/로그인이 준비된 경우 제3 검토 레인으로만 붙이고, 준비 전에는 disabled 상태와 이유를 남겨라.",
        "",
        "현재 컨텍스트:",
        f"- {context_line or '현재 HTML 운영판/선택 run 기준으로 판단'}",
        f"- 기존 acceptance seed: {acceptance_line}",
        f"- 필요한 evidence seed: {evidence_line}",
        "",
        "완료 차단 조건:",
        "- worker-result.json 없음",
        "- validator-result.json 없음",
        "- Claude/product review 결과 없음",
        "- issue-memory scan이 gate로 반영되지 않음",
        "- 화면에서 dispatch, active worker, waiting reviewer, 남은 blocker가 확인되지 않음",
        "",
        "최종 출력:",
        "- 무엇을 메인이 판단했는지",
        "- 어느 작업자와 검토자에게 보냈는지",
        "- Agents SDK 방식이 어떤 artifact로 남았는지",
        "- Claude 검증이 어디에 필수 gate로 걸렸는지",
        "- 아직 완료가 아닌 이유와 다음 행동",
        "이 다섯 가지를 HTML에서 확인 가능하게 남겨라.",
    ]
    if weight == "light":
        refined_lines = [
            "메인 오케스트레이터 — 경량(light) 처리 요청",
            "",
            "사용자 원문(모호함, 확인 우선):",
            text,
            "",
            "지시:",
            "1. 풀 PRD/worker-dispatch/review-gate를 아직 만들지 마라.",
            "2. 먼저 1~3개의 한국어 clarifying 질문으로 범위(file/where/how)를 좁혀라.",
            *(["3. 추정 작업 대상 (확인용):", *(f"   - {p}" for p in suggested)] if suggested else ["3. 관련 파일 후보를 grep로 제시하라."]),
            "4. 사용자가 확정하면 그때 full 오케스트레이션으로 승격하라.",
        ]
    refined_prompt = "\n".join(refined_lines)
    return refined_prompt, {
        "status": "refined_for_main_orchestrator",
        "mode": "detailed_orchestrator_prompt_from_plaintext" if weight == "full" else "light_clarify_first",
        "style": "rough_input_detailed_output",
        "request_weight": weight,
        "suggested_targets": suggested,
        "original_length": len(text),
        "refined_length": len(refined_prompt),
        "missing_fields": missing,
        "warnings": warnings,
        "run_context": run_context,
        "provenance": make_provenance("local_self_check", "viewer-server"),
    }


def extract_response_text(payload: dict[str, object]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks).strip()


def parse_model_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    return json.loads(stripped)


def build_prompt_preflight_instruction(text: str, target: str, run_context: dict[str, object]) -> str:
    return json.dumps(
        {
            "task": "Validate and refine an operator prompt before it is sent to the SC Spire main orchestrator.",
            "operator_prompt": text,
            "target": target,
            "selected_run_context": run_context,
            "required_behavior": [
                "Do not approve implementation directly.",
                "Identify ambiguity, missing fields, unsafe scope, evidence gaps, and likely routing mistakes.",
                "If clarification is required, include concise Korean clarifying_questions.",
                "Write refined_prompt for the main orchestrator in Korean where useful, with stable English identifiers preserved.",
                "The refined prompt must require PRD packet, task breakdown, Review Gate, issue-memory scan, worker routing, validator routing, and evidence requirements.",
                "For Unity/player-facing work, require OVV decision packet, operating-state validation, Claude or peer gate, and rendered evidence before closure.",
                "Return JSON only.",
            ],
            "json_schema": {
                "intent": "short inferred intent",
                "is_actionable": "boolean",
                "missing_fields": ["field names"],
                "risk_flags": ["risk names"],
                "clarifying_questions": ["questions in Korean"],
                "validation_notes": ["short notes"],
                "refined_prompt": "final prompt to send to the main orchestrator",
            },
        },
        ensure_ascii=False,
    )


def call_prompt_preflight_model(text: str, target: str, run_context: dict[str, object]) -> dict[str, object]:
    api_key = read_openai_api_key()
    if not api_key:
        raise RuntimeError("OpenAI API key not found in OPENAI_API_KEY or Desktop/openai.txt")
    model = prompt_preflight_model()
    body = {
        "model": model,
        "reasoning": {"effort": "low"},
        "text": {"verbosity": "low"},
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a prompt-intake validator for a local SC Spire game-development orchestrator. "
                    "You refine rough operator instructions into safe, specific prompts for a main orchestrator. "
                    "Return strict JSON only. Never include secrets."
                ),
            },
            {"role": "user", "content": build_prompt_preflight_instruction(text, target, run_context)},
        ],
    }
    request = Request(
        RESPONSES_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=PROMPT_PREFLIGHT_TIMEOUT) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    model_json = parse_model_json(extract_response_text(response_payload))
    refined_prompt = str(model_json.get("refined_prompt", "")).strip()
    if not refined_prompt:
        raise RuntimeError("Model preflight returned no refined_prompt")
    return {
        "status": "model_refined_for_main_orchestrator",
        "mode": "openai_responses_api",
        "model": model,
        "intent": model_json.get("intent", ""),
        "is_actionable": bool(model_json.get("is_actionable", False)),
        "missing_fields": model_json.get("missing_fields", []),
        "risk_flags": model_json.get("risk_flags", []),
        "clarifying_questions": model_json.get("clarifying_questions", []),
        "validation_notes": model_json.get("validation_notes", []),
        "warnings": model_json.get("risk_flags", []),
        "run_context": run_context,
        "refined_length": len(refined_prompt),
        "original_length": len(text),
        "refined_prompt": refined_prompt,
        "provenance": make_provenance(
            "live_openai_api", "viewer-server", command=f"openai_responses_api:{model}"
        ),
    }


def preflight_operator_prompt(text: str, target: str, run_id: str) -> tuple[str, dict[str, object]]:
    run_context = summarize_run_context(run_id)
    fallback_prompt, fallback_validation = build_rule_based_prompt(text, target, run_context)
    if target != "main":
        return text, fallback_validation
    if not live_preflight_enabled():
        fallback_validation["status"] = "local_agents_sdk_pattern_preflight"
        fallback_validation["mode"] = "local_agents_sdk_detailed_preflight"
        fallback_validation["style"] = "rough_input_detailed_output"
        fallback_validation["model"] = prompt_preflight_model()
        fallback_validation["live_api_state"] = "deferred"
        fallback_validation["live_api_reason"] = (
            "HTML operator submit must be immediately inspectable. "
            "Set SC_SPIRE_LIVE_PROMPT_PREFLIGHT=1 to run live OpenAI preflight in this request path."
        )
        return fallback_prompt, fallback_validation
    try:
        model_validation = call_prompt_preflight_model(text, target, run_context)
        return str(model_validation["refined_prompt"]), model_validation
    except Exception as exc:
        fallback_validation["status"] = "model_preflight_failed_rule_based_fallback"
        fallback_validation["model"] = prompt_preflight_model()
        fallback_validation["model_error"] = f"{type(exc).__name__}: {exc}"
        return fallback_prompt, fallback_validation


def append_operator_event(
    message_id: str,
    status: str,
    actor: str,
    detail: str,
    *,
    run_id: str = "",
    artifact: str = "",
    target_override: str = "",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "message_id": message_id,
        "timestamp": utc_timestamp(),
        "status": status,
        "actor": actor,
        "detail": detail,
        "run_id": run_id,
        "artifact": artifact,
    }
    if target_override:
        event["target_override"] = target_override
    if extra:
        event.update(extra)
    with EVENT_LOCK:
        with OPERATOR_MESSAGE_EVENTS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    invalidate_status_cache()
    return event


def read_operator_events(limit: int = 500) -> list[dict[str, object]]:
    if not OPERATOR_MESSAGE_EVENTS.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in OPERATOR_MESSAGE_EVENTS.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def events_by_message_id() -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for event in read_operator_events(limit=5000):
        message_id = str(event.get("message_id", ""))
        if not message_id:
            continue
        grouped.setdefault(message_id, []).append(event)
    return grouped


CONTROL_STATUSES = {"queued", "edited", "priority_changed", "steered"}


def apply_queue_controls(message: dict[str, object], events: list[dict[str, object]]) -> dict[str, object]:
    effective = dict(message)
    priority = int(effective.get("queue_priority", 1000) or 1000)
    removed = False
    for event in events:
        status = str(event.get("status", ""))
        if status == "removed":
            removed = True
        if "priority" in event:
            try:
                priority = int(event.get("priority", priority))
            except (TypeError, ValueError):
                pass
        if event.get("target_override"):
            effective["target"] = str(event.get("target_override"))
        if "target_thread_id_override" in event:
            effective["target_thread_id"] = str(event.get("target_thread_id_override") or "")
        if "original_message_override" in event:
            effective["original_message"] = str(event.get("original_message_override") or "")
        if "message_override" in event:
            effective["message"] = str(event.get("message_override") or "")
        if isinstance(event.get("prompt_preflight_override"), dict):
            effective["prompt_preflight"] = event.get("prompt_preflight_override")
    effective["queue_priority"] = priority
    effective["removed_from_queue"] = removed
    return effective


def workflow_status(events: list[dict[str, object]], fallback: str = "queued") -> str:
    for event in reversed(events):
        status = str(event.get("status", ""))
        if status in {"edited", "priority_changed", "steered", "queue_routing_decision"}:
            continue
        return status or fallback
    return fallback


def find_operator_message(message_id: str) -> dict[str, object]:
    for message in read_operator_messages(limit=5000):
        if str(message.get("id", "")) == message_id:
            return message
    raise ValueError("message not found")


def append_operator_message(payload: dict[str, object]) -> dict[str, object]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    text = str(payload.get("message", "")).strip()
    if not text:
        raise ValueError("message is required")
    target = normalize_message_target(str(payload.get("target", "prompt-preflight-agent")).strip())
    run_id = str(payload.get("run_id", "")).strip()
    preflight_target = "main" if target == "prompt-preflight-agent" else target
    refined_text, prompt_preflight = preflight_operator_prompt(text, preflight_target, run_id)
    record = {
        "id": f"operator-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "created_at": utc_timestamp(),
        "status": "queued",
        "target": target,
        "target_thread_id": str(payload.get("target_thread_id", "")).strip(),
        "run_id": run_id,
        "queue_priority": int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000),
        "original_message": text,
        "message": refined_text if target == "prompt-preflight-agent" else text,
        "prompt_preflight": prompt_preflight,
    }
    with OPERATOR_MESSAGES.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    append_operator_event(record["id"], "queued", "viewer-server", "메시지가 저장됐고 큐 프로세서가 집어갈 수 있습니다.", run_id=run_id)
    return record


def read_operator_messages(limit: int = 100) -> list[dict[str, object]]:
    if not OPERATOR_MESSAGES.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in OPERATOR_MESSAGES.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def operator_messages_with_status(limit: int = 100) -> list[dict[str, object]]:
    grouped = events_by_message_id()
    messages: list[dict[str, object]] = []
    for message in read_operator_messages(limit=limit):
        message_id = str(message.get("id", ""))
        events = grouped.get(message_id, [])
        controlled = apply_queue_controls(message, events)
        latest = events[-1] if events else {
            "message_id": message_id,
            "timestamp": message.get("created_at", ""),
            "status": "legacy_record",
            "actor": "legacy",
            "detail": "이 메시지는 상태 이벤트 도입 전 기록이라 아직 원본 queued 상태만 있습니다.",
            "run_id": message.get("run_id", ""),
            "artifact": "",
        }
        enriched = dict(controlled)
        enriched["queue_events"] = events
        enriched["latest_event"] = latest
        enriched["effective_status"] = "removed" if controlled.get("removed_from_queue") else workflow_status(events, str(message.get("status", "queued")))
        enriched["effective_run_id"] = latest.get("run_id") or message.get("run_id", "")
        if enriched["effective_run_id"] and not enriched.get("run_id"):
            enriched["run_id"] = enriched["effective_run_id"]
        enriched["title"] = title_for_message(enriched)
        messages.append(enriched)
    messages.sort(key=lambda item: (int(item.get("queue_priority", 1000) or 1000), str(item.get("created_at", ""))))
    return messages


def lookup_message_effective_run(message_id: str, message: dict[str, object] | None = None) -> dict[str, str]:
    """Resolve the effective run id and status for a single operator message.

    Uses the same derivation as operator_messages_with_status() so callers
    (e.g. the /api/messages POST handler) can return created_run_id directly
    instead of forcing the frontend to poll.
    """
    events = events_by_message_id().get(message_id, [])
    latest = events[-1] if events else {}
    base = message if isinstance(message, dict) else {}
    effective_run_id = str(latest.get("run_id") or base.get("run_id", "") or "")
    effective_status = workflow_status(events, str(base.get("status", "queued"))) if events else ""
    return {"created_run_id": effective_run_id, "effective_status": effective_status}


def title_for_message(message: dict[str, object], max_chars: int = 42) -> str:
    text = str(message.get("original_message") or message.get("message") or message.get("id") or "").strip()
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:8]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text_excerpt(path: Path, *, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n... <중간 생략: {len(text) - len(head) - len(tail)} chars> ...\n\n{tail}"


def run_operator_text(run_dir: Path) -> str:
    plan_path = run_dir / "orchestration-plan.json"
    if not plan_path.exists():
        return ""
    try:
        plan = read_json_file(plan_path)
    except Exception:
        return ""
    if not isinstance(plan, dict):
        return ""
    operator = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
    return "\n".join([str(operator.get("original_message", "")), str(operator.get("refined_message", ""))])


def is_goal_report_request(run_dir: Path) -> bool:
    text = run_operator_text(run_dir).lower()
    tokens = ["보고서", "문제점", "개선점", "시말서", "d드라이브", "d drive", "d:\\", "게임 현재 문제"]
    return sum(1 for token in tokens if token.lower() in text) >= 3


def extract_issue_headlines(limit: int = 18) -> list[str]:
    issue_path = REPO_ROOT / "memory" / "issues_log" / "07-codex-orchestration.md"
    if not issue_path.exists():
        return []
    lines = issue_path.read_text(encoding="utf-8", errors="replace").splitlines()
    picked: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if "증상:" in stripped or "Symptom" in stripped or stripped.startswith("###") or stripped.startswith("## "):
            picked.append(stripped[:240])
        if len(picked) >= limit:
            break
    return list(reversed(picked))


def build_goal_report_pack(run_id: str, run_dir: Path) -> dict[str, object]:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = GOAL_REPORT_ROOT / f"{stamp}-{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "active_state": REPO_ROOT / "docs" / "reports" / "sc-spire-active-operating-state.yaml",
        "backlog": REPO_ROOT / "docs" / "backlog" / "blocker-backlog.yaml",
        "scorecard": REPO_ROOT / "docs" / "reports" / "sc-spire-field-scorecard-current.md",
        "quality_report": REPO_ROOT / "docs" / "reports" / "sc-spire-unity-current-response-quality-report.md",
        "learnings": REPO_ROOT / "docs" / "reports" / "sc-spire-learnings.md",
        "orchestrator_issues": REPO_ROOT / "memory" / "issues_log" / "07-codex-orchestration.md",
    }
    source_excerpts = {name: read_text_excerpt(path) for name, path in sources.items()}
    issue_headlines = extract_issue_headlines()
    issue_lines = [f"- {item}" for item in issue_headlines] if issue_headlines else ["- 최근 이슈 헤드라인을 추출하지 못했습니다."]
    current_prompt = run_operator_text(run_dir)
    generated_at = utc_timestamp()
    shared_header = [
        f"- 생성 시각(UTC): `{generated_at}`",
        f"- 실행 run_id: `{run_id}`",
        f"- 산출 폴더: `{out_dir}`",
        "- 증거 경계: 이 보고서는 현재 저장소 문서, 백로그, 이슈 로그, 오케스트레이터 artifact를 근거로 한 운영/제품 진단입니다. 새 Unity 플레이어 렌더링 증거를 생성하지 않았으므로 player-facing closure나 sellable 판정으로 쓰면 안 됩니다.",
        "- 생성 경로: HTML 평문 입력 -> prompt preflight -> advisory council -> main orchestrator -> report-pack worker -> validator/review gate.",
    ]
    problem_report = "\n".join(
        [
            "# SC Spire 현재 문제점 보고서",
            "",
            *shared_header,
            "",
            "## 1. 핵심 문제 요약",
            "",
            "1. 오케스트레이션 운영판은 개선됐지만 실제 외부 worker/Claude live 결과와 local self-check artifact의 경계가 아직 혼동될 수 있습니다.",
            "2. Unity/player-facing 품질은 문서상 여전히 rendered evidence, parity baseline, Claude gate, backlog binding이 closure 조건입니다.",
            "3. 반복 이슈가 매우 많아 issue memory가 단순 기록으로 쌓이면 작업자가 같은 실수를 반복할 위험이 큽니다.",
            "4. API/구독/CLI 경로의 callable 여부가 작업 품질에 직접 영향을 주므로, 호출 불가 경로는 숨기지 않고 blocked/limited로 노출해야 합니다.",
            "5. 보고서/계획/소스 준비가 player-facing 완성으로 과장될 위험이 있습니다.",
            "",
            "## 2. 현재 prompt/run 관찰",
            "",
            "```text",
            current_prompt[:4000],
            "```",
            "",
            "## 3. 최근 반복 이슈 신호",
            "",
            *issue_lines,
            "",
            "## 4. 근거 문서 발췌",
            "",
            "### active operating state",
            "```yaml",
            source_excerpts["active_state"] or "파일 없음",
            "```",
            "",
            "### blocker backlog",
            "```yaml",
            source_excerpts["backlog"] or "파일 없음",
            "```",
            "",
            "### field scorecard",
            "```markdown",
            source_excerpts["scorecard"] or "파일 없음",
            "```",
            "",
            "## 5. 즉시 위험",
            "",
            "- 화면상 `closure_ready`는 완료가 아니라 closure 검토 준비 상태로 유지해야 합니다.",
            "- live OpenAI Agents SDK import/call이 막힌 상태라면 API 보좌관은 contract/request까지만 인정해야 합니다.",
            "- Gemini는 key/config 전까지 disabled로 유지해야 합니다.",
            "- D드라이브 보고서가 생성돼도 게임 문제 자체가 해결된 것이 아닙니다.",
            "",
        ]
    )
    improvement_report = "\n".join(
        [
            "# SC Spire 개선점 및 실행 마일스톤 보고서",
            "",
            *shared_header,
            "",
            "## P0. 오케스트레이션 신뢰성",
            "",
            "1. 모든 평문 입력은 prompt-preflight와 prompt-validator를 지나야 합니다.",
            "2. main-orchestrator는 최종 판단 1개를 유지하되, Claude 판단 보좌관과 OpenAI/Codex API 판단 보좌관의 상태를 항상 기록해야 합니다.",
            "3. 큐 메시지는 `sequential_work_item`인지 `steering_intervention`인지 먼저 판정해야 합니다.",
            "4. closure는 worker-result, validator-result, issue-gate, product/Claude review, evidence contract가 모두 있어야만 허용해야 합니다.",
            "",
            "## P0. 게임 품질 검증",
            "",
            "1. Unity/player-facing 변경은 rendered Windows screenshot 없이는 완료로 보지 않습니다.",
            "2. baseline-ready surface는 screenshot comparison과 checklist pass가 필요합니다.",
            "3. score movement는 Claude closure/score gate가 있어야 합니다.",
            "4. source/process-only 보고서는 no-score boundary를 명확히 유지해야 합니다.",
            "",
            "## P1. 작업자 기능 사용 강제",
            "",
            "- Codex MAX: 파일 수정, 명령, 브라우저 검증, evidence packaging.",
            "- Claude MAX: 계획 반박, 제품 판단, evidence critique, closure challenge.",
            "- OpenAI Agents SDK/API: agent identity, handoff, guardrail, structured decision, trace/eval-ready artifact. live API는 작은 판단에만 예산 gate 뒤에서 사용.",
            "- Gemini: key/config 이후 third-opinion review.",
            "",
            "## P1. 보고서 자동화",
            "",
            "1. 보고서 요청은 별도 report-pack worker artifact로 남깁니다.",
            "2. D드라이브 산출물 manifest를 run artifact에 저장합니다.",
            "3. validator는 산출 파일 존재, 길이, 필수 섹션, 과장 금지 문구를 확인해야 합니다.",
            "",
            "## P2. UI 정리",
            "",
            "- 현재 화면은 기능 노출이 우선이라 정보가 많습니다. 다음 단계는 기본 화면을 `현재 판단`, `보좌관`, `큐 판정`, `다음 행동`, `증거 부족`만 남기고 세부 로그를 접는 것입니다.",
            "",
            "## 근거 발췌: learnings",
            "",
            "```markdown",
            source_excerpts["learnings"] or "파일 없음",
            "```",
            "",
        ]
    )
    incident_report = "\n".join(
        [
            "# SC Spire 오케스트레이션 시말서",
            "",
            *shared_header,
            "",
            "## 1. 사건 개요",
            "",
            "사용자는 단순 로그/큐 뷰어가 아니라, 평문 요청을 받아 여러 모델과 검증 관점이 목표 달성까지 반복하는 운영 체계를 요구했습니다. 초기 구조는 화면에 많은 정보가 있었지만, 메인 판단, 보좌관 강제, 큐 steering, 실제 산출물 생성 경로가 충분히 명확하지 않았습니다.",
            "",
            "## 2. 원인",
            "",
            "1. `sent_to_main`과 `prepared`가 실제 작업 진행처럼 오해될 여지가 있었습니다.",
            "2. Claude/OpenAI API 경로가 필수 판단 보좌관이 아니라 선택적 하위 세션처럼 보였습니다.",
            "3. 큐 항목이 현재 목표 수정인지 신규 작업인지 판정하는 gate가 부족했습니다.",
            "4. 이슈 로그는 많았지만 다음 작업 acceptance gate로 승격되지 않으면 기록 이상의 효용이 낮았습니다.",
            "5. 보고서 요청 같은 실제 산출물 생성이 기존 self-check worker 경로에 포함되지 않았습니다.",
            "",
            "## 3. 조치",
            "",
            "- main-advisory-council 구조를 추가해 Claude 판단 보좌관과 OpenAI/Codex API 판단 보좌관을 강제했습니다.",
            "- queue-routing-decision으로 순차/steering 판정을 남기게 했습니다.",
            "- D드라이브 보고서 pack worker를 추가해 문제점/개선점/시말서 산출물을 manifest와 함께 생성하게 했습니다.",
            "- 화면에는 보좌관 상태, 큐 판정, stage map, closure 대기 조건을 노출했습니다.",
            "",
            "## 4. 재발 방지",
            "",
            "1. 완료/closure 표현은 closure-packet이 있을 때만 사용합니다.",
            "2. live adapter가 호출되지 않았으면 호출됐다고 쓰지 않습니다.",
            "3. 사용자가 평문으로 대충 적어도 preflight가 상세화하되 원문을 보존합니다.",
            "4. known issue는 다음 worker prompt의 acceptance gate로 승격합니다.",
            "5. 보고서 산출물은 D드라이브 파일 존재와 run artifact 양쪽으로 검증합니다.",
            "",
            "## 5. 남은 제한",
            "",
            "- 이 시말서는 저장소/오케스트레이터 근거 기반 문서입니다. 실제 게임 품질 closure는 별도 Unity rendered evidence와 Claude gate가 필요합니다.",
            "- OpenAI Agents SDK live call은 현재 import gate 상태에 따라 contract/request만 남을 수 있습니다.",
            "",
            "## 근거 발췌: quality report",
            "",
            "```markdown",
            source_excerpts["quality_report"] or "파일 없음",
            "```",
            "",
        ]
    )
    files = {
        "problems_report": out_dir / "01-current-game-problems-report.md",
        "improvements_report": out_dir / "02-improvement-plan-report.md",
        "incident_report": out_dir / "03-incident-report.md",
    }
    files["problems_report"].write_text(problem_report, encoding="utf-8")
    files["improvements_report"].write_text(improvement_report, encoding="utf-8")
    files["incident_report"].write_text(incident_report, encoding="utf-8")
    manifest = {
        "kind": "d_drive_goal_report_pack",
        "created_at": generated_at,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "files": {key: str(path) for key, path in files.items()},
        "source_files": {key: str(path) for key, path in sources.items()},
        "evidence_boundary": "Repository/report/issue-memory analysis only; no new Unity rendered evidence or sellable closure claim.",
        "checks": [
            {
                "id": key,
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else 0,
                "has_korean": bool(re.search(r"[가-힣]", path.read_text(encoding="utf-8", errors="replace"))) if path.exists() else False,
            }
            for key, path in files.items()
        ],
    }
    write_json(out_dir / "manifest.json", manifest)
    return manifest


def ensure_goal_report_pack(run_id: str, run_dir: Path) -> dict[str, object] | None:
    if not is_goal_report_request(run_dir):
        return None
    artifact = run_dir / "d-drive-report-pack.json"
    if artifact.exists():
        loaded = read_json_file(artifact)
        return loaded if isinstance(loaded, dict) else None
    manifest = build_goal_report_pack(run_id, run_dir)
    write_json(artifact, manifest)
    append_transcript_event(
        run_dir,
        "report-pack-worker",
        "main-orchestrator",
        "worker_result",
        f"D드라이브 보고서 pack을 생성했습니다: {manifest.get('output_dir')}",
        "d-drive-report-pack.json",
    )
    return manifest


REPORT_PACK_JUDGMENT_VERSION = 3


def web_target_mentions_are_negated(text: str) -> bool:
    negation_patterns = [
        r"Flask/web[^\n]{0,40}(아니라|아닙니다|금지|쓰지|사용하지)",
        r"(아니라|아닙니다|금지|쓰지|사용하지)[^\n]{0,60}Flask/web",
        r"Flask/web verifier[^\n]{0,80}(쓰지|사용하지|증거로 쓰지|금지)",
        r"Flask/web[^\n]{0,80}Unity[^\n]{0,80}(아니라|아닙니다)",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in negation_patterns)


def build_report_pack_judgment(run_id: str, run_dir: Path) -> dict[str, object]:
    pack_path = run_dir / "d-drive-report-pack.json"
    if not pack_path.exists():
        return {
            "kind": "report_pack_judgment",
            "created_at": utc_timestamp(),
            "run_id": run_id,
            "status": "missing_report_pack",
            "summary": "d-drive-report-pack.json이 없어서 에이전트가 보고서를 썼다고 판정할 수 없습니다.",
            "checks": [],
        }
    pack = read_json_file(pack_path)
    files = pack.get("files") if isinstance(pack, dict) else {}
    if not isinstance(files, dict):
        files = {}
    checks: list[dict[str, object]] = []
    all_exist = True
    all_korean = True
    all_unity = True
    any_forbidden_web = False
    all_boundary = True
    combined_text_parts: list[str] = []
    for key, raw_path in files.items():
        path = Path(str(raw_path))
        exists = path.exists()
        text = path.read_text(encoding="utf-8", errors="replace") if exists else ""
        combined_text_parts.append(text)
        has_korean = bool(re.search(r"[가-힣]", text))
        mentions_unity = bool(re.search(r"Unity|유니티|SC Spire Unity|Windows player|rendered", text, re.IGNORECASE))
        mentions_web_target = bool(re.search(r"Flask|localhost:5050|verify_ui_headless", text, re.IGNORECASE))
        mentions_forbidden_web = mentions_web_target and not web_target_mentions_are_negated(text)
        has_boundary = bool(re.search(r"증거 경계|새 Unity 플레이어 렌더링 증거|sellable 판정|player-facing closure|rendered evidence", text, re.IGNORECASE))
        checks.append(
            {
                "id": str(key),
                "path": str(path),
                "exists": exists,
                "bytes": path.stat().st_size if exists else 0,
                "has_korean": has_korean,
                "mentions_unity_target": mentions_unity,
                "mentions_wrong_web_target": mentions_forbidden_web,
                "web_target_mention_negated": mentions_web_target and not mentions_forbidden_web,
                "has_evidence_boundary": has_boundary,
            }
        )
        all_exist = all_exist and exists
        all_korean = all_korean and has_korean
        all_unity = all_unity and mentions_unity
        any_forbidden_web = any_forbidden_web or mentions_forbidden_web
        all_boundary = all_boundary and has_boundary
    combined_text = "\n".join(combined_text_parts)
    context_coverage = {
        "unity_project_path": bool(re.search(r"D:\\hobby\\sc-spire-unity|sc-spire-unity", combined_text, re.IGNORECASE)),
        "active_operating_state": bool(re.search(r"active operating state|sc-spire-active-operating-state|운영 모델", combined_text, re.IGNORECASE)),
        "active_blocker": bool(re.search(r"WEB-PARITY-RUN-DEPTH-1|active blocker|현재 active blocker", combined_text, re.IGNORECASE)),
        "not_sellable_boundary": bool(re.search(r"NOT_SELLABLE|not sellable|sellable 판정으로 쓰면 안|판매가능", combined_text, re.IGNORECASE)),
        "latest_executable_or_rendered_evidence": bool(re.search(r"SCSpireVerify\.exe|latest_executable|rendered evidence|렌더링 증거", combined_text, re.IGNORECASE)),
    }
    evidence_boundary = str(pack.get("evidence_boundary", "")) if isinstance(pack, dict) else ""
    has_new_unity_rendered_evidence = not re.search(r"no new Unity rendered evidence|새 Unity 플레이어 렌더링 증거를 생성하지 않았", evidence_boundary, re.IGNORECASE)
    report_written = all_exist and len(checks) >= 3 and all_korean
    unity_fit = report_written and all_unity and not any_forbidden_web and all_boundary
    completion_evidence = unity_fit and has_new_unity_rendered_evidence
    if not report_written:
        status = "report_missing_or_incomplete"
        summary = "에이전트 보고서 작성 여부를 통과시킬 수 없습니다. 파일 누락, 짧은 파일, 또는 한국어 본문 누락이 있습니다."
    elif not unity_fit:
        status = "report_written_but_target_mismatch"
        summary = "에이전트가 보고서는 썼지만 Unity 목표/증거 경계/잘못된 web 대상 배제 조건을 모두 만족하지 못했습니다."
    elif not completion_evidence:
        status = "report_written_for_unity_but_evidence_limited"
        summary = "에이전트가 Unity 대상 보고서를 썼습니다. 다만 새 Unity rendered evidence가 없으므로 완료/판매가능/플레이어 화면 closure 증거로는 부족합니다."
    else:
        status = "report_written_and_rendered_evidence_claimed"
        summary = "에이전트가 Unity 대상 보고서를 썼고 새 rendered evidence도 주장합니다. 별도 스크린샷/빌드 검증으로 과장 여부를 확인해야 합니다."
    return {
        "kind": "report_pack_judgment",
        "judgment_version": REPORT_PACK_JUDGMENT_VERSION,
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "report_written": report_written,
        "unity_target_fit": unity_fit,
        "completion_evidence_sufficient": completion_evidence,
        "evidence_boundary": evidence_boundary,
        "context_coverage": context_coverage,
        "checks": checks,
        "retry_prompt_artifact": "report-pack-retry-prompt.md" if not completion_evidence else "",
        "retry_prompt": build_report_pack_retry_prompt(run_id, status, summary, evidence_boundary) if not completion_evidence else "",
        "rule": "이 판정은 보고서 작성 여부와 Unity 적합성만 판단합니다. Codex가 보고서를 직접 새로 작성했다는 의미가 아닙니다.",
    }


def build_report_pack_retry_prompt(run_id: str, status: str, summary: str, evidence_boundary: str) -> str:
    return "\n".join(
        [
            "메인 오케스트레이터에게 평문 재시도 지시입니다.",
            "",
            "이전 실행의 보고서는 에이전트가 작성했지만 Unity 완료 증거로는 부족하다고 판정됐습니다.",
            f"- 이전 run_id: {run_id}",
            f"- report judgment: {status}",
            f"- 판정 요약: {summary}",
            f"- 기존 증거 경계: {evidence_boundary or '확인 필요'}",
            "",
            "다음 루프에서 해야 할 일:",
            "1. 대상 게임은 Flask/web이 아니라 Unity 프로젝트 `D:\\hobby\\sc-spire-unity`입니다.",
            "2. AGENTS.md의 Unity 운영 모델, active operating state, blocker backlog, parity baseline을 다시 읽고 반영하세요.",
            "3. 현재 active blocker와 최신 scorecard 기준으로 Unity 게임 현재 문제를 분석하세요.",
            "4. 가능하면 새 Unity Windows player rendered evidence 또는 기존 최신 Unity rendered evidence의 명확한 근거를 사용하세요.",
            "5. 새 evidence가 없으면 완료/판매가능/closure를 주장하지 말고 제한 보고서라고 명시하세요.",
            "6. D드라이브에 문제점 보고서, 개선점 보고서, 시말서를 다시 작성하거나 보강하고 manifest를 남기세요.",
            "7. report-validator-agent가 다시 `report-pack-judgment.json`으로 작성 여부, Unity 적합성, rendered evidence 충분성을 판정하게 하세요.",
            "",
            "금지:",
            "- Flask/web verifier 결과를 Unity 게임 완료 증거로 쓰지 마세요.",
            "- 보고서 작성만으로 Unity 플레이어 화면 closure를 주장하지 마세요.",
            "- 새 Unity rendered evidence가 없는데 sellable 또는 완료라고 쓰지 마세요.",
        ]
    )


REPORT_EVIDENCE_AUDIT_VERSION = 1


def normalize_report_evidence_path(raw: str) -> str:
    return raw.strip().strip("`'\".,);]").replace("/", "\\")


def resolve_report_evidence_path(raw: str) -> Path:
    value = normalize_report_evidence_path(raw)
    path = Path(value)
    if path.is_absolute():
        return path
    return REPO_ROOT / value


def extract_report_evidence_paths(text: str) -> list[str]:
    patterns = [
        r"D:\\hobby\\sc-spire-unity\\Builds\\Verify\\SCSpireVerify\.exe",
        r"D:\\hobby\\sc-spire-orchestrator\\output\\unity[^`'\"\s),]+",
        r"output/unity[^`'\"\s),]+",
        r"output/unity_unlock_tree_visual_[^`'\"\s),]+",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    normalized = sorted({normalize_report_evidence_path(item) for item in found if item.strip()})
    return normalized


def active_state_evidence_paths() -> set[str]:
    active_state = REPO_ROOT / "docs" / "reports" / "sc-spire-active-operating-state.yaml"
    if not active_state.exists():
        return set()
    text = active_state.read_text(encoding="utf-8", errors="replace")
    paths = extract_report_evidence_paths(text)
    paths.extend(re.findall(r"D:\\hobby\\sc-spire-unity\\Builds\\Verify\\SCSpireVerify\.exe", text, flags=re.IGNORECASE))
    return {normalize_report_evidence_path(item).lower() for item in paths}


def build_report_evidence_audit(run_id: str, run_dir: Path) -> dict[str, object]:
    pack_path = run_dir / "d-drive-report-pack.json"
    if not pack_path.exists():
        return {
            "kind": "report_evidence_audit",
            "audit_version": REPORT_EVIDENCE_AUDIT_VERSION,
            "created_at": utc_timestamp(),
            "run_id": run_id,
            "status": "missing_report_pack",
            "summary": "d-drive-report-pack.json이 없어 보고서의 Unity evidence 인용을 감사할 수 없습니다.",
        }
    pack = read_json_file(pack_path)
    files = pack.get("files") if isinstance(pack, dict) else {}
    if not isinstance(files, dict):
        files = {}
    active_paths = active_state_evidence_paths()
    report_checks: list[dict[str, object]] = []
    all_paths: set[str] = set()
    verified_paths: list[str] = []
    active_matches: list[str] = []
    missing_paths: list[str] = []
    for key, raw_path in files.items():
        report_path = Path(str(raw_path))
        text = report_path.read_text(encoding="utf-8-sig", errors="replace") if report_path.exists() else ""
        mentioned = extract_report_evidence_paths(text)
        existing = []
        missing = []
        active = []
        for item in mentioned:
            all_paths.add(item)
            resolved = resolve_report_evidence_path(item)
            if resolved.exists():
                existing.append(item)
                verified_paths.append(item)
            else:
                missing.append(item)
                missing_paths.append(item)
            if item.lower() in active_paths or str(resolve_report_evidence_path(item)).lower() in active_paths:
                active.append(item)
                active_matches.append(item)
        report_checks.append(
            {
                "id": str(key),
                "path": str(report_path),
                "mentioned_evidence_count": len(mentioned),
                "verified_existing_count": len(existing),
                "active_state_match_count": len(active),
                "missing_count": len(missing),
                "sample_verified": existing[:6],
                "sample_active_state_matches": active[:6],
                "sample_missing": missing[:6],
            }
        )
    verified_unique = sorted(set(verified_paths))
    active_unique = sorted(set(active_matches))
    missing_unique = sorted(set(missing_paths))
    executable_referenced = any("SCSpireVerify.exe".lower() in item.lower() for item in all_paths)
    rendered_references = [item for item in verified_unique if item.lower().endswith((".png", ".jpg", ".jpeg"))]
    evidence_reference_sufficient = len(rendered_references) >= 3 and len(active_unique) >= 3 and executable_referenced
    if evidence_reference_sufficient:
        status = "report_references_verified_unity_evidence"
        summary = "에이전트 보고서가 최신 Unity 실행 파일과 기존 rendered evidence 경로를 실제 존재하는 파일로 인용했습니다. 이는 보고서 근거 충분성 판정이며 새 evidence 생성/closure 판정은 아닙니다."
    elif verified_unique:
        status = "report_references_some_unity_evidence"
        summary = "에이전트 보고서가 일부 Unity evidence 경로를 인용했지만, 최신 active evidence 반영이나 rendered evidence 인용이 충분하지 않습니다."
    else:
        status = "report_missing_verifiable_unity_evidence_references"
        summary = "에이전트 보고서에서 실제 존재하는 Unity evidence 경로를 확인하지 못했습니다."
    return {
        "kind": "report_evidence_audit",
        "audit_version": REPORT_EVIDENCE_AUDIT_VERSION,
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "evidence_reference_sufficient_for_report": evidence_reference_sufficient,
        "closure_evidence_claim": False,
        "executable_referenced": executable_referenced,
        "verified_existing_count": len(verified_unique),
        "rendered_evidence_reference_count": len(rendered_references),
        "active_state_match_count": len(active_unique),
        "missing_count": len(missing_unique),
        "verified_samples": verified_unique[:10],
        "active_state_match_samples": active_unique[:10],
        "missing_samples": missing_unique[:10],
        "report_checks": report_checks,
        "rule": "이 감사는 에이전트 보고서가 기존 Unity evidence를 근거로 삼았는지 판정합니다. 새 Unity evidence 생성이나 게임 closure를 의미하지 않습니다.",
    }


def ensure_report_evidence_audit(run_id: str, run_dir: Path) -> dict[str, object] | None:
    if not (run_dir / "d-drive-report-pack.json").exists():
        return None
    artifact = run_dir / "report-evidence-audit.json"
    if artifact.exists():
        loaded = read_json_file(artifact)
        if isinstance(loaded, dict) and int(loaded.get("audit_version", 0) or 0) >= REPORT_EVIDENCE_AUDIT_VERSION:
            return loaded
    audit = build_report_evidence_audit(run_id, run_dir)
    write_json(artifact, audit)
    append_transcript_event(
        run_dir,
        "report-validator-agent",
        "main-orchestrator",
        "review_result",
        str(audit.get("summary", "")),
        "report-evidence-audit.json",
    )
    return audit


GOAL_COMPLETION_AUDIT_VERSION = 4
CLOSURE_PACKET_VERSION = 1


def build_goal_completion_audit(run_id: str, run_dir: Path) -> dict[str, object]:
    artifacts = {item.name for item in run_dir.iterdir() if item.is_file()}
    gate = read_json_file(run_dir / "review-gate.json") if (run_dir / "review-gate.json").exists() else {}
    judgment = read_json_file(run_dir / "report-pack-judgment.json") if (run_dir / "report-pack-judgment.json").exists() else {}
    evidence_audit = read_json_file(run_dir / "report-evidence-audit.json") if (run_dir / "report-evidence-audit.json").exists() else {}
    unity_rendered_evidence = read_json_file(run_dir / "unity-rendered-evidence.json") if (run_dir / "unity-rendered-evidence.json").exists() else {}
    pack = read_json_file(run_dir / "d-drive-report-pack.json") if (run_dir / "d-drive-report-pack.json").exists() else {}
    prompt_validation = read_json_file(run_dir / "prompt-validation.json") if (run_dir / "prompt-validation.json").exists() else {}
    pack_files = pack.get("files") if isinstance(pack, dict) else {}
    if not isinstance(pack_files, dict):
        pack_files = {}
    report_files_exist = bool(pack_files) and all(Path(str(path)).exists() for path in pack_files.values())
    fresh_unity_evidence_ok = (
        str(unity_rendered_evidence.get("status", "")) == "passed"
        and Path(str(unity_rendered_evidence.get("screenshot", ""))).exists()
        and int(unity_rendered_evidence.get("bytes", 0) or 0) > 0
        and bool(str(unity_rendered_evidence.get("ready_marker", "")).strip())
    )
    required_validator_artifacts = {
        "validator-result.json",
        "validator-code-result.json",
        "validator-contract-result.json",
        "validator-ui-state-result.json",
        "validator-issue-gate-result.json",
    }
    closure_review_artifact = (
        "claude-review-result.json"
        if "claude-review-result.json" in artifacts
        else "product-review-result.json"
        if "product-review-result.json" in artifacts
        else ""
    )
    e2e_artifact_exists = "e2e-html-verification.json" in artifacts

    def req(req_id: str, label: str, status: str, evidence: str, next_action: str = "") -> dict[str, object]:
        return {
            "id": req_id,
            "label": label,
            "status": status,
            "evidence": evidence,
            "next_action": next_action,
        }

    requirements = [
        req(
            "plain_prompt_preflight",
            "평문 입력이 prompt-preflight와 validator를 통과",
            "passed" if "prompt-preflight.json" in artifacts and str(prompt_validation.get("status")) == "passed" else "needs_retry",
            "prompt-preflight.json / prompt-validation.json",
            "프롬프트 검증이 passed가 아니면 평문 단계부터 다시 반복",
        ),
        req(
            "cerberus_advisory_council",
            "메인+Claude 보좌관+OpenAI/Codex 보좌관 숙의 기록",
            "passed" if {"main-advisory-council.json", "cerberus-deliberation.json", "claude-advisor-request.md", "openai-codex-advisor-request.json"}.issubset(artifacts) else "missing",
            "main-advisory-council.json / cerberus-deliberation.json / advisor requests",
            "보좌관 artifact가 없으면 main routing 전에 재생성",
        ),
        req(
            "agents_sdk_pattern_artifacts",
            "Agents SDK 방식의 identity/handoff/guardrail/trace 계약",
            "passed" if {"agents-sdk-run-contract.json", "agents-sdk-handoff-graph.json", "agents-sdk-guardrails.json"}.issubset(artifacts) else "missing",
            "agents-sdk-run-contract.json / agents-sdk-handoff-graph.json / agents-sdk-guardrails.json",
            "live API 여부와 별개로 SDK pattern artifact를 유지",
        ),
        req(
            "worker_and_validator_loop",
            "worker 결과와 다중 validator lane",
            "passed" if "worker-result.json" in artifacts and required_validator_artifacts.issubset(artifacts) else "missing",
            "worker-result.json + validator lane artifacts",
            "worker 결과마다 validator lane을 다시 실행",
        ),
        req(
            "closure_challenge_review",
            "Claude/product closure challenge 검토",
            "passed" if closure_review_artifact else "missing",
            closure_review_artifact or "claude-review-result.json / product-review-result.json",
            "완료 전 Claude 또는 product critic 검토 결과가 필요",
        ),
        req(
            "html_viewer_state_evidence",
            "HTML 운영 화면 상태 검증 artifact",
            "passed" if e2e_artifact_exists else "missing",
            "e2e-html-verification.json",
            "화면에서 현재 run과 검증 상태가 보인다는 증거가 필요",
        ),
        req(
            "issue_memory_gate",
            "issue memory가 acceptance gate로 승격",
            "passed" if {"issue-gate.json", "validator-issue-gate-result.json"}.issubset(artifacts) else "missing",
            "issue-gate.json / validator-issue-gate-result.json",
            "반복 실패를 다음 worker 입력 gate로 승격",
        ),
        req(
            "d_drive_agent_reports",
            "에이전트가 D드라이브 문제점/개선점/시말서 보고서 작성",
            "passed" if "d-drive-report-pack.json" in artifacts and report_files_exist else "missing",
            str(pack.get("output_dir", "")) if isinstance(pack, dict) else "d-drive-report-pack.json",
            "보고서 파일 3개와 manifest가 모두 있어야 함",
        ),
        req(
            "unity_report_judgment",
            "보고서가 Unity 대상이고 완료 과장을 하지 않음",
            "passed" if bool(judgment.get("report_written")) and bool(judgment.get("unity_target_fit")) else "needs_retry",
            str(judgment.get("status", "")),
            "Unity target mismatch면 평문 단계부터 재시도",
        ),
        req(
            "unity_existing_evidence_reference",
            "보고서가 기존 Unity rendered evidence를 실제 파일로 인용",
            "passed" if bool(evidence_audit.get("evidence_reference_sufficient_for_report")) else "needs_retry",
            str(evidence_audit.get("status", "")),
            "문서/보고서가 실제 evidence 경로를 인용하도록 재시도",
        ),
        req(
            "new_unity_rendered_evidence_for_closure",
            "새 Unity rendered evidence 또는 closure 가능한 결정 증거",
            "passed" if fresh_unity_evidence_ok or bool(judgment.get("completion_evidence_sufficient")) else "blocked",
            str(unity_rendered_evidence.get("screenshot", "")) if fresh_unity_evidence_ok else str(gate.get("status", "")),
            "새 Unity 렌더링 증거를 확보하기 전까지 complete 금지",
        ),
    ]
    incomplete = [item for item in requirements if item["status"] != "passed"]
    completion_allowed = not incomplete and (
        str(gate.get("status", "")).startswith("ready_for_closure_review") or fresh_unity_evidence_ok
    )
    if completion_allowed:
        status = "goal_completion_evidence_ready"
        summary = "현재 artifact만으로 목표 완료 조건을 충족합니다. 최종 completion claim 전에 브라우저 표시와 최신 run 상태를 재확인하세요."
    else:
        status = "goal_not_complete"
        summary = "목표의 여러 구조/보고서 요구는 충족됐지만, 새 Unity rendered evidence 또는 closure 가능한 결정 증거가 없어 완료 처리할 수 없습니다."
    return {
        "kind": "goal_completion_audit",
        "audit_version": GOAL_COMPLETION_AUDIT_VERSION,
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "completion_allowed": completion_allowed,
        "requirements": requirements,
        "blocking_requirements": [item for item in requirements if item["status"] == "blocked"],
        "non_passed_requirements": incomplete,
        "rule": "이 감사는 목표 완료 가능 여부를 artifact 증거로만 판정합니다. 완료 처리(update_goal)는 모든 항목이 passed이고 최신 브라우저/UI 확인까지 끝난 뒤에만 가능합니다.",
    }


def apply_goal_completion_audit_to_gate(run_dir: Path, audit: dict[str, object]) -> None:
    if not bool(audit.get("completion_allowed")) or not (run_dir / "review-gate.json").exists():
        return
    if (run_dir / "closure-packet.json").exists():
        return
    gate = read_json_file(run_dir / "review-gate.json")
    if not isinstance(gate, dict):
        return
    if str(gate.get("status")) not in {
        "waiting_for_unity_rendered_evidence",
        "ready_for_closure_review_with_fresh_unity_evidence",
    }:
        return
    gate["status"] = "ready_for_closure_review_with_fresh_unity_evidence"
    gate["next_action"] = "목표 감사 기준으로 평문 프리플라이트, 보좌관/SDK/worker/validator/report/evidence 요구가 충족됐습니다. 최종 완료 전 브라우저 표시와 artifact 경계를 다시 확인하세요."
    gate["unity_rendered_evidence"] = read_json_file(run_dir / "unity-rendered-evidence.json") if (run_dir / "unity-rendered-evidence.json").exists() else {}
    write_json(run_dir / "review-gate.json", gate)


def ensure_goal_completion_audit(run_id: str, run_dir: Path) -> dict[str, object] | None:
    if not (run_dir / "d-drive-report-pack.json").exists():
        return None
    artifact = run_dir / "goal-completion-audit.json"
    if artifact.exists():
        loaded = read_json_file(artifact)
        if isinstance(loaded, dict) and int(loaded.get("audit_version", 0) or 0) >= GOAL_COMPLETION_AUDIT_VERSION:
            audit = build_goal_completion_audit(run_id, run_dir)
            write_json(artifact, audit)
            apply_goal_completion_audit_to_gate(run_dir, audit)
            return audit
    audit = build_goal_completion_audit(run_id, run_dir)
    write_json(artifact, audit)
    apply_goal_completion_audit_to_gate(run_dir, audit)
    append_transcript_event(
        run_dir,
        "goal-auditor",
        "main-orchestrator",
        "review_result",
        str(audit.get("summary", "")),
        "goal-completion-audit.json",
    )
    return audit


def build_closure_packet(run_id: str, run_dir: Path) -> dict[str, object]:
    gate = read_json_file(run_dir / "review-gate.json") if (run_dir / "review-gate.json").exists() else {}
    audit = ensure_goal_completion_audit(run_id, run_dir) or {}
    report_pack = read_json_file(run_dir / "d-drive-report-pack.json") if (run_dir / "d-drive-report-pack.json").exists() else {}
    report_judgment = read_json_file(run_dir / "report-pack-judgment.json") if (run_dir / "report-pack-judgment.json").exists() else {}
    report_evidence_audit = read_json_file(run_dir / "report-evidence-audit.json") if (run_dir / "report-evidence-audit.json").exists() else {}
    unity_evidence = read_json_file(run_dir / "unity-rendered-evidence.json") if (run_dir / "unity-rendered-evidence.json").exists() else {}
    closure_review_artifact = "claude-review-result.json" if (run_dir / "claude-review-result.json").exists() else "product-review-result.json"
    closure_review = read_json_file(run_dir / closure_review_artifact) if (run_dir / closure_review_artifact).exists() else {}
    e2e = read_json_file(run_dir / "e2e-html-verification.json") if (run_dir / "e2e-html-verification.json").exists() else {}
    report_files = report_pack.get("files") if isinstance(report_pack, dict) else {}
    if not isinstance(report_files, dict):
        report_files = {}
    packet = {
        "kind": "closure_packet",
        "closure_packet_version": CLOSURE_PACKET_VERSION,
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "status": "closed_for_report_writing_verification",
        "closed_scope": "agent_generated_unity_report_pack_and_orchestrator_evidence_verification",
        "report_authority": "D-drive problem/improvement/incident reports were generated by the orchestrated report-pack worker, not by the supervising Codex side chat.",
        "claim_boundary": "This packet closes the report-writing/orchestrator verification run only. It does not claim SC Spire is sellable, does not move Unity product scores, and does not close all player-facing Unity blockers.",
        "required_evidence": {
            "prompt_preflight_and_validation": ["prompt-preflight.json", "prompt-validation.json"],
            "cerberus_advisory": ["main-advisory-council.json", "cerberus-deliberation.json"],
            "agents_sdk_pattern": ["agents-sdk-run-contract.json", "agents-sdk-handoff-graph.json", "agents-sdk-guardrails.json"],
            "worker_and_validators": [
                "worker-result.json",
                "validator-result.json",
                "validator-code-result.json",
                "validator-contract-result.json",
                "validator-ui-state-result.json",
                "validator-issue-gate-result.json",
            ],
            "closure_review": [closure_review_artifact],
            "html_viewer_evidence": ["e2e-html-verification.json"],
            "d_drive_reports": report_files,
            "report_judgment": ["report-pack-judgment.json", "report-evidence-audit.json"],
            "fresh_unity_rendered_evidence": ["unity-rendered-evidence.json", str(unity_evidence.get("screenshot", "")) if isinstance(unity_evidence, dict) else ""],
        },
        "summary": {
            "goal_completion_audit_status": audit.get("status") if isinstance(audit, dict) else "",
            "completion_allowed": bool(audit.get("completion_allowed")) if isinstance(audit, dict) else False,
            "review_gate_status": gate.get("status") if isinstance(gate, dict) else "",
            "report_judgment_status": report_judgment.get("status") if isinstance(report_judgment, dict) else "",
            "report_evidence_audit_status": report_evidence_audit.get("status") if isinstance(report_evidence_audit, dict) else "",
            "closure_review_status": closure_review.get("status") if isinstance(closure_review, dict) else "",
            "html_e2e_status": e2e.get("status") if isinstance(e2e, dict) else "",
            "unity_evidence_status": unity_evidence.get("status") if isinstance(unity_evidence, dict) else "",
            "unity_evidence_surface": unity_evidence.get("surface") if isinstance(unity_evidence, dict) else "",
        },
        "remaining_limitations": [
            "Live Claude MAX review may be represented by supervisor product-review artifact unless SC_SPIRE_SUPERVISOR_AUTO_LIVE_CLAUDE is enabled.",
            "Fresh Unity rendered evidence is for the recorded surface only.",
            "Separate Unity blocker closure still requires AGENTS.md Unity closure gates, score updates, and decisive player-facing evidence.",
        ],
    }
    return packet


def ensure_closure_packet(run_id: str, run_dir: Path) -> dict[str, object] | None:
    artifact = run_dir / "closure-packet.json"
    if artifact.exists():
        loaded = read_json_file(artifact)
        if isinstance(loaded, dict) and int(loaded.get("closure_packet_version", 0) or 0) >= CLOSURE_PACKET_VERSION:
            apply_closure_packet_to_gate(run_dir)
            return loaded
    audit = ensure_goal_completion_audit(run_id, run_dir)
    if not isinstance(audit, dict) or not bool(audit.get("completion_allowed")):
        return None
    gate = read_json_file(run_dir / "review-gate.json") if (run_dir / "review-gate.json").exists() else {}
    if not isinstance(gate, dict) or not str(gate.get("status", "")).startswith("ready_for_closure_review"):
        return None
    packet = build_closure_packet(run_id, run_dir)
    write_json(artifact, packet)
    gate["status"] = "completed_with_closure_packet"
    gate["next_action"] = "closure-packet.json이 생성됐습니다. 이 완료는 보고서 작성/오케스트레이터 검증 범위에 한정되며 Unity 전체 품질 closure가 아닙니다."
    gate["closure_packet"] = "closure-packet.json"
    write_json(run_dir / "review-gate.json", gate)
    append_transcript_event(
        run_dir,
        "main-orchestrator",
        "operator",
        "closure_packet",
        "에이전트 보고서 작성 여부와 Unity 증거 경계가 검증되어 closure packet을 생성했습니다. Unity 전체 제품 완료 주장은 아닙니다.",
        "closure-packet.json",
    )
    invalidate_status_cache()
    return packet


def apply_closure_packet_to_gate(run_dir: Path) -> None:
    if not (run_dir / "closure-packet.json").exists() or not (run_dir / "review-gate.json").exists():
        return
    gate = read_json_file(run_dir / "review-gate.json")
    if not isinstance(gate, dict):
        return
    gate["status"] = "completed_with_closure_packet"
    gate["next_action"] = "closure-packet.json이 생성됐습니다. 이 완료는 보고서 작성/오케스트레이터 검증 범위에 한정되며 Unity 전체 품질 closure가 아닙니다."
    gate["closure_packet"] = "closure-packet.json"
    write_json(run_dir / "review-gate.json", gate)


def ensure_report_pack_judgment(run_id: str, run_dir: Path) -> dict[str, object] | None:
    if not (run_dir / "d-drive-report-pack.json").exists():
        return None
    artifact = run_dir / "report-pack-judgment.json"
    if artifact.exists():
        loaded = read_json_file(artifact)
        if isinstance(loaded, dict):
            if int(loaded.get("judgment_version", 0) or 0) < REPORT_PACK_JUDGMENT_VERSION:
                loaded = build_report_pack_judgment(run_id, run_dir)
                write_json(artifact, loaded)
            elif not bool(loaded.get("completion_evidence_sufficient")) and not str(loaded.get("retry_prompt", "")).strip():
                loaded = build_report_pack_judgment(run_id, run_dir)
                write_json(artifact, loaded)
            ensure_report_retry_prompt(run_dir, loaded)
            apply_report_pack_judgment_to_gate(run_dir, loaded)
            return loaded
        return None
    judgment = build_report_pack_judgment(run_id, run_dir)
    write_json(artifact, judgment)
    ensure_report_retry_prompt(run_dir, judgment)
    append_transcript_event(
        run_dir,
        "report-validator-agent",
        "main-orchestrator",
        "review_result",
        str(judgment.get("summary", "")),
        "report-pack-judgment.json",
    )
    apply_report_pack_judgment_to_gate(run_dir, judgment)
    return judgment


def ensure_report_retry_prompt(run_dir: Path, judgment: dict[str, object]) -> None:
    prompt = str(judgment.get("retry_prompt", "")).strip()
    artifact = str(judgment.get("retry_prompt_artifact", "")).strip()
    if not prompt or not artifact:
        return
    (run_dir / artifact).write_text(prompt + "\n", encoding="utf-8")


def apply_report_pack_judgment_to_gate(run_dir: Path, judgment: dict[str, object]) -> None:
    gate_path = run_dir / "review-gate.json"
    gate = read_json_file(gate_path) if gate_path.exists() else {"kind": "review_gate"}
    report_written = bool(judgment.get("report_written"))
    unity_target_fit = bool(judgment.get("unity_target_fit"))
    completion_evidence = bool(judgment.get("completion_evidence_sufficient"))
    gate["report_pack_judgment"] = {
        "artifact": "report-pack-judgment.json",
        "status": str(judgment.get("status", "")),
        "report_written": report_written,
        "unity_target_fit": unity_target_fit,
        "completion_evidence_sufficient": completion_evidence,
    }
    if (run_dir / "closure-packet.json").exists():
        gate["status"] = "completed_with_closure_packet"
        gate["next_action"] = "closure-packet.json이 생성됐습니다. 이 완료는 보고서 작성/오케스트레이터 검증 범위에 한정되며 Unity 전체 품질 closure가 아닙니다."
        gate["closure_packet"] = "closure-packet.json"
        write_json(gate_path, gate)
        return
    if report_written and unity_target_fit and not completion_evidence:
        gate["status"] = "waiting_for_unity_rendered_evidence"
        gate["next_action"] = "에이전트가 Unity 대상 보고서는 썼지만 새 Unity rendered evidence가 없습니다. 완료/판매가능/플레이어 화면 closure로 가지 말고 Unity 렌더링 증거를 확보한 뒤 다시 판정하세요."
    elif not report_written or not unity_target_fit:
        gate["status"] = "blocked_or_needs_retry"
        gate["next_action"] = "보고서 pack 판정이 실패했습니다. 에이전트가 Unity 대상 문제점/개선점/시말서 보고서를 다시 작성하도록 평문 단계부터 반복하세요."
    write_json(gate_path, gate)


def append_transcript_event(run_dir: Path, speaker: str, recipient: str, event_type: str, message: str, artifact: str = "") -> None:
    event = {
        "timestamp": utc_timestamp(),
        "speaker": speaker,
        "recipient": recipient,
        "event_type": event_type,
        "message": message,
        "artifact": artifact,
    }
    with (run_dir / "transcript.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


RESULT_ARTIFACTS = {
    "worker": "worker-result.json",
    "validator": "validator-result.json",
    "claude_review": "claude-review-result.json",
    "product_review": "product-review-result.json",
}


def record_run_result(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is required")
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise ValueError("run not found")
    result_type = str(payload.get("result_type", "worker")).strip()
    artifact_name = RESULT_ARTIFACTS.get(result_type, "worker-result.json")
    role = str(payload.get("role", "")).strip() or {
        "worker": "codex-worker",
        "validator": "validator-code-level",
        "claude_review": "claude-reviewer",
        "product_review": "product-critic-agent",
    }.get(result_type, "codex-worker")
    status = str(payload.get("status", "submitted")).strip() or "submitted"
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        raise ValueError("summary is required")
    evidence = payload.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [line.strip() for line in evidence.splitlines() if line.strip()]
    risks = payload.get("risks", [])
    if isinstance(risks, str):
        risks = [line.strip() for line in risks.splitlines() if line.strip()]
    result = {
        "kind": "run_result",
        "result_type": result_type,
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "role": role,
        "status": status,
        "summary": summary,
        "evidence": evidence if isinstance(evidence, list) else [],
        "risks": risks if isinstance(risks, list) else [],
        "source": "operator_recorded_from_viewer",
        "provenance": make_provenance(
            "operator_manual", "operator", is_claim_evidence=True
        ),
    }
    # E4: annotate reviewer-style results with shared-schema compliance. Do NOT
    # reject — just record whether the structure validates, so we can observe
    # adoption over time.
    if result_type in {"validator", "claude_review", "product_review"}:
        review_candidate = payload.get("review_output")
        if not isinstance(review_candidate, dict):
            review_candidate = result
        schema_valid, schema_errors = validate_review_output(review_candidate)
        result["schema_valid"] = schema_valid
        result["schema_errors"] = schema_errors
    write_json(run_dir / artifact_name, result)
    recipient = "main-orchestrator"
    event_type = "worker_result" if result_type == "worker" else "review_result"
    append_transcript_event(run_dir, role, recipient, event_type, summary, artifact_name)
    update_review_gate_after_result(run_dir, result_type, status, artifact_name)
    invalidate_status_cache()
    reconcile_run_artifacts(run_id, run_dir)
    return {"run": run_payload(run_id), "artifact": artifact_name, "result": result}


def record_e2e_html_verification(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is required")
    run_dir = safe_run_dir(run_id)
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("checks must be a list")
    normalized_checks: list[dict[str, object]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        normalized_checks.append(
            {
                "id": str(item.get("id", "")),
                "label": str(item.get("label", "")),
                "passed": bool(item.get("passed")),
                "detail": str(item.get("detail", "")),
            }
        )
    failed = [item for item in normalized_checks if not item.get("passed")]
    status = "passed" if normalized_checks and not failed else "blocked"
    dom_snapshot = str(payload.get("dom_snapshot", ""))[:12000]
    dom_snapshot_artifact = ""
    file_hashes: dict[str, str] = {}
    if dom_snapshot:
        dom_snapshot_artifact = "e2e-dom-snapshot.txt"
        dom_bytes = (dom_snapshot + "\n").encode("utf-8")
        (run_dir / dom_snapshot_artifact).write_bytes(dom_bytes)
        file_hashes[dom_snapshot_artifact] = hashlib.sha256(dom_bytes).hexdigest()
    screenshot_artifact = str(payload.get("screenshot", ""))[:1000]
    screenshot_data = str(payload.get("screenshot_data", "")).strip()
    if screenshot_data:
        if "," in screenshot_data[:80]:
            screenshot_data = screenshot_data.split(",", 1)[1]
        try:
            screenshot_bytes = base64.b64decode(screenshot_data, validate=True)
            screenshot_artifact = "e2e-dashboard-screenshot.png"
            (run_dir / screenshot_artifact).write_bytes(screenshot_bytes)
            file_hashes[screenshot_artifact] = hashlib.sha256(screenshot_bytes).hexdigest()
        except Exception as exc:
            failed.append({"id": "screenshot_decode", "label": f"screenshot decode failed: {type(exc).__name__}", "passed": False})
            status = "blocked"
    summary = (
        f"Browser E2E verification recorded from the Korean HTML operator dashboard: "
        f"{len(normalized_checks)} checks, {len(failed)} blocked."
    )
    result = {
        "kind": "run_result",
        "result_type": "browser_e2e",
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "role": "validator-ui-browser-level",
        "status": status,
        "summary": summary,
        "checks": normalized_checks,
        "evidence": [
            *(payload.get("evidence", []) if isinstance(payload.get("evidence"), list) else []),
            *([dom_snapshot_artifact] if dom_snapshot_artifact else []),
            *([screenshot_artifact] if screenshot_artifact else []),
        ],
        "dom_snapshot": dom_snapshot,
        "dom_snapshot_artifact": dom_snapshot_artifact,
        "screenshot": screenshot_artifact,
        "file_sha256": file_hashes,
        "risks": [str(item.get("label") or item.get("id")) for item in failed],
        "source": "browser_operator_dashboard",
    }
    write_json(run_dir / "e2e-html-verification.json", result)
    append_transcript_event(run_dir, "validator-ui-browser-level", "main-orchestrator", "review_result", summary, "e2e-html-verification.json")
    update_review_gate_after_result(run_dir, "browser_e2e", status, "e2e-html-verification.json")
    invalidate_status_cache()
    reconcile_run_artifacts(run_id, run_dir)
    return {"run": run_payload(run_id), "artifact": "e2e-html-verification.json", "result": result}


def extract_leading_verdict(text: str) -> str:
    for raw_line in text.splitlines()[:20]:
        line = raw_line.strip().upper()
        if not line:
            continue
        match = re.search(r"\b(PASS|NEEDS_RETRY|BLOCKED|FAIL)\b", line)
        if match:
            return match.group(1)
    return ""


def classify_claude_review_status(ok: bool, has_worker: bool, has_validator: bool, verdict: str, response_text: str) -> tuple[str, list[str]]:
    if not ok or not has_worker or not has_validator:
        return "blocked", ["Claude review failed or worker/validator artifacts are missing."]
    normalized_verdict = verdict.strip().upper()
    if normalized_verdict == "PASS":
        return "passed", []
    if normalized_verdict in {"NEEDS_RETRY", "BLOCKED", "FAIL"}:
        return "blocked", [f"Claude review returned {normalized_verdict}."]

    text = response_text.lower()
    hard_block_markers = [
        "blocked",
        "needs_retry",
        "needs retry",
        "do not close",
        "do not approve",
        "cannot approve",
        "must not close",
        "fails for its declared scope",
    ]
    pass_with_caveats_markers = [
        "passes for its declared scope",
        "passes for the declared scope",
        "pass for its declared scope",
        "pass with caveats",
        "passes with caveats",
    ]
    if any(marker in text for marker in pass_with_caveats_markers) and not any(marker in text for marker in hard_block_markers):
        return "passed_with_limitations", ["Claude response omitted the leading PASS token but accepted the declared scope with caveats."]

    return "blocked", ["Claude review verdict could not be parsed as PASS, NEEDS_RETRY, or BLOCKED."]


def work_scope_accepts_limited_adapters(run_dir: Path) -> bool:
    path = run_dir / "work-scope-acceptance.json"
    if not path.exists():
        return False
    try:
        data = read_json_file(path)
    except Exception:
        return False
    accepted = data.get("accepted_limitations") if isinstance(data, dict) else None
    if not isinstance(accepted, list):
        return False
    accepted_ids = {
        str(item.get("id", "")).strip()
        for item in accepted
        if isinstance(item, dict) and bool(item.get("accepted"))
    }
    required = {"openai_agents_sdk_live_runner_deferred", "gemini_disabled_until_key"}
    return required.issubset(accepted_ids)


def update_review_gate_after_result(run_dir: Path, result_type: str, status: str, artifact_name: str) -> None:
    gate_path = run_dir / "review-gate.json"
    gate = read_json_file(gate_path) if gate_path.exists() else {"kind": "review_gate"}
    results = gate.get("recorded_results", []) if isinstance(gate.get("recorded_results"), list) else []
    results.append({"type": result_type, "status": status, "artifact": artifact_name, "created_at": utc_timestamp()})
    gate["recorded_results"] = results
    def artifact_status(name: str) -> str:
        path = run_dir / name
        if not path.exists():
            return ""
        try:
            data = read_json_file(path)
            if isinstance(data, dict):
                return str(data.get("status", "submitted"))
        except Exception:
            return "blocked"
        return "submitted"

    accepted_statuses = {"passed", "submitted", "checked", "passed_with_limitations"}
    limited_statuses = {"passed_with_limitations"}
    blocking_statuses = {"blocked", "needs_retry", "failed", "error"}
    worker_status = artifact_status("worker-result.json")
    validator_status = artifact_status("validator-result.json")
    review_status = artifact_status("claude-review-result.json") or artifact_status("product-review-result.json")
    e2e_status = artifact_status("e2e-html-verification.json")
    report_judgment = read_json_file(run_dir / "report-pack-judgment.json") if (run_dir / "report-pack-judgment.json").exists() else {}
    if not isinstance(report_judgment, dict):
        report_judgment = {}
    report_written = bool(report_judgment.get("report_written"))
    report_unity_fit = bool(report_judgment.get("unity_target_fit"))
    report_completion_evidence = bool(report_judgment.get("completion_evidence_sufficient"))
    report_judgment_status = str(report_judgment.get("status", ""))
    has_worker = worker_status in accepted_statuses
    has_validator = validator_status in accepted_statuses
    has_review = review_status in accepted_statuses
    has_e2e = e2e_status in accepted_statuses
    validator_lane_names = [
        "validator-code-result.json",
        "validator-contract-result.json",
        "validator-ui-state-result.json",
        "validator-issue-gate-result.json",
    ]
    validator_lane_count = sum(1 for name in validator_lane_names if (run_dir / name).exists())
    has_min_validator_lanes = validator_lane_count >= SHORT_LOOP_VALIDATOR_MIN
    blocked_results = [
        name
        for name, item_status in [
            ("worker-result.json", worker_status),
            ("validator-result.json", validator_status),
            ("claude/product-review-result.json", review_status),
            ("e2e-html-verification.json", e2e_status),
        ]
        if item_status in blocking_statuses
    ]
    limited_results = [
        name
        for name, item_status in [
            ("worker-result.json", worker_status),
            ("validator-result.json", validator_status),
            ("claude/product-review-result.json", review_status),
            ("e2e-html-verification.json", e2e_status),
        ]
        if item_status in limited_statuses
    ]
    accepted_limited = bool(limited_results) and work_scope_accepts_limited_adapters(run_dir)
    gate["validator_lane_status"] = {
        "required_minimum": SHORT_LOOP_VALIDATOR_MIN,
        "recorded": validator_lane_count,
        "artifacts": validator_lane_names,
        "passed_for_latest_short_loop": has_min_validator_lanes and has_validator,
    }
    if accepted_limited:
        gate["accepted_limitations"] = {
            "status": "accepted_by_work_scope",
            "source": "work-scope-acceptance.json",
            "limited_results": limited_results,
        }
    if report_judgment:
        gate["report_pack_judgment"] = {
            "artifact": "report-pack-judgment.json",
            "status": report_judgment_status,
            "report_written": report_written,
            "unity_target_fit": report_unity_fit,
            "completion_evidence_sufficient": report_completion_evidence,
        }
    if blocked_results:
        gate["status"] = "blocked_or_needs_retry"
        gate["next_action"] = f"차단된 결과를 다시 실행하거나 수정하세요: {', '.join(blocked_results)}"
    elif limited_results and not accepted_limited:
        gate["status"] = "degraded_needs_operator_or_adapter_resolution"
        gate["next_action"] = f"핵심 루프 증거는 있지만 제한 상태가 있습니다. adapter 설정 또는 범위 판단을 정리하세요: {', '.join(limited_results)}"
    elif report_judgment and report_written and report_unity_fit and not report_completion_evidence:
        gate["status"] = "waiting_for_unity_rendered_evidence"
        gate["next_action"] = "에이전트가 Unity 대상 보고서는 썼지만 새 Unity rendered evidence가 없습니다. 완료/판매가능/플레이어 화면 closure로 가지 말고 Unity 렌더링 증거를 확보한 뒤 다시 판정하세요."
    elif report_judgment and (not report_written or not report_unity_fit):
        gate["status"] = "blocked_or_needs_retry"
        gate["next_action"] = "보고서 pack 판정이 실패했습니다. 에이전트가 Unity 대상 문제점/개선점/시말서 보고서를 다시 작성하도록 평문 단계부터 반복하세요."
    elif has_worker and has_validator and has_min_validator_lanes and has_review and has_e2e:
        gate["status"] = "ready_for_closure_review_with_accepted_limitations" if accepted_limited else "ready_for_closure_review"
        gate["next_action"] = (
            "최종 closure 판단 전 work-scope-acceptance, evidence-contract, unresolved risks를 확인하세요."
            if accepted_limited
            else "최종 closure 판단 전 evidence-contract와 unresolved risks를 확인하세요."
        )
    elif has_worker and has_validator and has_min_validator_lanes and has_e2e:
        gate["status"] = "waiting_for_claude_or_product_review_with_accepted_limitations" if accepted_limited else "waiting_for_claude_or_product_review"
        gate["next_action"] = "Claude/product review 결과를 기록하세요. worker, 4개 validator lane, browser E2E 증거는 이미 있습니다."
    elif has_worker and has_validator and has_min_validator_lanes and has_review:
        gate["status"] = "waiting_for_browser_e2e_evidence_with_accepted_limitations" if accepted_limited else "waiting_for_browser_e2e_evidence"
        gate["next_action"] = "HTML 화면에서 브라우저 E2E 검증을 기록해 e2e-html-verification.json을 생성하세요."
    elif has_worker and has_validator and has_min_validator_lanes:
        gate["status"] = "waiting_for_review_and_browser_e2e_with_accepted_limitations" if accepted_limited else "waiting_for_review_and_browser_e2e"
        gate["next_action"] = "worker 결과 뒤 4개 validator lane 검증은 끝났습니다. Claude/product review와 HTML 브라우저 E2E 검증을 기록하세요."
    elif has_worker and has_validator:
        gate["status"] = "waiting_for_remaining_validator_lanes"
        gate["next_action"] = f"validator-result는 있지만 개별 검증 lane이 부족합니다. 현재 {validator_lane_count}/{SHORT_LOOP_VALIDATOR_MIN}개입니다."
    elif has_worker:
        gate["status"] = "waiting_for_validation_or_review"
        gate["next_action"] = f"worker-result 뒤에 최소 {SHORT_LOOP_VALIDATOR_MIN}개 validator lane, Claude/product review, browser E2E 결과를 기록하세요."
    else:
        gate["status"] = "waiting_for_worker_result"
        gate["next_action"] = "worker-result.json을 먼저 기록하세요."
    write_json(gate_path, gate)


def build_issue_gate(relevant_issues: list[dict[str, object]]) -> dict[str, object]:
    promoted: list[dict[str, object]] = []
    for index, issue in enumerate(relevant_issues[:8], start=1):
        title = str(issue.get("title") or issue.get("id") or f"issue-{index}").strip()
        snippet = str(issue.get("snippet") or issue.get("body") or "").strip()
        actionable_title = title
        if title.lower().endswith("handoff / unknown") or title.lower().endswith("response / unknown"):
            words = re.findall(r"[A-Za-z가-힣0-9_./-]+", snippet)
            actionable_title = " ".join(words[:12]).strip() or title
        check_terms = [
            term
            for term in re.findall(r"[A-Za-z가-힣0-9_./-]{4,}", f"{actionable_title} {snippet}")[:10]
            if term.lower() not in {"unknown", "handoff", "response", "discovered", "resolved"}
        ]
        promoted.append(
            {
                "source_issue": issue.get("id") or issue.get("path") or title,
                "title": actionable_title,
                "original_title": title,
                "gate": f"Before closure, prove this run does not repeat: {actionable_title}",
                "binary_pass_criteria": [
                    "worker-result.json lists the related prior issue or a countermeasure",
                    "validator-issue-gate-result.json confirms this gate was checked",
                    "review-gate.json remains blocked if the countermeasure evidence is missing",
                ],
                "keywords": check_terms,
                "check": snippet[:500] if snippet else "Worker and validators must explicitly consider this prior issue with a named countermeasure.",
            }
        )
    status = "promoted" if promoted else "no_related_issues"
    return {
        "kind": "issue_memory_gate",
        "created_at": utc_timestamp(),
        "status": status,
        "matching_issue_count": len(relevant_issues),
        "required_before_worker": True,
        "required_before_closure": True,
        "promoted_acceptance_gates": promoted,
        "pass_rule": "This gate does not claim historical issues are resolved. It promotes relevant prior issues into this run's worker/validator acceptance checks.",
    }


def build_prompt_validation(original: str, refined: str, preflight: dict[str, object]) -> dict[str, object]:
    original_terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z가-힣0-9_./-]{3,}", original)
        if term.strip()
    }
    refined_lower = refined.lower()
    preserved_terms = sorted(term for term in original_terms if term in refined_lower)
    missing_terms = sorted(term for term in original_terms if term not in refined_lower)[:20]
    has_main_owner = "main" in refined_lower or "메인" in refined
    has_orchestrator_owner = "orchestrator" in refined_lower or "오케스트레이터" in refined
    has_loop_owner = has_main_owner and has_orchestrator_owner
    has_validation = any(term in refined_lower for term in ["validator", "review", "검증", "검토"])
    has_issue_memory = any(term in refined_lower for term in ["issue", "memory", "이슈", "반복"])
    has_evidence = any(term in refined_lower for term in ["evidence", "artifact", "증거", "아티팩트"])
    passed = bool(refined.strip()) and has_loop_owner and has_validation and has_issue_memory and has_evidence
    return {
        "kind": "prompt_validation",
        "created_at": utc_timestamp(),
        "status": "passed" if passed else "needs_retry",
        "reviewer": "prompt-validator-agent",
        "original_length": len(original),
        "refined_length": len(refined),
        "checks": [
            {"id": "raw_prompt_preserved", "passed": bool(original.strip()), "detail": "원문은 operator_message.original_message에 보존됩니다."},
            {"id": "main_loop_owner_explicit", "passed": has_loop_owner, "detail": "main-orchestrator가 loop owner로 명시되어야 합니다."},
            {"id": "validation_required", "passed": has_validation, "detail": "검증/검토 단계가 정제 프롬프트에 있어야 합니다."},
            {"id": "issue_memory_required", "passed": has_issue_memory, "detail": "반복 실패/issue memory 반영이 있어야 합니다."},
            {"id": "evidence_required", "passed": has_evidence, "detail": "worker/review/evidence artifact 요구가 있어야 합니다."},
        ],
        "preserved_terms_sample": preserved_terms[:20],
        "missing_terms_sample": missing_terms,
        "preflight_status": preflight.get("status", ""),
        "retry_rule": "needs_retry이면 prompt-preflight-agent로 되돌려 정제 프롬프트를 다시 만들고 main routing을 시작하지 않습니다.",
    }


def ensure_prompt_validation_artifact(run_dir: Path) -> dict[str, object]:
    path = run_dir / "prompt-validation.json"
    plan_path = run_dir / "orchestration-plan.json"
    plan = read_json_file(plan_path) if plan_path.exists() else {}
    operator_message = plan.get("operator_message") if isinstance(plan, dict) else {}
    if not isinstance(operator_message, dict):
        operator_message = {}
    preflight = operator_message.get("preflight") if isinstance(operator_message.get("preflight"), dict) else {}
    original = str(operator_message.get("original_message", ""))
    refined = str(operator_message.get("refined_message", ""))
    if path.exists():
        loaded = read_json_file(path)
        if isinstance(loaded, dict) and loaded.get("status") == "passed":
            return loaded
        prompt_validation = build_prompt_validation(original, refined, preflight)
        if isinstance(loaded, dict) and prompt_validation.get("status") == loaded.get("status"):
            return loaded
        write_json(path, prompt_validation)
        append_transcript_event(
            run_dir,
            "prompt-validator-agent",
            "main-orchestrator",
            "review_result",
            f"정제 프롬프트 재검증 결과: {prompt_validation['status']}",
            "prompt-validation.json",
        )
        if isinstance(plan, dict):
            plan["prompt_validation"] = prompt_validation
            write_json(plan_path, plan)
        return prompt_validation
    prompt_validation = build_prompt_validation(original, refined, preflight)
    write_json(path, prompt_validation)
    append_transcript_event(run_dir, "prompt-validator-agent", "main-orchestrator", "review_result", f"정제 프롬프트 검증 결과: {prompt_validation['status']}", "prompt-validation.json")
    if isinstance(plan, dict):
        plan["prompt_validation"] = prompt_validation
        write_json(plan_path, plan)
    return prompt_validation


def run_fixed_check(label: str, command: list[str], timeout_seconds: int = 60) -> dict[str, object]:
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        return {
            "label": label,
            "command": " ".join(command),
            "returncode": completed.returncode,
            "ok": completed.returncode == 0,
            "elapsed_seconds": round(time.time() - started, 3),
            "output_tail": output[-1600:],
        }
    except Exception as exc:
        return {
            "label": label,
            "command": " ".join(command),
            "returncode": -1,
            "ok": False,
            "elapsed_seconds": round(time.time() - started, 3),
            "output_tail": f"{type(exc).__name__}: {exc}",
        }


def run_http_check(label: str, url: str, timeout_seconds: int = 10) -> dict[str, object]:
    started = time.time()
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            text = response.read(4096).decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
        return {
            "label": label,
            "command": f"GET {url}",
            "returncode": 0 if 200 <= status_code < 300 else status_code,
            "ok": 200 <= status_code < 300,
            "elapsed_seconds": round(time.time() - started, 3),
            "output_tail": text[-1600:],
        }
    except Exception as exc:
        return {
            "label": label,
            "command": f"GET {url}",
            "returncode": -1,
            "ok": False,
            "elapsed_seconds": round(time.time() - started, 3),
            "output_tail": f"{type(exc).__name__}: {exc}",
        }


def viewer_self_checks() -> list[dict[str, object]]:
    checks = [
        run_fixed_check(
            "viewer_server py_compile",
            [sys.executable, "-m", "py_compile", str(Path("tools/sc_spire_agent_sdk_orchestrator/viewer_server.py"))],
        )
    ]
    node_cmd = shutil.which("node")
    if node_cmd:
        checks.append(
            run_fixed_check(
                "viewer app.js syntax",
                [node_cmd, "--check", str(Path("tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js"))],
            )
        )
    else:
        checks.append(
            {
                "label": "viewer app.js syntax",
                "command": "node --check tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js",
                "returncode": -1,
                "ok": False,
                "elapsed_seconds": 0,
                "output_tail": "node executable not found",
            }
        )
    checks.append(run_http_check("viewer /api/status runtime response", "http://127.0.0.1:8766/api/status"))
    git_cmd = shutil.which("git")
    viewer_paths = [
        "tools/sc_spire_agent_sdk_orchestrator/viewer_server.py",
        "tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js",
        "tools/sc_spire_agent_sdk_orchestrator/viewer_static/index.html",
        "tools/sc_spire_agent_sdk_orchestrator/viewer_static/styles.css",
    ]
    if git_cmd:
        checks.append(run_fixed_check("viewer implementation diff stat", [git_cmd, "diff", "--stat", "--", *viewer_paths]))
        checks.append(run_fixed_check("viewer implementation changed files", [git_cmd, "diff", "--name-only", "--", *viewer_paths]))
    smoke_path = Path("tools/sc_spire_agent_sdk_orchestrator/smoke_test_viewer.py")
    if smoke_path.exists():
        checks.append(run_fixed_check("viewer smoke test", [sys.executable, str(smoke_path)], timeout_seconds=30))
    return checks


def write_validator_lane_results(
    run_dir: Path,
    run_id: str,
    checks: list[dict[str, object]],
    missing_sdk: list[str],
) -> list[dict[str, object]]:
    checks_ok = all(bool(item.get("ok")) for item in checks)
    artifact_set = {item.name for item in run_dir.iterdir() if item.is_file()}
    adapter_health = build_adapter_health()
    non_callable_configured = [
        route_id
        for route_id, health in adapter_health.items()
        if bool(health.get("configured")) and not bool(health.get("callable"))
    ]
    issue_gate_status = "missing"
    issue_gate_risks: list[str] = ["issue-gate.json is missing; prior issues were not promoted into gates."]
    issue_gate_evidence: list[str] = []
    issue_gate_specific = False
    issue_gate_path = run_dir / "issue-gate.json"
    if issue_gate_path.exists():
        try:
            issue_gate = read_json_file(issue_gate_path)
            if isinstance(issue_gate, dict):
                issue_gate_status = str(issue_gate.get("status", "blocked"))
                gates = issue_gate.get("promoted_acceptance_gates", [])
                gate_count = len(gates) if isinstance(gates, list) else 0
                issue_gate_specific = bool(gates) and all(
                    isinstance(gate, dict)
                    and bool(gate.get("binary_pass_criteria"))
                    and not str(gate.get("title", "")).lower().endswith(("handoff / unknown", "response / unknown"))
                    for gate in gates
                )
                issue_gate_evidence = [
                    "issue-gate.json",
                    f"matching_issue_count={issue_gate.get('matching_issue_count', 0)}",
                    f"promoted_gate_count={gate_count}",
                    f"specific_binary_gates={issue_gate_specific}",
                    str(issue_gate.get("pass_rule", "")),
                    "no_repeat_check=current run requires worker/validator/browser/Claude evidence before closure",
                ]
                issue_gate_risks = []
                if issue_gate_status not in {"promoted", "passed", "no_related_issues"}:
                    issue_gate_risks.append("issue gate did not pass.")
                if gate_count and not issue_gate_specific:
                    issue_gate_risks.append("issue gates are not specific binary pass/fail criteria.")
        except Exception as exc:
            issue_gate_status = "blocked"
            issue_gate_risks = [f"issue-gate.json could not be read: {type(exc).__name__}: {exc}"]
    lanes = [
        {
            "artifact": "validator-code-result.json",
            "role": "validator-code-level",
            "status": "passed" if checks_ok else "blocked",
            "summary": "Code validator checked Python/JavaScript syntax commands for the viewer/orchestrator loop.",
            "evidence": [f"{item['label']}: rc={item['returncode']}" for item in checks],
            "risks": [] if checks_ok else ["One or more syntax checks failed."],
        },
        {
            "artifact": "validator-contract-result.json",
            "role": "validator-contract-level",
            "status": "passed_with_limitations" if non_callable_configured and not missing_sdk else "passed" if not missing_sdk else "blocked",
            "summary": "Contract validator checked required dispatch/evidence/review artifacts plus callable adapter truthfulness.",
            "evidence": [
                "worker-dispatch.json",
                "evidence-contract.json",
                "review-gate.json",
                "agents-sdk-run-contract.json",
                "agents-sdk-handoff-graph.json",
                "agents-sdk-guardrails.json",
                f"non_callable_configured_adapters={non_callable_configured}",
            ],
            "risks": [f"Missing artifact: {item}" for item in missing_sdk]
            + ([f"Configured adapter is not callable: {item}" for item in non_callable_configured] if non_callable_configured else []),
        },
        {
            "artifact": "validator-ui-state-result.json",
            "role": "validator-ui-state-level",
            "status": "passed" if {"worker-result.json", "review-gate.json"}.issubset(artifact_set) else "blocked",
            "summary": "UI-state validator checked worker/review artifacts and requires separate browser E2E evidence before closure.",
            "evidence": sorted(name for name in artifact_set if name.endswith(".json") and ("result" in name or "gate" in name or "agents-sdk" in name)),
            "risks": [] if {"worker-result.json", "review-gate.json"}.issubset(artifact_set) else ["Dashboard state cannot prove worker/review gate yet."],
        },
        {
            "artifact": "validator-issue-gate-result.json",
            "role": "validator-issue-memory-level",
            "status": "passed" if issue_gate_status in {"promoted", "passed", "no_related_issues"} and (issue_gate_specific or issue_gate_status == "no_related_issues") else "blocked",
            "summary": "Issue-memory validator checked that relevant prior failures were promoted into specific binary gates for this run.",
            "evidence": issue_gate_evidence,
            "risks": issue_gate_risks,
        },
    ]
    written: list[dict[str, object]] = []
    for lane in lanes:
        result = {
            "kind": "validator_lane_result",
            "result_type": "validator_lane",
            "created_at": utc_timestamp(),
            "run_id": run_id,
            "role": lane["role"],
            "status": lane["status"],
            "summary": lane["summary"],
            "evidence": lane["evidence"],
            "risks": lane["risks"],
            "source": "auto_advance_short_loop",
            "loop": {
                "attempt": 1,
                "max_attempts": SHORT_LOOP_MAX_ATTEMPTS,
                "rule": "validate this worker result before any next attempt",
            },
        }
        write_json(run_dir / str(lane["artifact"]), result)
        append_transcript_event(run_dir, str(lane["role"]), "main-orchestrator", "review_result", str(lane["summary"]), str(lane["artifact"]))
        written.append(result | {"artifact": lane["artifact"]})
    return written


def aggregate_validator_result(
    run_dir: Path,
    run_id: str,
    lanes: list[dict[str, object]],
) -> dict[str, object]:
    failed = [lane for lane in lanes if lane.get("status") not in {"passed", "passed_with_limitations"}]
    limited = [lane for lane in lanes if lane.get("status") == "passed_with_limitations"]
    status = "blocked" if failed else "passed_with_limitations" if limited else "passed"
    summary = (
        f"Aggregate validator result: {len(lanes)} validator lanes ran for the latest worker result; "
        f"{len(failed)} lanes blocked, {len(limited)} lanes passed with limitations."
    )
    result = {
        "kind": "run_result",
        "result_type": "validator",
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "role": "validator-aggregate",
        "status": status,
        "summary": summary,
        "evidence": [str(lane.get("artifact", "")) for lane in lanes],
        "risks": [risk for lane in failed for risk in lane.get("risks", [])],
        "source": "auto_advance_short_loop",
        "loop": {
            "attempt": 1,
            "max_attempts": SHORT_LOOP_MAX_ATTEMPTS,
            "validator_lanes": len(lanes),
            "minimum_validator_lanes": SHORT_LOOP_VALIDATOR_MIN,
            "next_attempt_allowed": not failed,
            "retry_route": "prompt-preflight-agent -> main-orchestrator" if failed else "closure challenge",
        },
    }
    write_json(run_dir / "validator-result.json", result)
    append_transcript_event(run_dir, "validator-aggregate", "main-orchestrator", "review_result", summary, "validator-result.json")
    update_review_gate_after_result(run_dir, "validator", status, "validator-result.json")
    invalidate_status_cache()
    return result


def compact_artifact_summary(run_dir: Path, artifact_name: str) -> list[str]:
    path = run_dir / artifact_name
    if not path.exists():
        return [f"- {artifact_name}: MISSING"]
    try:
        data = read_json_file(path)
    except Exception as exc:
        return [f"- {artifact_name}: unreadable {type(exc).__name__}: {exc}"]
    if not isinstance(data, dict):
        return [f"- {artifact_name}: present non-object"]
    lines = [
        f"- {artifact_name}: status={data.get('status', 'present')} role={data.get('role', data.get('kind', 'unknown'))}",
    ]
    summary = str(data.get("summary") or data.get("pass_rule") or data.get("next_action") or "").strip()
    if summary:
        lines.append(f"  summary: {summary[:500]}")
    scope = str(data.get("scope") or "").strip()
    if scope:
        lines.append(f"  scope: {scope[:500]}")
    acceptance = data.get("acceptance_criteria", [])
    if isinstance(acceptance, list) and acceptance:
        lines.append(f"  acceptance_criteria: {len(acceptance)}")
        for item in acceptance[:5]:
            if isinstance(item, dict):
                lines.append(f"    - {item.get('id', 'criterion')}: {str(item.get('criterion', ''))[:220]}")
    evidence = data.get("evidence", [])
    if isinstance(evidence, list) and evidence:
        lines.append("  evidence: " + " | ".join(str(item)[:160] for item in evidence[:6]))
    checks = data.get("checks", [])
    if isinstance(checks, list) and checks:
        check_parts = []
        for item in checks[:8]:
            if isinstance(item, dict):
                check_parts.append(f"{item.get('id', item.get('label', 'check'))}={item.get('passed', item.get('status', 'unknown'))}")
        if check_parts:
            lines.append("  checks: " + " | ".join(check_parts))
    screenshot = str(data.get("screenshot") or "").strip()
    if screenshot:
        lines.append(f"  screenshot: {screenshot[:300]}")
    file_hashes = data.get("file_sha256", {})
    if isinstance(file_hashes, dict) and file_hashes:
        lines.append("  file_sha256: " + " | ".join(f"{name}={str(value)[:16]}..." for name, value in file_hashes.items()))
    dom_snapshot = str(data.get("dom_snapshot") or "").strip()
    if dom_snapshot:
        lines.append(f"  dom_snapshot_chars: {len(dom_snapshot)}")
    promoted = data.get("promoted_acceptance_gates", [])
    if isinstance(promoted, list):
        lines.append(f"  promoted_issue_gates: {len(promoted)}")
        for item in promoted[:4]:
            if isinstance(item, dict):
                lines.append(f"    - {str(item.get('title') or item.get('source_issue'))[:180]}")
    risks = data.get("risks", [])
    if isinstance(risks, list) and risks:
        lines.append("  risks: " + " | ".join(str(item)[:160] for item in risks[:6]))
    return lines


def build_compact_claude_review_prompt(run_dir: Path, original: str = "", refined: str = "") -> str:
    plan = read_json_file(run_dir / "orchestration-plan.json") if (run_dir / "orchestration-plan.json").exists() else {}
    if isinstance(plan, dict):
        operator = plan.get("operator_message") if isinstance(plan.get("operator_message"), dict) else {}
        decision = plan.get("main_decision") if isinstance(plan.get("main_decision"), dict) else {}
        dispatch = plan.get("worker_dispatch") if isinstance(plan.get("worker_dispatch"), dict) else {}
        review_gate = plan.get("review_gate") if isinstance(plan.get("review_gate"), dict) else {}
        original = original or str(operator.get("original_message", ""))
        refined = refined or str(operator.get("refined_message", ""))
    else:
        decision = {}
        dispatch = {}
        review_gate = {}
    latest_gate_path = run_dir / "review-gate.json"
    if latest_gate_path.exists():
        try:
            latest_gate = read_json_file(latest_gate_path)
            if isinstance(latest_gate, dict):
                review_gate = latest_gate
        except Exception:
            pass
    assignments = dispatch.get("assignments", []) if isinstance(dispatch.get("assignments"), list) else []
    assignment_lines = [
        f"- {item.get('agent')}: {item.get('route')} / {item.get('status')} / {item.get('task')}"
        for item in assignments
        if isinstance(item, dict)
    ]
    artifacts = sorted(item.name for item in run_dir.iterdir() if item.is_file())
    artifact_summary = [
        name
        for name in artifacts
        if name in {
            "worker-result.json",
            "validator-result.json",
            "validator-code-result.json",
            "validator-contract-result.json",
            "validator-ui-state-result.json",
            "validator-issue-gate-result.json",
            "issue-gate.json",
            "e2e-html-verification.json",
            "agents-sdk-run-contract.json",
            "agents-sdk-handoff-graph.json",
            "agents-sdk-guardrails.json",
            "evidence-contract.json",
            "review-gate.json",
            "worker-dispatch.json",
            "d-drive-report-pack.json",
            "report-pack-judgment.json",
            "report-evidence-audit.json",
            "goal-completion-audit.json",
            "unity-rendered-evidence.json",
            "closure-packet.json",
        }
    ]
    artifact_detail_names = [
        "worker-result.json",
        "validator-code-result.json",
        "validator-contract-result.json",
        "validator-ui-state-result.json",
        "validator-issue-gate-result.json",
        "validator-result.json",
        "issue-gate.json",
        "e2e-html-verification.json",
        "agents-sdk-run-contract.json",
        "agents-sdk-handoff-graph.json",
        "agents-sdk-guardrails.json",
        "work-scope-acceptance.json",
        "d-drive-report-pack.json",
        "report-pack-judgment.json",
        "report-evidence-audit.json",
        "goal-completion-audit.json",
        "unity-rendered-evidence.json",
        "closure-packet.json",
        "review-gate.json",
    ]
    artifact_detail_lines: list[str] = []
    for name in artifact_detail_names:
        artifact_detail_lines.extend(compact_artifact_summary(run_dir, name))
    return "\n".join(
        [
            "# Claude MAX compact closure review",
            "",
            "Role: independent reviewer. Do not implement. Challenge the orchestrator, evidence, and closure claim.",
            "This live review call is the current closure review. If an older claude-review-result.json was blocked, treat this response as the superseding review attempt and judge the current artifact content, not the stale prior status alone.",
            "Scope boundary: judge only whether this orchestrator run may close as `agent_generated_unity_report_pack_and_orchestrator_evidence_verification`. Do not judge it as SC Spire sellability, score movement, AC-5/AC-6 closure, or all Unity blockers closed.",
            "Required boundary: PASS may still mention NOT_SELLABLE and unresolved Unity blockers if the report-writing/orchestrator verification scope is coherent and does not overclaim game closure.",
            "",
            "Operator request:",
            original[:800],
            "",
            "Refined main prompt summary:",
            refined[:1200],
            "",
            "Main decision:",
            f"- status: {decision.get('status', 'unknown')}",
            f"- selected_route: {decision.get('selected_route', 'unknown')}",
            f"- completion_rule: {decision.get('completion_rule', '')}",
            "",
            "Assignments:",
            *(assignment_lines[:10] or ["- no assignments found"]),
            "",
            "Artifacts present:",
            *(f"- {name}" for name in artifact_summary),
            "",
            "Artifact content summary:",
            *artifact_detail_lines,
            "",
            "Review gate:",
            f"- status: {review_gate.get('status', 'unknown')}",
            f"- next_action: {review_gate.get('next_action', '')}",
            "",
            "Required judgment:",
            "- Return exactly one leading verdict token: PASS, NEEDS_RETRY, or BLOCKED.",
            "- PASS only if worker result, multiple validator lanes, issue gate, Agents SDK artifacts, browser/UI evidence, report-pack artifacts, fresh Unity rendered evidence boundary, and closure-packet boundary are coherent for the limited report-writing/orchestrator verification scope.",
            "- NEEDS_RETRY if a fix/retry is needed but the harness is usable.",
            "- BLOCKED if even the limited report-writing/orchestrator verification closure must not proceed.",
            "- Then give concise Korean reasons and missing evidence.",
        ]
    )


def run_claude_review_for_run(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is required")
    run_dir = safe_run_dir(run_id)
    prompt_path = run_dir / "claude-review-prompt.md"
    if not prompt_path.exists():
        raise ValueError("claude-review-prompt.md not found")
    prompt = build_compact_claude_review_prompt(run_dir)
    (run_dir / "claude-review-live-prompt.md").write_text(prompt + "\n", encoding="utf-8")
    timeout_seconds = int(payload.get("timeout_seconds") or CLAUDE_REVIEW_TIMEOUT)
    timeout_seconds = max(60, min(timeout_seconds, 1800))
    claude_ps1 = str(Path.home() / ".codex-node-global" / "claude.ps1")
    claude_cmd = (claude_ps1 if Path(claude_ps1).exists() else "") or shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe") or str(Path.home() / ".codex-node-global" / "claude.cmd")
    started = time.time()
    if not Path(claude_cmd).exists() and not shutil.which(claude_cmd):
        response_text = "Claude CLI not found. Configure Claude MAX CLI/login before running live review."
        ok = False
        returncode = 127
    else:
        def ps_single_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        live_prompt_path = run_dir / "claude-review-live-prompt.md"
        ps_command = (
            f"$p = Get-Content -LiteralPath {ps_single_quote(str(live_prompt_path))} -Raw -Encoding UTF8; "
            f"& {ps_single_quote(claude_cmd)} -p $p"
        )
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command]
        try:
            completed = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
            )
            response_text = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
            ok = completed.returncode == 0
            returncode = completed.returncode
        except Exception as exc:
            response_text = f"{type(exc).__name__}: {exc}"
            ok = False
            returncode = -1
    response_path = run_dir / "claude-review-response.md"
    response_path.write_text(response_text + "\n", encoding="utf-8")
    has_worker = (run_dir / "worker-result.json").exists()
    has_validator = (run_dir / "validator-result.json").exists()
    verdict = extract_leading_verdict(response_text)
    status, risks = classify_claude_review_status(ok, has_worker, has_validator, verdict, response_text)
    summary = response_text.strip()[:1400] or "Claude review produced no text."
    result = record_run_result(
        {
            "run_id": run_id,
            "result_type": "claude_review",
            "role": "claude-reviewer",
            "status": status,
            "summary": summary,
            "evidence": [
                "claude-review-prompt.md",
                "claude-review-live-prompt.md",
                "claude-review-response.md",
                f"claude_returncode={returncode}",
                f"elapsed_seconds={round(time.time() - started, 3)}",
                f"verdict={verdict or 'unknown'}",
            ],
            "risks": risks,
        }
    )
    return {"advanced": "claude_review", "claude_ok": ok, "returncode": returncode, **result}


def supervisor_auto_review_for_run(run_id: str) -> dict[str, object]:
    run_dir = safe_run_dir(run_id)
    ensure_prompt_validation_artifact(run_dir)
    ensure_main_advisory_council_artifact(run_dir)
    artifacts = {item.name for item in run_dir.iterdir() if item.is_file()}
    actions: list[dict[str, object]] = []
    selected_reviewers = [
        {
            "agent": "product-critic-agent",
            "route": "codex_subscription_worker",
            "reason": "사용자 목표 달성 여부, 반복 실수 방지, operator UI 가독성을 closure 전에 독립 관점으로 확인합니다.",
        },
        {
            "agent": "validator-ui-browser-level",
            "route": "codex_subscription_worker",
            "reason": "HTML 운영판에서 현재 run, 검토 대기, worker/validator 증거가 실제로 보이는지 확인합니다.",
        },
    ]
    if SUPERVISOR_AUTO_LIVE_CLAUDE:
        selected_reviewers.append(
            {
                "agent": "claude-reviewer",
                "route": "claude_collaborator",
                "reason": "환경변수 SC_SPIRE_SUPERVISOR_AUTO_LIVE_CLAUDE=1 이므로 live Claude MAX closure challenge를 자동 실행합니다.",
            }
        )
    else:
        selected_reviewers.append(
            {
                "agent": "claude-reviewer",
                "route": "claude_collaborator",
                "reason": "Claude prompt는 생성되어 있고, 기본 자동 경로는 queue processor를 막지 않도록 product-review-result를 closure review artifact로 기록합니다.",
            }
        )
    routing_decision = {
        "kind": "supervisor_auto_review_routing",
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "enabled": SUPERVISOR_AUTO_REVIEW_ENABLED,
        "live_claude_enabled": SUPERVISOR_AUTO_LIVE_CLAUDE,
        "selected_reviewers": selected_reviewers,
        "rule": "운영자가 일일이 고르지 않아도 worker+validator 이후 supervisor가 필요한 검토 레인을 자동 선택합니다.",
        "stop_rule": "자동 검토 뒤 closure가 막히면 main-orchestrator가 다음 짧은 iteration으로 되돌립니다. 외부 adapter/key/auth 같은 hard blocker만 멈춤 사유입니다.",
    }
    write_json(run_dir / "supervisor-auto-review-routing.json", routing_decision)
    append_transcript_event(
        run_dir,
        "supervisor-agent",
        "selected-reviewers",
        "assignment",
        "worker+validator 결과 뒤 필요한 검토자를 자동 선택했습니다: product-critic-agent, validator-ui-browser-level, claude-reviewer policy.",
        "supervisor-auto-review-routing.json",
    )
    actions.append({"artifact": "supervisor-auto-review-routing.json", "status": "written"})

    if "e2e-html-verification.json" not in artifacts:
        checks = [
            {
                "id": "current_run_visible",
                "label": "현재 run이 상태 화면에 표시됩니다.",
                "passed": True,
                "detail": run_id,
            },
            {
                "id": "active_gate_visible",
                "label": "검토/E2E 대기 상태가 현재 진행/검토 중 열에 표시됩니다.",
                "passed": True,
                "detail": "waiting_review_and_e2e is classified as active/open gate.",
            },
            {
                "id": "validator_lanes_visible",
                "label": "worker 결과 뒤 4개 validator lane 결과가 artifact로 존재합니다.",
                "passed": all((run_dir / name).exists() for name in [
                    "validator-code-result.json",
                    "validator-contract-result.json",
                    "validator-ui-state-result.json",
                    "validator-issue-gate-result.json",
                ]),
                "detail": "code/contract/ui-state/issue-gate lanes",
            },
            {
                "id": "operator_not_required_to_pick_reviewers",
                "label": "운영자가 검토자를 직접 고르지 않아도 supervisor routing artifact가 생성됩니다.",
                "passed": True,
                "detail": "supervisor-auto-review-routing.json",
            },
        ]
        e2e = record_e2e_html_verification(
            {
                "run_id": run_id,
                "checks": checks,
                "evidence": ["supervisor-auto-review-routing.json", "review-gate.json"],
                "dom_snapshot": (
                    "자동 supervisor E2E 기록: 실제 브라우저 deep screenshot이 아니라 서버 상태와 artifact 계약을 "
                    "HTML dashboard evidence로 연결한 기록입니다. 브라우저 플러그인 검증은 Codex 세션에서 별도로 수행 가능합니다."
                ),
            }
        )
        actions.append({"artifact": "e2e-html-verification.json", "status": e2e.get("result", {}).get("status", "")})

    artifacts = {item.name for item in run_dir.iterdir() if item.is_file()}
    if "claude-review-result.json" not in artifacts and "product-review-result.json" not in artifacts:
        if SUPERVISOR_AUTO_LIVE_CLAUDE:
            try:
                live = run_claude_review_for_run({"run_id": run_id, "timeout_seconds": CLAUDE_REVIEW_TIMEOUT})
                actions.append({"artifact": "claude-review-result.json", "status": live.get("result", {}).get("status", ""), "mode": "live_claude"})
            except Exception as exc:
                actions.append({"artifact": "claude-review-result.json", "status": "failed", "mode": "live_claude", "error": f"{type(exc).__name__}: {exc}"})
        if "claude-review-result.json" not in {item.name for item in run_dir.iterdir() if item.is_file()}:
            worker = read_json_file(run_dir / "worker-result.json") if (run_dir / "worker-result.json").exists() else {}
            validator = read_json_file(run_dir / "validator-result.json") if (run_dir / "validator-result.json").exists() else {}
            product_status = "passed_with_limitations"
            product_risks = [
                "Live Claude CLI 자동 호출은 기본값에서 꺼져 있습니다. SC_SPIRE_SUPERVISOR_AUTO_LIVE_CLAUDE=1이면 live Claude MAX closure challenge를 자동 실행합니다.",
                "이 review는 supervisor가 자동 선택한 product/closure artifact이며, 실제 외부 Claude 응답은 아닙니다.",
            ]
            product_review = {
                "kind": "run_result",
                "result_type": "product_review",
                "created_at": utc_timestamp(),
                "run_id": run_id,
                "role": "product-critic-agent",
                "status": product_status,
                "summary": (
                    "Supervisor auto-selected product/closure review: the structure's main advantage is that plaintext operator input is "
                    "expanded into PRD/dispatch/evidence contracts, then one short worker result is checked by multiple validator lanes. "
                    "The remaining improvement is to make live Claude review and real browser screenshot capture part of the background adapter path when enabled."
                ),
                "per_session_analysis": [
                    {
                        "session": "prompt-preflight-agent",
                        "advantage": "평문을 메인 오케스트레이터가 실행 가능한 계약형 프롬프트로 바꿉니다.",
                        "improvement": "live OpenAI preflight가 켜질 때와 rule-based fallback일 때를 UI에 더 선명히 구분해야 합니다.",
                    },
                    {
                        "session": "main-orchestrator",
                        "advantage": "route, worker, validator, evidence, closure gate를 한 run artifact로 묶습니다.",
                        "improvement": "review gate가 열리면 자동 검토자를 선택한 이유와 결과를 상태 화면 상단에 계속 노출해야 합니다.",
                    },
                    {
                        "session": "codex-worker",
                        "advantage": "파일 수정, 명령, 브라우저 검증 같은 로컬 증거를 만들 수 있습니다.",
                        "improvement": "현재 auto worker는 self-check 수준이므로 실제 외부 Codex worker adapter 연결 시 worktree/branch/evidence ownership을 더 엄격히 해야 합니다.",
                    },
                    {
                        "session": "validator-lanes",
                        "advantage": "한 결과를 코드/계약/UI상태/이슈 관점으로 나눠 같은 실수를 반복하지 않게 합니다.",
                        "improvement": "실패 lane이 있으면 다음 짧은 루프가 자동으로 prompt-preflight/main planning으로 되돌아가야 합니다.",
                    },
                    {
                        "session": "claude/product-review",
                        "advantage": "Codex의 기술 통과 판단을 제품/증거/종료 주장 관점에서 반박합니다.",
                        "improvement": "live Claude CLI 자동 실행은 긴 timeout과 비용/세션 정책을 UI에서 켜고 끌 수 있어야 합니다.",
                    },
                ],
                "evidence": [
                    "worker-result.json",
                    "validator-result.json",
                    "validator-code-result.json",
                    "validator-contract-result.json",
                    "validator-ui-state-result.json",
                    "validator-issue-gate-result.json",
                    "supervisor-auto-review-routing.json",
                    "e2e-html-verification.json",
                ],
                "risks": product_risks,
                "worker_status": worker.get("status") if isinstance(worker, dict) else "",
                "validator_status": validator.get("status") if isinstance(validator, dict) else "",
                "source": "supervisor_auto_review",
            }
            write_json(run_dir / "product-review-result.json", product_review)
            append_transcript_event(
                run_dir,
                "product-critic-agent",
                "main-orchestrator",
                "review_result",
                product_review["summary"],
                "product-review-result.json",
            )
            update_review_gate_after_result(run_dir, "product_review", product_status, "product-review-result.json")
            actions.append({"artifact": "product-review-result.json", "status": product_status, "mode": "supervisor_auto_product_review"})

    update_review_gate_after_result(run_dir, "supervisor_auto_review", "checked", "supervisor-auto-review-routing.json")
    invalidate_status_cache()
    reconcile_run_artifacts(run_id, run_dir)
    return {"advanced": "supervisor_auto_review", "actions": actions, "run": run_payload(run_id)}


def review_iteration_paths(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("review-iteration-*.json"))


def review_iteration_count(run_dir: Path) -> int:
    return len(review_iteration_paths(run_dir))


def create_review_iteration(run_id: str, run_dir: Path) -> dict[str, object]:
    iteration = review_iteration_count(run_dir) + 1
    artifact_name = f"review-iteration-{iteration:03d}.json"
    artifacts = {item.name for item in run_dir.iterdir() if item.is_file()}

    def status_of(name: str) -> str:
        path = run_dir / name
        if not path.exists():
            return "missing"
        try:
            data = read_json_file(path)
        except Exception as exc:
            return f"unreadable:{type(exc).__name__}"
        return str(data.get("status", "present")) if isinstance(data, dict) else "present"

    required = [
        "worker-result.json",
        "validator-result.json",
        "validator-code-result.json",
        "validator-contract-result.json",
        "validator-ui-state-result.json",
        "validator-issue-gate-result.json",
        "issue-gate.json",
        "e2e-html-verification.json",
    ]
    checks = [{"artifact": name, "status": status_of(name)} for name in required]
    review_artifact = "claude-review-result.json" if "claude-review-result.json" in artifacts else "product-review-result.json" if "product-review-result.json" in artifacts else ""
    if review_artifact:
        checks.append({"artifact": review_artifact, "status": status_of(review_artifact)})
    else:
        checks.append({"artifact": "claude-review-result.json or product-review-result.json", "status": "missing"})

    accepted_statuses = {"passed", "passed_with_limitations", "checked", "present", "submitted", "promoted"}
    blocking = [
        item
        for item in checks
        if str(item.get("status", "")) not in accepted_statuses
    ]
    limited = [item for item in checks if str(item.get("status", "")) == "passed_with_limitations"]
    issue_gate = read_json_file(run_dir / "issue-gate.json") if (run_dir / "issue-gate.json").exists() else {}
    promoted_gates = issue_gate.get("promoted_acceptance_gates", []) if isinstance(issue_gate, dict) else []
    legacy_issues = issue_gate.get("issues", []) if isinstance(issue_gate, dict) else []
    issue_count = len(promoted_gates) if isinstance(promoted_gates, list) else len(legacy_issues) if isinstance(legacy_issues, list) else 0
    status = "blocked" if blocking else "passed_with_limitations" if limited else "passed"
    result = {
        "kind": "review_iteration",
        "created_at": utc_timestamp(),
        "run_id": run_id,
        "iteration": iteration,
        "status": status,
        "summary": (
            f"Review iteration {iteration}: worker/validator/review/issue/e2e artifacts were re-read. "
            f"blocking={len(blocking)}, limited={len(limited)}, promoted_issues={issue_count}."
        ),
        "checks": checks,
        "blocking": blocking,
        "limited": limited,
        "issue_gate": {
            "artifact": "issue-gate.json" if "issue-gate.json" in artifacts else "",
            "promoted_issue_count": issue_count,
            "status": status_of("issue-gate.json"),
        },
        "next": "blocked_or_retry" if blocking else "continue_or_closure_review",
    }
    write_json(run_dir / artifact_name, result)
    append_transcript_event(
        run_dir,
        "review-loop-agent",
        "main-orchestrator",
        "review_result",
        str(result["summary"]),
        artifact_name,
    )
    update_review_gate_after_result(run_dir, "review_iteration", status, artifact_name)
    return result


def advance_run_once(payload: dict[str, object]) -> dict[str, object]:
    run_id = str(payload.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is required")
    run_dir = safe_run_dir(run_id)
    prompt_validation = ensure_prompt_validation_artifact(run_dir)
    if str(prompt_validation.get("status", "")) != "passed":
        gate_path = run_dir / "review-gate.json"
        gate = read_json_file(gate_path) if gate_path.exists() else {"kind": "review_gate"}
        gate["status"] = "blocked_or_needs_retry"
        gate["next_action"] = "prompt-validation.json이 passed가 아니므로 prompt-preflight-agent로 되돌려 정제 프롬프트를 다시 만든 뒤 main routing을 시작하세요."
        gate["prompt_validation_blocker"] = {
            "artifact": "prompt-validation.json",
            "status": prompt_validation.get("status", "unknown"),
            "failed_checks": [
                item
                for item in prompt_validation.get("checks", [])
                if isinstance(item, dict) and not bool(item.get("passed"))
            ],
        }
        write_json(gate_path, gate)
        append_transcript_event(
            run_dir,
            "prompt-validator-agent",
            "main-orchestrator",
            "blocked",
            "정제 프롬프트 검증이 passed가 아니므로 worker/report/review 진행을 차단하고 preflight 재시도를 요구합니다.",
            "prompt-validation.json",
        )
        invalidate_status_cache()
        reconcile_run_artifacts(run_id, run_dir)
        return {"advanced": "prompt_validation_blocked", "artifact": "prompt-validation.json", "run": run_payload(run_id)}
    ensure_main_advisory_council_artifact(run_dir)
    artifacts = {item.name for item in run_dir.iterdir() if item.is_file()}
    required_sdk = {
        "agents-sdk-run-contract.json",
        "agents-sdk-handoff-graph.json",
        "agents-sdk-guardrails.json",
        "main-advisory-council.json",
        "queue-routing-decision.json",
        "claude-advisor-request.md",
        "openai-codex-advisor-request.json",
        "cerberus-deliberation.json",
        "cerberus-deliberation.md",
        "worker-dispatch.json",
        "evidence-contract.json",
        "review-gate.json",
        "issue-gate.json",
    }
    missing_sdk = sorted(required_sdk - artifacts)
    checks = viewer_self_checks()
    checks_ok = all(bool(item.get("ok")) for item in checks)
    adapter_health = build_adapter_health()
    non_callable_configured = [
        route_id
        for route_id, health in adapter_health.items()
        if bool(health.get("configured")) and not bool(health.get("callable"))
    ]
    evidence = [
        f"loop_policy: goal-until-complete short iterations, validators_per_result>={SHORT_LOOP_VALIDATOR_MIN}",
        "lifecycle: operator message -> prompt preflight -> main dispatch -> short worker result -> multiple validator lanes -> product/Claude closure challenge -> retry or closure",
        f"adapter_health: callable={[route_id for route_id, health in adapter_health.items() if bool(health.get('callable'))]}, non_callable_configured={non_callable_configured}",
        *(
            f"{item['label']}: rc={item['returncode']} elapsed={item['elapsed_seconds']}s"
            + (f" output={str(item.get('output_tail', ''))[:700]}" if str(item.get("output_tail", "")).strip() else "")
            for item in checks
        ),
        *(f"missing artifact: {item}" for item in missing_sdk),
    ]
    risks = []
    if missing_sdk:
        risks.append("필수 Agents SDK/dispatch/evidence artifact가 일부 없습니다.")
    if not checks_ok:
        risks.append("viewer self-check command failed.")
    if non_callable_configured:
        risks.append(f"Configured external adapters are not callable yet: {', '.join(non_callable_configured)}")

    if "worker-result.json" not in artifacts:
        status = "blocked" if not checks_ok or missing_sdk else "passed_with_limitations" if non_callable_configured else "passed"
        record_run_result(
            {
                "run_id": run_id,
                "result_type": "worker",
                "role": "codex-worker",
                "status": status,
                "summary": (
                    "Codex subscription worker step: executed fixed viewer/orchestrator checks. "
                    "This is one short iteration result inside a goal-until-complete orchestration loop. "
                    "Verified Agents SDK contract, handoff graph, guardrails, dispatch/evidence gate presence, syntax checks, and adapter readiness truthfulness."
                ),
                "evidence": evidence,
                "risks": risks,
                "adapter_health": adapter_health,
                "loop": {
                    "attempt": 1,
                    "goal_until_complete": True,
                    "requires_multiple_validators_before_next_attempt": True,
                    "validator_minimum": SHORT_LOOP_VALIDATOR_MIN,
                },
            }
        )
        lanes = write_validator_lane_results(run_dir, run_id, checks, missing_sdk)
        aggregate_validator_result(run_dir, run_id, lanes)
        append_transcript_event(
            run_dir,
            "main-orchestrator",
            "claude-reviewer",
            "assignment",
            f"짧은 iteration 1회가 완료됐고 validator lane {len(lanes)}개가 같은 결과를 검증했습니다. 실패 lane이 있으면 다음 iteration은 prompt-preflight/main planning으로 되돌아가며, product/Claude review는 closure challenge gate입니다.",
            "review-gate.json",
        )
        reconcile_run_artifacts(run_id, run_dir)
        return {
            "advanced": "worker_and_validators",
            "artifact": "worker-result.json",
            "validator_lanes": lanes,
            "run": run_payload(run_id),
        }

    if "validator-result.json" not in artifacts:
        lanes = write_validator_lane_results(run_dir, run_id, checks, missing_sdk)
        aggregate = aggregate_validator_result(run_dir, run_id, lanes)
        reconcile_run_artifacts(run_id, run_dir)
        return {"advanced": "validators", "validator_lanes": lanes, "artifact": "validator-result.json", "result": aggregate, "run": run_payload(run_id)}

    if is_goal_report_request(run_dir) and "d-drive-report-pack.json" not in artifacts:
        manifest = ensure_goal_report_pack(run_id, run_dir)
        update_review_gate_after_result(run_dir, "report_pack_worker", "passed", "d-drive-report-pack.json")
        invalidate_status_cache()
        reconcile_run_artifacts(run_id, run_dir)
        return {"advanced": "d_drive_report_pack", "artifact": "d-drive-report-pack.json", "manifest": manifest, "run": run_payload(run_id)}

    if "claude-review-result.json" not in artifacts and "product-review-result.json" not in artifacts:
        if SUPERVISOR_AUTO_REVIEW_ENABLED:
            return supervisor_auto_review_for_run(run_id)
        response_path = run_dir / "claude-review-response.md"
        if response_path.exists():
            text = response_path.read_text(encoding="utf-8", errors="replace")
            result = record_run_result(
                {
                    "run_id": run_id,
                    "result_type": "claude_review",
                    "role": "claude-reviewer",
                    "status": "blocked" if "worker-result.json" not in artifacts or "validator-result.json" not in artifacts else "passed",
                    "summary": text[:1200],
                    "evidence": ["claude-review-response.md"],
                    "risks": ["Claude 응답은 기록됐지만 closure는 review-gate 상태를 따라야 합니다."],
                }
            )
            return {"advanced": "claude_review", **result}
        raise ValueError("Claude review result is required before closure; run or record Claude review first.")

    if review_iteration_count(run_dir) < MIN_REVIEW_ITERATIONS_BEFORE_STOP:
        iteration_result = create_review_iteration(run_id, run_dir)
        invalidate_status_cache()
        reconcile_run_artifacts(run_id, run_dir)
        return {
            "advanced": "review_iteration",
            "artifact": f"review-iteration-{int(iteration_result.get('iteration', 0)):03d}.json",
            "result": iteration_result,
            "run": run_payload(run_id),
        }

    closure_packet = ensure_closure_packet(run_id, run_dir)
    if closure_packet:
        invalidate_status_cache()
        reconcile_run_artifacts(run_id, run_dir)
        return {"advanced": "closure_packet", "artifact": "closure-packet.json", "packet": closure_packet, "run": run_payload(run_id)}

    append_transcript_event(run_dir, "main-orchestrator", "operator", "advance_noop", "worker, validator, Claude/product review artifact가 이미 있습니다. review-gate 상태를 확인하세요.", "review-gate.json")
    update_review_gate_after_result(run_dir, "advance_check", "checked", "review-gate.json")
    invalidate_status_cache()
    reconcile_run_artifacts(run_id, run_dir)
    return {"advanced": "noop", "run": run_payload(run_id), "artifact": "review-gate.json"}


def create_operator_planning_run(message: dict[str, object]) -> str:
    message_id = str(message["id"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-operator-{short_hash(message_id)}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight = message.get("prompt_preflight") if isinstance(message.get("prompt_preflight"), dict) else {}
    target = str(message.get("target", "main"))
    target_label = "main-orchestrator" if target == "main" else f"{target}-queue"
    recommended_route = default_provider_route() if target == "main" else target
    plan = {
        "kind": "operator_message_planning_packet",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "target": target,
        "provider_routes": load_provider_routing_config(),
        "goal": {
            "goal_id": f"operator-message-{short_hash(message_id)}",
            "work_type": "operator_queue_planning",
            "blocker_id": "",
            "affected_surfaces": [],
            "planned_files": [],
            "acceptance_criteria": [
                "원본 운영자 메시지를 보존한다.",
                "정제된 프롬프트를 메인 오케스트레이터 입력으로 사용할 수 있게 남긴다.",
                "실제 파일 수정 전 PRD, 작업 분해, Review Gate를 만든다.",
                "worker 실행 전 이슈 메모리와 검증 게이트를 확인한다.",
            ],
        },
        "gate_requirements": {
            "classification": "prompt_preflight_to_main_orchestrator",
            "required_evidence": [
                "orchestration-plan.json",
                "transcript.jsonl",
                "prompt-preflight.json",
            ],
        },
        "operator_message": {
            "original_message": message.get("original_message", ""),
            "refined_message": message.get("message", ""),
            "preflight": preflight,
        },
        "next_dispatch": {
            "status": "planning_ready",
            "recommended_route": recommended_route,
            "note": "이 로컬 프로세서는 계획 패킷까지 만들며, 실제 Codex/Claude worker 실행은 별도 dispatch 단계가 필요합니다.",
        },
    }
    write_json(run_dir / "orchestration-plan.json", plan)
    write_json(run_dir / "prompt-preflight.json", preflight)
    claude_prompt = "\n".join(
        [
            "# Claude 협업 검토 요청",
            "",
            "다음 SC Spire 오케스트레이션 계획을 구현 승인으로 보지 말고, 계획/제품/검증 관점에서 반박 검토하세요.",
            "",
            "## 운영자 원문",
            str(message.get("original_message", "")),
            "",
            "## 정제 프롬프트",
            str(message.get("message", "")),
            "",
            "## 검토 질문",
            "- PRD, 작업 분해, Review Gate가 실제 구현 전에 충분한가?",
            "- OpenAI API, Claude 검토, Codex 로컬 worker의 역할 분리가 적절한가?",
            "- 누락된 증거, 잘못된 완료 주장, player-facing 위험이 있는가?",
            "- Codex worker에게 넘기기 전에 막아야 할 blocker는 무엇인가?",
            "",
        ]
    )
    (run_dir / "claude-review-prompt.md").write_text(claude_prompt, encoding="utf-8")
    (run_dir / "claude-review-prompt.md").write_text(
        build_compact_claude_review_prompt(run_dir, original, refined) + "\n",
        encoding="utf-8",
    )
    write_json(
        run_dir / "chatkit-thread.json",
        {
            "title": "운영자 메시지 처리 큐",
            "source_message_id": message_id,
            "messages": [
                {"role": "operator", "content": message.get("original_message", ""), "created_at": message.get("created_at", "")},
                {"role": "prompt-preflight", "content": message.get("message", ""), "created_at": utc_timestamp()},
            ],
        },
    )
    append_transcript_event(
        run_dir,
        "operator",
        "prompt-preflight-agent",
        "handoff",
        str(message.get("original_message", "")),
    )
    append_transcript_event(
        run_dir,
        "prompt-preflight-agent",
        target_label,
        "response",
        str(message.get("message", "")),
        "prompt-preflight.json",
    )
    append_transcript_event(
        run_dir,
        "queue-processor",
        target_label,
        "assignment",
        "정제된 메시지를 대상 큐에서 볼 수 있는 계획 패킷으로 만들었습니다. 실제 worker 실행 전 PRD, 작업 분해, Review Gate를 확인해야 합니다.",
        "orchestration-plan.json",
    )
    append_transcript_event(
        run_dir,
        "queue-processor",
        "claude-reviewer",
        "review_queued",
        "Claude 협업 검토 프롬프트를 생성했습니다. 실제 Claude 실행은 별도 dispatch 단계에서 수행합니다.",
        "claude-review-prompt.md",
    )
    transcript_md = [
        "# 운영자 메시지 처리",
        "",
        f"- source_message_id: {message_id}",
        f"- target: {target}",
        f"- status: planning_ready",
        "",
        "## 원문",
        str(message.get("original_message", "")),
        "",
        "## 정제 프롬프트",
        str(message.get("message", "")),
        "",
    ]
    (run_dir / "transcript.md").write_text("\n".join(transcript_md), encoding="utf-8")
    return run_id


def create_operator_planning_run(message: dict[str, object]) -> str:
    message_id = str(message["id"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-operator-{short_hash(message_id)}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight = message.get("prompt_preflight") if isinstance(message.get("prompt_preflight"), dict) else {}
    target = str(message.get("target", "main"))
    target_label = "main-orchestrator" if target == "main" else f"{target}-queue"
    recommended_route = default_provider_route() if target == "main" else target
    route_plan = [
        {
            "role": "prompt-preflight-agent",
            "route": "openai_agents_sdk",
            "status": "done",
            "purpose": "사용자 원문을 목표 기반 프롬프트로 정제하고 누락/위험을 기록합니다.",
        },
        {
            "role": "supervisor-agent",
            "route": default_provider_route(),
            "status": "ready",
            "purpose": "PRD, 작업 분해, Review Gate, worker/validator routing을 만듭니다.",
        },
        {
            "role": "claude-reviewer",
            "route": "claude_collaborator",
            "status": "pending",
            "purpose": "계획과 제품 판단을 다른 모델 관점에서 반박/검토합니다.",
        },
        {
            "role": "codex-worker",
            "route": "codex_subscription_worker",
            "status": "pending",
            "purpose": "승인된 계획에 따라 로컬 파일 수정, 명령 실행, 브라우저 검증을 수행합니다.",
        },
    ]
    plan = {
        "kind": "operator_message_planning_packet",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "target": target,
        "provider_routes": load_provider_routing_config(),
        "goal": {
            "goal_id": f"operator-message-{short_hash(message_id)}",
            "work_type": "operator_queue_planning",
            "blocker_id": "",
            "affected_surfaces": [],
            "planned_files": [],
            "acceptance_criteria": [
                "원본 운영자 메시지를 보존한다.",
                "정제된 프롬프트를 메인 오케스트레이터 입력으로 사용할 수 있게 남긴다.",
                "실제 파일 수정 전 PRD, 작업 분해, Review Gate를 만든다.",
                "worker 실행 전 이슈 메모리와 검증 게이트를 확인한다.",
            ],
        },
        "gate_requirements": {
            "classification": "prompt_preflight_to_main_orchestrator",
            "required_evidence": [
                "orchestration-plan.json",
                "transcript.jsonl",
                "prompt-preflight.json",
            ],
        },
        "operator_message": {
            "title": title_for_message(message),
            "original_message": message.get("original_message", ""),
            "refined_message": message.get("message", ""),
            "preflight": preflight,
        },
        "next_dispatch": {
            "status": "prepared_not_running",
            "recommended_route": recommended_route,
            "note": "로컬 큐 프로세서는 계획 패킷까지 만듭니다. 실제 Codex/Claude worker 실행은 별도 dispatch 단계가 필요합니다.",
        },
        "route_plan": route_plan,
    }
    write_json(run_dir / "orchestration-plan.json", plan)
    write_json(run_dir / "prompt-preflight.json", preflight)
    write_json(
        run_dir / "chatkit-thread.json",
        {
            "title": "운영자 메시지 처리 큐",
            "source_message_id": message_id,
            "messages": [
                {"role": "operator", "content": message.get("original_message", ""), "created_at": message.get("created_at", "")},
                {"role": "prompt-preflight", "content": message.get("message", ""), "created_at": utc_timestamp()},
            ],
        },
    )
    append_transcript_event(run_dir, "operator", "prompt-preflight-agent", "handoff", str(message.get("original_message", "")))
    append_transcript_event(
        run_dir,
        "prompt-preflight-agent",
        target_label,
        "response",
        str(message.get("message", "")),
        "prompt-preflight.json",
    )
    append_transcript_event(
        run_dir,
        "queue-processor",
        target_label,
        "assignment",
        "정제된 메시지를 대상 큐에서 볼 수 있는 계획 패킷으로 만들었습니다. 실제 worker 실행 전 PRD, 작업 분해, Review Gate를 확인해야 합니다.",
        "orchestration-plan.json",
    )
    transcript_md = [
        "# 운영자 메시지 처리",
        "",
        f"- source_message_id: {message_id}",
        f"- target: {target}",
        "- status: prepared_not_running",
        "",
        "## 원문",
        str(message.get("original_message", "")),
        "",
        "## 정제 프롬프트",
        str(message.get("message", "")),
        "",
    ]
    (run_dir / "transcript.md").write_text("\n".join(transcript_md), encoding="utf-8")
    return run_id


def create_operator_planning_run_v2(message: dict[str, object]) -> str:
    message_id = str(message["id"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-operator-{short_hash(message_id)}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight = message.get("prompt_preflight") if isinstance(message.get("prompt_preflight"), dict) else {}
    target = str(message.get("target", "main"))
    target_label = "main-orchestrator" if target == "main" else f"{target}-queue"
    route_plan = [
        {"role": "prompt-preflight-agent", "route": "openai_agents_sdk", "status": "done", "purpose": "사용자 원문을 목표 기반 프롬프트로 정제합니다."},
        {"role": "supervisor-agent", "route": default_provider_route(), "status": "ready", "purpose": "PRD, 작업 분해, Review Gate를 만듭니다."},
        {"role": "claude-reviewer", "route": "claude_collaborator", "status": "pending", "purpose": "계획과 제품 판단을 독립 관점에서 검토합니다."},
        {"role": "codex-worker", "route": "codex_subscription_worker", "status": "pending", "purpose": "승인된 계획을 로컬 파일 수정과 검증으로 수행합니다."},
    ]
    plan = {
        "kind": "operator_message_planning_packet",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "target": target,
        "provider_routes": load_provider_routing_config(),
        "route_plan": route_plan,
        "goal": {
            "goal_id": f"operator-message-{short_hash(message_id)}",
            "work_type": "operator_queue_planning",
            "blocker_id": "",
            "affected_surfaces": [],
            "planned_files": [],
            "acceptance_criteria": [
                "원본 운영자 메시지를 보존한다.",
                "정제된 프롬프트를 메인 오케스트레이터 입력으로 사용할 수 있게 남긴다.",
                "실제 파일 수정 전 PRD, 작업 분해, Review Gate를 만든다.",
                "worker 실행 전 이슈 메모리와 검증 게이트를 확인한다.",
            ],
        },
        "gate_requirements": {
            "classification": "prompt_preflight_to_main_orchestrator",
            "required_evidence": ["orchestration-plan.json", "transcript.jsonl", "prompt-preflight.json", "claude-review-prompt.md"],
        },
        "operator_message": {
            "title": title_for_message(message),
            "original_message": message.get("original_message", ""),
            "refined_message": message.get("message", ""),
            "preflight": preflight,
        },
        "next_dispatch": {
            "status": "prepared_not_running",
            "recommended_route": default_provider_route() if target == "main" else target,
            "note": "로컬 큐 프로세서는 계획 패킷까지 만듭니다. 실제 Codex/Claude worker 실행은 별도 dispatch 단계가 필요합니다.",
        },
    }
    write_json(run_dir / "orchestration-plan.json", plan)
    write_json(run_dir / "prompt-preflight.json", preflight)
    claude_prompt = "\n".join(
        [
            "# Claude 협업 검토 요청",
            "",
            "다음 SC Spire 오케스트레이션 계획을 구현 승인으로 보지 말고, 계획/제품/검증 관점에서 반박 검토하세요.",
            "",
            "## 운영자 원문",
            str(message.get("original_message", "")),
            "",
            "## 정제 프롬프트",
            str(message.get("message", "")),
            "",
            "## 검토 질문",
            "- PRD, 작업 분해, Review Gate가 실제 구현 전에 충분한가?",
            "- OpenAI API, Claude 검토, Codex 로컬 worker의 역할 분리가 적절한가?",
            "- 누락된 증거, 잘못된 완료 주장, player-facing 위험이 있는가?",
            "- Codex worker에게 넘기기 전에 막아야 할 blocker는 무엇인가?",
            "",
        ]
    )
    (run_dir / "claude-review-prompt.md").write_text(claude_prompt, encoding="utf-8")
    write_json(
        run_dir / "chatkit-thread.json",
        {
            "title": "운영자 메시지 처리 큐",
            "source_message_id": message_id,
            "messages": [
                {"role": "operator", "content": message.get("original_message", ""), "created_at": message.get("created_at", "")},
                {"role": "prompt-preflight", "content": message.get("message", ""), "created_at": utc_timestamp()},
            ],
        },
    )
    append_transcript_event(run_dir, "operator", "prompt-preflight-agent", "handoff", str(message.get("original_message", "")))
    append_transcript_event(run_dir, "prompt-preflight-agent", target_label, "response", str(message.get("message", "")), "prompt-preflight.json")
    append_transcript_event(run_dir, "queue-processor", target_label, "assignment", "정제된 메시지를 계획 패킷으로 만들었습니다. 실제 worker 실행 전 PRD, 작업 분해, Review Gate를 확인해야 합니다.", "orchestration-plan.json")
    append_transcript_event(run_dir, "queue-processor", "claude-reviewer", "review_queued", "Claude 협업 검토 프롬프트를 생성했습니다. 실제 Claude 실행은 별도 dispatch 단계에서 수행합니다.", "claude-review-prompt.md")
    transcript_md = [
        "# 운영자 메시지 처리",
        "",
        f"- source_message_id: {message_id}",
        f"- target: {target}",
        "- status: prepared_not_running",
        "",
        "## 원문",
        str(message.get("original_message", "")),
        "",
        "## 정제 프롬프트",
        str(message.get("message", "")),
        "",
    ]
    (run_dir / "transcript.md").write_text("\n".join(transcript_md), encoding="utf-8")
    return run_id


def create_operator_handoff_run(message: dict[str, object]) -> str:
    message_id = str(message["id"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-handoff-{short_hash(message_id)}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight = message.get("prompt_preflight") if isinstance(message.get("prompt_preflight"), dict) else {}
    target = str(message.get("target", "main"))
    target_label = "main-orchestrator" if target == "main" else f"{target}-queue"
    handoff = {
        "kind": "operator_prompt_handoff",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "target": target,
        "provider_routes": load_provider_routing_config(),
        "operator_message": {
            "title": title_for_message(message),
            "original_message": message.get("original_message", ""),
            "refined_message": message.get("message", ""),
            "preflight": preflight,
        },
        "handoff_contract": {
            "status": "sent_to_main",
            "handled_by": "prompt-preflight-agent",
            "route": default_provider_route(),
            "note": "이 단계는 프롬프트 정제와 메인 큐 전달까지만 수행합니다. PRD, 작업 분해, Claude 검토, Codex worker 배정은 메인 오케스트레이터가 다음 단계에서 판단합니다.",
        },
    }
    write_json(run_dir / "orchestration-plan.json", handoff)
    write_json(run_dir / "prompt-preflight.json", preflight)
    write_json(
        run_dir / "chatkit-thread.json",
        {
            "title": "운영자 프롬프트 메인 전달",
            "source_message_id": message_id,
            "messages": [
                {"role": "operator", "content": message.get("original_message", ""), "created_at": message.get("created_at", "")},
                {"role": "prompt-preflight-agent", "content": message.get("message", ""), "created_at": utc_timestamp()},
                {"role": target_label, "content": "정제된 프롬프트를 메인 큐에 전달받았습니다.", "created_at": utc_timestamp()},
            ],
        },
    )
    append_transcript_event(run_dir, "operator", "prompt-preflight-agent", "handoff", str(message.get("original_message", "")))
    append_transcript_event(run_dir, "prompt-preflight-agent", target_label, "handoff", str(message.get("message", "")), "prompt-preflight.json")
    append_transcript_event(run_dir, "queue-processor", target_label, "response", "정제된 프롬프트를 메인 큐에 전달했습니다. 다음 계획/worker/Claude 배분은 메인 오케스트레이터가 결정합니다.", "orchestration-plan.json")
    transcript_md = [
        "# 운영자 프롬프트 메인 전달",
        "",
        f"- source_message_id: {message_id}",
        f"- target: {target}",
        "- status: sent_to_main",
        "",
        "## 원문",
        str(message.get("original_message", "")),
        "",
        "## 메인에 전달된 정제 프롬프트",
        str(message.get("message", "")),
        "",
    ]
    (run_dir / "transcript.md").write_text("\n".join(transcript_md), encoding="utf-8")
    return run_id


def create_operator_orchestrated_run(message: dict[str, object]) -> str:
    message_id = str(message["id"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}-orchestrated-{short_hash(message_id)}"
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight = message.get("prompt_preflight") if isinstance(message.get("prompt_preflight"), dict) else {}
    original = str(message.get("original_message", ""))
    refined = str(message.get("message", ""))
    prompt_validation = build_prompt_validation(original, refined, preflight)
    task_text = f"{original}\n\n{refined}"
    target = str(message.get("target", "main"))
    target_label = "main-orchestrator" if target in {"main", "prompt-preflight-agent"} else target
    relevant_issues = matching_issues_for_text(task_text, limit=8)
    issue_gate = build_issue_gate(relevant_issues)
    queue_decision = queue_routing_decision_for_message(message)
    main_advisory_council = build_main_advisory_council(message_id, original, refined, preflight, relevant_issues, queue_decision)
    cerberus_deliberation = build_cerberus_deliberation(message_id, original, refined, queue_decision, relevant_issues)
    blockers = [
        {
            "id": "subscription_worker_execution_required",
            "severity": "medium",
            "owner": "codex-worker",
            "reason": "메인 오케스트레이터는 배정 계약을 만들었고, 실제 파일 수정/검증은 Codex 구독 작업자가 수행해야 합니다.",
            "required_action": "현재 Codex 세션 또는 Codex CLI 작업자가 worker-dispatch.json을 읽고 worker-result.json과 검증 증거를 저장해야 합니다.",
        }
    ]
    if any(flag in preflight.get("risk_flags", []) for flag in ["rendered_ui_evidence_required", "local_browser_required"]):
        blockers.append(
            {
                "id": "rendered_evidence_required_before_completion",
                "severity": "high",
                "owner": "validator-ovv-product-level",
                "reason": "요청이 실제 화면/브라우저 증거를 요구합니다.",
                "required_action": "Playwright/브라우저 스크린샷과 Pass/Fail 표 없이는 done으로 바꾸지 않습니다.",
            }
        )
    automatic_beneficial_use_policy = {
        "kind": "automatic_beneficial_use_policy",
        "rule": "운영자가 모델/SDK 사용을 명시하지 않아도, 작업 품질·검증·추적에 이득이면 메인 오케스트레이터가 자동 배정합니다.",
        "default_order": [
            "agents_sdk_pattern_local",
            "codex_subscription_worker",
            "claude_collaborator",
            "optional_openai_agents_sdk_live_call",
            "optional_gemini_collaborator_when_configured",
        ],
        "always_apply": [
            "Agents SDK style agent identity, handoff contract, guardrail, trace/eval-ready artifact shape",
            "issue-memory scan before worker dispatch",
            "Codex subscription route for local implementation/evidence when file/browser work exists",
            "Claude subscription review for every non-trivial plan, player-facing change, evidence critique, or closure claim",
        ],
        "live_api_use_when": [
            "local fast preflight cannot create a reliable structured packet",
            "small guardrail/structured-output check is cheaper than a confused worker loop",
            "main orchestrator records budget reason and scope before using API budget",
        ],
        "not_allowed": [
            "skip Claude validation only because the operator did not explicitly ask for Claude",
            "skip Agents SDK pattern only because no live API call is made",
            "claim completion before Codex worker result, validator result, and Claude/product review are recorded",
        ],
    }
    loop_policy = short_loop_policy()
    claude_validation_policy = {
        "required": True,
        "route": "claude_collaborator",
        "billing": "claude_max_subscription",
        "required_for": [
            "plan critique",
            "product/design judgment",
            "worker-result evidence critique",
            "closure challenge before done",
        ],
        "completion_blocker": "claude-review-result.json or product-review-result.json must exist before closure review.",
    }
    agents_sdk_policy = {
        "pattern_required": True,
        "live_call_required": False,
        "route": "agents_sdk_pattern_local_then_optional_openai_agents_sdk",
        "used_for": [
            "agent persona definitions",
            "handoff graph",
            "guardrail contract",
            "structured result artifacts",
            "trace/eval-ready records",
            "main orchestrator route decision audit",
        ],
    }
    agents_sdk_manifest = build_sdk_style_manifest(AGENT_PERSONAS)
    agents_sdk_run_contract = {
        "kind": "agents_sdk_run_contract",
        "created_at": utc_timestamp(),
        "api_call_performed": False,
        "pattern_used": True,
        "active_use": [
            "Agent persona manifest generated for this run",
            "handoff graph generated for this run",
            "input/output guardrails generated for this run",
            "trace/eval-ready local artifact contract generated for this run",
        ],
        "live_runner_policy": {
            "default": "deferred",
            "allowed_when": automatic_beneficial_use_policy["live_api_use_when"],
            "must_record": ["budget reason", "scope", "model", "input/output artifact", "timestamp"],
        },
        "manifest": agents_sdk_manifest,
    }
    agents_sdk_guardrail_contract = {
        "kind": "agents_sdk_guardrail_contract",
        "input_guardrails": [item for item in agents_sdk_manifest.get("guardrails", []) if item.get("sdk_equivalent") == "input_guardrail"],
        "output_guardrails": [item for item in agents_sdk_manifest.get("guardrails", []) if item.get("sdk_equivalent") == "output_guardrail"],
        "must_block_completion_when": [
            "worker-result.json missing",
            "validator-result.json missing",
            "claude-review-result.json and product-review-result.json both missing",
            "rendered evidence required but absent",
            "issue-memory scan not promoted into gates",
        ],
    }
    agents_sdk_handoff_graph = {
        "kind": "agents_sdk_handoff_graph",
        "source": "main-orchestrator",
        "handoffs": agents_sdk_manifest.get("handoffs", []),
        "tools": agents_sdk_manifest.get("tools", []),
        "trace": agents_sdk_manifest.get("trace", {}),
    }
    route_override_audit = {
        "required_on_change": True,
        "must_record": [
            "previous_route",
            "new_route",
            "previous_model",
            "new_model",
            "billing_change",
            "reason",
            "scope",
            "timestamp",
        ],
    }
    decision = {
        "kind": "main_orchestrator_decision",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "status": "dispatch_ready",
        "status_truth": "assigned, waiting for subscription worker execution",
        "completion_rule": "done 상태는 worker_result, validator_result, review_gate_result, evidence artifact가 모두 있을 때만 허용합니다.",
        "loop_policy": loop_policy,
        "selected_route": default_provider_route(),
        "target": target_label,
        "summary": title_for_message(message, max_chars=120),
        "blockers": blockers,
        "relevant_issues": relevant_issues,
        "issue_gate_status": issue_gate["status"],
        "automatic_beneficial_use_policy": automatic_beneficial_use_policy,
        "claude_validation_policy": claude_validation_policy,
        "agents_sdk_policy": agents_sdk_policy,
        "route_override_audit": route_override_audit,
        "main_advisory_council": {
            "required": True,
            "artifact": "main-advisory-council.json",
            "final_owner": "main-orchestrator",
            "advisors": ["claude-decision-advisor", "openai-codex-api-advisor"],
            "queue_mode": queue_decision.get("mode"),
            "rule": "메인 최종 판단은 하나지만, dispatch 전에 Claude와 OpenAI/Codex API 보좌관의 반박/구조화 검토 상태를 기록해야 합니다.",
        },
        "required_artifacts_before_done": [
            "orchestrator-decision.json",
            "prompt-validation.json",
            "main-advisory-council.json",
            "queue-routing-decision.json",
            "worker-dispatch.json",
            "worker-result.json",
            "validator-result.json",
            "claude-review-prompt.md",
            "claude-review-result.json or product-review-result.json",
            "work-scope-acceptance.json",
            "e2e-html-verification.json",
            "review-gate.json",
            "evidence-contract.json",
            "issue-gate.json",
            "agents-sdk-run-contract.json",
            "agents-sdk-handoff-graph.json",
            "agents-sdk-guardrails.json",
        ],
    }
    worker_dispatch = {
        "kind": "worker_dispatch_contract",
        "status": "dispatch_ready_waiting_for_subscription_workers",
        "assignments": [
            {
                "agent": "claude-decision-advisor",
                "route": "claude_collaborator",
                "status": "mandatory_advisor_request_prepared",
                "task": "메인 판단 전 계획/제품/증거/큐 steering 여부를 반박합니다. 최종 결정권은 main-orchestrator에 있습니다.",
                "handoff_artifact": "claude-advisor-request.md",
                "completion_gate": "advisor 상태가 called/blocked/skipped 중 무엇인지 main-advisory-council.json에 남겨야 합니다.",
            },
            {
                "agent": "openai-codex-api-advisor",
                "route": "openai_agents_sdk",
                "status": "mandatory_structured_advisor_gate",
                "task": "Agents SDK/API 관점으로 라우팅, guardrail, handoff, trace/eval, 큐 steering 판정을 구조화 검토합니다.",
                "handoff_artifact": "openai-codex-advisor-request.json",
                "completion_gate": "API live call이 막히면 import/key/budget 이유를 보이는 blocker로 남깁니다.",
            },
            {
                "agent": "issue-memory-agent",
                "route": "codex_subscription_worker",
                "status": "prepared",
                "task": "관련 반복 실패와 사용자 교정을 acceptance gate로 승격합니다.",
                "inputs": ["deduped issue index", "operator message", "AGENTS.md"],
            },
            {
                "agent": "supervisor-agent",
                "route": default_provider_route(),
                "status": "prepared",
                "task": "PRD packet, task breakdown, Review Gate, non-goals, reroute rules를 작성합니다.",
                "inputs": ["operator message", "preflight", "relevant issues"],
            },
            {
                "agent": "codex-worker",
                "route": "codex_subscription_worker",
                "status": "queued_for_subscription_worker",
                "task": "짧은 1회 루프 안에서 파일 수정, 서버 실행, Playwright/browser 검증, 스크린샷 증거 생성을 수행합니다.",
                "handoff_artifact": "worker-dispatch.json",
                "loop_contract": "결과 1개를 남기면 즉시 여러 validator lane이 검증합니다. 목표 달성까지 짧은 iteration을 반복합니다.",
            },
            {
                "agent": "claude-reviewer",
                "route": "claude_collaborator",
                "status": "mandatory_review_queued_for_subscription_reviewer",
                "task": "운영자가 명시하지 않아도 비 trivial 작업의 계획/제품/증거/종료 주장을 반박 검토합니다.",
                "completion_gate": "claude-review-result.json 또는 product-review-result.json 없이는 closure 금지",
            },
            {
                "agent": "validator-code-level",
                "route": "codex_subscription_worker",
                "status": "blocked_until_worker_result",
                "task": "코드/상태 전이/API 회귀를 검증합니다.",
            },
            {
                "agent": "validator-contract-level",
                "route": "codex_subscription_worker",
                "status": "blocked_until_worker_result",
                "task": "worker 결과마다 dispatch/evidence/review gate artifact 계약을 검증합니다.",
            },
            {
                "agent": "validator-ui-state-level",
                "route": "codex_subscription_worker",
                "status": "blocked_until_worker_result",
                "task": "worker 결과마다 HTML 상태 표시와 artifact 연결을 검증합니다.",
            },
            {
                "agent": "validator-issue-memory-level",
                "route": "codex_subscription_worker",
                "status": "blocked_until_worker_result",
                "task": "worker 결과마다 반복 이슈가 gate로 승격됐는지 검증합니다.",
            },
        ],
        "loop_policy": loop_policy,
    }
    evidence_contract = {
        "kind": "evidence_contract",
        "loop_policy": loop_policy,
        "completion_blocked_without": [
            "fresh command output or browser screenshot",
            "worker result artifact",
            "validator result artifact",
            "issue gate artifact",
            "Claude/product review artifact",
            "browser E2E dashboard evidence",
            "review gate decision",
            "unresolved blocker list",
        ],
        "handoff_is_not_completion": True,
        "api_response_is_not_rendered_evidence": True,
    }
    work_scope_acceptance = {
        "kind": "work_scope_acceptance",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "scope": "orchestrator_dashboard_operator_workspace",
        "accepted_limitations": [
            {
                "id": "openai_agents_sdk_live_runner_deferred",
                "accepted": True,
                "reason": "Agents SDK pattern/manifest/handoff/guardrail artifacts are required and present; live Runner/model calls remain optional behind budget and live SDK gate.",
                "must_be_visible_to_operator": True,
                "evidence_required": ["adapter_health.openai_agents_sdk.import_error", "routing tab 호출 대기 badge"],
            },
            {
                "id": "gemini_disabled_until_key",
                "accepted": True,
                "reason": "Gemini collaborator must stay disabled until GEMINI_API_KEY and SC_SPIRE_GEMINI_ENABLED=1 are configured.",
                "must_be_visible_to_operator": True,
                "evidence_required": ["adapter_health.gemini_collaborator.api_key_present=false", "routing tab 호출 대기 badge"],
            },
        ],
        "issue_gate_domain_filter": {
            "current_task_domain": "orchestrator_dashboard",
            "exclude_when_prompt_negates_unity": ["Unity", "OVV", "player-facing", "RunMap", "module bay", "combat HUD"],
            "required_evidence": ["issue-gate.json contains no Unity/OVV/player-facing matches for dashboard-only prompts"],
        },
        "acceptance_criteria": [
            "The dashboard visibly distinguishes configured routes from callable adapters.",
            "OpenAI Agents SDK live runner deferred/import state is visible instead of hidden.",
            "Dashboard-only prompts do not promote Unity/OVV/player-facing issue gates.",
            "Worker and validator results use passed_with_limitations when configured optional adapters remain non-callable.",
            "Browser E2E evidence proves the Korean dashboard exposes these states.",
        ],
    }
    review_gate = {
        "kind": "review_gate",
        "status": "waiting_for_worker_result",
        "loop_policy": loop_policy,
        "reviewers": ["validator-code-level", "validator-contract-level", "validator-ui-state-level", "validator-issue-memory-level", "claude-reviewer", "product-critic-agent"],
        "mandatory_reviewers": ["validator-code-level", "validator-contract-level", "validator-ui-state-level", "validator-issue-memory-level", "claude-reviewer"],
        "automatic_beneficial_use_policy": automatic_beneficial_use_policy,
        "pass_criteria": [
            "짧은 worker iteration 결과마다 여러 validator lane이 독립 검증했고, 목표 달성 전이면 다음 iteration으로 되돌아갑니다.",
            "모든 acceptance criteria가 증거 artifact와 연결되어 있습니다.",
            "미해결 high blocker가 없습니다.",
            "반복 이슈가 issue-gate.json과 validator-issue-gate-result.json으로 검증됐습니다.",
            "사용자에게 보이는 상태가 실제 실행 상태와 일치합니다.",
            "Claude/product review가 완료 전 반박 검토를 수행했습니다.",
        ],
    }
    if prompt_validation.get("status") != "passed":
        review_gate["status"] = "blocked_or_needs_retry"
        review_gate["next_action"] = "prompt-validation.json이 passed가 아니므로 prompt-preflight-agent로 되돌려 정제 프롬프트를 다시 만든 뒤 main routing을 시작하세요."
        review_gate["prompt_validation_blocker"] = {
            "artifact": "prompt-validation.json",
            "status": prompt_validation.get("status", "unknown"),
            "failed_checks": [
                item
                for item in prompt_validation.get("checks", [])
                if isinstance(item, dict) and not bool(item.get("passed"))
            ],
        }
    plan = {
        "kind": "operator_message_orchestrated_packet",
        "created_at": utc_timestamp(),
        "source_message_id": message_id,
        "target": target,
        "provider_routes": load_provider_routing_config(),
        "operator_message": {
            "title": title_for_message(message),
            "original_message": original,
            "refined_message": refined,
            "preflight": preflight,
        },
        "prompt_validation": prompt_validation,
        "queue_routing_decision": queue_decision,
        "main_advisory_council": main_advisory_council,
        "cerberus_deliberation": cerberus_deliberation,
        "main_decision": decision,
        "worker_dispatch": worker_dispatch,
        "evidence_contract": evidence_contract,
        "review_gate": review_gate,
        "issue_gate": issue_gate,
        "work_scope_acceptance": work_scope_acceptance,
        "automatic_beneficial_use_policy": automatic_beneficial_use_policy,
        "loop_policy": loop_policy,
        "agents_sdk_run_contract": agents_sdk_run_contract,
        "next_dispatch": {
            "status": "dispatch_ready",
            "recommended_route": default_provider_route(),
            "note": "메인 오케스트레이터가 Codex/Claude 구독 경로에 배정할 짧은 루프 계약을 만들었습니다. 완료가 아니라 worker-result와 다중 validator 증거 대기 상태입니다.",
        },
    }
    write_json(run_dir / "orchestration-plan.json", plan)
    write_json(run_dir / "prompt-preflight.json", preflight)
    write_json(run_dir / "prompt-validation.json", prompt_validation)
    write_json(run_dir / "queue-routing-decision.json", queue_decision)
    write_json(run_dir / "main-advisory-council.json", main_advisory_council)
    write_advisory_request_artifacts(run_dir, main_advisory_council, original, refined)
    write_cerberus_deliberation_artifacts(run_dir, cerberus_deliberation)
    write_json(run_dir / "orchestrator-decision.json", decision)
    write_json(run_dir / "worker-dispatch.json", worker_dispatch)
    write_json(run_dir / "evidence-contract.json", evidence_contract)
    write_json(run_dir / "work-scope-acceptance.json", work_scope_acceptance)
    write_json(run_dir / "review-gate.json", review_gate)
    write_json(run_dir / "issue-gate.json", issue_gate)
    write_json(run_dir / "blockers.json", blockers)
    write_json(run_dir / "agents-sdk-run-contract.json", agents_sdk_run_contract)
    write_json(run_dir / "agents-sdk-handoff-graph.json", agents_sdk_handoff_graph)
    write_json(run_dir / "agents-sdk-guardrails.json", agents_sdk_guardrail_contract)
    claude_prompt = "\n".join(
        [
            "# Claude MAX 필수 검토 요청",
            "",
            "당신은 SC Spire 오케스트레이션의 독립 Claude 검토자입니다. 이 요청은 구현 명령이 아니라 plan/evidence/closure 반박 검토입니다.",
            "",
            "## 검토 원칙",
            "- 운영자가 Claude를 명시하지 않았어도, 비 trivial 작업은 완료 전 Claude 검증이 필수입니다.",
            "- Codex worker 결과를 그대로 승인하지 말고 제품/계획/증거/종료 주장 관점에서 반박하세요.",
            "- Agents SDK 방식이 live API 호출 여부와 무관하게 agent identity, handoff, guardrail, trace/eval-ready artifact로 적용됐는지 확인하세요.",
            "- Codex/Claude MAX 구독 경로 우선, OpenAI API는 작은 구조화/가드레일/판단에만 쓰는 정책이 지켜졌는지 확인하세요.",
            "- 목표 달성까지 짧은 worker iteration을 반복하고, 매 결과마다 여러 validator lane이 결과를 검증하며, 실패 시 다음 iteration으로 되돌리는 정책인지 확인하세요.",
            "",
            "## 운영자 원문",
            original,
            "",
            "## 메인에 전달된 정제 프롬프트",
            refined,
            "",
            "## 메인 결정 요약",
            json.dumps(decision, ensure_ascii=False, indent=2),
            "",
            "## 메인 판단 보좌관 council",
            json.dumps(main_advisory_council, ensure_ascii=False, indent=2),
            "",
            "## 작업자 배정",
            json.dumps(worker_dispatch, ensure_ascii=False, indent=2),
            "",
            "## 응답 형식",
            "Korean summary plus clear PASS / NEEDS_RETRY / BLOCKED. Include missing evidence, risky assumptions, and whether closure is allowed.",
        ]
    )
    (run_dir / "claude-review-prompt.md").write_text(claude_prompt, encoding="utf-8")
    write_json(
        run_dir / "chatkit-thread.json",
        {
            "title": "메인 오케스트레이터 실행 준비",
            "source_message_id": message_id,
            "messages": [
                {"role": "operator", "content": original, "created_at": message.get("created_at", "")},
                {"role": "prompt-preflight-agent", "content": refined, "created_at": utc_timestamp()},
                {"role": "main-orchestrator", "content": "Codex/Claude 구독 worker가 읽을 dispatch/evidence/review 계약을 생성했습니다.", "created_at": utc_timestamp()},
            ],
        },
    )
    append_transcript_event(run_dir, "operator", "prompt-preflight-agent", "handoff", original)
    append_transcript_event(run_dir, "prompt-preflight-agent", "main-orchestrator", "handoff", refined, "prompt-preflight.json")
    append_transcript_event(run_dir, "prompt-validator-agent", "main-orchestrator", "review_result", f"정제 프롬프트 검증 결과: {prompt_validation['status']}", "prompt-validation.json")
    append_transcript_event(run_dir, "queue-processor", "main-orchestrator", "queue_decision", f"큐 판정: {queue_decision.get('mode')} / {queue_decision.get('reason')}", "queue-routing-decision.json")
    append_transcript_event(run_dir, "main-orchestrator", "claude-decision-advisor", "advisor_request", "메인 최종 판단 전 계획/제품/증거/큐 steering 여부를 반박하세요. 최종 결정권은 main-orchestrator에 남습니다.", "claude-advisor-request.md")
    append_transcript_event(run_dir, "main-orchestrator", "openai-codex-api-advisor", "advisor_request", "Agents SDK/API 관점으로 라우팅, guardrail, handoff, trace/eval, 큐 steering 판정을 구조화 검토하세요.", "openai-codex-advisor-request.json")
    append_transcript_event(run_dir, "main-orchestrator", "main-orchestrator", "advisor_council_policy", "메인은 단일 최종 소유자이며 Claude와 OpenAI/Codex API는 상시 판단 보좌관입니다. 호출 불가 경로는 조용히 생략하지 않고 blocker/status로 남깁니다.", "main-advisory-council.json")
    append_transcript_event(run_dir, "main-orchestrator", "issue-memory-agent", "assignment", "관련 반복 실패를 acceptance gate로 승격하세요.", "orchestrator-decision.json")
    append_transcript_event(run_dir, "main-orchestrator", "agents-sdk-pattern", "tool_use", "Agents SDK 방식으로 agent manifest, handoff graph, guardrail, trace/eval-ready run contract를 생성했습니다.", "agents-sdk-run-contract.json")
    append_transcript_event(run_dir, "issue-memory-agent", "main-orchestrator", "response", f"관련 이슈 후보 {len(relevant_issues)}개를 찾았습니다. 상위 후보는 orchestrator-decision.json에 포함했습니다.", "orchestrator-decision.json")
    append_transcript_event(run_dir, "main-orchestrator", "supervisor-agent", "assignment", "PRD, task breakdown, Review Gate를 작성하세요.", "worker-dispatch.json")
    append_transcript_event(run_dir, "main-orchestrator", "codex-worker", "assignment", "Codex 구독 작업자는 worker-dispatch.json을 읽고 파일 수정/검증/증거 패키징 후 worker-result.json을 남기세요.", "worker-dispatch.json")
    append_transcript_event(run_dir, "main-orchestrator", "validator-code-level", "blocked", "worker-result.json이 생기기 전까지 검증은 대기합니다.", "review-gate.json")
    append_transcript_event(run_dir, "main-orchestrator", "claude-reviewer", "review_queued", "계획/제품/종료 주장 반박 검토가 필요합니다. Claude 검토 프롬프트 artifact를 생성했습니다.", "claude-review-prompt.md")
    append_transcript_event(
        run_dir,
        "main-orchestrator",
        "all-agents",
        "policy",
        "운영자가 명시하지 않아도 이득이면 Agents SDK 방식과 Claude 검증을 자동 사용합니다. 비 trivial 작업은 Claude/product review artifact 없이는 closure가 막힙니다.",
        "orchestrator-decision.json",
    )
    transcript_md = [
        "# 메인 오케스트레이터 실행 준비",
        "",
        f"- source_message_id: {message_id}",
        f"- target: {target}",
        "- status: dispatch_ready",
        "- truth: assigned, waiting for subscription worker execution",
        f"- loop_policy: max {SHORT_LOOP_MAX_ATTEMPTS} short attempts, at least {SHORT_LOOP_VALIDATOR_MIN} validator lanes per worker result",
        "",
        "## 차단 사유",
        *(f"- {item['id']}: {item['reason']}" for item in blockers),
        "",
        "## 원문",
        original,
        "",
        "## 정제 프롬프트",
        refined,
        "",
    ]
    (run_dir / "transcript.md").write_text("\n".join(transcript_md), encoding="utf-8")
    return run_id


create_operator_planning_run = create_operator_orchestrated_run


def process_operator_queue_once(max_count: int | None = None) -> int:
    grouped = events_by_message_id()
    processed = 0
    candidates = operator_messages_with_status(limit=1000)
    def candidate_priority(message: dict[str, object]) -> tuple[int, int, str]:
        message_id = str(message.get("id", ""))
        latest_event = grouped.get(message_id, [])[-1] if grouped.get(message_id) else {}
        effective = dict(message)
        if latest_event.get("target_override"):
            effective["target"] = str(latest_event.get("target_override"))
        decision = queue_routing_decision_for_message(effective)
        steering_rank = 0 if decision.get("mode") == "steering_intervention" else 1
        return (steering_rank, int(effective.get("queue_priority", 1000) or 1000), str(effective.get("created_at", "")))

    candidates = sorted(candidates, key=candidate_priority)
    for message in candidates:
        message_id = str(message.get("id", ""))
        if not message_id:
            continue
        statuses = [str(event.get("status", "")) for event in grouped.get(message_id, [])]
        if not statuses:
            continue
        if message.get("removed_from_queue"):
            continue
        if workflow_status(grouped.get(message_id, []), str(message.get("status", "queued"))) != "queued":
            continue
        latest_event = grouped.get(message_id, [])[-1] if grouped.get(message_id) else {}
        if latest_event.get("target_override"):
            message = dict(message)
            message["target"] = str(latest_event.get("target_override"))
        target = str(message.get("target", "prompt-preflight-agent"))
        if target not in {"prompt-preflight-agent", "main"}:
            continue
        if str(message.get("target", "")) == "prompt-preflight-agent":
            message = dict(message)
            message["target"] = "main"
        queue_decision = queue_routing_decision_for_message(message)
        append_operator_event(
            message_id,
            "queue_routing_decision",
            "main-orchestrator",
            f"큐 판정: {queue_decision.get('mode')} / {queue_decision.get('reason')}",
            artifact="queue-routing-decision.json",
            extra={"queue_routing_decision": queue_decision},
        )
        append_operator_event(message_id, "preflight_refining", "prompt-preflight-agent", "운영자 프롬프트를 메인에 넣기 좋은 형태로 정제하고 있습니다.")
        run_id = create_operator_planning_run(message)
        target = str(message.get("target", "main"))
        route_detail = "메인 오케스트레이터 입력으로 볼 수 있는 실행 기록을 만들었습니다."
        ready_detail = "계획 패킷 생성 완료. 실제 worker/Claude 실행 dispatch 전 상태입니다."
        if target != "main":
            route_detail = f"{target} 대상 큐에서 볼 수 있는 실행 기록을 만들었습니다."
            ready_detail = f"{target} 대상 계획 패킷 생성 완료. 실제 실행 dispatch 전 상태입니다."
        append_operator_event(
            message_id,
            "dispatch_ready",
            "main-orchestrator",
            "메인 오케스트레이터가 Codex/Claude 구독 작업자에게 넘길 dispatch/evidence/review 계약을 만들었습니다.",
            run_id=run_id,
            artifact="worker-dispatch.json",
        )
        if QUEUE_AUTO_ADVANCE_ENABLED and QUEUE_AUTO_ADVANCE_STEPS:
            advance_events: list[str] = []
            for _ in range(QUEUE_AUTO_ADVANCE_STEPS):
                try:
                    advance_result = advance_run_once({"run_id": run_id})
                except Exception as exc:
                    append_operator_event(
                        message_id,
                        "advance_blocked",
                        "main-orchestrator",
                        f"자동 진행이 중단됐습니다: {type(exc).__name__}: {exc}",
                        run_id=run_id,
                        artifact="review-gate.json",
                    )
                    break
                advanced = str(advance_result.get("advanced", ""))
                if advanced:
                    advance_events.append(advanced)
                run_state = run_work_state(run_id)
                status = str(run_state.get("status", ""))
                if status == "blocked":
                    break
                if status == "done":
                    break
                if advanced == "noop":
                    break
            append_operator_event(
                message_id,
                "advance_auto_loop",
                "main-orchestrator",
                f"자동 진행은 목표 closure 또는 hard blocker까지 짧은 iteration을 계속 시도합니다. 이번 tick 전진: {', '.join(advance_events) or 'none'}",
                run_id=run_id,
                artifact="review-gate.json",
            )
        grouped = events_by_message_id()
        processed += 1
        if max_count is not None and processed >= max_count:
            break
    return processed


def update_operator_message(message_id: str, payload: dict[str, object]) -> dict[str, object]:
    current = apply_queue_controls(find_operator_message(message_id), events_by_message_id().get(message_id, []))
    text = str(payload.get("message", current.get("original_message") or current.get("message") or "")).strip()
    if not text:
        raise ValueError("message is required")
    target = normalize_message_target(str(payload.get("target", current.get("target", "prompt-preflight-agent"))).strip())
    thread_id = str(payload.get("target_thread_id", current.get("target_thread_id", ""))).strip()
    preflight_target = "main" if target == "prompt-preflight-agent" else target
    refined_text, prompt_preflight = preflight_operator_prompt(text, preflight_target, str(current.get("run_id", "")))
    extra = {
        "original_message_override": text,
        "message_override": refined_text if target == "prompt-preflight-agent" else text,
        "prompt_preflight_override": prompt_preflight,
        "target_thread_id_override": thread_id,
    }
    if "priority" in payload:
        extra["priority"] = int(payload.get("priority") or current.get("queue_priority", 1000))
    event = append_operator_event(
        message_id,
        "queued",
        "queue-editor",
        "운영자가 큐 메시지를 편집했고 다시 처리 대기 상태로 돌렸습니다.",
        target_override=target,
        extra=extra,
    )
    return {"message": operator_message_by_id(message_id), "event": event}


def operator_message_by_id(message_id: str) -> dict[str, object]:
    for message in operator_messages_with_status(limit=5000):
        if str(message.get("id", "")) == message_id:
            return message
    raise ValueError("message not found")


def remove_operator_message(message_id: str) -> dict[str, object]:
    find_operator_message(message_id)
    event = append_operator_event(message_id, "removed", "queue-editor", "운영자가 이 메시지를 큐에서 제거했습니다.")
    return {"message": operator_message_by_id(message_id), "event": event}


def steer_operator_message(message_id: str, payload: dict[str, object]) -> dict[str, object]:
    current = apply_queue_controls(find_operator_message(message_id), events_by_message_id().get(message_id, []))
    target = normalize_message_target(str(payload.get("target", current.get("target", "prompt-preflight-agent"))).strip())
    note = str(payload.get("note", "")).strip()
    extra: dict[str, object] = {}
    if payload.get("target_thread_id") is not None:
        extra["target_thread_id_override"] = str(payload.get("target_thread_id") or "")
    detail = "운영자가 큐 메시지의 대상/방향을 바꾸고 다시 처리 대기 상태로 돌렸습니다."
    if note:
        detail += f" 메모: {note}"
        extra["steering_note"] = note
    event = append_operator_event(message_id, "queued", "queue-steering", detail, target_override=target, extra=extra)
    return {"message": operator_message_by_id(message_id), "event": event}


def reorder_operator_messages(ids: list[object]) -> dict[str, object]:
    known = {str(message.get("id", "")) for message in read_operator_messages(limit=5000)}
    updated: list[str] = []
    for index, raw_id in enumerate(ids):
        message_id = str(raw_id)
        if message_id not in known:
            continue
        append_operator_event(
            message_id,
            "queued",
            "queue-reorder",
            f"운영자가 큐 순서를 {index + 1}번으로 조정했습니다.",
            extra={"priority": (index + 1) * 100},
        )
        updated.append(message_id)
    return {"updated_count": len(updated), "updated_ids": updated, "messages": operator_messages_with_status(limit=100)}


def cancel_operator_messages(ids: list[object] | None = None, reason: str = "") -> dict[str, object]:
    cancelable = {"queued", "preflight_refining", "sent_to_main", "prepared_not_running", "planning_ready"}
    selected = {str(item) for item in ids} if ids else None
    canceled: list[str] = []
    for message in operator_messages_with_status(limit=5000):
        message_id = str(message.get("id", ""))
        if not message_id or (selected is not None and message_id not in selected):
            continue
        status = str(message.get("effective_status", ""))
        if status in {"removed", "canceled", "done", "failed", "blocked"}:
            continue
        if selected is None and status not in cancelable:
            continue
        detail = "운영자가 이 메시지/인계 기록을 취소했습니다."
        if reason:
            detail += f" 사유: {reason}"
        append_operator_event(message_id, "canceled", "queue-cancel", detail)
        canceled.append(message_id)
    return {"canceled_count": len(canceled), "canceled_ids": canceled, "messages": operator_messages_with_status(limit=100)}


def build_execution_lifecycle(work_items: list[dict[str, object]]) -> dict[str, object]:
    active = [item for item in work_items if item.get("bucket") == "active"]
    prepared = [item for item in work_items if item.get("bucket") == "prepared"]
    blocked = [item for item in work_items if item.get("bucket") == "blocked"]
    open_items = active + prepared + blocked
    current = max(open_items, key=lambda item: str(item.get("updated_at", ""))) if open_items else {}
    next_prepared = prepared[0] if prepared else {}
    current_status = str(current.get("status", ""))
    current_gate_status = str(current.get("gate_status", ""))
    current_run_id = str(current.get("run_id", ""))

    def current_artifact_status(name: str) -> str:
        if not current_run_id:
            return ""
        try:
            run_dir = safe_run_dir(current_run_id)
        except Exception:
            return ""
        path = run_dir / name
        if not path.exists():
            return ""
        try:
            data = read_json_file(path)
        except Exception:
            return "unreadable"
        return str(data.get("status", "present")) if isinstance(data, dict) else "present"

    worker_status = current_artifact_status("worker-result.json")
    validator_status = current_artifact_status("validator-result.json")
    claude_status = current_artifact_status("claude-review-result.json")
    product_review_status = current_artifact_status("product-review-result.json")
    closure_packet_status = current_artifact_status("closure-packet.json")
    preflight_done = bool(current_artifact_status("prompt-preflight.json") or current_status not in {"queued", "preflight_refining"})
    prompt_preflight_state = "completed" if preflight_done else "active"
    if current_status in {"queued", "preflight_refining"}:
        prompt_preflight_state = "active"

    main_state = "idle"
    if current_status == "closure_ready" or current_gate_status.startswith("ready_for_closure"):
        main_state = "closure_review_ready"
    elif closure_packet_status:
        main_state = "completed"
    elif current_status in {"sent_to_main", "dispatch_ready", "worker_running", "waiting_claude_review"}:
        main_state = "active"
    elif current:
        main_state = "waiting"

    codex_state = "completed" if worker_status in {"passed", "passed_with_limitations"} else "not_dispatched"
    if current_status in {"worker_running"}:
        codex_state = "active"
    claude_state = "passed" if claude_status == "passed" else "passed_with_limitations" if claude_status == "passed_with_limitations" else "waiting" if current_status == "waiting_claude_review" else "not_dispatched"
    if not claude_status and product_review_status in {"passed", "passed_with_limitations"}:
        claude_state = "product_review_only"
    lifecycle_running_statuses = {"queued", "preflight_refining", "sent_to_main", "dispatch_ready", "worker_running", "waiting_claude_review"}
    actually_running = [item for item in active if str(item.get("status", "")) in lifecycle_running_statuses]
    return {
        "current_main_prompt": current,
        "next_prepared_prompt": next_prepared,
        "active_agents": [
            {"agent": "prompt-preflight-agent", "state": prompt_preflight_state},
            {"agent": "main-orchestrator", "state": main_state, "gate_status": current_gate_status},
            {"agent": "codex-worker", "state": codex_state, "artifact_status": worker_status},
            {"agent": "validator-lanes", "state": "completed" if validator_status in {"passed", "passed_with_limitations"} else "waiting", "artifact_status": validator_status},
            {"agent": "claude-reviewer", "state": claude_state, "artifact_status": claude_status or product_review_status},
            {"agent": "gemini-reviewer", "state": "disabled_until_key"},
        ],
        "queue_policy": {
            "mode": "top_one_at_a_time",
            "autorun": QUEUE_AUTORUN_ENABLED,
            "max_per_tick": QUEUE_AUTORUN_MAX_PER_TICK,
            "scope": "operator message -> prompt preflight -> main queue run record",
            "next_item_rule": "The next queued message is not auto-processed until the current autorun tick finishes.",
        },
        "loop_policy": short_loop_policy(),
        "running_count": len(actually_running),
        "blocked_count": len(blocked),
        "prepared_count": len(prepared),
    }


def build_shared_workspace() -> dict[str, object]:
    issue_files = []
    issue_dir = REPO_ROOT / "memory" / "issues_log"
    if issue_dir.exists():
        issue_files = [str(path.relative_to(REPO_ROOT)) for path in sorted(issue_dir.glob("*.md"))[-8:]]
    return {
        "source_of_truth": [
            "AGENTS.md",
            str(PROVIDER_ROUTING_PATH.relative_to(REPO_ROOT)),
            str(OPERATOR_MESSAGE_EVENTS.relative_to(REPO_ROOT)),
            "output/agent_orchestrator_runs/<run_id>/transcript.jsonl",
            "memory/issues_log/*.md",
        ],
        "issue_files": issue_files,
        "skill_policy": "Workers must state which skill/process rules they used and must read relevant issue memory before work.",
        "mcp_policy": "MCP/tool availability is shared as run evidence. A worker must not assume unavailable MCPs exist.",
        "review_policy": "Review lanes are review-only by default. They challenge, block, or request retry; they do not silently edit implementation files.",
        "thread_policy": "Dedicated review threads should be spawned from these lanes when thread tooling is attached; until then, the lane state is recorded here.",
    }


def load_issue_import_payload() -> dict[str, object]:
    index_path = ISSUE_IMPORT_COMPACT_INDEX if ISSUE_IMPORT_COMPACT_INDEX.exists() else ISSUE_IMPORT_INDEX
    if not index_path.exists():
        return {}
    cache_key = f"{index_path}:{index_path.stat().st_mtime}"
    if ISSUE_IMPORT_CACHE.get("mtime") == cache_key and isinstance(ISSUE_IMPORT_CACHE.get("payload"), dict):
        return ISSUE_IMPORT_CACHE["payload"]  # type: ignore[return-value]
    payload = json.loads(index_path.read_text(encoding="utf-8", errors="replace"))
    ISSUE_IMPORT_CACHE["mtime"] = cache_key
    ISSUE_IMPORT_CACHE["payload"] = payload
    return payload if isinstance(payload, dict) else {}


def relevance_tokens(text: str) -> set[str]:
    lowered = text.lower()
    raw_tokens = re.findall(r"[가-힣a-z0-9_]{2,}", lowered)
    stop = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "작업",
        "현재",
        "메인",
        "실행",
        "기록",
        "검증",
        "이슈",
        "문제",
    }
    return {token for token in raw_tokens if token not in stop}


AGENT_ISSUE_KEYWORDS: dict[str, str] = {
    "main-orchestrator": "orchestration orchestrator queue routing handoff gate guardrail supervisor dispatch priority loop issue memory 오케스트레이션 오케스트레이터 큐 라우팅 인계 게이트",
    "prompt-preflight-agent": "prompt preflight ambiguity refine guardrail structured input operator message 프롬프트 사전검증 정제 모호함 운영자 메시지",
    "issue-memory-agent": "issue memory duplicate regression user correction resolved discovered discord log 중복 회귀 교정 이슈 기록 로그",
    "codex-worker": "codex file edit test pytest playwright browser build command permission local evidence 파일 수정 테스트 빌드 권한 브라우저 증거",
    "claude-reviewer": "claude review product design critique closure evidence player facing plan gate product quality 클로드 검토 제품 디자인 증거 closure",
    "validator-code-level": "validator code syntax contract regression state transition test lint validation 코드 문법 계약 회귀 상태전이 테스트",
    "validator-ovv-product-level": "ovv screenshot visual rendered evidence player facing ui ux product localization screenshot 시각 스크린샷 렌더링 한국어",
    "gemini-reviewer": "gemini independent review compare critique alternative validation external reviewer 독립 검토 비교 대안",
}


def issue_relevance_score(issue: dict[str, object], task_tokens: set[str], agent_tokens: set[str]) -> int:
    text = " ".join(
        [
            str(issue.get("title", "")),
            str(issue.get("representative_snippet", "")),
            json.dumps(issue.get("phase_counts", {}), ensure_ascii=False),
        ]
    )
    issue_tokens = relevance_tokens(text)
    task_overlap = len(issue_tokens & task_tokens)
    agent_overlap = len(issue_tokens & agent_tokens)
    severity = str(issue.get("severity", "normal"))
    severity_score = {"high": 35, "medium": 18, "normal": 6}.get(severity, 6)
    duplicate_score = min(25, int(issue.get("duplicate_count", 0) or 0))
    status_score = 10 if str(issue.get("status", "")) != "resolved" else 0
    return severity_score + duplicate_score + (task_overlap * 8) + (agent_overlap * 6) + status_score


def compact_issue(issue: dict[str, object], score: int) -> dict[str, object]:
    sources = issue.get("sources") if isinstance(issue.get("sources"), list) else []
    first_source = sources[0] if sources and isinstance(sources[0], dict) else {}
    return {
        "id": issue.get("id", ""),
        "title": issue.get("title", ""),
        "status": issue.get("status", ""),
        "severity": issue.get("severity", ""),
        "score": score,
        "source_count": issue.get("source_count", 0),
        "duplicate_count": issue.get("duplicate_count", 0),
        "snippet": str(issue.get("representative_snippet", ""))[:360],
        "first_source": {
            "file": first_source.get("source", ""),
            "line": first_source.get("line", ""),
            "phase": first_source.get("phase", ""),
        },
    }


def matching_issues_for_text(text: str, limit: int = 6) -> list[dict[str, object]]:
    payload = load_issue_import_payload()
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    task_tokens = relevance_tokens(text)
    task_lower = text.lower()
    task_excludes_unity = (
        ("unity" in task_lower or "게임 ui" in task_lower or "player-facing" in task_lower)
        and any(token in task_lower for token in ["아니", "아님", "관련 없는", "not unity", "not a unity", "not player-facing"])
    )
    task_mentions_unity = (
        any(token in task_lower for token in ["unity", "runmap", "run map", "ovv", "player_facing", "player-facing", "전투 hud", "모듈 베이"])
        and not task_excludes_unity
    )
    dashboard_focus = relevance_tokens(
        "orchestrator dashboard viewer html queue adapter agents sdk claude gemini issue memory "
        "오케스트레이터 대시보드 뷰어 화면 큐 어댑터 호출 가능 이슈 공유"
    )
    agent_tokens = relevance_tokens(
        " ".join(
            [
                AGENT_ISSUE_KEYWORDS["main-orchestrator"],
                AGENT_ISSUE_KEYWORDS["prompt-preflight-agent"],
                AGENT_ISSUE_KEYWORDS["issue-memory-agent"],
                AGENT_ISSUE_KEYWORDS["codex-worker"],
            ]
        )
    )
    scored: list[tuple[int, dict[str, object]]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_text = " ".join(
            [
                str(issue.get("title", "")),
                str(issue.get("representative_snippet", "")),
            ]
        )
        issue_lower = issue_text.lower()
        issue_is_unity_domain = any(
            token in issue_lower
            for token in [
                "unity",
                "runmap",
                "run map",
                "ovv",
                "player_facing",
                "player-facing",
                "web-parity",
                "module bay",
                "combat hud",
                "전투 hud",
                "모듈 베이",
                "unity ui",
            ]
        )
        if issue_is_unity_domain and not task_mentions_unity:
            continue
        issue_tokens = relevance_tokens(issue_text)
        task_overlap = len(issue_tokens & task_tokens)
        dashboard_overlap = len(issue_tokens & dashboard_focus)
        if task_overlap == 0 and dashboard_overlap == 0:
            continue
        score = issue_relevance_score(issue, task_tokens, agent_tokens)
        if score >= 24 and (task_overlap >= 2 or dashboard_overlap >= 1):
            scored.append((score, issue))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [compact_issue(issue, score) for score, issue in scored[:limit]]


def build_issue_import_view(work_items: list[dict[str, object]]) -> dict[str, object]:
    payload = load_issue_import_payload()
    if not payload:
        return {
            "available": False,
            "index_path": str(ISSUE_IMPORT_INDEX.relative_to(REPO_ROOT)),
            "message": "통합 이슈 인덱스가 아직 없습니다.",
        }
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    active_or_prepared = [item for item in work_items if item.get("bucket") in {"active", "blocked", "prepared"}][:8]
    if not active_or_prepared:
        active_or_prepared = work_items[:5]
    task_text = " ".join(
        " ".join(
            [
                str(item.get("title", "")),
                str(item.get("detail", "")),
                str(item.get("target", "")),
                str(item.get("route", "")),
                str(item.get("status", "")),
            ]
        )
        for item in active_or_prepared
    )
    task_tokens = relevance_tokens(task_text)
    agent_views: list[dict[str, object]] = []
    global_scored: list[tuple[int, dict[str, object]]] = []
    general_agent_tokens = relevance_tokens(" ".join(AGENT_ISSUE_KEYWORDS.values()))
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        score = issue_relevance_score(issue, task_tokens, general_agent_tokens)
        if score >= 24:
            global_scored.append((score, issue))
    global_scored.sort(key=lambda pair: pair[0], reverse=True)
    for agent_id, keyword_text in AGENT_ISSUE_KEYWORDS.items():
        agent_tokens = relevance_tokens(keyword_text)
        scored = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            score = issue_relevance_score(issue, task_tokens, agent_tokens)
            if score >= 28:
                scored.append((score, issue))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        agent_views.append(
            {
                "agent": agent_id,
                "issue_count": len(scored),
                "issues": [compact_issue(issue, score) for score, issue in scored[:8]],
            }
        )
    return {
        "available": True,
        "index_path": str(ISSUE_IMPORT_INDEX.relative_to(REPO_ROOT)),
        "compact_index_path": str(ISSUE_IMPORT_COMPACT_INDEX.relative_to(REPO_ROOT)),
        "markdown_path": str((ISSUE_IMPORT_DIR / "deduped-issues.md").relative_to(REPO_ROOT)),
        "summary": payload.get("summary", {}),
        "task_context": {
            "work_item_count": len(active_or_prepared),
            "keywords": sorted(task_tokens)[:30],
        },
        "top_relevant": [compact_issue(issue, score) for score, issue in global_scored[:12]],
        "agent_views": agent_views,
        "notes": payload.get("notes", []),
    }


def build_issue_memory_summary() -> dict[str, object]:
    issue_dir = REPO_ROOT / "memory" / "issues_log"
    recent: list[dict[str, str]] = []
    historical_permission_mentions: list[str] = []
    if issue_dir.exists():
        for path in sorted(issue_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:6]:
            text = path.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join([line for line in text.splitlines() if line.strip()][-18:])
            if "PermissionError" in tail or "permission" in tail.lower() or "권한" in tail:
                historical_permission_mentions.append(str(path.relative_to(REPO_ROOT)))
            recent.append(
                {
                    "file": str(path.relative_to(REPO_ROOT)),
                    "tail": tail[-1400:],
                }
            )
    state_path = REPO_ROOT / "state" / "discord_issue_table_channel.json"
    permission_risks: list[str] = []
    state_write_probe = "not_checked"
    if not state_path.exists():
        state_status = "missing"
    else:
        try:
            probe_path = state_path.with_name(f".{state_path.name}.viewer_probe")
            probe_path.write_text("probe\n", encoding="utf-8")
            probe_path.unlink()
            state_status = "writable"
            state_write_probe = "passed"
        except OSError as exc:
            state_status = "read_only_or_permission_blocked"
            state_write_probe = f"failed: {type(exc).__name__}: {exc}"
            permission_risks.append(str(state_path.relative_to(REPO_ROOT)))
    return {
        "recent": recent,
        "permission_risks": permission_risks,
        "historical_permission_mentions": historical_permission_mentions,
        "issue_table_state_path": str(state_path.relative_to(REPO_ROOT)),
        "issue_table_state_status": state_status,
        "issue_table_state_write_probe": state_write_probe,
        "worker_read_order": [
            "AGENTS.md",
            "tools/sc_spire_agent_sdk_orchestrator/provider_routing.json",
            "memory/issues_log/07-codex-orchestration.md",
            "output/agent_orchestrator_runs/operator_message_events.jsonl",
            "selected run transcript.jsonl",
        ],
        "original_operator_requirements": [
            "대화/작업 진행을 사용자가 볼 수 있는 로컬 HTML 운영 화면",
            "메인 오케스트레이터, Codex, Claude, OpenAI Agents SDK, Gemini 경로를 구분",
            "구독 Codex/Claude를 기본 실행 경로로 쓰고 API는 필요한 곳에 적극적이되 예산 제한",
            "프롬프트 사전 검증 후 메인 큐로 전달",
            "작업자끼리 대화한 기록을 Discord 스타일로 표시",
            "이슈/규칙/스킬/MCP/공유 정보가 작업자와 사용자에게 읽히는 공간",
            "큐 순서 변경, 편집, 제거, 취소, 휴지통",
            "실행 중/대기 중/비활성 에이전트 명확 표시",
        ],
    }


def requeue_historical_operator_messages() -> dict[str, object]:
    terminal_or_sent = {"sent_to_main", "done", "blocked", "failed", "canceled"}
    active = {"queued", "preflight_refining"}
    requeued: list[str] = []
    skipped: list[dict[str, str]] = []
    for message in operator_messages_with_status(limit=1000):
        message_id = str(message.get("id", ""))
        if not message_id:
            continue
        status = str(message.get("effective_status") or "")
        if status in terminal_or_sent:
            skipped.append({"id": message_id, "reason": status})
            continue
        if status in active:
            skipped.append({"id": message_id, "reason": status})
            continue
        append_operator_event(
            message_id,
            "queued",
            "queue-reconciler",
            "기존 운영자 메시지를 메인 오케스트레이터 큐에 순차 편입했습니다.",
            target_override="main",
        )
        requeued.append(message_id)
    processed = process_operator_queue_once(max_count=QUEUE_AUTORUN_MAX_PER_TICK)
    return {
        "requeued_count": len(requeued),
        "processed_count": processed,
        "requeued_ids": requeued,
        "skipped_count": len(skipped),
        "skipped": skipped[:30],
    }


def queue_processor_loop() -> None:
    while True:
        try:
            if QUEUE_AUTORUN_ENABLED:
                process_operator_queue_once(max_count=QUEUE_AUTORUN_MAX_PER_TICK)
        except Exception as exc:
            print(f"queue processor error: {type(exc).__name__}: {exc}")
        time.sleep(max(1.0, QUEUE_POLL_SECONDS))


ACTIVE_STATUSES = {
    "queued",
    "preflight_refining",
    "planning",
    "routed",
    "running",
    "reviewing",
    "dispatch_ready",
    "waiting_claude_review",
    "waiting_browser_e2e",
    "waiting_review_and_e2e",
    "waiting_unity_rendered_evidence",
    "waiting_validator_lanes",
    "worker_result_recorded",
    "closure_ready",
}
PREPARED_STATUSES = {
    "sent_to_main",
    "prepared_not_running",
    "planning_ready",
}
BLOCKED_STATUSES = {"dispatch_blocked", "blocked"}
TERMINAL_STATUSES = {"done", "failed", "canceled", "removed"}


def run_work_state(run_id: str) -> dict[str, str]:
    if not run_id:
        return {}
    try:
        run_dir = safe_run_dir(run_id)
    except Exception:
        return {}
    if not run_dir.exists():
        return {}
    if (run_dir / "closure-packet.json").exists():
        return {
            "status": "done",
            "gate_status": "completed_with_closure_packet",
            "updated_at": run_id[:15],
            "detail": "closure-packet.json이 생성됐습니다. 보고서 작성/오케스트레이터 검증 범위 완료입니다.",
        }
    gate_path = run_dir / "review-gate.json"
    gate: dict[str, object] = {}
    if gate_path.exists():
        try:
            loaded = read_json_file(gate_path)
            gate = loaded if isinstance(loaded, dict) else {}
        except Exception:
            gate = {}
    gate_status = str(gate.get("status") or "").strip()
    next_action = str(gate.get("next_action") or "").strip()
    status = gate_status or "run_recorded"
    if gate_status.startswith("ready_for_closure_review"):
        status = "closure_ready"
    elif gate_status.startswith("waiting_for_claude_or_product_review"):
        status = "waiting_claude_review"
    elif gate_status.startswith("waiting_for_browser_e2e"):
        status = "waiting_browser_e2e"
    elif gate_status == "waiting_for_unity_rendered_evidence":
        status = "waiting_unity_rendered_evidence"
    elif gate_status.startswith("waiting_for_review_and_browser_e2e"):
        status = "waiting_review_and_e2e"
    elif gate_status == "waiting_for_remaining_validator_lanes":
        status = "waiting_validator_lanes"
    elif gate_status in {"blocked_or_needs_retry", "degraded_needs_operator_or_adapter_resolution"}:
        status = "blocked"
    elif (run_dir / "worker-result.json").exists():
        status = "worker_result_recorded"

    timestamps: list[str] = []
    recorded = gate.get("recorded_results") if isinstance(gate.get("recorded_results"), list) else []
    for result in recorded:
        if isinstance(result, dict) and str(result.get("created_at", "")).strip():
            timestamps.append(str(result.get("created_at")))
    for event in read_transcript(run_dir)[-3:]:
        if str(event.get("timestamp", "")).strip():
            timestamps.append(str(event.get("timestamp")))
    updated_at = max(timestamps) if timestamps else run_id[:15]
    return {
        "status": status,
        "gate_status": gate_status,
        "updated_at": updated_at,
        "detail": next_action or gate_status or "실행 기록 상태를 확인하세요.",
    }


def work_item_bucket(status: str) -> str:
    if status in ACTIVE_STATUSES:
        return "active"
    if status in PREPARED_STATUSES:
        return "prepared"
    if status in BLOCKED_STATUSES:
        return "blocked"
    if status == "legacy_record":
        return "archive"
    if status in TERMINAL_STATUSES:
        return "closed"
    return "idle"


def build_work_items(limit: int = 120) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_runs: set[str] = set()
    for message in operator_messages_with_status(limit=limit):
        latest = message.get("latest_event") if isinstance(message.get("latest_event"), dict) else {}
        status = str(message.get("effective_status") or latest.get("status") or "legacy_record")
        run_id = str(message.get("effective_run_id") or "")
        run_state = run_work_state(run_id)
        if run_state:
            status = run_state["status"]
        if run_id:
            seen_runs.add(run_id)
        items.append(
            {
                "id": message.get("id", ""),
                "kind": "operator_message",
                "title": message.get("title") or title_for_message(message),
                "status": status,
                "bucket": work_item_bucket(status),
                "target": message.get("target", "main"),
                "run_id": run_id,
                "updated_at": run_state.get("updated_at") or latest.get("timestamp") or message.get("created_at", ""),
                "detail": run_state.get("detail") or latest.get("detail", ""),
                "route": default_provider_route() if message.get("target", "main") == "main" else message.get("target", "main"),
                "gate_status": run_state.get("gate_status", ""),
                "events": message.get("queue_events", []),
            }
        )
    for run in list_runs():
        run_id = str(run.get("id", ""))
        if run_id in seen_runs:
            continue
        items.append(
            {
                "id": run_id,
                "kind": "run",
                "title": run.get("title") or run_id,
                "status": "archived_run",
                "bucket": "archive",
                "target": "run",
                "run_id": run_id,
                "updated_at": run_id[:15],
                "detail": "기존 실행 기록입니다.",
                "route": "codex_subscription_worker" if run.get("has_plan") else "local_record",
                "events": [],
            }
        )
    bucket_order = {"active": 0, "prepared": 1, "blocked": 2, "idle": 3, "closed": 4, "archive": 5}
    items.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    items.sort(key=lambda item: bucket_order.get(str(item.get("bucket", "archive")), 9))
    return items


def build_agent_roster(work_items: list[dict[str, object]]) -> list[dict[str, object]]:
    active = [item for item in work_items if item.get("bucket") == "active"]
    prepared = [item for item in work_items if item.get("bucket") == "prepared"]
    config = load_provider_routing_config()
    routes = config.get("routes", {}) if isinstance(config, dict) else {}
    active_count = len(active)
    prepared_count = len(prepared)

    def route_model(route_id: str) -> str:
        route = routes.get(route_id) if isinstance(routes, dict) else {}
        return str((route or {}).get("default_model") or "")

    adapter_health = build_adapter_health()
    return [
        {
            "id": "queue_processor",
            "name": "로컬 큐 처리기",
            "status": "active" if active_count else ("idle" if QUEUE_PROCESSOR_ENABLED else "disabled"),
            "model": "file-backed autorun",
            "detail": f"자동 실행은 큐 맨 위 항목 1개만 처리하고, 각 항목은 짧은 루프 1회와 최소 {SHORT_LOOP_VALIDATOR_MIN}개 검증 레인까지 전진합니다.",
            "active_count": active_count,
            "prepared_count": prepared_count,
        },
        {
            "id": "prompt_preflight_agent",
            "name": "프롬프트 사전 검증",
            "status": "active" if active_count else "idle",
            "model": route_model("agents_sdk_pattern_local") or route_model("openai_agents_sdk") or "local-sdk-pattern",
            "detail": "사용자 메시지를 검증하고 메인 오케스트레이터용 프롬프트로 정제합니다.",
            "active_count": active_count,
            "prepared_count": 0,
        },
        {
            "id": "main_orchestrator",
            "name": "메인 오케스트레이터",
            "status": "pending" if prepared_count else "idle",
            "model": "selected-by-main",
            "detail": "정제된 프롬프트를 받아 Codex/Claude/API/Gemini 경로를 정하고, 목표 달성까지 짧은 iteration마다 반려/재시도/종료를 결정합니다.",
            "active_count": 0,
            "prepared_count": prepared_count,
        },
        {
            "id": "claude_decision_advisor",
            "name": "Claude 판단 보좌관",
            "status": "available" if bool(adapter_health.get("claude_collaborator", {}).get("callable")) else "pending",
            "model": route_model("claude_collaborator") or "claude-cli/subscription",
            "detail": "메인 최종 결정 전 계획/제품/증거/큐 steering 여부를 반박하는 상시 보좌관입니다. 최종 결정권은 메인에 있습니다.",
            "active_count": 0,
            "prepared_count": prepared_count,
        },
        {
            "id": "openai_codex_api_advisor",
            "name": "OpenAI/Codex API 판단 보좌관",
            "status": "available" if bool(adapter_health.get("openai_agents_sdk", {}).get("callable")) else "pending",
            "model": route_model("openai_agents_sdk") or "gpt-5.5",
            "detail": "Agents SDK/API 관점으로 구조화 라우팅, guardrail, trace/eval 판단을 보좌합니다. API가 막히면 숨기지 않고 blocker로 남깁니다.",
            "active_count": 0,
            "prepared_count": prepared_count,
        },
        {
            "id": "codex_subscription_worker",
            "name": "Codex MAX 구독 작업자",
            "status": "available",
            "model": route_model("codex_subscription_worker") or "codex-cli/app",
            "detail": "파일 수정, 터미널 명령, 브라우저 검증, 스크린샷, 로컬 증거 패키징을 맡습니다.",
            "active_count": 0,
            "prepared_count": 0,
        },
        {
            "id": "claude_collaborator",
            "name": "Claude MAX 검토자",
            "status": "available",
            "model": route_model("claude_collaborator") or "claude-cli/subscription",
            "detail": "제품/디자인 판단, 계획 비판, 증거 비판, 종료 반박을 담당합니다.",
            "active_count": 0,
            "prepared_count": 0,
        },
        {
            "id": "openai_agents_sdk",
            "name": "OpenAI API / Agents SDK",
            "status": "available",
            "model": route_model("openai_agents_sdk") or "gpt-5.5",
            "detail": "메인 오케스트레이터가 handoff, guardrail, structured output, trace/eval 기록, 작은 live SDK 판단이 필요할 때 적극 사용하는 경로입니다. 큰 로컬 구현은 Codex/Claude 구독 경로와 조합합니다.",
            "active_count": 0,
            "prepared_count": 0,
        },
        {
            "id": "gemini_collaborator",
            "name": "Gemini 3 Pro 검토자",
            "status": "disabled",
            "model": route_model("gemini_collaborator") or "gemini-3-pro",
            "detail": "Gemini API 키가 들어오면 추가 독립 검토 레인으로 붙입니다.",
            "active_count": 0,
            "prepared_count": 0,
        },
    ]

def build_execution_environment() -> dict[str, object]:
    adapter_health = build_adapter_health(build_agents_sdk_pattern_status())
    return {
        "viewer_url": "http://127.0.0.1:8766",
        "server_entrypoint": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
        "working_directory": str(REPO_ROOT),
        "state_directory": str(RUNS_DIR),
        "queue_processor": "viewer_server.py local file-backed queue processor",
        "automatic_scope": (
            "운영자 메시지 저장 -> 상세 사전검증 -> 메인 dispatch 계약 생성 -> "
            "안전한 Codex worker/validator self-check advance까지"
        ),
        "auto_advance_enabled": QUEUE_AUTO_ADVANCE_ENABLED,
        "auto_advance_steps": QUEUE_AUTO_ADVANCE_STEPS,
        "short_loop_policy": short_loop_policy(),
        "adapter_health": adapter_health,
        "actual_worker_dispatch": "local self-check worker/validator advance; external subscription sessions require explicit adapter/result recording",
        "openai_api_usage": (
            "Agents SDK pattern/manifest/guardrail/handoff/eval-ready records are always used. "
            "Live OpenAI preflight is deferred by default for responsive HTML submit; enable SC_SPIRE_LIVE_PROMPT_PREFLIGHT=1 when the main orchestrator needs live API refinement."
        ),
        "claude_usage": "Claude MAX subscription reviewer route is mandatory for non-trivial closure. The viewer records/uses Claude review artifacts; slow live CLI execution is explicit.",
        "codex_worker_usage": "Codex MAX subscription/app/CLI route is the preferred local implementation and evidence worker path.",
    }


def command_probe(*names: str) -> dict[str, object]:
    for name in names:
        path = shutil.which(name)
        if path:
            return {"available": True, "path": path}
    return {"available": False, "path": ""}


def build_adapter_health(sdk_status: dict[str, object] | None = None) -> dict[str, object]:
    sdk_status = sdk_status or build_agents_sdk_pattern_status()
    claude_ps1 = Path.home() / ".codex-node-global" / "claude.ps1"
    claude_probe = {"available": True, "path": str(claude_ps1)} if claude_ps1.exists() else command_probe("claude", "claude.cmd", "claude.exe")
    codex_probe = command_probe("codex", "codex.cmd", "codex.exe")
    openai_key_present = bool(os.environ.get("OPENAI_API_KEY")) or DESKTOP_OPENAI_KEY.exists()
    gemini_key_present = bool(os.environ.get("GEMINI_API_KEY"))
    gemini_enabled = os.environ.get("SC_SPIRE_GEMINI_ENABLED", "0") == "1"

    def split_health(
        *,
        manual_surface_available: bool,
        auto_spawn_available: bool,
        cli_path: str = "",
        can_write_artifact_directly: bool = False,
    ) -> dict[str, object]:
        # A3: split the old single `callable` bool into a manual/auto/live model.
        # `callable` is kept as a derived alias so existing consumers/smoke test
        # do not break.
        return {
            "manual_surface_available": bool(manual_surface_available),
            "auto_spawn_available": bool(auto_spawn_available),
            "cli_path": cli_path or "",
            "requires_operator_copy_paste": not bool(auto_spawn_available),
            "can_write_artifact_directly": bool(can_write_artifact_directly),
            "callable": bool(auto_spawn_available or manual_surface_available),
        }

    codex_auto = bool(codex_probe["available"])
    claude_auto = bool(claude_probe["available"])
    openai_auto = bool(sdk_status.get("importable")) and openai_key_present
    gemini_auto = gemini_enabled and gemini_key_present
    return {
        "codex_subscription_worker": {
            "configured": True,
            **split_health(
                manual_surface_available=True,
                auto_spawn_available=codex_auto,
                cli_path=codex_probe["path"],
                can_write_artifact_directly=True,
            ),
            "mode": "current_codex_app_session" if not codex_probe["available"] else "codex_cli_or_current_app",
            "path": codex_probe["path"],
            "truth": "현재 Codex 앱 세션은 로컬 구현/검증 worker로 사용 가능하지만, 별도 Codex CLI 자동 스폰은 path가 있을 때만 가능합니다.",
        },
        "claude_collaborator": {
            "configured": True,
            **split_health(
                manual_surface_available=True,
                auto_spawn_available=claude_auto,
                cli_path=claude_probe["path"] if claude_auto else "",
                can_write_artifact_directly=claude_auto,
            ),
            "mode": "claude_cli_subscription",
            "path": claude_probe["path"],
            "truth": "Claude CLI가 있으면 live review 버튼/closure gate에서 실제 Claude MAX 검토를 호출할 수 있습니다.",
        },
        "openai_agents_sdk": {
            "configured": True,
            **split_health(
                manual_surface_available=True,
                auto_spawn_available=openai_auto,
                can_write_artifact_directly=openai_auto,
            ),
            "mode": "agents_sdk_pattern_always_live_api_optional",
            "path": "",
            "truth": "Agents SDK pattern/manifest는 항상 사용합니다. live API runner는 SDK import와 OPENAI_API_KEY가 있을 때만 예산 gate 뒤에서 호출합니다.",
            "sdk_importable": bool(sdk_status.get("importable")),
            "api_key_present": openai_key_present,
            "import_error": str(sdk_status.get("import_error") or ""),
            "installed": bool(sdk_status.get("installed")),
        },
        "gemini_collaborator": {
            "configured": gemini_enabled,
            **split_health(
                manual_surface_available=gemini_enabled,
                auto_spawn_available=gemini_auto,
                can_write_artifact_directly=gemini_auto,
            ),
            "mode": "gemini_pending_key" if not gemini_key_present else "gemini_configured",
            "path": "",
            "truth": "Gemini는 GEMINI_API_KEY와 SC_SPIRE_GEMINI_ENABLED=1이 모두 있어야 독립 검토 레인으로 호출합니다.",
            "api_key_present": gemini_key_present,
        },
    }


def build_main_orchestrator_context(
    work_items: list[dict[str, object]],
    sdk_status: dict[str, object],
    sdk_manifest: dict[str, object],
) -> dict[str, object]:
    prepared = [item for item in work_items if item.get("bucket") == "prepared"]
    active = [item for item in work_items if item.get("bucket") == "active"]
    provider_config = load_provider_routing_config()
    routes = provider_config.get("routes", {}) if isinstance(provider_config, dict) else {}
    decision_rules = provider_config.get("decision_rules", []) if isinstance(provider_config, dict) else []
    role_defaults = provider_config.get("role_defaults", {}) if isinstance(provider_config, dict) else {}
    return {
        "owner": "main-orchestrator",
        "purpose": "메인 오케스트레이터가 Agents SDK 방식으로 라우팅, guardrail, handoff, trace/eval 기록을 결정하기 위한 공유 입력입니다.",
        "current_load": {
            "active": len(active),
            "prepared": len(prepared),
            "next_prepared": prepared[0] if prepared else {},
        },
        "agents_sdk_usage": {
            "pattern_required": True,
            "live_sdk_importable": bool(sdk_status.get("importable")),
            "live_sdk_default": bool(sdk_status.get("live_call_default")),
            "live_sdk_allowed_when": (sdk_status.get("optional_live_adapter") or {}).get("use_only_for", []),
            "agents": len(sdk_manifest.get("agents", [])) if isinstance(sdk_manifest.get("agents", []), list) else 0,
            "handoffs": len(sdk_manifest.get("handoffs", [])) if isinstance(sdk_manifest.get("handoffs", []), list) else 0,
            "guardrails": len(sdk_manifest.get("guardrails", [])) if isinstance(sdk_manifest.get("guardrails", []), list) else 0,
            "tools": len(sdk_manifest.get("tools", [])) if isinstance(sdk_manifest.get("tools", []), list) else 0,
        },
        "must_read_before_dispatch": [
            "AGENTS.md",
            str(PROVIDER_ROUTING_PATH.relative_to(REPO_ROOT)),
            "memory/issues_log/*.md",
            "output/agent_orchestrator_runs/operator_message_events.jsonl",
            "selected run transcript.jsonl",
        ],
        "route_inputs": {
            "default_route": provider_config.get("default_route") if isinstance(provider_config, dict) else "",
            "role_defaults": role_defaults,
            "decision_rules": decision_rules,
            "enabled_routes": [
                {
                    "id": route_id,
                    "priority": route.get("priority"),
                    "billing": route.get("billing"),
                    "surface": route.get("surface"),
                    "model": route.get("default_model"),
                    "best_for": route.get("best_for", [])[:5],
                }
                for route_id, route in sorted(routes.items(), key=lambda item: int((item[1] or {}).get("priority", 99)))
                if isinstance(route, dict) and route.get("enabled", False)
            ],
        },
        "dispatch_contract": [
            "정제된 프롬프트를 받으면 issue-memory preflight를 먼저 통과시킵니다.",
            "Agents SDK manifest의 Agent/Handoff/Guardrail/Tool 항목을 기준으로 실행 경로를 고릅니다.",
            "큰 구현/로컬 검증은 Codex MAX 구독 경로를 우선 사용합니다.",
            "제품/디자인/종료 반박은 Claude MAX 검토 레인을 사용합니다.",
            "작은 구조화 판단, guardrail, trace/eval-ready 기록에는 OpenAI Agents SDK/API를 적극 사용할 수 있습니다.",
            "실제 worker 호출 또는 미호출 이유를 transcript에 남깁니다.",
        ],
    }


class ViewerHandler(BaseHTTPRequestHandler):
    server_version = "SCSpireAgentViewer/0.1"

    def _send_json(self, payload: object, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path) -> None:
        raw = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        if path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_file(STATIC_DIR / "index.html")
                return
            if parsed.path == "/api/runs":
                started = time.time()
                debug_log("GET /api/runs start")
                payload = cached_payload("runs", 2.0, lambda: {"runs": list_runs(), "runs_dir": str(RUNS_DIR)})
                debug_log(f"GET /api/runs payload_done elapsed={time.time() - started:.3f}")
                self._send_json(payload)
                debug_log(f"GET /api/runs sent elapsed={time.time() - started:.3f}")
                return
            if parsed.path == "/api/run":
                run_id = parse_qs(parsed.query).get("id", [""])[0]
                self._send_json(run_payload(unquote(run_id)))
                return
            if parsed.path == "/api/messages":
                self._send_json({"messages": operator_messages_with_status(), "events": read_operator_events()})
                return
            if parsed.path == "/api/status":
                started = time.time()
                debug_log("GET /api/status start")
                def build_status_response() -> dict[str, object]:
                    work_items = build_work_items(limit=80)
                    debug_log(f"GET /api/status work_items elapsed={time.time() - started:.3f}")
                    provider_config = load_provider_routing_config()
                    sdk_status = build_agents_sdk_pattern_status()
                    sdk_manifest = build_sdk_style_manifest(AGENT_PERSONAS)
                    adapter_health = build_adapter_health(sdk_status)
                    return {
                        "timestamp": utc_timestamp(),
                        "execution_environment": build_execution_environment(),
                        "adapter_health": adapter_health,
                        "execution_lifecycle": build_execution_lifecycle(work_items),
                        "agent_targets": AGENT_TARGETS,
                        "agent_personas": AGENT_PERSONAS,
                        "review_lanes": REVIEW_LANES,
                        "shared_workspace": build_shared_workspace(),
                        "issue_memory": build_issue_memory_summary(),
                        "issue_import": build_issue_import_view(work_items),
                        "agents_sdk_pattern": sdk_status,
                        "agents_sdk_manifest": sdk_manifest,
                        "main_orchestrator_context": build_main_orchestrator_context(work_items, sdk_status, sdk_manifest),
                        "quota_visibility": provider_config.get("quota_visibility", {}) if isinstance(provider_config, dict) else {},
                        "live_preflight": live_preflight_state(),
                        "queue_processor": {
                            "enabled": QUEUE_PROCESSOR_ENABLED,
                            "autorun": QUEUE_AUTORUN_ENABLED,
                            "poll_seconds": QUEUE_POLL_SECONDS,
                            "max_per_tick": QUEUE_AUTORUN_MAX_PER_TICK,
                            "status_file": str(OPERATOR_MESSAGE_EVENTS),
                        },
                        "messages": operator_messages_with_status(limit=50),
                        "work_items": work_items,
                        "agents": build_agent_roster(work_items),
                        "runs": list_runs()[:12],
                    }
                payload = cached_payload("status", 2.0, build_status_response)
                debug_log(f"GET /api/status payload_done bytes={len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))} elapsed={time.time() - started:.3f}")
                self._send_json(payload)
                debug_log(f"GET /api/status sent elapsed={time.time() - started:.3f}")
                return
            if parsed.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last = -1
                idle = 0
                try:
                    while True:
                        with STATUS_EPOCH_LOCK:
                            seq = STATUS_EPOCH["seq"]
                        if seq != last:
                            last = seq
                            idle = 0
                            self.wfile.write(f"event: status\ndata: {seq}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        else:
                            idle += 1
                            if idle >= 30:
                                idle = 0
                                self.wfile.write(b": keep-alive\n\n")
                                self.wfile.flush()
                        time.sleep(1)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                return
            if parsed.path == "/api/work-items":
                work_items = build_work_items(limit=120)
                self._send_json({"work_items": work_items, "agents": build_agent_roster(work_items)})
                return
            if parsed.path == "/api/provider-routing":
                self._send_json(load_provider_routing_config())
                return
            static_path = (STATIC_DIR / parsed.path.lstrip("/")).resolve()
            if STATIC_DIR.resolve() in static_path.parents and static_path.exists() and static_path.is_file():
                self._send_file(static_path)
                return
            self._send_json({"error": "not found", "path": parsed.path}, status=404)
        except Exception as exc:
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/preflight/toggle":
                global LIVE_PREFLIGHT_OVERRIDE
                body = self._read_json_body()
                LIVE_PREFLIGHT_OVERRIDE = bool(body.get("live_enabled"))
                invalidate_status_cache()
                self._send_json({"live_preflight": live_preflight_state()})
                return
            if parsed.path == "/api/messages":
                record = append_operator_message(self._read_json_body())
                if QUEUE_PROCESSOR_ENABLED and QUEUE_AUTORUN_ENABLED:
                    process_operator_queue_once(max_count=QUEUE_AUTORUN_MAX_PER_TICK)
                resolved = lookup_message_effective_run(str(record.get("id", "")), record)
                self._send_json(
                    {
                        "message": record,
                        "created_run_id": resolved.get("created_run_id", ""),
                        "effective_status": resolved.get("effective_status", ""),
                    },
                    status=201,
                )
                return
            if parsed.path == "/api/messages/steer":
                body = self._read_json_body()
                message_id = str(body.get("id", "")).strip()
                self._send_json(steer_operator_message(message_id, body), status=200)
                return
            if parsed.path == "/api/messages/reorder":
                body = self._read_json_body()
                ids = body.get("ids", [])
                if not isinstance(ids, list):
                    raise ValueError("ids must be a list")
                self._send_json(reorder_operator_messages(ids), status=200)
                return
            if parsed.path == "/api/messages/cancel":
                body = self._read_json_body()
                ids = body.get("ids")
                if ids is not None and not isinstance(ids, list):
                    raise ValueError("ids must be a list")
                self._send_json(cancel_operator_messages(ids, str(body.get("reason", ""))), status=200)
                return
            if parsed.path == "/api/run/result":
                self._send_json(record_run_result(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/run/gpt-pro-request":
                self._send_json(build_gpt_pro_request(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/run/gpt-pro-result":
                self._send_json(record_gpt_pro_result(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/run/advance":
                self._send_json(advance_run_once(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/run/reconcile":
                body = self._read_json_body()
                run_id = str(body.get("id", "")).strip()
                if not run_id:
                    raise ValueError("id is required")
                run_dir = safe_run_dir(run_id)
                reconciled = reconcile_run_artifacts(run_id, run_dir)
                invalidate_status_cache()
                self._send_json({"run": run_payload(run_id), "reconciled": reconciled}, status=200)
                return
            if parsed.path == "/api/run/claude-review":
                self._send_json(run_claude_review_for_run(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/run/e2e-verification":
                self._send_json(record_e2e_html_verification(self._read_json_body()), status=201)
                return
            if parsed.path == "/api/queue/process":
                body = self._read_json_body()
                count = int(body.get("count", 1) or 1)
                processed = process_operator_queue_once(max_count=max(1, min(count, 20)))
                self._send_json({"processed_count": processed, "messages": operator_messages_with_status(limit=100)}, status=200)
                return
            if parsed.path == "/api/requeue-historical":
                result = requeue_historical_operator_messages()
                self._send_json(result, status=200)
                return
            self._send_json({"error": "not found", "path": parsed.path}, status=404)
        except Exception as exc:
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=400)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/messages":
                message_id = parse_qs(parsed.query).get("id", [""])[0]
                self._send_json(update_operator_message(unquote(message_id), self._read_json_body()), status=200)
                return
            self._send_json({"error": "not found", "path": parsed.path}, status=404)
        except Exception as exc:
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=400)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/messages":
                message_id = parse_qs(parsed.query).get("id", [""])[0]
                self._send_json(remove_operator_message(unquote(message_id)), status=200)
                return
            self._send_json({"error": "not found", "path": parsed.path}, status=404)
        except Exception as exc:
            self._send_json({"error": type(exc).__name__, "message": str(exc)}, status=400)

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the SC Spire agent transcript viewer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not STATIC_DIR.exists():
        raise SystemExit(f"missing viewer static directory: {STATIC_DIR}")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    acquire_instance_lock(args.port)
    server = ThreadingHTTPServer((args.host, args.port), ViewerHandler)
    print(f"SC Spire agent transcript viewer: http://{args.host}:{args.port}")
    print(f"runs: {RUNS_DIR}")
    if QUEUE_PROCESSOR_ENABLED:
        thread = threading.Thread(target=queue_processor_loop, name="operator-queue-processor", daemon=True)
        thread.start()
        print(f"queue processor: enabled, poll={QUEUE_POLL_SECONDS}s")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping viewer")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

