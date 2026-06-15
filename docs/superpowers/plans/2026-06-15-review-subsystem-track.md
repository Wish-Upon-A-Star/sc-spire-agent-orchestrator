# SC Spire Orchestrator — Review Subsystem Track (Trust + Efficiency + Strategist Lanes)

> **상태:** 설계(design/RFC) 문서. M1~M6는 이미 구현·검증·push 완료([2026-06-15-agent-sdk-viewer-improvements.md](2026-06-15-agent-sdk-viewer-improvements.md), [verification-log.md](verification-log.md)). 이 문서는 그 위에 올릴 **다음 트랙**을 통합 정리한 것 — 외부 AI 교차검증용이기도 함.
>
> **출처:** (1) Claude M1~M6 실측 + Codex 리뷰, (2) 외부평가 GPT-5.4 #1 "신뢰축 A1~A12", (3) 외부평가 #2 "효율축(persona/capsule/matrix/budget)", (4) 외부평가 #3 "ChatGPT Pro 전략 레인".

---

## 0. North-star (왜 이 트랙인가)

오너는 빠른 실행자가 아니라 **느린 reviewer/architect**다. 그래서 원하는 건 단순 기능추가가 아니라 —
**오케스트레이터가 *스스로* 다축(多軸) 검증 루프를 조립해서, 여러 AI에게 토큰을 적게 쓰며 검증을 받아내는 시스템.**

M1~M6는 "사람이 쓰기 편하게"(UX/실시간/정제품질). 이 트랙은 "**시스템이 스스로 믿을 수 있게**"다. 후자가 오케스트레이터의 존재 이유(*완료를 거짓보고하지 않는다*)에 더 본질적.

---

## 1. 핵심 합성 — 세 평가는 한 서브시스템의 3층이다

```
Layer 2  LANES        누가 검토하나   codex / claude / openai-api / gpt-pro / (claude-architect)
                              ▲  동일 lane 규격으로 꽂힘
Layer 1  EFFICIENCY   어떻게 싸게     context-capsule · review-matrix · output-schema · mode-budget
                              ▲  모든 lane이 같은 입력(capsule)·같은 출력(schema)
Layer 0  SUBSTRATE    무엇을 믿나     GET read-only · provenance · callable-split · state-machine
```

**수렴(중요):** 평가 3의 Pro 레인이 요구하는 것은 전부 평가 1·2에 이미 있다 → Pro는 독립 기능이 아니라 substrate 위에 꽂히는 **또 하나의 lane**이다.

| 평가 3(Pro)이 요구 | = 사실 이것 |
|---|---|
| `auto_spawn:false, manual_surface_available:true` | **A3** callable 분리 |
| `source: manual_chatgpt_pro`, `model_claimed_by_operator` | **A2** provenance |
| persona `must_read: context-capsule.json` | **E2** context capsule |
| 결과 JSON `verdict/top_objections` | **E4** output schema + **E3** review-matrix |

→ substrate 한 번 깔면 Claude·Codex·API·Pro·심지어 메인 Claude(나)까지 전부 "lane"으로 통일된다. 최종 소유자는 끝까지 **main-orchestrator 하나**.

---

## 2. Layer 0 — Substrate (Trust)

### A1. GET read-only 원칙 (검증된 실제 버그 · 최우선)
- **증거:** [viewer_server.py:231](../../tools/sc_spire_agent_sdk_orchestrator/viewer_server.py) `run_payload()` → L239-241 `ensure_report_pack_judgment / ensure_report_evidence_audit / ensure_goal_completion_audit` → 내부 `(run_dir/artifact).write_text(...)`. 즉 **GET `/api/run`으로 "보기만 해도" 디스크에 artifact가 써짐.**
- **문제:** "내가 클릭해서 생긴 건지, worker가 만든 건지, closure 루프가 만든 건지"가 흐려짐. 캐시 무효화 + 동시성 위험도 동반.
- **수정:** GET은 순수 조회만. 자동 보정/재계산은 명시적 POST `/api/run/reconcile`(또는 `/migrate`, `/audit`)로 분리. UI엔 "derived artifact outdated"만 표시.
- **회귀 테스트:** `test_get_run_is_read_only` (A7).

### A2. Artifact provenance / trust-level 스키마
- **문제:** artifact가 많아졌지만 "누가/어떤 경로로/실제 실행인지/수동입력인지/self-check인지/live인지/template인지"가 일관되게 안 박힘. `record_run_result()`만 `operator_recorded_from_viewer` 남김.
- **수정:** 모든 artifact write에 provenance 강제.
```json
{ "provenance": {
  "source_type": "contract_generated | local_self_check | external_codex_cli | live_claude_cli | live_openai_api | external_chatgpt_pro_manual | operator_manual",
  "created_by": "viewer-server | codex-worker | claude-reviewer | gpt-pro-advisor | operator",
  "command": "...", "exit_code": 0,
  "input_artifacts": ["..."], "stdout_artifact": "...", "stderr_artifact": "...",
  "verified_by": ["validator-code-level"],
  "is_claim_evidence": true } }
```
- 이게 신뢰축의 뼈대. Pro 레인의 `source: manual_chatgpt_pro`도 이 스키마의 한 값.

### A3. callable → manual/auto/live/API 분리
- **문제:** `codex_subscription_worker`가 CLI 없어도 `callable:true`. UI/라우팅이 "자동 실행 가능"으로 오인.
- **수정:** adapter_health를 쪼갠다.
```json
{ "manual_surface_available": true, "auto_spawn_available": false,
  "cli_path": "", "requires_operator_copy_paste": true, "can_write_artifact_directly": false }
```
- Claude도 동일(CLI 있으면 auto, 없으면 manual). **Pro 레인의 전제.**

### A4. workflow state machine 단일 스키마
- **문제:** backend `ACTIVE/PREPARED/BLOCKED/TERMINAL_STATUSES` ↔ frontend `statusLabel()` 이중 관리 → 상태 추가 시 어긋남.
- **수정:** `workflow_states.py`(또는 `workflow_state_schema.json`) 하나로 backend/frontend/smoke가 같은 정의 사용.
```json
{ "waiting_for_worker_result": { "bucket":"active","label_ko":"작업자 결과 대기",
  "allowed_next":["worker_result_recorded","blocked_or_needs_retry"],
  "is_terminal":false,"requires_artifacts":["worker-dispatch.json"] } }
```
- **추가 상태 `waiting_for_operator`** 필수 (Pro 수동 레인이 멈추는 곳, §4 캐비엇).

### A5. POST `/api/messages` 응답에 created_run_id (M2의 정식 대체)
- **문제:** 현재 응답 `{message}`만 → 프론트가 run을 폴링으로 추측(M2 `selectRunForMessage`는 그 미봉책).
- **수정:** API 계약 변경.
```json
{ "message": {...}, "created_run_id": "20260615T...", "effective_status": "dispatch_ready",
  "created_artifacts": ["orchestration-plan.json","worker-dispatch.json"],
  "queue_routing_decision": {...} }
```
- 그러면 프론트는 즉시 `loadRun(created_run_id)`. M2 폴링 제거.

### A6. atomic write + run-level lock
- **문제:** transcript append가 lock 없이 직접 append. `EVENT_LOCK`은 operator event에만. 자동진행+UI버튼+polling+수동기록 겹치면 partial write/gate overwrite.
- **수정:** `write_json_atomic(temp→fsync→os.replace)`, `append_jsonl_locked(per-file lock)`, `run_dir/.lock`.

### A7. 핵심 regression pytest
`test_get_run_is_read_only`, `test_post_message_returns_created_run_id`, `test_artifact_provenance_required`, `test_state_transition_schema_has_all_frontend_labels`, `test_worker_result_without_validator_cannot_close`, `test_closure_packet_not_created_by_reading_run`, `test_adapter_health_splits_manual_vs_auto`, `test_light_mode_does_not_auto_generate_heavy_artifacts`.

### A8. localhost 안전장치 (사고방지 수준)
127.0.0.1 외 bind 경고/차단, Origin/Host 검사, mutating endpoint에 local token(옵션 `--allow-remote --token-file`). *단일사용자 localhost라 token까지는 과함 — host-bind 가드만 우선.*

### A9. Unity target-repo adapter + project inventory *(조건부: Unity 작업이 실제로 이 도구를 통할 때만)*
하드코딩된 Unity 힌트 → 구조화 adapter(`target_repo, project_type, root_path, unity_version, entry_scenes, build_targets, verification_commands, rendered_evidence_required, parity_sources`) + scene/prefab/UI inventory(=A3 file/where 제안의 Unity판).

### A10. budget-ledger.jsonl
run별 API 사용 기록(`provider, model, purpose, budget_gate, est_tokens, reason`). 구독 레인도 `manual subscription route used` 정도는 남김.

### A11. trace_event_v2 스키마 정리
manifest required(`actor/type/status/target`) ↔ 실제 transcript(`speaker/recipient/event_type/message`) 불일치 → `trace_event_v2`로 점진 이관(전면 migration은 무거우니 호환 shim부터).

### A12. issue-memory → eval seed → pytest 연결
`memory/issues_log/*.md` → `generated/evals/issue_regressions/*.json` → pytest parametrized → `validator-issue-gate-result.json`에 결과 연결. "이전 실패를 읽었다"가 아니라 "이전 실패가 재발 안 한다는 binary check를 실행했다"까지.

### B (Claude 실측 추가)
- **B1. 동적 캐시버전:** `index.html`의 `?v=` 정적 고정 → 프론트 변경이 브라우저에 안 닿음(M1~M5 내내 수동 bump v1→v4). 서버가 mtime/해시 기반 버전 주입하게.
- **B2. SSE 스레드 상한:** `/api/events`가 탭당 ThreadingHTTPServer 스레드 영구 점유(Codex 지적, 로컬 단일사용자라 보류했던 항목). 다중탭/원격 전환 시 연결 상한 필요.
- **B3. POST 동기·무거움:** target=main이 응답까지 풀 오케스트레이션(수~수십초). A5(created_run_id) + 비동기 처리/진행 스트림으로 완화.

---

## 3. Layer 1 — Efficiency (페르소나는 많이가 아니라 짧고 선별)

> 한 줄: **페르소나는 짧게 고정, 컨텍스트는 선별, 검증은 질문 단위로 쪼개고, 장문 판단은 closure 근처에서만.**

### E1. persona card (300~600토큰 고정)
긴 identity를 매번 태우지 말고 짧은 role card + `persona_id`/`persona_version`. 원본은 `agent-personas.json` artifact로 두고 참조만.

### E2. context capsule (run마다 1개)
각 lane이 AGENTS/provider_routing/issue_memory/transcript를 각자 읽지 말고, main 앞에서 capsule 하나 생성 → 모든 lane은 이것부터 읽고 필요시 `source_refs`만 따라감.
```json
{ "context_capsule_version":1,
  "task":{"raw":"...","refined":"...","mode":"light"},
  "relevant_policy":["player-facing closure requires rendered evidence","worker result alone cannot close"],
  "relevant_issues":[{"id":"issue-123","summary":"...","countermeasure":"..."}],
  "current_artifacts":[{"name":"worker-dispatch.json","status":"exists","trust":"contract_only"}],
  "missing_evidence":["worker-result.json","validator-result.json"] }
```
`must_read`도 "전체 읽기"가 아니라 **context-query 계약**으로: `{source, mode:"top_k_relevant|section_query|latest_and_artifact_referenced", max_items/max_chars/query}`.

### E3. review-matrix / 렌즈 (검증=다중모델 아니라 다중렌즈 먼저)
검토자마다 같은 거대한 context 주지 말고 **렌즈당 질문 1개 + max findings**.
```json
{ "review_matrix":[
  {"lane":"intent","question":"원문에서 누락/왜곡된 요구가 있나?","reviewer":"prompt-validator","max_findings":3},
  {"lane":"contract","question":"plan→dispatch→evidence→review-gate→closure가 연결됐나?","reviewer":"validator-contract","max_findings":5},
  {"lane":"evidence","question":"완료 주장에 실제 증거가 있나?","reviewer":"claude-reviewer","max_findings":5},
  {"lane":"regression","question":"이전 실패가 gate로 승격됐고 재발 안 했나?","reviewer":"issue-memory-agent","max_findings":4},
  {"lane":"product","question":"플레이어 관점 과장된 주장이 있나?","reviewer":"product-reviewer","max_findings":4} ]}
```
기본 5렌즈: **intent / contract / evidence / regression / product.** light에선 한 validator가 5렌즈 짧게, closure에서만 Claude/product 붙임.

### E4. 출력 구조 강제 (길이제한보다 구조제한)
모든 검토자 공통 JSON:
```json
{ "verdict":"pass|needs_retry|blocked",
  "top_findings":[{"severity":"high","claim":"closure not allowed","because":"worker-result.json missing","required_evidence":"worker-result.json"}],
  "missing_evidence":[], "do_not_repeat":[], "next_action":"..." }
```
규칙: max 5 findings · 전체 task 재진술 금지 · generic advice 금지 · 모든 finding은 artifact/file/command/screenshot/missing-evidence를 지명 · 증거 없으면 "insufficient evidence".

### E5. mode별 prompt budget (light/normal/closure)
모든 요청이 full council 타지 않게.
```json
{ "run_mode":"light",   "token_budget":{"context_capsule_chars":4000,"issue_memory_items":3,"review_lanes":["contract-lite"],"claude":"skip_until_closure","openai_api":"off_by_default"} }
{ "run_mode":"closure", "token_budget":{"context_capsule_chars":12000,"issue_memory_items":8,"review_lanes":["code","contract","ui","issue","product"],"claude":"required","openai_api":"structured_guardrail_allowed"} }
```
(M6 light-run이 이 mode 개념의 첫 구현 — 여기로 일반화.)

### E6. retry는 delta만
retry마다 같은 원문/정책/artifact 재전송 금지.
```json
{ "retry_of":"run_id","unchanged_context_ref":"context-capsule.json",
  "changed_since_last_attempt":["worker-result.json added","validator-code blocked"],
  "last_blockers":[{"id":"missing_e2e","required_fix":"record browser E2E evidence"}],
  "task":"Only address changed blockers. Do not re-plan from scratch." }
```

### E7. hard-rules-first (긴 역할극보다 실패방지 문장)
모든 prompt 앞에 공통 hard rule:
```
1. Do not claim completion from planning artifacts.
2. Do not treat sent_to_main/prepared/dispatch_ready as done.
3. Do not approve player-facing Unity work without rendered evidence.
4. Every PASS must name the artifact that proves it.
5. If evidence is missing, verdict must be NEEDS_RETRY or BLOCKED.
```
(main persona의 `sent_to_main 오인 금지` 초점을 전 lane 공통으로 승격.)

---

## 4. Layer 2 — Lanes (오너/AI를 "전략 레인"으로 박기)

### L1. 통합 lane 규격
모든 검토자(codex/claude/openai-api/gpt-pro/메인Claude)는 동일 계약: **입력=context-capsule + 배정된 lens, 출력=E4 스키마, 메타=A2 provenance + A3 callable.** 새 캐릭터 추가가 아니라 같은 소켓에 꽂기.

### L2. gpt-pro-strategy-advisor (수동 copy-paste)
- **왜 수동:** ChatGPT Pro 자동 스크래핑은 ToS 위반 + 우리가 이미 겪은 UIPI/Electron 주입 차단 함정. **브라우저 자동화 금지, 사람이 중간에 붙여넣음.**
- **흐름:** 오케스트레이터 `gpt-pro-review-request.md` 생성 → 오너가 Pro에 붙여넣음 → Pro 답변 → 오너가 붙여넣음 → `gpt-pro-review-result.json` 저장 → main이 accepted/rejected objection으로 반영.
- **persona:** `route: chatgpt_pro_manual_strategist`, `review_only:true`, forbidden=[최종완료승인, 파일직접수정, Pro응답만으로 closure, 자동브라우저세션].
- **route(provider_routing.json):**
```json
"chatgpt_pro_manual_strategist": { "enabled":true,"priority":2,"provider":"openai",
  "billing":"chatgpt_pro_subscription_manual","surface":"manual_copy_paste_chatgpt_pro",
  "default_model":"gpt-5.5-pro","auto_spawn":false,"manual_surface_available":true,
  "best_for":["slow strategic review","orchestrator architecture critique","prompt/persona compression","failure pattern analysis","Unity recovery plan review","closure challenge for high-risk work"],
  "avoid_for":["automatic background execution","local file edits","high-frequency preflight","programmatic account automation"] }
```
- **결과 JSON:** `kind:"gpt_pro_strategy_review", source:"manual_chatgpt_pro", model_claimed_by_operator:"gpt-5.5-pro", verdict:"pass|needs_retry|blocked|replan", top_objections[], closure_allowed:false`. ← `source`/`model_claimed_by_operator`가 A2 provenance의 정직성(수동이라 시스템이 모델 검증 불가, operator claim, `is_claim_evidence:true`).
- **언제 호출(상시 아님, 전략 회의실):** ①Codex/Claude가 2회+ 헛돌 때 ②Unity 복구 방향 대전환 전 ③오케스트레이터 구조 변경 전 ④prompt/persona/budget 재설계 ⑤closure 직전 증거/제품성 애매 ⑥"게임을 살리나, 오케스트레이터만 예뻐지나" 판단.
- **UI:** 우측 패널 버튼 2개 — `[GPT Pro 검토 패킷 만들기]` / `[GPT Pro 답변 붙여넣기]`.

### L3. openai-strategy-advisor-api (자동 소형)
완전 자동이 필요한 짧은 구조화 판단은 Pro가 아니라 Responses API로. 기존 `call_prompt_preflight_model()` 패턴으로 `call_openai_strategy_review()`. 용도: light/normal/closure 분류 · Pro 수동리뷰 필요여부 · Claude 필요여부 · 어떤 lens만 돌릴지 · closure claim 금지여부. (길게 다각도 ✗, 짧은 JSON ✓.)

### L4. claude / codex를 동일 lane 규격으로
Claude: 평소엔 **quick objection**(max 5, 계획 재작성 금지), closure 직전에만 **closure review**(PASS/NEEDS_RETRY/BLOCKED, max 8). Codex: 실제 파일/명령/증거(auto if CLI). 둘 다 L1 규격.

### L5. waiting_for_operator 상태 (수동 레인의 구조적 귀결)
**캐비엇:** 수동 lane은 연속 루프를 깬다. 오케스트레이터는 Pro를 자동 실행 못 함 → packet 만들고 **멈춤**. 이건 버그가 아니라 비용통제 feature. A4 state machine에 `waiting_for_operator` 명시. (= "오케스트레이터 자가실행"의 정직한 한계: auto 레인은 self-run, Pro는 의도적 human-gated escalation.)

---

## 5. 신규 파일 (구현 시)

```
tools/sc_spire_agent_sdk_orchestrator/prompt_contracts/
  persona_cards.json            (E1)
  review_lenses.json            (E3)
  context_capsule_schema.json   (E2)
  output_schemas.json           (E4)
  token_budget_profiles.json    (E5)
  workflow_states.json          (A4)
output/agent_orchestrator_runs/<run_id>/
  context-capsule.json          (E2)
  prompt-budget.json            (E5)
  selected-review-lenses.json   (E3)
  gpt-pro-review-request.md      / gpt-pro-review-result.json   (L2)
  compact-*-prompt.md           (E1/E6)
output/agent_orchestrator_runs/budget-ledger.jsonl   (A10)
```

---

## 6. 빌드 순서 (의존성 기반) + 기존 코드 매핑

| 단계 | 항목 | 이유/의존 | 닿는 곳 |
|---|---|---|---|
| 1 | **A1 + A5** | 싸고 본질, 무의존 | `run_payload`/`ensure_*`, `do_POST /api/messages` |
| 2 | **A2 + A3** | Pro 레인·신뢰 뼈대 | `record_run_result`/모든 write, `build_adapter_health` |
| 3 | **E2 + E4** | 효율 핵심, lane 입출력 통일 | `build_main_orchestrator_context` 자리, 신규 schema |
| 4 | **L2 Pro 레인 MVP** | **여기서 north-star 첫 동작** — 기존 `submit_result`(`/api/run/result`) 위에 버튼2+artifact | `index.html`, `submit_result`, viewer_server |
| 5 | **E3 + E5 + L5(waiting_for_operator)** | review-matrix + mode budget + 수동멈춤 | A4 state, 신규 schema |
| 6 | A6/A7/B1/B2 → A9~A12/L3 | 위생·확장 | 광범위 |

> **MVP 지름길:** 4번 Pro 레인은 "제대로"는 capsule+provenance 전제지만, 기존 운영자 결과기록 plumbing(`source=operator_recorded_from_viewer`) 위에 `gpt_pro_strategy_review` 타입만 얹으면 **한 사이클로 동작**. 1~3을 다 끝내기 전에 4의 MVP를 먼저 손에 쥐고, 그 위에 substrate를 채우는 것도 가능(권장: 동작하는 걸 먼저).

---

## 7. 상태 보드

| 트랙 | 항목 | 상태 |
|---|---|---|
| (완료) | M1 라이브정제 노출+토글 / M2 제출UX / M3 file제안 / M4 SSE / M5 커맨드띠 / M6 light-run | ✅ 구현·3중검증·push |
| (완료) | Codex 리뷰 수정: SSE disconnect, None 가드, reconnect 타이머 | ✅ |
| Substrate | A1·A5 | ☐ 다음 1순위 |
| Substrate | A2·A3·A4·A6·A7·A8·A9·A10·A11·A12·B1·B2·B3 | ☐ backlog |
| Efficiency | E1~E7 | ☐ backlog (E2·E4 우선) |
| Lanes | L1·L2(Pro MVP)·L3·L4·L5 | ☐ backlog (L2 MVP 빠름) |

---

## 8. 판단·캐비엇 (Claude)

1. **Pro=수동 정답.** 자동화는 ToS+UIPI 함정. manual copy-paste + provenance 정직성(`model_claimed_by_operator`)이 안전+효율.
2. **수동 레인 = 연속루프 단절** → `waiting_for_operator`(L5) 없으면 루프가 어색하게 멈춤. 이걸 feature로 명시.
3. **MVP 먼저:** 동작하는 Pro 레인을 기존 plumbing 위에 빠르게 → 검증 루프를 실제로 돌려보며 substrate 채우기.
4. **메인 Claude(나)도 lane:** 전략 입력은 review-only, 실행 아님. 오너의 self-description("느린 reviewer/architect")과 같은 자리. 최종 소유자는 main 하나.
5. **B1(동적 캐시버전)은 사실상 즉시 해야** — 안 하면 모든 프론트 작업이 "안 닿는" 디버깅 지옥(이미 4번 수동 bump).

## 9. 외부 AI 검증용 열린 질문

- A1을 GET→POST로 분리할 때, 기존에 GET 부작용에 **암묵적으로 의존하던 호출자**가 있나? (reconcile을 누가/언제 트리거?)
- E2 capsule의 "relevance" 선별을 무엇이 결정하나? (rule? L3 API? 둘 다?)
- L5 `waiting_for_operator`에서 타임아웃/리마인더 정책은?
- A2 provenance를 **소급 적용**(기존 artifact)할 것인가, 신규부터인가?
- 5렌즈(E3)가 light에서 1 validator로 합쳐질 때 품질 저하 임계는?
