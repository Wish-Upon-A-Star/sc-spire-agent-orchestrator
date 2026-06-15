# SC Spire Agent SDK Viewer Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영자가 화면만 보고 "지금 무엇이, 어떻게 정제/실행되는지"를 정확히 신뢰할 수 있게 만들고, 평문 정제를 실제로 쓸모 있게 고친다.

**Architecture:** 단일 `viewer_server.py`(stdlib http.server) 백엔드 + 바닐라 JS `viewer_static/`. 변경은 기존 패턴(append-only 이벤트, `cached_payload`, 해시 기반 재렌더, env 플래그)을 따른다. 새 동작은 순수 함수로 빼서 pytest 단위 테스트로 잠그고, 엔드포인트/UI 동작은 `smoke_test_viewer.py` 패턴으로 통합 검증한다.

**Tech Stack:** Python 3.13 stdlib (`http.server`, `threading`, `json`), 바닐라 JS (ES2020), pytest(`.venv\Scripts\python.exe -m pytest`), stdlib 스모크 스크립트.

**실측 근거 (이 계획의 출처):** 브라우저로 평문 "테란 카드 밸런스가 좀 이상한 거 같으니까 한번 봐줘"를 제출한 결과 — (1) `model: None`, `mode: detailed_orchestrator_prompt_from_plaintext`로 **라이브 LLM 정제가 아닌 결정론적 템플릿**이 적용됨([viewer_server.py:1237-1249](../../../tools/sc_spire_agent_sdk_orchestrator/viewer_server.py)), (2) `LIVE_PROMPT_PREFLIGHT_ENABLED` 기본 0이라 키 파일이 있어도 브라우저 경로는 항상 강등, (3) 강등 사유가 화면에 안 뜨고 `검증: 통과`로 보임, (4) 한 문장이 37파일 런 생성, (5) 제출 후 textarea 미초기화 + 새 런 미선택.

---

## File Structure

| 파일 | 책임 | 마일스톤 |
|------|------|---------|
| `tools/sc_spire_agent_sdk_orchestrator/viewer_server.py` | 백엔드 라우트/정제/SSE | M1,M3,M4,M6 |
| `tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js` | 프론트 상태/렌더/SSE 구독 | M1,M2,M4,M5,M6 |
| `tools/sc_spire_agent_sdk_orchestrator/viewer_static/index.html` | 토글/배지/배너 마크업 | M1,M5,M6 |
| `tools/sc_spire_agent_sdk_orchestrator/viewer_static/styles.css` | 배지/배너/light-run 스타일 | M1,M5,M6 |
| `tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py` | **신규** 순수 함수 pytest | M1,M3,M6 |
| `tools/sc_spire_agent_sdk_orchestrator/smoke_test_viewer.py` | 통합 스모크 확장 | M1,M3,M4,M6 |

**우선순위 정렬 (영향×비용):**
1. **M1 (G2) — Live preflight 상태 노출 + UI 토글** · P0 · 신뢰 버그(silent degradation) 제거, 저비용
2. **M2 (G4) — 제출 UX (textarea 초기화 + 새 런 자동선택)** · P0 · 일상 마찰, 최저비용
3. **M3 (G1) — 로컬 정제에 file/where 후보 자동 제안** · P1 · 정제를 실제로 쓸모있게
4. **M4 (P1) — SSE 실시간 + 활성 변경 중 포커스 보존** · P1 · 지연·낭비요청 제거
5. **M5 (P2) — 커맨드 센터 상시 노출** · P2 · "화면만 보고 파악" 완성
6. **M6 (G3) — light run 모드 (vague 요청 ceremony 축소)** · P2 · 코어 변경, 가장 신중

각 마일스톤은 독립적으로 머지·배포 가능하다.

---

## 사전 준비 (모든 마일스톤 공통)

- [ ] **Step 0: 작업 브랜치 생성 (현재 main이면)**

Run:
```bash
cd D:\hobby\sc-spire-orchestrator
git checkout -b feat/viewer-improvements
```

- [ ] **Step 0b: 베이스라인 스모크 통과 확인**

Run (서버가 8766에 떠 있어야 함):
```bash
.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py
```
Expected: 마지막 줄 `{"ok": true, ...}` 출력, exit 0.

---

## M1 (G2): Live preflight 상태 노출 + UI 토글

**왜:** 키 파일이 있어도 `LIVE_PROMPT_PREFLIGHT_ENABLED=0`이면 브라우저 제출이 조용히 템플릿으로 강등되는데, 화면은 `검증: 통과`로 보여 운영자가 정제 누락을 모른다. 강등 상태를 화면에 노출하고, 숨은 env 대신 런타임 토글을 제공한다.

**Files:**
- Create: `tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py`
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_server.py` (전역 플래그 → 가변 상태, `do_GET`/`do_POST`, `preflight_operator_prompt`)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js` (`530-580`, `2700-2719`)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/index.html` (`81-101`)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/styles.css`
- Modify: `tools/sc_spire_agent_sdk_orchestrator/smoke_test_viewer.py`

- [ ] **Step 1: 순수 함수 `live_preflight_state()` 추가 — 실패 테스트 먼저**

Create `tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py`:
```python
import importlib.util
from pathlib import Path

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
```

- [ ] **Step 2: 테스트 실패 확인**

Run:
```bash
.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v
```
Expected: FAIL — `AttributeError: module 'viewer_server' has no attribute 'live_preflight_state'`.

- [ ] **Step 3: 전역 플래그를 가변 상태로 바꾸고 헬퍼 추가**

`viewer_server.py:41` 을 아래로 교체:
```python
LIVE_PROMPT_PREFLIGHT_ENABLED = os.environ.get("SC_SPIRE_LIVE_PROMPT_PREFLIGHT", "0") == "1"
LIVE_PREFLIGHT_OVERRIDE: bool | None = None  # None=env 따름, True/False=런타임 토글
```

`viewer_server.py` 의 `read_openai_api_key`(380) 정의 **다음 줄**에 추가:
```python
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
```

`preflight_operator_prompt`(1239) 의 `if not LIVE_PROMPT_PREFLIGHT_ENABLED:` 를 `if not live_preflight_enabled():` 로, `if ... try: model_validation = call_prompt_preflight_model` 진입 조건도 동일 헬퍼 기준으로 맞춘다 (1250 직전 분기). `read_openai_api_key`(380) 은 키 부재 시 빈 문자열을 반환하도록 이미 동작하면 그대로, 아니면 `return ""` 로 보장.

- [ ] **Step 4: 테스트 통과 확인**

Run:
```bash
.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v
```
Expected: PASS.

- [ ] **Step 5: `/api/status` 에 상태 노출 + 토글 엔드포인트 추가**

`do_GET` 의 `/api/status` 응답 dict(`build_status_response`, 5757-5783)에 한 줄 추가:
```python
                        "live_preflight": live_preflight_state(),
```
`do_POST`(5804) 의 첫 `if` 앞에 새 라우트 추가:
```python
            if parsed.path == "/api/preflight/toggle":
                global LIVE_PREFLIGHT_OVERRIDE
                body = self._read_json_body()
                LIVE_PREFLIGHT_OVERRIDE = bool(body.get("live_enabled"))
                invalidate_status_cache()
                self._send_json({"live_preflight": live_preflight_state()})
                return
```

- [ ] **Step 6: 스모크에 상태 키 검증 추가, 실패 확인**

`smoke_test_viewer.py` 의 `/api/status` 키 루프(162)에 `"live_preflight"` 추가하고, `main()` 의 `queue_controls = verify_queue_controls()` 앞에 삽입:
```python
    toggled = send_json("POST", "/api/preflight/toggle", {"live_enabled": False})
    if toggled["live_preflight"]["effective_mode"] not in {"template_only", "template_degraded"}:
        raise AssertionError("toggle off did not report a template mode")
```
Run: `.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py`
Expected: 서버가 옛 코드면 FAIL (`/api/status missing key: live_preflight`).

- [ ] **Step 7: 서버 재시작 후 스모크 통과 확인**

Run:
```bash
powershell -File tools\sc_spire_agent_sdk_orchestrator\start_agent_viewer.ps1
.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py
```
Expected: `{"ok": true, ...}`.

- [ ] **Step 8: 프론트 — 정제 결과에 effective_mode 배지 표시**

`app.js` 의 send 핸들러 프리뷰 블록(2707-2719)에서 `preflight-meta` 다음에 추가:
```javascript
      ${preflight.live_api_state ? `<span class="pf-badge ${preflight.live_api_state === "deferred" ? "warn" : ""}">live: ${escapeHtml(preflight.live_api_state)}</span>` : ""}
```
그리고 `refreshLiveStatus`(562 블록) 의 재렌더 구간에 `renderPreflightBanner(queueStatus?.live_preflight)` 호출을 추가하고, 새 함수 정의:
```javascript
function renderPreflightBanner(state) {
  const host = document.getElementById("preflight-banner");
  if (!host || !state) return;
  const degraded = state.effective_mode === "template_degraded";
  host.className = `preflight-banner ${degraded ? "warn" : "ok"}`;
  host.textContent = degraded
    ? "정제: 템플릿 강등 (키 있음 · 라이브 꺼짐) — 토글로 켜기"
    : `정제: ${state.effective_mode}`;
  host.hidden = false;
}
```

- [ ] **Step 9: index.html — 배너 + 토글 마크업**

`index.html` 의 `operator-box`(81) 안 `<details ...>` 바로 아래에 삽입:
```html
          <div id="preflight-banner" class="preflight-banner" hidden></div>
          <label class="preflight-toggle">
            <input id="toggle-live-preflight" type="checkbox" />
            <span>라이브 LLM 정제</span>
          </label>
```
`app.js` 초기화부(상단 `el` 객체 부근, 333 근처)에 `toggleLivePreflight: document.getElementById("toggle-live-preflight")` 추가하고, send 핸들러 등록부 근처에 바인딩:
```javascript
if (el.toggleLivePreflight) {
  el.toggleLivePreflight.addEventListener("change", async () => {
    const data = await postJson("/api/preflight/toggle", { live_enabled: el.toggleLivePreflight.checked });
    renderPreflightBanner(data.live_preflight);
  });
}
```

- [ ] **Step 10: styles.css — 배지/배너 스타일 (다크 테마 토큰 사용)**

`styles.css` 끝에 추가:
```css
.preflight-banner { margin: 6px 0; padding: 6px 9px; border-radius: 6px; font-size: 12px; }
.preflight-banner.ok { background: rgba(88, 213, 186, 0.12); color: var(--accent); }
.preflight-banner.warn { background: rgba(231, 182, 90, 0.16); color: var(--accent-2); }
.preflight-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
.pf-badge { display: inline-block; padding: 1px 6px; border-radius: 999px; font-size: 11px; background: var(--panel-2); color: var(--muted); }
.pf-badge.warn { background: rgba(231, 182, 90, 0.16); color: var(--accent-2); }
```
스모크에 마커 추가: `smoke_test_viewer.py` styles 검증(159)에 `"preflight-banner"`, app js 검증(132)에 `"renderPreflightBanner"` 추가.

- [ ] **Step 11: 전체 검증 후 커밋**

Run:
```bash
.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v
.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py
```
Expected: pytest PASS + 스모크 `{"ok": true}`.
```bash
git add tools/sc_spire_agent_sdk_orchestrator/
git commit -m "feat(viewer): surface live preflight state and add runtime toggle (G2)"
```

---

## M2 (G4): 제출 UX — textarea 초기화 + 새 런 자동 선택

**왜:** 실측 시 제출 후 textarea가 안 비워지고, 방금 만든 런이 가운데에 자동으로 안 열려 "내가 보낸 게 어떻게 정제됐나"를 한 번에 못 본다.

**Files:**
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js` (`2685-2723`)

- [ ] **Step 1: 새 런 자동 선택 동작 확인 테스트 (스모크 확장)**

`smoke_test_viewer.py` `main()` 에 추가 (POST 응답이 run_id 또는 메시지 id를 돌려주는지 잠금):
```python
    submit = send_json("POST", "/api/messages", {"target": "prompt-preflight-agent", "message": "테란 카드 자동선택 스모크 점검"})
    sub_msg = submit.get("message") or {}
    if not sub_msg.get("id"):
        raise AssertionError("submit did not return message id for auto-select")
    send_json("DELETE", f"/api/messages?id={quote(str(sub_msg['id']))}")
```
Run: `.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py`
Expected: PASS (이미 id 반환하므로 통과 — 프론트 동작 잠금용 회귀 가드).

- [ ] **Step 2: 프론트 send 핸들러에 초기화 + 자동선택 추가**

`app.js` send 핸들러(2700-2702)에서 `const data = await postJson(...)` 직후를 교체:
```javascript
    const data = await postJson("/api/messages", payload);
    el.messageStatus.textContent = `${t.queued}: ${data.message.id}`;
    el.messageText.value = "";
    await refreshLiveStatus();
    const newRunId = data.message.effective_run_id || data.message.run_id || "";
    if (newRunId) {
      await loadRun(newRunId);
      setActiveTab("status");
    }
```

- [ ] **Step 3: 수동 검증 (브라우저)**

Run: 서버 떠 있는 상태에서 `http://127.0.0.1:8766` 열고 평문 제출.
Expected: 제출 직후 textarea 비워짐 + 가운데가 방금 만든 런의 `상태` 탭으로 전환됨.

- [ ] **Step 4: 커밋**
```bash
git add tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js tools/sc_spire_agent_sdk_orchestrator/smoke_test_viewer.py
git commit -m "feat(viewer): clear input and auto-open new run after submit (G4)"
```

---

## M3 (G1): 로컬 정제에 file/where 후보 자동 제안

**왜:** 로컬 정제가 원문을 템플릿에 복붙만 해 file/where/how(본체 CLAUDE.md §0.7 기준)가 0. repo를 grep해 후보 파일/심볼을 정제 프롬프트에 주입한다.

**Files:**
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_server.py` (`build_rule_based_prompt` 1037)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py`

- [ ] **Step 1: 순수 함수 `suggest_targets(text)` 실패 테스트**

`test_viewer_units.py` 에 추가:
```python
def test_suggest_targets_maps_terran_card_to_records(tmp_path):
    hits = viewer_server.suggest_targets("테란 카드 밸런스가 좀 이상한 거 같으니까 한번 봐줘")
    joined = " ".join(hits)
    assert "cards_terran" in joined or "records" in joined
    assert isinstance(hits, list)


def test_suggest_targets_empty_on_no_signal():
    assert viewer_server.suggest_targets("ㅇㅇ") == []
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py::test_suggest_targets_maps_terran_card_to_records -v`
Expected: FAIL — `has no attribute 'suggest_targets'`.

- [ ] **Step 3: 키워드→경로 매핑 구현**

`build_rule_based_prompt`(1037) 정의 **앞**에 추가:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v`
Expected: PASS.

- [ ] **Step 5: 정제 프롬프트에 후보 주입**

`build_rule_based_prompt`(1037) 의 `normalized = " ".join(text.split())` 다음 줄에 추가:
```python
    suggested = suggest_targets(text)
```
`refined_lines` 의 `"먼저 해야 할 일:"` 블록(1074) 바로 위에 삽입:
```python
        *( ["추정 작업 대상 (확인 후 확정):", *(f"- {path}" for path in suggested), ""] if suggested else [] ),
```
그리고 반환 메타(1113 dict)에 `"suggested_targets": suggested,` 추가.

- [ ] **Step 6: 회귀 — 후보가 메타에 실리는지 단위 테스트**

`test_viewer_units.py` 에 추가:
```python
def test_rule_based_prompt_includes_suggested_targets():
    refined, meta = viewer_server.build_rule_based_prompt(
        "테란 카드 밸런스 봐줘", "main", {"run_id": "x"}
    )
    assert "data/records/cards_terran.json" in refined
    assert meta["suggested_targets"]
```
Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v`
Expected: PASS.

- [ ] **Step 7: 커밋**
```bash
git add tools/sc_spire_agent_sdk_orchestrator/viewer_server.py tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py
git commit -m "feat(viewer): suggest target files/where in local preflight refinement (G1)"
```

---

## M4 (P1): SSE 실시간 + 활성 변경 중 포커스 보존

**왜:** 3초 폴링(`app.js:2919`)은 지연 + 낭비 요청을 만든다. 프론트는 이미 해시로 idle 재렌더는 막지만(562), 변경 시 섹션을 innerHTML로 통째 갈아 입력 포커스를 잃는다. 이벤트 발생 시점에 push하고, 큐/상태 변경 알림만 보내 필요한 섹션만 갱신한다.

**Files:**
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_server.py` (`do_GET`, `invalidate_status_cache` 122)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js` (`2919`, `refreshLiveStatus` 530)

- [ ] **Step 1: 서버에 변경 시퀀스 카운터 추가**

`invalidate_status_cache`(122) 함수 내부 끝에 전역 카운터 증가 로직 추가. 파일 상단 락 근처(54)에 추가:
```python
STATUS_EPOCH = {"seq": 0}
STATUS_EPOCH_LOCK = threading.Lock()
```
`invalidate_status_cache`(122) 본문 끝에:
```python
    with STATUS_EPOCH_LOCK:
        STATUS_EPOCH["seq"] += 1
```

- [ ] **Step 2: `/api/events` SSE 엔드포인트 추가**

`do_GET`(5726) 의 `/api/status` 분기 다음에 추가:
```python
            if parsed.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last = -1
                idle = 0
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
```
참고: `ThreadingHTTPServer`(5893)라 장기 연결이 다른 요청을 막지 않는다. 클라이언트 끊김은 `wfile.write` 예외로 루프 종료된다 (`do_GET` 의 `except Exception` 이 흡수).

- [ ] **Step 3: 수동 검증 — SSE 스트림 수신**

Run:
```bash
curl -N -m 6 http://127.0.0.1:8766/api/events
```
(서버 재시작 후) 다른 창에서 `POST /api/messages` 한 번 → 첫 창에 `event: status` 라인이 즉시 떠야 함.
Expected: `event: status\ndata: <n>` 수신.

- [ ] **Step 4: 프론트 — 폴링을 SSE 트리거로 교체**

`app.js` 끝(2919) 의 `state.statusTimer = window.setInterval(refreshLiveStatus, 3000);` 를 교체:
```javascript
function startLiveStream() {
  try {
    const source = new EventSource("/api/events");
    source.addEventListener("status", () => { refreshLiveStatus(); });
    source.onerror = () => { source.close(); window.setTimeout(startLiveStream, 5000); };
    state.eventSource = source;
  } catch (_) {
    state.statusTimer = window.setInterval(refreshLiveStatus, 3000);
  }
}
refreshLiveStatus();
startLiveStream();
state.statusTimer = window.setInterval(refreshLiveStatus, 15000);
```
(15초 백업 폴링은 SSE 누락 대비 안전망.)

- [ ] **Step 5: 포커스 보존 — 입력 중이면 큐 재렌더 스킵**

`refreshLiveStatus`(566) 의 `renderQueueStatus(queueStatus);` 를 가드:
```javascript
      if (document.activeElement !== el.messageText) {
        renderQueueStatus(queueStatus);
      }
```

- [ ] **Step 6: 수동 검증**

Run: 브라우저에서 textarea에 타이핑 중 다른 창에서 메시지 POST → 타이핑 포커스 유지되는지 확인. 큐는 포커스 벗어나면 갱신.
Expected: 입력 안 끊김, 변경은 1초 내 반영.

- [ ] **Step 7: 커밋**
```bash
git add tools/sc_spire_agent_sdk_orchestrator/viewer_server.py tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js
git commit -m "feat(viewer): push updates via SSE and preserve input focus (P1)"
```

---

## M5 (P2): 커맨드 센터 상시 노출

**왜:** "현재 판단/명령 상태/다음 액션"이 이미 `상태` 탭 안에 있지만(work-board), 탭을 떠나면 안 보인다. validator persona가 요구하는 "화면만 보고 단계·모델·blocked·다음행동 파악"을 충족하려면 탭과 무관하게 상단 고정 띠가 필요하다.

**Files:**
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/index.html` (`22-48`)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js` (`renderWorkBoard` 770, `refreshLiveStatus` 562)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_static/styles.css`

- [ ] **Step 1: index.html — main-tabs(41) 위에 고정 띠 컨테이너 추가**

`index.html` 의 `<nav class="main-tabs" ...>`(41) **바로 위**에 삽입:
```html
        <section id="command-strip" class="command-strip" aria-live="polite"></section>
```

- [ ] **Step 2: app.js — 커맨드 띠 렌더 함수**

`renderWorkBoard`(770) 정의 앞에 추가 (work_items[0] 또는 현재 선택 run의 요약을 사용):
```javascript
function renderCommandStrip(payload) {
  const host = document.getElementById("command-strip");
  if (!host) return;
  const items = payload?.work_items || [];
  const current = items.find((it) => it.status === "running") || items[0];
  if (!current) { host.hidden = true; return; }
  const live = payload?.live_preflight?.effective_mode || "";
  host.hidden = false;
  host.innerHTML = `
    <span class="cs-cell"><b>단계</b> ${escapeHtml(statusLabel(current.status) || current.status || "-")}</span>
    <span class="cs-cell"><b>경로</b> ${escapeHtml(current.route || "-")}</span>
    <span class="cs-cell ${current.blocked_reason ? "warn" : ""}"><b>막힘</b> ${escapeHtml(current.blocked_reason || "없음")}</span>
    <span class="cs-cell"><b>정제</b> ${escapeHtml(live || "-")}</span>
    <span class="cs-cell"><b>다음</b> ${escapeHtml(current.next_action || "-")}</span>`;
}
```
(필드명 `route`/`blocked_reason`/`next_action` 은 work_item 실제 키에 맞춰 조정 — Step 3에서 확인.)

- [ ] **Step 3: work_item 실제 키 확인 후 매핑 확정**

Run:
```bash
curl -s http://127.0.0.1:8766/api/status | python -c "import json,sys; d=json.load(sys.stdin); wi=d.get('work_items') or []; print(json.dumps(wi[0], ensure_ascii=False, indent=2)) if wi else print('no work_items')"
```
Expected: 첫 work_item의 키 목록 출력. Step 2의 `current.route`/`blocked_reason`/`next_action` 을 실제 키(예: `route`, `blocker`, `next`)로 교체.

- [ ] **Step 4: 렌더 훅 연결**

`refreshLiveStatus`(562 블록) 재렌더 구간에 추가:
```javascript
      renderCommandStrip(queueStatus);
```

- [ ] **Step 5: styles.css — 고정 띠 스타일**

`styles.css` 끝에 추가:
```css
.command-strip { display: flex; flex-wrap: wrap; gap: 14px; padding: 8px 12px; margin: 0 0 8px; background: var(--panel-2); border: 1px solid var(--line); border-radius: 8px; font-size: 12px; }
.command-strip .cs-cell b { color: var(--muted); font-weight: 500; margin-right: 5px; }
.command-strip .cs-cell.warn { color: var(--accent-2); }
```

- [ ] **Step 6: 스모크 마커 + 수동 검증**

`smoke_test_viewer.py` app js 검증(132)에 `"renderCommandStrip"`, styles 검증(159)에 `"command-strip"` 추가.
Run: `.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py`
Expected: PASS. 브라우저에서 탭을 `라우팅/규칙` 등으로 옮겨도 상단 띠가 계속 보이는지 확인.

- [ ] **Step 7: 커밋**
```bash
git add tools/sc_spire_agent_sdk_orchestrator/
git commit -m "feat(viewer): always-visible command strip across tabs (P2)"
```

---

## M6 (G3): light run 모드 — vague 요청 ceremony 축소

**왜:** "봐줘" 한 문장이 37파일/90KB plan을 만든다. vague/탐색 요청은 풀 PRD 대신 "의도 확인 먼저" 경량 런으로 처리해 잡음과 디스크를 줄인다. 가장 코어에 가까운 변경이라 마지막.

**Files:**
- Modify: `tools/sc_spire_agent_sdk_orchestrator/viewer_server.py` (`build_rule_based_prompt` 1037, 메시지 처리 경로)
- Modify: `tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py`

- [ ] **Step 1: 순수 함수 `classify_request_weight(text)` 실패 테스트**

`test_viewer_units.py` 에 추가:
```python
def test_classify_request_weight_flags_vague():
    assert viewer_server.classify_request_weight("한번 봐줘") == "light"
    assert viewer_server.classify_request_weight("ㅇㅇ 확인") == "light"


def test_classify_request_weight_keeps_specific_as_full():
    text = "data/records/cards_terran.json 의 supply_surge 카드 damage를 12에서 8로 낮춰줘"
    assert viewer_server.classify_request_weight(text) == "full"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py::test_classify_request_weight_flags_vague -v`
Expected: FAIL — `has no attribute 'classify_request_weight'`.

- [ ] **Step 3: 분류기 구현**

`build_rule_based_prompt`(1037) 앞(`suggest_targets` 근처)에 추가:
```python
VAGUE_TOKENS = ["봐줘", "한번", "좀", "어떤지", "확인해", "체크", "이상한", "대충"]
SPECIFIC_SIGNALS = ["/", ".json", ".py", "->", "→", "라인", "L", "필드", "에서", "로 낮", "로 바�", "추가"]


def classify_request_weight(text: str) -> str:
    lowered = text.lower()
    has_path = any(sig in text for sig in [".json", ".py", "/"])
    specific = has_path or sum(1 for s in SPECIFIC_SIGNALS if s in text) >= 2
    if specific and len(text.split()) >= 4:
        return "full"
    if any(tok in text for tok in VAGUE_TOKENS) or len(text.split()) < 4:
        return "light"
    return "full"
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v`
Expected: PASS.

- [ ] **Step 5: light 모드일 때 정제 프롬프트를 "의도 확인 먼저"로 전환**

`build_rule_based_prompt`(1037) 의 `normalized = ...` / `suggested = ...` 다음에:
```python
    weight = classify_request_weight(text)
```
`refined_lines` 조립 직후, `refined_prompt = "\n".join(refined_lines)`(1112) **앞**에 분기 추가:
```python
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
            *( ["3. 추정 작업 대상 (확인용):", *(f"   - {p}" for p in suggested)] if suggested else ["3. 관련 파일 후보를 grep로 제시하라."] ),
            "4. 사용자가 확정하면 그때 full 오케스트레이션으로 승격하라.",
        ]
```
반환 메타(1113 dict)에 `"request_weight": weight,` 추가.

- [ ] **Step 6: 회귀 — light 런 프롬프트 검증**

`test_viewer_units.py` 에 추가:
```python
def test_light_request_skips_full_prd():
    refined, meta = viewer_server.build_rule_based_prompt("한번 봐줘", "main", {})
    assert meta["request_weight"] == "light"
    assert "clarifying" in refined.lower()
    assert "worker-dispatch" not in refined
```
Run: `.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v`
Expected: PASS.

- [ ] **Step 7: 스모크 회귀 + 커밋**

Run: `.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py`
Expected: `{"ok": true}` (light 분기가 기존 통합 흐름을 깨지 않음).
```bash
git add tools/sc_spire_agent_sdk_orchestrator/viewer_server.py tools/sc_spire_agent_sdk_orchestrator/test_viewer_units.py
git commit -m "feat(viewer): light-run mode for vague requests to cut ceremony (G3)"
```

---

## 최종 통합 검증

- [ ] **Step F1: 전체 단위 + 스모크 재실행**

Run:
```bash
.venv\Scripts\python.exe -m pytest tools\sc_spire_agent_sdk_orchestrator\test_viewer_units.py -v
powershell -File tools\sc_spire_agent_sdk_orchestrator\start_agent_viewer.ps1
.venv\Scripts\python.exe tools\sc_spire_agent_sdk_orchestrator\smoke_test_viewer.py
```
Expected: pytest 전부 PASS + 스모크 `{"ok": true}`.

- [ ] **Step F2: 브라우저 수동 E2E**

평문 "한번 봐줘" 제출 → ① textarea 비워짐 ② 새 런 자동선택(M2) ③ 정제 배너가 `template_degraded` 표시(M1) ④ 토글 켜면 라이브로 전환 ⑤ light 런이라 clarifying 질문 위주(M6) ⑥ 상단 커맨드 띠가 탭 이동에도 유지(M5) ⑦ 변경이 1초 내 반영(M4).

---

## Self-Review 메모

- **Spec 커버리지:** G2→M1, G4→M2, G1→M3, P1→M4, P2→M5, G3→M6 전부 매핑됨.
- **타입 일관성:** `live_preflight_state()` 반환 키(`effective_mode`)가 M1·M5에서 동일하게 사용됨. `suggest_targets`/`classify_request_weight`/`build_rule_based_prompt` 시그니처가 M3·M6에서 일치.
- **주의(실측 기반 조정 필요):** M5 Step 3에서 work_item 실제 키 확인 후 매핑 확정 — 추정 키(`route`/`blocked_reason`/`next_action`)는 실제 응답으로 교체할 것. M1 Step 3의 `read_openai_api_key` 가 키 부재 시 빈 문자열 반환을 보장하는지 확인 후 진행.
