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

## 남은 일 (커밋 보류 상태)
- git 커밋 전부 보류 중 (working tree에 무관 게임 WIP 995개). 사용자가 원하면 `tools/sc_spire_agent_sdk_orchestrator/` + `docs/superpowers/plans/` 만 scoped commit 가능.
- 변경 파일: viewer_server.py, viewer_static/{app.js,index.html,styles.css}, test_viewer_units.py, smoke_test_viewer.py (+ ~/.codex/config.toml 1줄).
