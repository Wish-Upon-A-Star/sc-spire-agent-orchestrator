# Orchestrator Improvement Plan

## 1. 핵심 판단

현재 오케스트레이터가 더 좋아지려면 “하위 세션을 많이 부르는 구조”보다 “메인 판단을 강하게 만들고, Claude와 OpenAI/Codex API를 보좌관으로 붙이는 구조”가 낫습니다.

최종 소유자는 `main-orchestrator` 하나로 유지합니다. 대신 메인이 판단하기 전후에 두 보좌관이 반드시 기록을 남깁니다.

- `claude-decision-advisor`: 계획, 제품성, 종료 주장, 약한 가정을 반박합니다.
- `openai-codex-api-advisor`: Agents SDK/API 관점에서 handoff, guardrail, structured output, trace/eval 가능성을 검토합니다.
- `codex-worker`: 로컬 파일, 명령, 브라우저 검증, screenshot/evidence를 실제로 만듭니다.

이 방식은 “누가 최종 책임자인지”를 흐리지 않으면서도, 모델별 장점을 강제로 활용할 수 있습니다.

## 2. OpenAI Agents SDK에서 가져올 것

OpenAI Agents SDK 문서의 핵심 패턴을 로컬 오케스트레이터에 그대로 매핑합니다.

| SDK 패턴 | 우리 오케스트레이터 적용 |
|---|---|
| Agent definitions | 각 역할 persona, 권한, 입력/출력 계약을 `agent-persona` artifact로 고정 |
| Handoffs | 메인이 소유권을 넘길 때만 handoff, 보좌 검토는 agents-as-tools처럼 취급 |
| Guardrails | prompt validation, issue gate, evidence gate, closure gate를 명시 |
| Results and state | run directory를 session/result store로 사용 |
| Tracing/observability | transcript.jsonl, operator_message_events.jsonl, review artifacts를 trace로 사용 |
| Evals | 반복 실패 목록을 eval seed로 승격해 regression checklist 생성 |

중요한 점은 API 호출 여부와 SDK 방식 적용 여부를 분리하는 것입니다. API 예산을 아끼더라도 Agents SDK식 구조, handoff, guardrail, trace artifact는 항상 남겨야 합니다.

## 3. Claude를 더 잘 쓰는 방법

Claude는 worker가 아니라 “반박과 제품 판단”에 더 강하게 배정합니다.

필수 Claude 검토:

- 큰 계획 변경 전 plan critique
- UI/제품/게임 품질 판단
- worker evidence가 충분한지 검토
- closure claim 반박
- 사용자가 화를 낸 반복 실패가 다시 발생했는지 검토

Claude 결과는 `claude-review-result.json` 또는 `claude-advisor-result.json`으로 저장하고, 메인은 그 결과를 받아 최종 결정을 내립니다. Claude 단독으로 completed를 찍지 않습니다.

## 4. Codex 구독 작업자의 위치

Codex 구독/CLI/앱은 비용 대비 가장 자주 써야 하는 실제 실행자입니다.

Codex가 맡는 것:

- repo 조사
- 파일 수정
- 테스트 실행
- 브라우저 확인
- screenshot/evidence 생성
- 실행 실패 원인 추적

Codex가 혼자 판단하면 안 되는 것:

- 제품 완성도 최종 승인
- Claude 검토가 필요한 closure 생략
- issue-memory gate 없이 반복 실패 무시

## 5. OpenAI API/Codex API를 써야 하는 순간

API 예산이 제한되어 있으므로 전부 API로 돌리지 않습니다. 대신 다음처럼 작고 구조화된 판단에 씁니다.

- 평문 프롬프트를 JSON 작업 계약으로 변환
- guardrail pass/fail 판정
- routing decision structured output
- trace/eval metadata 생성
- Claude/Codex 판단이 충돌할 때 tie-break summary

API 호출이 실패하면 숨기지 말고 `api-call-blocked` 또는 `api-call-failed` artifact를 남깁니다.

## 6. UI 개선 방향

운영자는 로그를 읽으러 온 것이 아니라 현재 상태를 판단하러 옵니다. 기본 화면은 다음 순서로 보여야 합니다.

1. 현재 명령
2. 지금 상태
3. 다음 액션
4. 누가 작업 중인지
5. 무엇이 막혔는지
6. 이번 run의 실제 대화
7. evidence와 review gate

이미 적용한 방향:

- `현재 명령` 카드로 원문/상태/경로/검증/다음 액션 분리
- 작업자 대화는 선택 run의 실제 transcript event만 표시
- 이슈 게이트는 선택 run 기준으로 표시
- 반복 review artifact를 run에 남김

## 7. 다음 마일스톤

### M1. 보좌관 council 강제

- 모든 non-trivial run에 `main-advisory-council.json` 생성
- Claude advisor와 OpenAI/Codex API advisor 요청/응답 artifact 분리
- 메인이 두 보좌관 의견을 합성한 `main-decision.json` 생성

### M2. 진짜 trace store

- `transcript.jsonl`을 event schema로 고정
- model route, tool call, handoff, guardrail, artifact를 모두 trace event로 저장
- UI에서 run timeline과 worker conversation을 같은 event source에서 필터링

### M3. issue-memory를 eval로 승격

- `memory/issues_log/*.md`를 단순 목록이 아니라 eval seed로 변환
- 반복 실패마다 binary acceptance check 생성
- review gate에서 “이전 실패 재발 여부”를 필수 체크

### M4. ChatKit 또는 ChatKit-like UI

- ChatKit을 직접 붙일 수 있으면 operator chat surface로 사용
- 당장 붙이지 못하면 현재 HTML을 ChatKit식 message/action/widget 구조로 유지
- 버튼 action: retry, steer, request Claude review, request API guardrail, open evidence

### M5. provider budget/availability panel

- Codex subscription, Claude subscription, OpenAI API, Gemini API 상태를 route health로 표시
- API는 budget guard와 per-run spend note를 남김
- subscription route는 CLI/login availability와 timeout을 별도로 표시

## 8. 성공 기준

좋은 오케스트레이터는 다음 질문에 바로 답해야 합니다.

- 내가 보낸 원문은 무엇인가?
- 프롬프트가 어떻게 정제됐는가?
- 메인은 무엇을 판단했는가?
- Claude는 무엇을 반박했는가?
- OpenAI/Codex API 보좌관은 어떤 guardrail을 제안했는가?
- Codex worker는 실제로 무엇을 수정/검증했는가?
- 반복 이슈는 어떤 acceptance gate로 승격됐는가?
- 왜 완료 또는 미완료인가?

이 질문에 UI와 artifact가 답하지 못하면 아직 오케스트레이터가 아니라 로그 뷰어에 가깝습니다.
