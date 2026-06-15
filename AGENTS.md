# AGENTS.md

이 repo에서 작업할 때는 다음 규칙을 따릅니다.

1. 사용자의 평문 명령을 바로 구현하지 말고 prompt preflight, issue-memory, routing, review gate를 먼저 확인합니다.
2. worker result만으로 completed 처리하지 않습니다. evidence, validator result, review gate가 필요합니다.
3. Codex는 로컬 실행과 검증을 맡고, Claude는 반박 검토를 맡고, OpenAI Agents SDK/API는 구조화 판단과 guardrail에 사용합니다.
4. API 키와 실제 실행 산출물은 commit하지 않습니다.
5. UI 변경 후에는 `node --check tools/sc_spire_agent_sdk_orchestrator/viewer_static/app.js`와 `smoke_test_viewer.py`를 실행합니다.
6. 반복 실패를 발견하면 `memory/issues_log/`에 기록하고 다음 run의 acceptance gate로 승격합니다.
