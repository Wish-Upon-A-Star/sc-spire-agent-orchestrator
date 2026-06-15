# Viewer Improvements — 검증 로그

플랜: `2026-06-15-agent-sdk-viewer-improvements.md` · 실행: subagent-driven + 3중 검증(나 직접 / 라이브 API키 / Codex)
참고: git 커밋은 보류(working tree에 무관한 게임 WIP 995개 + pre-commit hook). 변경은 in-place.

---

## M1 (G2) — Live preflight 상태 노출 + UI 토글 · ✅ 완료·검증

**검증 결과 (3중):**
- ✅ 나 직접: `pytest test_viewer_units.py` 1 passed · `smoke_test_viewer.py` `{"ok": true}` · `/api/status`에 `live_preflight` 노출
- ✅ 라이브 API키: 토글 ON → `effective_mode: live` → `target=main` 제출 → **실제 호출 `mode: openai_responses_api`, `model: gpt-5.5`** (경고 `missing_target_cards` 등 생성) → 토글 OFF → `template_degraded`. silent-degradation을 실제로 노출/제어함을 증명.
- ✅ spec 리뷰(서브): SPEC_COMPLIANT (10단계 전부)
- ✅ Codex 리뷰: sound. 배너 색상 버그 1건 지적(아래 반영)

**리뷰 지적 → 반영:**
1. `read_openai_api_key`가 `/api/status` 핫패스에서 raise 가능(TOCTOU) → `read_text`를 `try/except OSError`로 가드. (viewer_server.py:385)
2. 토글 change 핸들러 에러처리 부재 → `try/catch` + 실패 시 체크박스 revert + 메시지 표시. (app.js:2740)
3. `renderPreflightBanner`가 `live_requested_no_key`(키 없이 라이브 켬)를 초록 ok로 표시 → warn 분기 추가 + 전용 문구. (app.js:587)
4. Codex 시작 불가(`~/.codex/config.toml` line6 `service_tier="default"`) → `"flex"`로 수정 → 이후 Codex 검증축 정상화.

**남은 관측(미차단):** 토글 POST의 malformed body는 조용히 OFF 처리(허용 가능). 단위테스트는 4-way mode matrix 중 1개만 핀(향후 monkeypatch로 보강 가능).

### 🔑 검증 중 발견한 인프라 이슈 (모든 프론트 변경에 영향)
- **정적 캐시버전**: `index.html`이 `app.js?v=...`/`styles.css?v=...`로 고정 버전 쿼리를 박아둠. 안 바꾸면 브라우저가 옛 JS/CSS를 계속 씀 → M1/M2 UI가 안 닿았었음. `20260613-visual-ops-v1` → `20260615-viewer-improv-v1`로 bump. **향후 프론트 변경 시마다 bump 필수** (또는 서버가 mtime 기반 동적 버전 주입하도록 개선 권장 — 별도 항목).
- **POST /api/messages는 동기 + 무거움**: target=main이면 응답까지 풀 오케스트레이션(수~수십초). UI auto-select/clear가 그 후에 동작 → 검증 시 충분히 대기 필요.

---

## M2 (G4) — 제출 UX (입력 비우기 + 새 런 auto-select) · ✅ 완료·검증

구현: send 핸들러에 `el.messageText.value=""` + `selectRunForMessage(id)` 추가. POST 응답엔 run_id가 없어(비동기 생성) plan의 naive `data.message.run_id` 대신 **메시지 id로 /api/messages 폴링**(최대 6회×500ms)해서 effective_run_id 확보 후 loadRun+상태탭 전환.

**검증 (브라우저 실제 조작, Chrome MCP):**
- ✅ 나 직접: 평문 제출 → `textareaVal: ""` (비워짐) + `status: "검증 후 큐에 저장됨: operator-..."` + `runHeader: 20260615T060949Z-...b83cb783` (새 런 auto-select)
- ✅ 부수효과: M1 배너도 동시 확인 — `banner: "정제: 템플릿 강등..."`(degraded warn) / 토글 ON → `banner: "정제: live"`(ok green). M1 UI 3중축 브라우저 검증 완료.
- 주의: 첫 시도에서 안 비워진 듯 보였으나 = 동기 POST 지연 + 캐시버전 미bump 복합. 둘 다 해결 후 정상.

## M3 (G1) — 로컬 정제 file/where 자동 제안 · ✅ 완료·검증
## M6 (G3) — light run 모드 (vague 요청 ceremony 축소) · ✅ 완료·검증

M3·M6 둘 다 `build_rule_based_prompt` 수정이라 함께 처리(효율). `SUGGEST_KEYWORD_MAP`+`suggest_targets()`로 키워드→경로 제안, `classify_request_weight()`로 vague/specific 분류 → light면 PRD ceremony 생략하고 clarifying-first 프롬프트.

**검증:**
- ✅ 나 직접: `pytest test_viewer_units.py` **7 passed** (suggest_targets 2 + classify 2 + rule_based 1 + light 1 + M1 1)
- ✅ 스모크: `{"ok": true}`
- ✅ 라이브(Bash UTF-8): `테란 카드 한번 봐줘` → **weight: light + suggested: [cards_terran.json]** / `data/records/cards_terran.json ... 낮춰` → **weight: full**. 분기 정상.
- 노트1: light 테스트는 처음 `"worker-dispatch" not in refined`로 과엄격(텍스트가 단어 언급) → full 전용 섹션 `"완료 차단 조건:"` 부재로 판별 변경.
- 노트2: PowerShell heredoc로 한글 POST 시 인코딩 깨져 분기 오판정됨 → **라이브 한글 검증은 Bash+python(UTF-8) 또는 브라우저로** 할 것.

검증 메모: Codex 리뷰는 토큰 효율 위해 M3~M6 + SSE/커맨드띠를 묶어 **최종 1회 consolidated 리뷰**로 처리 예정.

---

## M4 (P1) — SSE 실시간 + 포커스 보존 · ✅ 완료·검증

구현: `STATUS_EPOCH` 카운터 + `invalidate_status_cache`에서 bump → `/api/events`(text/event-stream)가 변경 시 `event: status` push. 프론트는 EventSource 구독(+15초 백업 폴링, 에러 시 5초 재연결), 입력 포커스 중엔 큐 재렌더 스킵.

**검증:**
- ✅ 나 직접(implementer): `curl -N /api/events` 연결 시 `data:0`, POST 후 ~1-2초 내 `data:1` push 확인 / 클라 끊김 시 루프 정상 종료(서버 유지)
- ✅ smoke `{"ok": true}` / pytest 7 passed
- 캐시버전 `v2`로 bump (프론트 변경 반영). 브라우저 시각 포커스 테스트는 최종 E2E에서.

## M5 (P2) — 커맨드 센터 상시 노출 · ✅ 완료·검증

구현: 탭 nav 위에 `#command-strip` 추가, `renderCommandStrip()`이 work_items 현재 항목으로 5칸(단계/경로/막힘/정제/다음) 렌더. **plan의 추측 키가 실제와 달라 교정**: `blocked_reason`→`gate_status`, `next_action`→`detail` (실제 work_item 키: id/kind/title/status/bucket/target/run_id/updated_at/detail/route/gate_status/events). escapeHtml로 XSS 안전, work_items 비면 hide.

**검증:** ✅ smoke `{"ok":true}` / pytest 7 passed / 캐시 `v3` bump.

---

## 🧪 최종 브라우저 E2E (Chrome MCP, v3) · ✅ 전부 통과

평문 `최종 E2E: 저그 카드 밸런스 한번 봐줘` 제출 결과:
- ✅ M2: `textareaCleared: true` + `status: 검증 후 큐에 저장됨` + `runHeader: 20260615T063057Z-...581e436a` (새 런 auto-select)
- ✅ M1: 배너 `정제: 템플릿 강등 (키 있음·라이브 꺼짐)` 표시
- ✅ M5: 커맨드 띠 `단계 대기 | 경로 html | 막힘 없음 | 정제 template_degraded | 다음 메시지가 저장됐고...` (실데이터 5칸) + **탭 "라우팅/규칙"으로 이동해도 계속 보임**
- ✅ M4: liveStatus 타임스탬프 갱신 + SSE `/api/events` push(implementer curl로 `data:1` 확인)

## 검증 요약 (3중축)
| 마일스톤 | 나 직접 | 라이브 API/E2E | Codex |
|---|---|---|---|
| M1 G2 | ✅ pytest+smoke | ✅ 실 OpenAI 호출(gpt-5.5) + 브라우저 토글/배너 | ✅ (배너 버그 1건 잡아 수정) |
| M2 G4 | ✅ | ✅ 브라우저 E2E | (UI, 최종리뷰 포함) |
| M3 G1 | ✅ pytest 7 | ✅ Bash UTF-8 라이브 | ⏳ consolidated |
| M6 G3 | ✅ pytest 7 | ✅ Bash UTF-8 라이브 | ⏳ consolidated |
| M4 P1 | ✅ pytest+smoke | ✅ SSE curl push + E2E | ⏳ consolidated |
| M5 P2 | ✅ smoke | ✅ E2E 탭이동 유지 | ⏳ consolidated |

~~⏳ = 백그라운드 최종 Codex consolidated 리뷰 진행 중~~ → ✅ 완료, 아래 반영.

## 🔍 최종 Codex consolidated 리뷰 (M3~M6+SSE) → 수정 완료

Codex가 진짜 버그 4건 지적:
1. **SSE disconnect (viewer_server.py)**: write/flush 예외가 do_GET 바깥 except로 빠져 헤더 이중전송 위험 → **루프를 try/except (BrokenPipe/ConnectionReset/Aborted/OSError)로 감싸고 return** 추가. ✅ 수정
3. **classify/build_rule_based_prompt None 입력 → TypeError** → `build_rule_based_prompt` 진입부 `text = text if isinstance(text, str) else ""` 가드 + 단위테스트 추가. ✅ 수정
4. **app.js reconnect 타이머 누적**: onerror마다 setTimeout/EventSource 누적 가능 → reconnect 타이머 single-flight 가드 + 기존 source close + backup poll 단일화. ✅ 수정 (참고: Codex가 "3초+15초 동시"라 한 건 부분오해 — 3초는 EventSource 미지원 폴백)
2. **SSE 스레드 탭당 점유(무제한)**: 구조적이나 **로컬 단일사용자 도구라 저위험 → 기록만, 미수정**. 다중사용자/원격 전환 시 연결 상한 필요.

**수정 후 재검증:** pytest **8 passed**(None가드 포함) / smoke `{"ok": true}` / SSE `data:11`→`data:12` push + disconnect 후 서버 정상. 캐시 `v4` bump.

→ 검증 요약표의 ⏳ 칸 전부 ✅ (Codex axis 통과).

---

# Review Subsystem track — 구현 진행 (/loop 자동)

## A1 (GET read-only) + A5 (created_run_id) · ✅ 완료·검증

**A1:** `run_payload`에서 `ensure_*`(write_text) 블록을 `reconcile_run_artifacts()`로 추출 → run_payload는 순수 read. 명시적 `POST /api/run/reconcile` 신설. 기존 동작 보존 위해 모든 mutating POST(record_run_result, e2e, supervisor_auto_review, advance_run_once 6개 return점)에서 reconcile 명시 호출.
**A5:** `POST /api/messages`가 `created_run_id`+`effective_status` 반환(`lookup_message_effective_run`). 프론트는 created_run_id 우선, 없으면 폴링 폴백. 캐시 v5.

**검증 (3중):**
- ✅ 나 직접: pytest **9 passed**(+`test_get_run_is_read_only`) / smoke `{"ok":true}` / 라이브 GET → **새 파일 0**(read-only 확인) / A5 `created_run_id` 비어있지 않음
- ✅ Codex: **SOUND** — run_payload 완전 side-effect-free, mutating POST 6+개 전부 reconcile 연결(누락 0), `run_claude_review`는 record_run_result 경유라 이중호출 없음, lookup 빈문자열→폴백 안전, reconcile `id` 검증+path-traversal 차단(`safe_run_dir`)+예외 삼킴(mutating POST 안 깨짐)
- 수정 불필요.

## A2 (provenance) + A3 (callable split) · ✅ 완료·검증

**A2:** `make_provenance(source_type, created_by, ...)` 헬퍼 + `PROVENANCE_SOURCE_TYPES` enum(contract_generated/local_self_check/external_codex_cli/live_claude_cli/live_openai_api/external_chatgpt_pro_manual/operator_manual). 뷰어가 쓰는 artifact에 provenance 부착: record_run_result→operator_manual, reconcile→contract_generated, preflight 로컬→local_self_check / 라이브→live_openai_api. (전체 소급 아님, 신규 write부터.)
**A3:** adapter_health `callable` 단일 → `manual_surface_available/auto_spawn_available/cli_path/requires_operator_copy_paste/can_write_artifact_directly` 5키 분리. `callable`=`auto_spawn or manual` 파생 alias로 back-compat 유지. 프론트에 "자동 가능/수동 전용" 배지. 캐시 v6.

**검증:** ✅ 나 직접 pytest **12 passed**(+make_provenance/record_result_provenance/adapter_split 3개) / smoke `{"ok":true}`(callable 유지) / 라이브 adapter_health 5키 확인. 저위험 추가형이라 Codex는 다음 큰 항목과 배치.

## E2 (context capsule) + E4 (output schema) · ✅ 완료·검증

**E2:** `build_context_capsule(run_id,run_dir,mode)` — task/relevant_policy/relevant_issues(top-k, light3·normal8)/current_artifacts(provenance.source_type→trust)/missing_evidence 조립. `reconcile_run_artifacts`에서만 `context-capsule.json` write(A1: GET 아님), `run_payload`는 read만. `prompt_contracts/context_capsule_schema.json` 추가.
**E4:** `prompt_contracts/output_schemas.json` + **stdlib 손수** `validate_review_output(obj)->(ok,errors)`(zero-dep 유지, raise 없음). record_run_result가 validator/claude_review/product_review 결과에 `schema_valid/schema_errors` **주석만**(reject 안 함).

**검증 (3중):**
- ✅ 나 직접: pytest **15 passed** / smoke `{"ok":true}` / 라이브 GET **새 파일 0**(A1 회귀 없음) / reconcile→capsule 생성·GET read-only 확인 / zero-dep 유지(requirements 불변)
- ✅ Codex: **SOUND** — run_payload 순수 read 유지, build_context_capsule 전 예외경로 폴백(reconcile try/except 안), validate_review_output 완전 방어적(어떤 입력도 raise 안 함)
- 비차단 노트(Codex): (MEDIUM) run_dir 없으면 missing_evidence 노이즈 / (LOW) `_artifact_trust`가 reconcile마다 artifact 전부 read·상한 없음 → artifact 폭발 시 A6/B2와 함께 처리. 현 규모(~37개) 무시 가능.

## L2 (GPT-Pro 수동 전략레인 MVP) · ✅ 완료·검증 — north-star 첫 동작

route `chatgpt_pro_manual_strategist`(auto_spawn:false, manual surface) + persona `gpt-pro-strategy-advisor`(review_only) + POST `/api/run/gpt-pro-request`(context-capsule 기반 압축 패킷 `gpt-pro-review-request.md`) + POST `/api/run/gpt-pro-result`(운영자 붙여넣기→`gpt-pro-review-result.json`, source=manual_chatgpt_pro, provenance external_chatgpt_pro_manual, model_claimed_by_operator, E4 validate 주석) + 우측 패널 버튼 2개. 캐시 v7. zero-dep.

**검증:**
- ✅ 나 직접: pytest **16 passed**(+gpt_pro_result_record_shape, JSON/비JSON 양쪽) / smoke `{"ok":true}` / 라이브 두 엔드포인트(패킷 생성 + result 저장 schema_valid=true) / served app.js gpt-pro 핸들러 확인
- ✅ 자가 코드검토(Codex infra 다운 — `service_tier:flex` 계정 거부): `safe_run_dir`로 path-traversal 차단, id/answer 검증, parse 실패→wrap(raise 없음), 패킷 입력=capsule만이라 시크릿 누출 없음. sound.
- 🔧 인프라: `~/.codex/config.toml` `service_tier="flex"` → 계정이 API 400 거부 → **제거(계정 기본 tier)**. 다음 Codex 검증축 복구 시도.

## A4 (workflow_states 단일화) + L5 (waiting_for_operator) · ✅ 완료·검증

**A4:** `prompt_contracts/workflow_states.json`(31 상태, bucket/label_ko/is_terminal/allowed_next/requires_artifacts) 단일 스키마. 서버가 startup에 로드 → ACTIVE/PREPARED/BLOCKED/TERMINAL 셋을 derive(이름 유지, 각 `or {hardcoded}` fallback). `/api/status`에 workflow_states 노출. frontend statusLabel이 그걸 우선 참조+hardcoded fallback. **4개 셋 byte-identical 동등성 확인.**
**L5:** `waiting_for_operator` 상태 + `gpt-pro-waiting.json` 플래그. 패킷 생성→waiting, 답변 저장→해제. work item에 waiting_for_operator 필드.

**검증 (3중):**
- ✅ 나 직접: pytest **18 passed**(+states_cover_backend_sets, gpt_pro_waiting_then_clears) / smoke `{"ok":true}` / GET 새파일 0(A1 회귀X) / workflow_states 31개·waiting 노출 / 상태셋 4개 동등
- ✅ Codex(복구됨!): problems 2건 지적 → #1 **build_gpt_pro_request가 기존 result를 무조건 삭제(데이터 손실)** → **삭제→타임스탬프 아카이브로 수정**(`gpt-pro-review-result.archived-<ts>.json`). #2 스키마 malformed→빈셋 우회 → **이미 4개 셋 모두 `or {hardcoded}` fallback 있어 방어됨**(Codex가 terminal fallback 못 봄), residual(non-empty 오분류)은 version-controlled+test로 수용.

## E3 (review-matrix/5렌즈) + E5 (mode budget) · ✅ 완료·검증

**E3:** `prompt_contracts/review_lenses.json`(intent/contract/evidence/regression/product, 각 question+reviewer+max_findings) + `load_review_lenses()` + `build_review_matrix(run,mode)`(mode별 렌즈 선택, GET 순수 no-write). run_payload에 `review_matrix` 노출.
**E5:** `prompt_contracts/token_budget_profiles.json`(light/normal/closure: capsule_chars·issue_items·review_lenses·claude·openai_api) + `budget_profile(mode)`. build_review_matrix·build_context_capsule가 이 budget 따름(issue cap light3/normal5/closure8).

**검증:** ✅ 나 직접 pytest **20 passed**(+matrix_by_mode, budget_profile_modes) / smoke `{"ok":true}` / 라이브 GET review_matrix 노출 + **새파일 0**(A1 회귀X) / budget가 capsule cap 구동 확인 / zero-dep. 추가형 config·GET try/except 가드라 직접검증으로 충분(Codex 생략).

## A13 (CI) + A9 (Unity adapter) + M3-Unity · ✅ 완료·검증

**A9:** `prompt_contracts/unity_target.json`(target_repo sc-spire-unity, project_type unity, root_path, rendered_evidence_required, parity_sources 등) + `load_unity_target()`/`unity_target_summary()`, `/api/status`에 unity_target 노출.
**M3-Unity:** SUGGEST_KEYWORD_MAP에 Unity surface 16키(전투/UI/씬/프리팹/에디터/유닛 → Assets/Scripts/SCSpire/Runtime·UI, Assets/UI, Assets/Scenes, Assets/Prefabs, Assets/Editor). 기존 Flask/records 유지.
**A13:** 로컬 `verify.py`(pytest + --smoke) + GitHub Actions `.github/workflows/ci.yml`(_sao-push 루트, push마다 pytest 자동 실행) — GPT가 지적한 "검증이 로컬뿐, CI 없음" 해소.

**검증:** ✅ 나 직접 pytest **22 passed**(+load_unity_target, suggest_unity_surface) / smoke `{"ok":true}` / verify.py exit 0 / 라이브 unity_target·`suggest_targets("전투 UI 봐줘")→Assets/...` / A1 회귀X / zero-dep. CI는 push 시 GitHub Actions에서 자동 실행.
- ✅ CI 결과: run 27535782542 **completed/success (21s)** — A13 end-to-end 검증, GPT "CI 없음" 완전 해소.

## B2 (SSE 상한) + A10 (budget-ledger) + A11 (trace_event_v2) · ✅ 완료·검증

**B2:** `/api/events` 동시연결 카운터+`SSE_MAX_CONNECTIONS`(16, env), 초과 503+Retry-After, finally로 슬롯 해제. **A10:** `append_budget_ledger`/`read_budget_ledger`+`GET /api/budget-ledger`, 라이브 OpenAI preflight·deferred 시 기록(suppress 가드). **A11:** `to_trace_event_v2` shim, append_transcript_event가 schema_version2+actor/target/type를 legacy와 함께(additive), run_payload에 trace_v2 노출.

**검증 (3중):**
- ✅ 나 직접: pytest **31 passed** / smoke `{"ok":true}` / ledger 엔드포인트 200 / A1 회귀X / zero-dep
- ✅ Codex: problems 2건 → #1 **B2 슬롯 누수**(send_response가 claim과 try 사이 → 헤더전송 예외 시 슬롯 영구누수) → **send_response를 try 안으로 이동**(finally 항상 해제). #2 read_budget_ledger 비-dict 행 통과 → **isinstance(dict) 필터**. 둘 다 수정. 나머지(503 클린·슬롯 atomic·trace 키 안전·read-only)는 sound.

## A12 (issue-memory→eval) + L3 (openai-strategy-api) + L4 (lane 규격) · ✅ 구현·검증중

**A12:** `load_issue_regression_seeds()`(issues_log/*.md를 `### ` 헤딩 기준 split, tolerant) + `issue_regression_report()`(count/with_countermeasure/seeds cap50) + `GET /api/issue-evals` + status 노출. 향후 parametrized regression pytest seed.
**L3:** `openai-strategy-advisor-api` route + `call_openai_strategy_review`(light/normal/closure·needs_gpt_pro·lens·block_closure 짧은 JSON; preflight처럼 게이트, 아니면 deterministic local_rule fallback·무네트워크) + `POST /api/run/strategy-review`(strategy-review.json, ledger+provenance).
**L4:** `lane_descriptor()`/`build_lanes()`(codex/claude/openai-api/gpt-pro 통일 규격: A3 callable + A2 provenance + E4 output_schema) → status `lanes` 4개. Claude quick-objection/closure-review 프롬프트 분리.

**검증:** ✅ 나 직접 pytest **35**(34+1skip) / smoke `{"ok":true}` / issue-evals 200·lanes 4·strategy-review local fallback 동작 / A1 회귀X / zero-dep. Codex 리뷰 진행중.
- 관측: `issue_regression.count=36968`(로그가 방대 — `### ` 헤딩 실제 다수). seeds는 50 cap이라 payload bounded, 2s status 캐시. Codex perf 판정 보고 필요시 on-demand로 분리.

## 🖥️ 사용자 요청 시각 QA (브라우저 직접 확인) · 버그 2건 발견·수정

루프 중 검증이 pytest/smoke/API/Codex 위주였고 **화면 직접 확인이 빠졌음** → 사용자 지적으로 브라우저 실측. 테스트/엔드포인트는 "통과"였으나 **실제 UI 버그 2건**:
1. **A3 배지 버그**: chatgpt_pro_manual_strategist·openai-strategy-advisor-api 등 새 route가 `호출 대기 / 호출 대기`(이중 배지). 원인 = `build_adapter_health`가 새 route엔 manual/auto 필드 미제공 → 프론트 fallback. **수정**: renderProviderRouting이 `health.x ?? route.x`로 route config(auto_spawn/manual_surface_available) fallback. → Pro 카드 **"수동 전용"** 정상 표시 확인.
2. **M5 커맨드 띠 빈 채로 표시**: renderCommandStrip이 status-hash 안 바뀐 refresh에서 스킵돼 첫 렌더 누락 가능. **수정**: hash 조건 밖에서 매 refresh 무조건 렌더(싸고 idempotent). → 띠에 `단계/경로/막힘/정제/다음` 정상 표시 확인(스크린샷).

**검증:** ✅ 브라우저 시각 확인 — Pro 배지 "수동 전용", 커맨드 띠 채워짐, B1 동적버전 자동 반영(`c6cdcc995056`, 서버 재시작·수동 bump 0). frontend-only(app.js) 변경이라 pytest 35 불변.
**교훈:** 백엔드 테스트 green ≠ UI OK. UI surface 추가 시 브라우저 시각 QA 필수.

## 🔁 GPT 2차 코드검증(실제 GitHub) 후속 5건 · ✅ 적용·검증

GPT가 live repo 코드를 직접 읽고 정확한 후속 5개 지적 → 전부 반영:
1. **A5 계약 완성**: POST /api/messages 응답에 `latest_event`+`created_artifacts`+`queue_routing_decision` 추가(기존 created_run_id/effective_status에 더해). 테스트로 5키 잠금.
2. **reconcile id||run_id**: /api/run/reconcile·gpt-pro-request·gpt-pro-result가 `id or run_id` 둘 다 수용.
3. **GPT-Pro 독립 health**: build_adapter_health에 `chatgpt_pro_manual_strategist` pseudo-adapter(manual True/auto False) 신설, LANE_SPECS를 claude_collaborator에서 분리.
4. **issue_regression status 핫패스 제거**: 대형 markdown scan을 /api/status에서 빼고 `GET /api/issue-evals` on-demand만 유지.
5. **unity_target.json 실값**: 실제 sc-spire-unity repo에서 검증 — `unity_version 6000.4.6f1`, scenes Main/CombatPrototype, surfaces, verification_commands(템플릿), known_missing_systems=[]+의도 note.

**검증:** ✅ 나 직접 pytest **39**(38+1 live skip) / smoke `{"ok":true}` / 라이브: A5 5키·reconcile run_id 200·gpt-pro health 독립·issue_regression status에서 제거·unity 실값 / A1 회귀X / zero-dep. Codex 리뷰 진행중(finish-now라 push 후 반영).
- 🔧 **CI 실측(gh)**: 최근 run 전부 **success**(45f63ad=27543774398, UI fix=27544290823, 후속배치=27545099376 포함). GPT가 "최신 커밋 workflow run 못 봄"이라 한 건 GPT GitHub 커넥터 한계 — 실제 Actions는 매 push 초록불.

## 🔎 GPT 3차(f6f84b9 리뷰, 1커밋 stale) — 진짜 남은 갭 1건 추가 처리

GPT가 `f6f84b9`(UI 패치)를 리뷰 → 5개 후속이 "아직"이라 했으나 그중 4개는 `58a40e0`에서 이미 완료. **유일하게 진짜 남았던 건 GPT #2**: `openai-strategy-advisor-api`가 adapter_health에 없어 프론트가 route config `auto_spawn:true`만 보고 "자동 가능"으로 **과장 표시**(실제 auto는 live토글+키 필요). chatgpt_pro만 pseudo-health 있었고 openai-strategy는 없었음.
**수정:** build_adapter_health에 `openai-strategy-advisor-api` pseudo-health 추가 — `auto_spawn_available = live_preflight_enabled() and openai_key_present`(정직). LANE_SPECS도 자기 health 키로 연결.
**검증:** ✅ pytest **39** / smoke ok / 라이브: openai-strategy health 존재, live off라 auto_spawn=False → 배지가 route-config 추측 대신 실제 상태 표시. live+키 켜면 "자동 가능"으로 전환. CI success(27545099376).

## 🎨 UI 전면 리디자인 1차 (사용자: "존나 깔끔하게 한눈에") · ✅ 1차·시각검증

**배경:** 사용자가 "backend 테스트 통과 ≠ UI OK"라며 화면 직접 보라고 정정. 인정 — 그동안 검증이 backend 편향. frontend-design 스킬로 리디자인.
**적용(디자인 시스템):** type scale(eyebrow/meta/body/title/h)+spacing scale(4/8/12/16/24)+mono(JetBrains Mono)/sans(Plus Jakarta Sans) 폰트, 카드 위계·여백 정리.
**핵심 구조 수정:**
- 좌측 런 목록 **중복 ID 버그 제거** → 짧은 해시 제목 + `hash · HH:MM`(mono) + 배지 2개.
- 상태 탭 **산문벽(보좌관 4라운드/케르베로스) → 접힌 `<details>` 한 줄 요약**. 구조화 현재-명령 카드 + 지표 타일 우선.
- 커맨드 바·탭·인스펙터 폼 여백/위계 정리.
**🔴 리디자인이 낸 회귀 → 즉시 수정:** 새 폰트(JetBrains Mono/Plus Jakarta Sans)가 **한글 글리프 없어 라벨 자모 깨짐**(검사기/운영자 메시지/실시간 큐 등). → 폰트 스택에 **Noto Sans KR + Malgun Gothic fallback** 추가, link에 Noto Sans KR 로드. 한글 정상 렌더 확인.
**검증:** ✅ 브라우저 시각 — 상태탭 커맨드바+구조화카드+산문벽 접힘+지표타일, 좌측 깔끔, 한글 정상. smoke ok / pytest 39(38+1skip). 모든 element id/data-attr/핸들러 보존.
**미완(정직):** 상태·작업자대화·라우팅 탭 + 좌/우 패널만 시각확인. 마일스톤·이슈공유·실행기록 탭은 전역 디자인시스템 상속됐을 뿐 미감사. mono 한글 eyebrow 자간 약간 넓음(minor).

## A6 (atomic write) + A7 (regression test) + B1 (동적 캐시버전) · ✅ 완료·검증

**A6:** `write_json_atomic`(temp 동일디렉토리+flush+fsync+os.replace), `write_json`이 위임 → 모든 caller atomic. per-run lock infra(`run_write_lock`) 제공(call site 소급은 점진).
**A7:** +regression test(write_json_atomic, reconcile idempotent, lookup_message_effective_run, post_message_created_run_id[live skip-if-no-server], static_asset_version, render_index_injects_version).
**B1:** `static_asset_version()`(app.js+styles.css sha1 12hex) + `render_index_html()`이 serve-time에 `?v=` 주입(디스크 불변, A1) → **수동 bump 끝**.

**검증 (3중):**
- ✅ 나 직접: pytest **28**(27 pass+1 live, 서버 있을 때 28 pass) / smoke `{"ok":true}` / A6 os.replace·tmp잔여0 / B1 `app.js?v=bc10d0a0fbbb`(content-hash, 디스크 불변) / A1 회귀X / zero-dep
- ✅ Codex: A6 **SOUND**(temp 동일dir·collision 방지·cleanup·JSON 계약 보존). B1 problems → 정규식 attribute-anchor 안 됨(`notapp.js?v=` 오매치 가능) → **leading `/`로 anchor 수정**. 비차단(per-request read·missing asset silent)은 단일사용자 규모 수용.

## 남은 일 (커밋 보류 상태)
- git 커밋 전부 보류 중 (working tree에 무관 게임 WIP 995개). 사용자가 원하면 `tools/sc_spire_agent_sdk_orchestrator/` + `docs/superpowers/plans/` 만 scoped commit 가능.
- 변경 파일: viewer_server.py, viewer_static/{app.js,index.html,styles.css}, test_viewer_units.py, smoke_test_viewer.py (+ ~/.codex/config.toml 1줄).
