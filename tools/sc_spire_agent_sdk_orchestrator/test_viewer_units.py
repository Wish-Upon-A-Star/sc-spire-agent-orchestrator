import importlib.util
import json
import shutil
import uuid
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "viewer_server",
    Path(__file__).resolve().parent / "viewer_server.py",
)
viewer_server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(viewer_server)


def test_live_preflight_state_reports_key_and_flag():
    state = viewer_server.live_preflight_state()
    assert set(state) >= {"live_enabled", "api_key_present", "effective_mode"}
    assert isinstance(state["live_enabled"], bool)
    assert isinstance(state["api_key_present"], bool)
    # 키는 있는데 플래그가 꺼져 있으면 degraded 로 보고해야 한다 (silent degradation 방지)
    if state["api_key_present"] and not state["live_enabled"]:
        assert state["effective_mode"] == "template_degraded"


def test_suggest_targets_maps_terran_card_to_records():
    hits = viewer_server.suggest_targets("테란 카드 밸런스가 좀 이상한 거 같으니까 한번 봐줘")
    assert isinstance(hits, list)
    assert any("cards_terran" in h or "records" in h for h in hits)


def test_suggest_targets_empty_on_no_signal():
    assert viewer_server.suggest_targets("ㅇㅇ") == []


def test_classify_request_weight_flags_vague():
    assert viewer_server.classify_request_weight("한번 봐줘") == "light"
    assert viewer_server.classify_request_weight("ㅇㅇ 확인") == "light"


def test_classify_request_weight_keeps_specific_as_full():
    text = "data/records/cards_terran.json 의 supply_surge 카드 damage를 12에서 8로 낮춰줘"
    assert viewer_server.classify_request_weight(text) == "full"


def test_rule_based_prompt_includes_suggested_targets():
    refined, meta = viewer_server.build_rule_based_prompt("테란 카드 밸런스 봐줘", "main", {"run_id": "x"})
    assert "data/records/cards_terran.json" in refined
    assert meta["suggested_targets"]


def test_build_rule_based_prompt_handles_none_text():
    # None 입력이 들어와도 TypeError 없이 안전하게 처리되어야 한다 (Codex 리뷰 #3)
    refined, meta = viewer_server.build_rule_based_prompt(None, "main", {})
    assert isinstance(refined, str)
    assert meta["request_weight"] in {"light", "full"}


def test_light_request_skips_full_prd():
    refined, meta = viewer_server.build_rule_based_prompt("한번 봐줘", "main", {})
    assert meta["request_weight"] == "light"
    assert "clarifying" in refined.lower()
    assert "경량(light)" in refined
    # full 모드 전용 섹션이 light 에는 없어야 한다 (ceremony 생략 확인)
    assert "완료 차단 조건:" not in refined


def test_get_run_is_read_only():
    # A1: run_payload (the GET /api/run path) must be PURE READ.
    # Construct a minimal temp run dir that lacks the derived audit artifacts
    # but DOES contain d-drive-report-pack.json (which, under the old code,
    # triggered ensure_* writes). Calling run_payload must NOT create
    # report-pack-judgment.json / report-evidence-audit.json /
    # goal-completion-audit.json.
    run_id = f"zz-test-readonly-{uuid.uuid4().hex[:12]}"
    run_dir = viewer_server.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    derived = [
        "report-pack-judgment.json",
        "report-evidence-audit.json",
        "goal-completion-audit.json",
    ]
    try:
        # Minimal inputs: an orchestration plan + a report pack so the reconcile
        # trigger condition (d-drive-report-pack.json exists) would fire if the
        # mutating block were still in run_payload.
        (run_dir / "orchestration-plan.json").write_text(
            json.dumps({"kind": "operator_prompt_handoff"}), encoding="utf-8"
        )
        (run_dir / "d-drive-report-pack.json").write_text(
            json.dumps({"kind": "d_drive_report_pack", "files": []}), encoding="utf-8"
        )

        before = {item.name for item in run_dir.iterdir() if item.is_file()}
        for name in derived:
            assert name not in before, f"precondition: {name} should not exist yet"

        payload = viewer_server.run_payload(run_id)
        assert payload["id"] == run_id

        after = {item.name for item in run_dir.iterdir() if item.is_file()}
        for name in derived:
            assert name not in after, f"GET /api/run created derived artifact {name}"
        # No new files at all should appear from a pure read.
        assert after == before, f"run_payload created files: {sorted(after - before)}"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_make_provenance_shape():
    # A2: provenance helper must expose the required keys and validate source_type.
    prov = viewer_server.make_provenance("operator_manual", "operator", is_claim_evidence=True)
    for key in ("source_type", "created_by", "is_claim_evidence", "stamped_at"):
        assert key in prov, f"provenance missing required key {key}"
    assert prov["source_type"] == "operator_manual"
    assert prov["created_by"] == "operator"
    assert prov["is_claim_evidence"] is True
    # Empty optional fields are omitted.
    assert "command" not in prov
    assert "exit_code" not in prov
    assert "input_artifacts" not in prov
    assert "verified_by" not in prov
    # Optional fields are included when supplied.
    full = viewer_server.make_provenance(
        "live_openai_api",
        "viewer-server",
        command="openai_responses_api:gpt",
        exit_code=0,
        input_artifacts=["a.json"],
        verified_by=["validator-code-level"],
    )
    assert full["command"] == "openai_responses_api:gpt"
    assert full["exit_code"] == 0
    assert full["input_artifacts"] == ["a.json"]
    assert full["verified_by"] == ["validator-code-level"]
    # Invalid source_type is rejected.
    with pytest.raises(ValueError):
        viewer_server.make_provenance("not_a_real_source", "operator")


def test_record_result_has_provenance():
    # A2: the result record built by record_run_result must carry a provenance
    # block stamped as operator_manual.
    run_id = f"zz-test-provenance-{uuid.uuid4().hex[:12]}"
    run_dir = viewer_server.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = viewer_server.record_run_result(
            {
                "run_id": run_id,
                "result_type": "worker",
                "summary": "provenance smoke summary",
            }
        )
        record = result["result"]
        assert "provenance" in record, "result record missing provenance"
        assert record["provenance"]["source_type"] == "operator_manual"
        assert record["source"] == "operator_recorded_from_viewer"
        # Verify it was actually persisted to disk too.
        written = json.loads((run_dir / result["artifact"]).read_text(encoding="utf-8"))
        assert written["provenance"]["source_type"] == "operator_manual"
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_adapter_health_splits_manual_vs_auto():
    # A3: each adapter must expose the 5 new keys, and callable must be the
    # derived alias of (auto_spawn_available or manual_surface_available).
    health = viewer_server.build_adapter_health()
    new_keys = {
        "manual_surface_available",
        "auto_spawn_available",
        "cli_path",
        "requires_operator_copy_paste",
        "can_write_artifact_directly",
    }
    assert health, "build_adapter_health returned empty"
    for name, adapter in health.items():
        assert new_keys <= set(adapter), f"{name} missing split keys: {new_keys - set(adapter)}"
        assert adapter["callable"] == (
            adapter["auto_spawn_available"] or adapter["manual_surface_available"]
        ), f"{name} callable is not the derived alias"
        assert adapter["requires_operator_copy_paste"] == (not adapter["auto_spawn_available"])
        assert isinstance(adapter["cli_path"], str)
