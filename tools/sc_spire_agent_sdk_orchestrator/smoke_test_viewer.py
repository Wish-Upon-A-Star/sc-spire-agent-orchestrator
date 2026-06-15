"""Smoke test for the local SC Spire orchestrator viewer.

Run while viewer_server.py is listening on http://127.0.0.1:8766.
This intentionally uses only the Python standard library so it can run in the
same lightweight environment as the viewer server.
"""

from __future__ import annotations

import json
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8766"


def fetch_text(path: str) -> str:
    with urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        if response.status != 200:
            raise AssertionError(f"{path} returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def fetch_json(path: str) -> dict[str, object]:
    return json.loads(fetch_text(path))


def send_json(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = b""
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=data if method in {"POST", "PATCH"} else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise AssertionError(f"{method} {path} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8", errors="replace"))


def assert_contains(label: str, text: str, needles: list[str]) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        raise AssertionError(f"{label} missing: {missing}")


def message_by_id(message_id: str) -> dict[str, object]:
    payload = fetch_json("/api/messages")
    for message in payload.get("messages", []):
        if str(message.get("id", "")) == message_id:
            return message
    raise AssertionError(f"message not found: {message_id}")


def create_html_queue_message(marker: str) -> str:
    payload = send_json("POST", "/api/messages", {"target": "html", "message": marker})
    message = payload.get("message") or {}
    message_id = str(message.get("id", ""))
    if not message_id:
        raise AssertionError("POST /api/messages did not return a message id")
    return message_id


def verify_queue_controls() -> dict[str, object]:
    stamp = str(int(time.time() * 1000))
    edit_id = create_html_queue_message(f"queue-smoke-edit-{stamp}")
    second_id = create_html_queue_message(f"queue-smoke-second-{stamp}")
    cancel_id = create_html_queue_message(f"queue-smoke-cancel-{stamp}")

    edited_text = f"queue-smoke-edited-{stamp}"
    send_json("PATCH", f"/api/messages?id={quote(edit_id)}", {"target": "html", "message": edited_text, "priority": 10})
    edited = message_by_id(edit_id)
    if edited.get("original_message") != edited_text:
        raise AssertionError("PATCH /api/messages did not update original_message")

    send_json("POST", "/api/messages/steer", {"id": edit_id, "target": "html", "note": "smoke steer"})
    steered = message_by_id(edit_id)
    if steered.get("target") != "html":
        raise AssertionError("POST /api/messages/steer did not keep target override")

    reordered = send_json("POST", "/api/messages/reorder", {"ids": [second_id, edit_id]})
    if int(reordered.get("updated_count", 0)) < 2:
        raise AssertionError("POST /api/messages/reorder did not update both test messages")

    canceled = send_json("POST", "/api/messages/cancel", {"ids": [cancel_id], "reason": "viewer smoke test"})
    if cancel_id not in canceled.get("canceled_ids", []):
        raise AssertionError("POST /api/messages/cancel did not cancel the test message")
    if message_by_id(cancel_id).get("effective_status") != "canceled":
        raise AssertionError("canceled message effective_status is not canceled")

    send_json("DELETE", f"/api/messages?id={quote(edit_id)}")
    send_json("DELETE", f"/api/messages?id={quote(second_id)}")
    if message_by_id(edit_id).get("effective_status") != "removed":
        raise AssertionError("DELETE /api/messages did not mark edit message removed")
    if message_by_id(second_id).get("effective_status") != "removed":
        raise AssertionError("DELETE /api/messages did not mark second message removed")

    return {
        "edited": edit_id,
        "reordered": [second_id, edit_id],
        "canceled": cancel_id,
        "removed": [edit_id, second_id],
    }


def main() -> int:
    html = fetch_text("/")
    assert_contains(
        "index html",
        html,
        [
            "에이전트 실행",
            "상태",
            "작업자 대화",
            "마일스톤",
            "이슈/공유정보",
            "실행 기록",
            "라우팅/규칙",
            "실시간 큐",
            "메시지 넣기",
            "작업자/검토 결과 기록",
            "화면 E2E 검증 기록",
            "GPT Pro 검토 패킷 만들기",
            "GPT Pro 답변 붙여넣기",
        ],
    )

    app_js = fetch_text("/app.js")
    assert_contains(
        "app js",
        app_js,
        [
            "renderOperationsConsole",
            "renderAdvisoryCouncil",
            "케르베로스",
            "d-drive-report-pack.json",
            "report-pack-judgment.json",
            "report-evidence-audit.json",
            "goal-completion-audit.json",
            "unity-rendered-evidence.json",
            "report-pack-retry-prompt.md",
            "평문 요청으로 생성된 D드라이브 보고서",
            "renderCompletionChecklist",
            "collectBrowserE2eChecks",
            "recordE2e",
            "loop-policy-line",
            "ops-validator-lanes",
            "ops-advisory",
            "handleQueueAction",
            "호출 가능",
            "Adapter",
            "renderPreflightBanner",
            "renderCommandStrip",
            "/api/run/gpt-pro-request",
            "/api/run/gpt-pro-result",
            "gptProRequest",
        ],
    )

    styles = fetch_text("/styles.css")
    assert_contains("styles", styles, ["ops-console", "ops-metric", "ops-checks", "ops-validator-lanes", "ops-advisory", "ops-advisor-grid", "ops-deliberation", "report-pack-summary", "report-pack-verdict", "report-evidence-audit", "goal-completion-audit", "unity-rendered-evidence", "preflight-banner", "command-strip", "gpt-pro-divider"])

    status = fetch_json("/api/status")
    for key in ["runs", "messages", "agents", "execution_lifecycle", "queue_processor", "execution_environment", "adapter_health", "live_preflight", "workflow_states"]:
        if key not in status:
            raise AssertionError(f"/api/status missing key: {key}")
    workflow_states = status.get("workflow_states") or {}
    if not isinstance(workflow_states, dict) or "waiting_for_operator" not in workflow_states:
        raise AssertionError("/api/status workflow_states must include waiting_for_operator (A4/L5)")
    if not isinstance(status["runs"], list):
        raise AssertionError("/api/status runs must be a list")
    if not isinstance(status["agents"], list):
        raise AssertionError("/api/status agents must be a list")
    agent_ids = {str(agent.get("id")) for agent in status["agents"] if isinstance(agent, dict)}
    for key in ["claude_decision_advisor", "openai_codex_api_advisor"]:
        if key not in agent_ids:
            raise AssertionError(f"/api/status agents missing advisory agent: {key}")

    loop_policy = status["execution_lifecycle"].get("loop_policy") or {}
    if loop_policy.get("goal_until_complete") is not True:
        raise AssertionError("/api/status loop_policy must continue short iterations until goal completion")
    if loop_policy.get("mode") != "goal_until_complete_short_iterations":
        raise AssertionError("/api/status loop_policy mode must be goal_until_complete_short_iterations")
    if int(loop_policy.get("minimum_validator_lanes_per_result", 0)) < 4:
        raise AssertionError("/api/status loop_policy must require multiple validator lanes")
    adapter_health = status.get("adapter_health") or {}
    for key in ["codex_subscription_worker", "claude_collaborator", "openai_agents_sdk", "gemini_collaborator"]:
        if key not in adapter_health:
            raise AssertionError(f"/api/status adapter_health missing key: {key}")
        if "callable" not in adapter_health[key]:
            raise AssertionError(f"/api/status adapter_health.{key} missing callable")

    toggled = send_json("POST", "/api/preflight/toggle", {"live_enabled": False})
    if toggled["live_preflight"]["effective_mode"] not in {"template_only", "template_degraded"}:
        raise AssertionError("toggle off did not report a template mode")

    queue_controls = verify_queue_controls()

    print(
        json.dumps(
            {
                "ok": True,
                "runs": len(status["runs"]),
                "agents": len(status["agents"]),
                "queue_autorun": bool(status["queue_processor"].get("autorun")),
                "short_loop_max_attempts": loop_policy.get("max_attempts"),
                "validator_lanes_per_result": loop_policy.get("minimum_validator_lanes_per_result"),
                "callable_adapters": [key for key, value in adapter_health.items() if value.get("callable")],
                "queue_controls": queue_controls,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
