# 도구 폴더

이 폴더에는 SC Spire Agent Orchestrator의 실제 실행 파일이 들어 있습니다.

상위 README를 먼저 읽으세요.

- `viewer_server.py`: 로컬 HTML/API 서버
- `viewer_static/`: 운영자 dashboard UI
- `sc_spire_ovv_orchestrator.py`: dry-run 및 local orchestration CLI
- `provider_routing.json`: Codex, Claude, OpenAI Agents SDK/API, Gemini 라우팅 정책
- `agents_sdk_pattern.py`: API 호출 없이 Agents SDK식 artifact를 만드는 로컬 패턴
- `agents_sdk_live_adapter.py`: 선택적 live Agents SDK adapter

실행:

```powershell
py -3.13 tools\sc_spire_agent_sdk_orchestrator\viewer_server.py --host 127.0.0.1 --port 8766
```

