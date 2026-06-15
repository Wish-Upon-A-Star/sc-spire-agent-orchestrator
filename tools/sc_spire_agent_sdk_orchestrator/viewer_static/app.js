const state = {
  runs: [],
  selectedRun: null,
  selectedEventIndex: null,
  queueStatus: null,
  statusTimer: null,
  showTrash: false,
  activeTab: localStorage.getItem("sc-spire-agent-viewer-active-tab") || "status",
  lastRunsHash: "",
  lastStatusHash: "",
  loadInFlight: false,
  refreshInFlight: false,
  pendingRunId: "",
};

const DETAILS_STORAGE_KEY = "sc-spire-agent-viewer-details-open";
const DETAILS_DEFAULTS_VERSION_KEY = "sc-spire-agent-viewer-details-version";
const DETAILS_DEFAULTS_VERSION = "visual-ops-v1";

try {
  if (localStorage.getItem(DETAILS_DEFAULTS_VERSION_KEY) !== DETAILS_DEFAULTS_VERSION) {
    localStorage.removeItem(DETAILS_STORAGE_KEY);
    localStorage.setItem(DETAILS_DEFAULTS_VERSION_KEY, DETAILS_DEFAULTS_VERSION);
  }
} catch {
  // Ignore storage failures; the viewer still works without persisted panels.
}

function readDetailsState() {
  try {
    return JSON.parse(localStorage.getItem(DETAILS_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeDetailsState(nextState) {
  localStorage.setItem(DETAILS_STORAGE_KEY, JSON.stringify(nextState));
}

function detailOpenAttr(key, defaultOpen = false) {
  const stored = readDetailsState()[key];
  const open = stored === undefined ? defaultOpen : Boolean(stored);
  return open ? " open" : "";
}

function bindDetailsPersistence(root = document) {
  root.querySelectorAll("details[data-details-key]").forEach((node) => {
    const key = node.dataset.detailsKey;
    const stored = readDetailsState()[key];
    if (stored !== undefined) node.open = Boolean(stored);
    if (node.dataset.detailsBound === "1") return;
    node.dataset.detailsBound = "1";
    node.addEventListener("toggle", () => {
      if (!key) return;
      const nextState = readDetailsState();
      nextState[key] = node.open;
      writeDetailsState(nextState);
    });
  });
}

const t = {
  title: "SC Spire \uc5d0\uc774\uc804\ud2b8 \uc2e4\ud589 \uae30\ub85d",
  runsHeading: "\uc5d0\uc774\uc804\ud2b8 \uc2e4\ud589",
  refresh: "\uc0c8\ub85c\uace0\uce68",
  noRun: "\uc120\ud0dd\ub41c \uc2e4\ud589 \uc5c6\uc74c",
  transcript: "\ub300\ud654 \uae30\ub85d",
  inspector: "\uac80\uc0ac\uae30",
  eventDetail: "\uc774\ubca4\ud2b8 \uc0c1\uc138",
  selectEvent: "\uc774\ubca4\ud2b8\ub97c \uc120\ud0dd\ud558\uc138\uc694.",
  operatorMessage: "\uc6b4\uc601\uc790 \uba54\uc2dc\uc9c0",
  target: "\ub300\uc0c1",
  mainQueue: "\ud504\ub86c\ud504\ud2b8 \uc0ac\uc804 \uac80\uc99d",
  viewerNote: "\ubdf0\uc5b4 \uba54\ubaa8",
  threadQueue: "\ud2b9\uc815 \uc2a4\ub808\ub4dc \ud050",
  threadId: "\uc2a4\ub808\ub4dc ID",
  optional: "\uc120\ud0dd \uc0ac\ud56d",
  messagePlaceholder: "\uc9e7\uac8c \uc368\ub3c4 \ub429\ub2c8\ub2e4. \uac80\uc99d\ud55c \ub4a4 \uba54\uc778 \uc624\ucf00\uc2a4\ud2b8\ub808\uc774\ud130\uc6a9 \ud504\ub86c\ud504\ud2b8\ub85c \ubc14\uafb8\uc5b4 \ud050\uc5d0 \ub123\uc2b5\ub2c8\ub2e4.",
  queueMessage: "\uc0ac\uc804 \uac80\uc99d \ud6c4 \ud050\uc5d0 \ub123\uae30",
  queued: "\uac80\uc99d \ud6c4 \ud050\uc5d0 \uc800\uc7a5\ub428",
  emptyMessage: "메시지를 입력하세요.",
  promptPreviewTitle: "\uba54\uc778\uc5d0\uac8c \ub118\uc5b4\uac08 \uc815\uc81c \ud504\ub86c\ud504\ud2b8",
  promptPreviewSummary: "\uc815\uc81c \ud504\ub86c\ud504\ud2b8 \uc5f4\uae30",
  promptWarnings: "\uac80\uc99d \uba54\ubaa8",
  preflightMode: "\uc0ac\uc804 \uac80\uc99d \ubaa8\ub4dc",
  preflightModel: "\uac80\uc99d \ubaa8\ub378",
  clarifyingQuestions: "\ubcf4\uac15 \uc9c8\ubb38",
  eventCount: "\uc774\ubca4\ud2b8",
  countSuffix: "\uac1c",
  claudeRequest: "Claude \uc694\uccad",
  claudeResponse: "Claude \uc751\ub2f5",
  plan: "\uacc4\ud68d",
  chatkit: "ChatKit",
  jsonl: "JSONL",
  currentRun: "\ud604\uc7ac \uae30\uc900",
  sdkNotLive: "SDK \uc900\ube44",
  sampleOnly: "\uc0d8\ud50c",
  promptOnly: "\ud504\ub86c\ud504\ud2b8\ub9cc",
  liveClaude: "Claude \uc2e4\ud589",
  speaker: "\ubc1c\ud654\uc790",
  recipient: "\uc218\uc2e0\uc790",
  type: "\uc720\ud615",
  time: "\uc2dc\uac04",
  artifact: "\uc544\ud2f0\ud329\ud2b8",
  none: "\uc5c6\uc74c",
  message: "\uba54\uc2dc\uc9c0",
  guideKicker: "\uc774 \ud654\uba74\uc758 \uc5ed\ud560",
  guideTitle: "\uac8c\uc784 \uc81c\uc791\uc744 \uc704\ud55c \uc5d0\uc774\uc804\ud2b8 \uc6b4\uc601\ud310\uc785\ub2c8\ub2e4",
  guideBody:
    "\uc774 \uc0ac\uc774\ud2b8\ub294 \uc5d0\uc774\uc804\ud2b8\ub4e4\uc774 \uc694\uad6c\uc0ac\ud56d\uc744 \uc5b4\ub5bb\uac8c \ub098\ub204\uace0, \uc5b4\ub5a4 \uadfc\uac70\ub85c \uac8c\uc784 \uc791\uc5c5\uc744 \uc9c4\ud589\ud574\uc57c \ud558\ub294\uc9c0 \ubcf4\ub294 \ub300\uc2dc\ubcf4\ub4dc\uc785\ub2c8\ub2e4. \uc644\ub8cc \ubcf4\uace0\uc11c\uac00 \uc544\ub2c8\ub77c, \ub2e4\uc74c \uad6c\ud604\uacfc \uac80\uc99d\uc744 \uacb0\uc815\ud558\ub294 \uc791\uc5c5\uc2e4\uc785\ub2c8\ub2e4.",
  guideSteps: [
    "\uc67c\ucabd\uc5d0\uc11c \uc2e4\ud589 \ud558\ub098\ub97c \uc120\ud0dd\ud569\ub2c8\ub2e4.",
    "\uac00\uc6b4\ub370\uc5d0\uc11c \uc778\uacc4, \uc9c8\ubb38, \ubc18\ubc15, \ud569\uc758, \uac80\ud1a0 \uc774\ubca4\ud2b8\ub97c \uc2dc\uac04\uc21c\uc73c\ub85c \ubd05\ub2c8\ub2e4.",
    "\uc774\ubca4\ud2b8\ub97c \ub204\ub974\uba74 \uc624\ub978\ucabd\uc5d0\uc11c \uc0c1\uc138 \ubc1c\ud654\uc790, \uc218\uc2e0\uc790, \uc544\ud2f0\ud329\ud2b8\ub97c \ud655\uc778\ud569\ub2c8\ub2e4.",
    "\uc9c0\uc2dc\ub098 \uc218\uc815\uc0ac\ud56d\uc740 \uc6b4\uc601\uc790 \uba54\uc2dc\uc9c0\uc5d0 \uc801\uc5b4 \uba54\uc778 \ud050\uc5d0 \ub123\uc2b5\ub2c8\ub2e4.",
  ],
  workflowTitle: "\uac8c\uc784 \uc81c\uc791\uc5d0\uc11c\ub294 \uc774\ub807\uac8c \uc4f0\uc138\uc694",
  workflowItems: [
    "\uad6c\ud604 \uc804: PRD, \uc791\uc5c5 \ubd84\ud574, Review Gate\uac00 \ucda9\ubd84\ud55c\uc9c0 \ud655\uc778",
    "\uad6c\ud604 \uc911: open issue\uc640 challenge\uac00 \ub2e4\uc74c worker \uc9c0\uc2dc\uc5d0 \ub4e4\uc5b4\uac14\ub294\uc9c0 \ud655\uc778",
    "\uc644\ub8cc \uc804: \ub80c\ub354\ub9c1 \uc99d\uac70, \ud569\uc758, \ubbf8\ud574\uacb0 \uc774\uc288\uac00 \ub0a8\uc558\ub294\uc9c0 \ud655\uc778",
  ],
  latestWorkTitle: "\ubc29\uae08 \ubdf0\uc5b4\uc5d0 \ucd94\uac00\ud55c \uac83",
  latestWorkItems: [
    "\ud654\uba74 \uc0ac\uc6a9\ubc95\uacfc \uac8c\uc784 \uc81c\uc791 \ud750\ub984 \uc548\ub0b4",
    "\ud604\uc7ac \uc2e4\ud589\uc758 \ube14\ub85c\ucee4, \ubd84\ub958, \ud544\uc694 \uc99d\uac70, \uc5f4\ub9b0 \uc774\uc288 \uc694\uc57d",
    "\uc5d0\uc774\uc804\ud2b8 \uc5ed\ud560 \uc124\uba85\uacfc \uc774\ubca4\ud2b8 \uc720\ud615 \ud55c\uad6d\uc5b4 \ud45c\uc2dc",
    "\uc6b4\uc601\uc790 \uba54\uc2dc\uc9c0\ub97c \uc0ac\uc804 \uac80\uc99d\ud558\uace0 \uba54\uc778 \uc624\ucf00\uc2a4\ud2b8\ub808\uc774\ud130\uc6a9 \ud504\ub86c\ud504\ud2b8\ub85c \uc815\uc81c\ud558\ub294 \ud750\ub984",
  ],
  providerRoutingTitle: "\ubaa8\ub378/\uc2e4\ud589 \uacbd\ub85c",
  providerRoutingBody: "\uae30\ubcf8\uc740 Codex/Claude MAX \uad6c\ub3c5 \uacbd\ub85c\uc785\ub2c8\ub2e4. OpenAI API\ub294 \uc0ac\uc804 \uc815\uc81c, \uad6c\uc870\ud654, \uac00\ub4dc\ub808\uc77c \uac19\uc740 \uc791\uc740 \uc791\uc5c5\uc5d0\ub9cc \uc4f0\ub3c4\ub85d \uc81c\ud55c\ud569\ub2c8\ub2e4. \uc2e4\uc218/\uac80\ud1a0 \uae30\ub85d\uc740 transcript\uc640 issue memory\ub97c \ud1b5\ud574 \ub2e4\uc74c Codex/Claude \uc785\ub825\uc73c\ub85c \uacf5\uc720\ud569\ub2c8\ub2e4.",
  openaiRoute: "OpenAI API / Agents SDK",
  claudeRoute: "Claude MAX \uad6c\ub3c5 \uac80\ud1a0",
  codexRoute: "Codex MAX \uad6c\ub3c5 CLI/\uc571",
  routeEnabled: "\uc124\uc815\ub428",
  routeDisabled: "\ube44\ud65c\uc131",
  routeModel: "\ubaa8\ub378",
  routeBilling: "\uacfc\uae08",
  routeSurface: "\uc2e4\ud589 \ud45c\uba74",
  routePriority: "\uc6b0\uc120\uc21c\uc704",
  routeDefault: "\uae30\ubcf8",
  lastQueuedMessage: "\ub9c8\uc9c0\ub9c9 \ud050 \uba54\uc2dc\uc9c0",
  queueHeading: "\uc2e4\uc2dc\uac04 \ud050",
  liveOn: "\uc790\ub3d9 \uac31\uc2e0",
  queueAutorunOn: "자동 처리 켜짐",
  liveError: "\uac31\uc2e0 \uc2e4\ud328",
  noMessages: "\uc544\uc9c1 \ubcf4\ub0b8 \uba54\uc2dc\uc9c0\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.",
  queueProcessor: "\ud050 \ud504\ub85c\uc138\uc11c",
  queueProcessorState: "큐 프로세서 상태",
  processNext: "\ub2e4\uc74c \ucc98\ub9ac",
  cancelAll: "\uc804\uccb4 \ucde8\uc18c",
  cancelAllConfirm: "대기 중인 메시지를 모두 취소합니다. 이미 실행 중인 작업은 중단하지 않을 수 있습니다. 계속할까요?",
  trash: "\ud734\uc9c0\ud1b5",
  hideTrash: "\ud734\uc9c0\ud1b5 \ub2eb\uae30",
  canceled: "\ucde8\uc18c\ub428",
  queueMoveUp: "\uc704",
  queueMoveDown: "\uc544\ub798",
  queueEdit: "\ud3b8\uc9d1",
  queueRemove: "\uc81c\uac70",
  queueSteer: "\uc2a4\ud2f0\uc5b4",
  queueEditPrompt: "\ud050 \uba54\uc2dc\uc9c0\ub97c \uc218\uc815\ud558\uc138\uc694.",
  queueSteerPrompt: "\ub300\uc0c1\uc744 \uc785\ub825\ud558\uc138\uc694: main, html, thread",
  queueRemoved: "\uc81c\uac70\ub428",
  queueAutorunOff: "\uc218\ub3d9 \ud050",
  statusQueued: "\ub300\uae30",
  statusPlanning: "\uc815\uc81c \uc911",
  statusPreflightRefining: "\uc815\uc81c \uc911",
  statusRouted: "\ub77c\uc6b0\ud305",
  statusPlanningReady: "\uba54\uc778 \ud050 \uc804\ub2ec\ub428",
  statusPreparedNotRunning: "실행 대기",
  statusSentToMain: "인계됨",
  statusDispatchReady: "작업자 배정됨",
  statusDispatchBlocked: "실행 차단",
  statusLegacyRecord: "\uc774\uc804 \uae30\ub85d",
  statusArchivedRun: "\ubcf4\uad00\ub41c \uc2e4\ud589",
  statusDone: "\uc644\ub8cc",
  statusBlocked: "\ube14\ub85d",
  statusRemoved: "\uc81c\uac70\ub428",
  statusCanceled: "\ucde8\uc18c\ub428",
  lifecycleTitle: "\ud604\uc7ac \uc9c4\ud589",
  currentPrompt: "\ud604\uc7ac \uba54\uc778 \ud504\ub86c\ud504\ud2b8",
  nextPreparedPrompt: "메인에 전달됐지만 아직 실행 안 됨",
  activeAgents: "\uc791\uc5c5\uc911/\ub300\uae30 \uc5d0\uc774\uc804\ud2b8",
  noCurrentPrompt: "\ud604\uc7ac \uc2e4\ud589 \uc911\uc778 \uba54\uc778 \ud504\ub86c\ud504\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.",
  quotaTitle: "\ud560\ub2f9\ub7c9 \ud655\uc778",
  sharedWorkspaceTitle: "\uacf5\uc720 \uc791\uc5c5\uc2e4",
  agentIdentityTitle: "\uc5d0\uc774\uc804\ud2b8 \uc815\uccb4\uc131",
  reviewLanesTitle: "\uac80\ud1a0 \uc804\uc6a9 \ub808\uc778",
  sharedSourcesTitle: "\uacf5\uc720 \uc790\ub8cc",
  reviewOnly: "\uac80\ud1a0 \uc804\uc6a9",
  sdkPatternTitle: "Agents SDK \ubc29\uc2dd \uc801\uc6a9",
  mainContextTitle: "메인 오케스트레이터 입력",
  dispatchContractTitle: "메인 dispatch 계약",
  workBoardTitle: "\uc791\uc5c5 \ub300\uc0c1",
  cleanGuideTitle: "\uc0ac\uc6a9 \uc21c\uc11c",
  cleanGuide: "\uba54\uc2dc\uc9c0\ub97c \ub123\uc73c\uba74 \ud504\ub86c\ud504\ud2b8 \uc0ac\uc804 \uac80\uc99d\uc774 \uba3c\uc800 \ub2e4\ub4ec\uace0, \ub2e4\uc74c \ucc98\ub9ac\ub85c \uba54\uc778\uc5d0 \ub118\uae41\ub2c8\ub2e4. \ud544\uc694\ud558\uba74 \ud050\uc5d0\uc11c \uc218\uc815, \uc21c\uc11c \ubcc0\uacbd, \ucde8\uc18c\ub97c \uba3c\uc800 \ud558\uc138\uc694.",
  dashboardTitle: "현재 작업 상황판",
  dashboardBody: "위쪽은 지금 판단해야 할 것만 보여줍니다. 상세 로그, SDK manifest, 공유 규칙은 아래 접힌 영역에서 확인하세요.",
  flowMapTitle: "오케스트레이션 흐름",
  flowMapBody: "각 단계를 누르면 이번 실행에서 만든 artifact와 이벤트가 보입니다.",
  flowTitle: "지금 메시지 흐름",
  nextActionTitle: "다음 단계",
  flowEmpty: "아직 추적 중인 메시지가 없습니다.",
  flowQueued: "저장됨",
  flowPreflight: "사전 검증",
  flowMain: "메인 전달",
  flowDispatch: "작업자 배정",
  flowReview: "검토",
  conversationTitle: "작업자 대화",
  conversationSubtitle: "선택한 실행의 transcript.jsonl에 저장된 실제 작업자/검토자 이벤트만 보여줍니다. 상태/계획 요약은 다른 탭에서 확인하세요.",
  noConversation: "선택한 실행에 표시할 작업자 대화가 없습니다.",
  recipientLabel: "수신",
  attachmentLabel: "첨부",
  recordedSummary: "기록 요약",
  rawTranscriptNoteTitle: "원본 실행 기록 범위",
  rawTranscriptNoteBody: "작업자 대화는 선택한 실행의 transcript.jsonl 이벤트만 사용합니다. 계획 요약, 상태 카드, 합성 대화는 섞지 않습니다.",
  mainStatusTitle: "메인 오케스트레이터 상태",
  mainStatusSentOnly: "메인 큐에 전달됨 · 실제 worker 호출 기록 없음",
  mainStatusWorkerNone: "작업자 배정",
  mainStatusNext: "다음 후보",
  details: "\uc0c1\uc138",
  executionTitle: "\uc2e4\uc81c \uc2e4\ud589 \uc704\uce58",
  executionServer: "\ub85c\uceec \uc11c\ubc84",
  executionEntrypoint: "\uc2e4\ud589 \ud30c\uc77c",
  executionStateDir: "\uae30\ub85d \uc800\uc7a5",
  executionScope: "\uc790\ub3d9 \ucc98\ub9ac",
  executionNoWorkers: "Claude/Codex worker \uc790\ub3d9 \uc2e4\ud589 \uc544\ub2d8",
  executionOpenAiOnly: "OpenAI\ub294 \ud504\ub86c\ud504\ud2b8 \uc0ac\uc804 \uac80\uc99d/\uc815\uc81c\uc5d0\ub9cc \uc0ac\uc6a9",
  executionThisChat: "\ud30c\uc77c \uc218\uc815\uacfc \uac80\uc99d\uc740 \uc9c0\uae08 \uc774 Codex \ub300\ud654\uc5d0\uc11c \uc218\ud589",
  requeueHistorical: "\uc774\uc804 \uba54\uc2dc\uc9c0 \uba54\uc778 \ud050 \ud3b8\uc785",
  activeWork: "현재 진행/검토 중",
  preparedWork: "대기/검토 필요",
  archivedWork: "\uc774\uc804 \uae30\ub85d",
  noActiveWork: "현재 진행 중이거나 검토 gate가 열린 run이 없습니다.",
  agentRoster: "\uc5d0\uc774\uc804\ud2b8 \uc0c1\ud0dc",
  agentOperationsTitle: "현재 에이전트 실행판",
  agentOpsCompactTitle: "작업자 상태",
  sdkStatusTitle: "Agents SDK 상태",
  sdkUsePolicy: "메인 오케스트레이터는 handoff, guardrail, structured output, trace/eval 기록, 작은 live SDK 판단이 필요할 때 Agents SDK를 적극 사용합니다. 큰 로컬 구현은 Codex/Claude 구독 경로와 조합합니다.",
  agentCardActive: "처리중",
  agentCardPrepared: "메인 대기",
  agentGroupActive: "처리중",
  agentGroupPending: "메인 대기",
  agentGroupAvailable: "사용 가능",
  agentGroupDisabled: "비활성/대기 없음",
  routePending: "\ub300\uae30",
  routeActive: "\uc791\uc5c5\uc911",
  routeIdle: "\ub300\uae30 \uc5c6\uc74c",
  routeAvailable: "사용 가능",
  milestonesTitle: "서비스 마일스톤",
  milestonesSubtitle: "실제 운영 사이트 품질로 가기 위한 우선순위, 현재 상태, 완료 증거, 다음 액션입니다.",
  knowledgeTitle: "이슈/공유 작업장",
  knowledgeSubtitle: "작업자와 검토자가 반복 실수를 피하기 위해 먼저 읽어야 하는 공유 정보입니다.",
  priority: "우선순위",
  status: "상태",
  why: "왜 중요",
  evidence: "완료 증거",
  nextAction: "다음 액션",
  workerReadOrder: "작업자 읽기 순서",
  originalRequirements: "최초 요구사항",
  recentIssues: "최근 이슈 메모리",
  permissionRisks: "권한/동기화 리스크",
  summaryTitle: "\ud604\uc7ac \uc2e4\ud589 \uc694\uc57d",
  dispatchTitle: "\uba54\uc778 \uc774\ud6c4 \ub77c\uc6b0\ud305",
  dispatchActual: "\uc2e4\uc81c \ubc30\uc815 \uc0c1\ud0dc",
  dispatchOwner: "\ud604\uc7ac \uc18c\uc720\uc790",
  dispatchNotYet: "\uc544\uc9c1 \uc2e4\uc81c \ud558\uc704 \uc5d0\uc774\uc804\ud2b8\ub85c \ubc30\uc815\ub41c \ub85c\uadf8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
  dispatchRecommended: "\ucd94\ucc9c \ub2e4\uc74c \uacbd\ub85c",
  blocker: "\ube14\ub85c\ucee4",
  classification: "\ubd84\ub958",
  surfaces: "\uc601\ud5a5 \ud654\uba74",
  evidenceRequired: "\ud544\uc694 \uc99d\uac70",
  openIssues: "\uc5f4\ub9b0 \uc774\uc288",
  plannedFiles: "\uacc4\ud68d \ud30c\uc77c",
  artifacts: "\uc0dd\uc131 \ud30c\uc77c",
  unknown: "\ud655\uc778 \ud544\uc694",
};

const eventTypeLabels = {
  handoff: "\uc778\uacc4",
  response: "\uc751\ub2f5",
  assignment: "\ubc30\uc815",
  question: "\uc9c8\ubb38",
  answer: "\ub2f5\ubcc0",
  challenge: "\ubc18\ubc15",
  consensus: "\ud569\uc758",
  review_request: "\uac80\ud1a0 \uc694\uccad",
  review_queued: "\uac80\ud1a0 \ub300\uae30",
  advisor_request: "보좌 요청",
  advisor_council_policy: "보좌관 규칙",
  queue_decision: "큐 판정",
  queue_routing_decision: "큐 판정",
  summary: "\uc694\uc57d",
};

const roleHints = {
  "supervisor-agent": "\uc791\uc5c5 \uc21c\uc11c\uc640 \ucd5c\uc885 \ud310\ub2e8\uc744 \uc7a1\ub294 \uba54\uc778 \uc624\ucf00\uc2a4\ud2b8\ub808\uc774\ud130",
  "intake-agent": "\uc0ac\uc6a9\uc790 \uc694\uccad\uc744 PRD\uc640 \uc218\uc6a9 \uae30\uc900\uc73c\ub85c \ubc14\uafb8\ub294 \uc5ed\ud560",
  "issue-memory-agent": "\uae30\uc874 \uc774\uc288 \uae30\ub85d\uc744 \ucc3e\uc544 \uc0c8 \uc791\uc5c5\uc758 \uac8c\uc774\ud2b8\ub85c \uc62c\ub9ac\ub294 \uc5ed\ud560",
  "codex-worker": "\uc2e4\uc81c \ud30c\uc77c \uc218\uc815, \uba85\ub839 \uc2e4\ud589, \uc99d\uac70 \ud328\ud0a4\uc9d5 \ub2f4\ub2f9",
  "product-critic-agent": "\ud50c\ub808\uc774\uc5b4 \ud654\uba74, \uc0c1\ud488\uc131, \uacfc\uc7a5\ub41c \uc644\ub8cc \uc8fc\uc7a5\uc744 \uac80\uc0ac",
  "validator-code-level": "\ubb38\ubc95, \uacc4\uc57d, \ud68c\uadc0, \uc0c1\ud0dc \uc804\uc774\ub97c \uac80\uc0ac",
  "validator-ovv-product-level": "OVV, \ub80c\ub354\ub9c1 \uc99d\uac70, \ubbf8\ud574\uacb0 \uc774\uc288, \uc644\ub8cc \uc815\uc9c1\uc131\uc744 \uac80\uc0ac",
  "claude-reviewer": "\ub2e4\ub978 \ubaa8\ub378 \uc2dc\uac01\uc73c\ub85c \uad6c\uc870\uc640 \uc81c\ud488 \ud310\ub2e8\uc744 \ubc18\ubc15/\uac80\ud1a0",
  "claude-decision-advisor": "메인 최종 판단 전 계획, 제품, 증거, 큐 steering을 반박하는 Claude 보좌관",
  "openai-codex-api-advisor": "Agents SDK/API 관점으로 구조화 라우팅, guardrail, trace/eval을 점검하는 OpenAI/Codex 보좌관",
};

const el = {
  runs: document.getElementById("runs"),
  refresh: document.getElementById("refresh-runs"),
  runId: document.getElementById("run-id"),
  runTitle: document.getElementById("run-title"),
  runMeta: document.getElementById("run-meta"),
  guideKicker: document.getElementById("guide-kicker"),
  guideTitle: document.getElementById("guide-title"),
  guideBody: document.getElementById("guide-body"),
  guideSteps: document.getElementById("guide-steps"),
  gameWorkflow: document.getElementById("game-workflow"),
  workBoard: document.getElementById("work-board"),
  providerRouting: document.getElementById("provider-routing"),
  agentConversation: document.getElementById("agent-conversation"),
  milestones: document.getElementById("milestones"),
  knowledgeHub: document.getElementById("knowledge-hub"),
  transcriptDetails: document.querySelector('[data-details-key="transcript-details"]'),
  runSummary: document.getElementById("run-summary"),
  timeline: document.getElementById("timeline"),
  inspector: document.getElementById("inspector"),
  messageTarget: document.getElementById("message-target"),
  messageThread: document.getElementById("message-thread"),
  messageText: document.getElementById("message-text"),
  sendMessage: document.getElementById("send-message"),
  messageStatus: document.getElementById("message-status"),
  promptPreview: document.getElementById("prompt-preview"),
  toggleLivePreflight: document.getElementById("toggle-live-preflight"),
  queueHeading: document.getElementById("queue-heading"),
  liveStatus: document.getElementById("live-status"),
  queueStatusList: document.getElementById("queue-status-list"),
  processNext: document.getElementById("process-next"),
  cancelAll: document.getElementById("cancel-all"),
  toggleTrash: document.getElementById("toggle-trash"),
  resultType: document.getElementById("result-type"),
  resultRole: document.getElementById("result-role"),
  resultStatus: document.getElementById("result-status"),
  resultSummary: document.getElementById("result-summary"),
  resultEvidence: document.getElementById("result-evidence"),
  resultRisks: document.getElementById("result-risks"),
  advanceRun: document.getElementById("advance-run"),
  runClaudeReview: document.getElementById("run-claude-review"),
  recordE2e: document.getElementById("record-e2e"),
  submitResult: document.getElementById("submit-result"),
  resultStatusMessage: document.getElementById("result-status-message"),
  tabButtons: Array.from(document.querySelectorAll("[data-tab-target]")),
  tabPanels: Array.from(document.querySelectorAll("[data-tab-panel]")),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function text(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setStaticText() {
  document.title = t.title;
  text("runs-heading", t.runsHeading);
  text("refresh-runs", t.refresh);
  text("run-id", t.noRun);
  text("run-title", t.transcript);
  text("inspector-kicker", t.inspector);
  text("inspector-heading", "운영 입력");
  text("operator-heading", t.operatorMessage);
  text("target-label", t.target);
  text("target-main", t.mainQueue);
  text("target-html", t.viewerNote);
  text("target-thread", t.threadQueue);
  text("thread-label", t.threadId);
  el.messageThread.placeholder = t.optional;
  el.messageText.placeholder = t.messagePlaceholder;
  el.sendMessage.textContent = t.queueMessage;
  el.queueHeading.textContent = t.queueHeading;
  el.liveStatus.textContent = t.queueAutorunOff;
  if (el.processNext) el.processNext.textContent = t.processNext;
  if (el.cancelAll) el.cancelAll.textContent = t.cancelAll;
  if (el.toggleTrash) el.toggleTrash.textContent = t.trash;
  el.guideKicker.textContent = t.guideKicker;
  el.guideTitle.textContent = t.guideTitle;
  el.guideBody.textContent = t.guideBody;
  el.guideSteps.innerHTML = t.guideSteps.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  el.gameWorkflow.innerHTML = `
    <div>
      <h4>${escapeHtml(t.workflowTitle)}</h4>
      ${t.workflowItems.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
    </div>
    <div class="latest-work">
      <h4>${escapeHtml(t.latestWorkTitle)}</h4>
      ${t.latestWorkItems.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
    </div>
  `;
  bindTabs();
  bindDetailsPersistence();
}

function bindTabs() {
  if (!el.tabButtons.length || !el.tabPanels.length) return;
  el.tabButtons.forEach((button) => {
    if (button.dataset.tabBound === "1") return;
    button.dataset.tabBound = "1";
    button.addEventListener("click", () => setActiveTab(button.dataset.tabTarget || "status"));
  });
  setActiveTab(state.activeTab, { persist: false });
}

function setActiveTab(tabName, options = {}) {
  const available = new Set(el.tabPanels.map((panel) => panel.dataset.tabPanel));
  const next = available.has(tabName) ? tabName : "status";
  state.activeTab = next;
  if (options.persist !== false) localStorage.setItem("sc-spire-agent-viewer-active-tab", next);
  el.tabButtons.forEach((button) => {
    const active = button.dataset.tabTarget === next;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  el.tabPanels.forEach((panel) => {
    const active = panel.dataset.tabPanel === next;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  if (next === "records" && el.transcriptDetails) el.transcriptDetails.open = true;
}

function stableHash(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return String(Date.now());
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || `${response.status} ${response.statusText}`);
  }
  return data;
}

async function patchJson(url, payload) {
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.error || "request failed");
  return data;
}

async function deleteJson(url) {
  const response = await fetch(url, { method: "DELETE" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.error || "request failed");
  return data;
}

async function loadRuns() {
  if (state.loadInFlight) return;
  state.loadInFlight = true;
  try {
  const [data, providerRouting, queueStatus] = await Promise.all([
    fetchJson("/api/runs"),
    fetchJson("/api/provider-routing").catch(() => null),
    fetchJson("/api/status").catch(() => null),
  ]);
  state.runs = data.runs || [];
  state.queueStatus = queueStatus;
  state.lastRunsHash = stableHash((state.runs || []).map((run) => [run.id, run.title, run.event_count, run.has_chatkit]));
  state.lastStatusHash = stableHash({
    lifecycle: queueStatus?.execution_lifecycle,
    queue_processor: queueStatus?.queue_processor,
    messages: (queueStatus?.messages || []).map((message) => [
      message.id,
      message.effective_status,
      message.target,
      message.effective_run_id,
      message.latest_event?.timestamp,
      message.latest_event?.detail,
    ]),
    agents: queueStatus?.agents,
    work_items: queueStatus?.work_items,
    sdk: queueStatus?.agents_sdk_pattern,
    sdk_manifest: queueStatus?.agents_sdk_manifest,
    issue_memory: queueStatus?.issue_memory,
  });
  renderProviderRouting(providerRouting, queueStatus?.adapter_health || queueStatus?.execution_environment?.adapter_health || {});
  renderLatestQueuedMessage(queueStatus);
  renderTargetOptions(queueStatus?.agent_targets || []);
  renderQueueStatus(queueStatus);
  renderWorkBoard(queueStatus);
  renderMilestones(queueStatus);
  renderKnowledgeHub(queueStatus);
  renderRuns();
  if (!state.selectedRun && state.runs.length) {
    await loadRun(state.runs[0].id);
  }
  } finally {
    state.loadInFlight = false;
  }
}

async function refreshLiveStatus() {
  if (state.loadInFlight || state.refreshInFlight) return;
  state.refreshInFlight = true;
  try {
    const [queueStatus, runsData] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/runs").catch(() => null),
    ]);
    state.queueStatus = queueStatus;
    const nextRunsHash = stableHash((runsData?.runs || []).map((run) => [run.id, run.title, run.event_count, run.has_chatkit]));
    if (runsData?.runs && nextRunsHash !== state.lastRunsHash) {
      state.lastRunsHash = nextRunsHash;
      state.runs = runsData.runs;
      renderRuns();
    }
    const nextStatusHash = stableHash({
      lifecycle: queueStatus?.execution_lifecycle,
      queue_processor: queueStatus?.queue_processor,
      messages: (queueStatus?.messages || []).map((message) => [
        message.id,
        message.effective_status,
        message.target,
        message.effective_run_id,
        message.latest_event?.timestamp,
        message.latest_event?.detail,
      ]),
      agents: queueStatus?.agents,
      work_items: queueStatus?.work_items,
      sdk: queueStatus?.agents_sdk_pattern,
      sdk_manifest: queueStatus?.agents_sdk_manifest,
      issue_memory: queueStatus?.issue_memory,
    });
    if (nextStatusHash !== state.lastStatusHash) {
      state.lastStatusHash = nextStatusHash;
      renderLatestQueuedMessage(queueStatus);
      renderTargetOptions(queueStatus?.agent_targets || []);
      if (document.activeElement !== el.messageText) {
        renderQueueStatus(queueStatus);
      }
      renderCommandStrip(queueStatus);
      renderWorkBoard(queueStatus);
      renderMilestones(queueStatus);
      renderKnowledgeHub(queueStatus);
      renderPreflightBanner(queueStatus?.live_preflight);
    }
    const mode = queueStatus?.queue_processor?.autorun ? t.queueAutorunOn : t.queueAutorunOff;
    el.liveStatus.textContent = `${mode} ${new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    el.liveStatus.className = "live-status";
  } catch (error) {
    el.liveStatus.textContent = t.liveError;
    el.liveStatus.className = "live-status error";
  } finally {
    state.refreshInFlight = false;
  }
}

function renderPreflightBanner(state) {
  const host = document.getElementById("preflight-banner");
  if (!host || !state) return;
  const mode = state.effective_mode;
  const warn = mode === "template_degraded" || mode === "live_requested_no_key";
  host.className = `preflight-banner ${warn ? "warn" : "ok"}`;
  host.textContent =
    mode === "template_degraded" ? "정제: 템플릿 강등 (키 있음 · 라이브 꺼짐) — 토글로 켜기"
    : mode === "live_requested_no_key" ? "정제: 라이브 요청됐으나 키 없음 — 템플릿으로 처리됨"
    : `정제: ${mode}`;
  host.hidden = false;
}

function statusLabel(status) {
  if (status === "queued") return t.statusQueued;
  if (status === "preflight_refining") return t.statusPreflightRefining;
  if (status === "planning") return t.statusPlanning;
  if (status === "routed") return t.statusRouted;
  if (status === "planning_ready") return t.statusPlanningReady;
  if (status === "prepared_not_running") return t.statusPreparedNotRunning;
  if (status === "sent_to_main") return t.statusSentToMain;
  if (status === "dispatch_ready") return t.statusDispatchReady;
  if (status === "dispatch_blocked") return t.statusDispatchBlocked;
  if (status === "closure_ready") return "종료 검토 준비";
  if (status === "waiting_claude_review") return "Claude 검토 대기";
  if (status === "waiting_browser_e2e") return "화면 E2E 대기";
  if (status === "waiting_review_and_e2e") return "검토/E2E 대기";
  if (status === "waiting_unity_rendered_evidence") return "Unity 증거 대기";
  if (status === "waiting_validator_lanes") return "검증 레인 대기";
  if (status === "worker_result_recorded") return "작업자 결과 기록됨";
  if (status === "legacy_record") return t.statusLegacyRecord;
  if (status === "archived_run") return t.statusArchivedRun;
  if (status === "passed") return "통과";
  if (status === "passed_with_limitations") return "제한부 통과";
  if (status === "checked") return "확인됨";
  if (status === "promoted") return "게이트 승격";
  if (status === "submitted") return "제출됨";
  if (status === "done") return t.statusDone;
  if (status === "blocked") return t.statusBlocked;
  if (status === "removed") return t.statusRemoved;
  if (status === "canceled") return t.statusCanceled;
  return status || t.unknown;
}

function gateStatusLabel(status) {
  if (!status) return "검토 상태 확인 필요";
  if (String(status).startsWith("ready_for_closure_review")) return "종료 검토 준비";
  if (String(status).startsWith("waiting_for_claude_or_product_review")) return "Claude/product 검토 대기";
  if (String(status).startsWith("waiting_for_browser_e2e")) return "화면 E2E 대기";
  if (status === "waiting_for_unity_rendered_evidence") return "Unity 렌더링 증거 대기";
  if (String(status).startsWith("waiting_for_review_and_browser_e2e")) return "검토/E2E 대기";
  if (status === "waiting_for_remaining_validator_lanes") return "검증 레인 대기";
  if (status === "blocked_or_needs_retry") return "차단됨/재시도 필요";
  if (status === "degraded_needs_operator_or_adapter_resolution") return "제한 상태 정리 필요";
  if (status === "waiting_for_worker_result") return "작업자 결과 대기";
  return statusLabel(status);
}

function renderTargetOptions(targets) {
  const current = el.messageTarget.value || "prompt-preflight-agent";
  const labels = {
    "prompt-preflight-agent": t.mainQueue,
    "main-orchestrator": "\uba54\uc778 \uc624\ucf00\uc2a4\ud2b8\ub808\uc774\ud130",
    "supervisor-agent": "supervisor-agent",
    "issue-memory-agent": "issue-memory-agent",
    "codex-worker": "codex-worker",
    "claude-reviewer": "claude-reviewer",
    "product-critic-agent": "product-critic-agent",
    "validator-code-level": "validator-code-level",
    "validator-ovv-product-level": "validator-ovv-product-level",
    "gemini-reviewer": "gemini-reviewer",
    html: t.viewerNote,
    thread: t.threadQueue,
  };
  const list = targets.length ? targets : Object.keys(labels);
  el.messageTarget.innerHTML = list.map((target) => `<option value="${escapeHtml(target)}">${escapeHtml(labels[target] || target)}</option>`).join("");
  el.messageTarget.value = list.includes(current) ? current : "prompt-preflight-agent";
}

function statusClass(status) {
  return String(status || "unknown").replace(/[^a-z0-9_-]/gi, "_");
}

function renderQueueStatus(payload) {
  const all = (payload?.messages || []).filter((message) => {
    const status = message.effective_status || message.latest_event?.status || "legacy_record";
    return status !== "legacy_record";
  });
  const historicalStatuses = new Set([
    "removed",
    "canceled",
    "sent_to_main",
    "dispatch_ready",
    "dispatch_blocked",
    "advance_waiting_review",
    "advance_auto_loop",
    "closure_ready",
    "waiting_claude_review",
    "waiting_browser_e2e",
    "waiting_review_and_e2e",
    "waiting_validator_lanes",
    "worker_result_recorded",
    "done",
    "failed",
    "blocked",
  ]);
  const isTrash = (message) => historicalStatuses.has(message.effective_status || message.latest_event?.status || "");
  const messages = state.showTrash ? all.filter(isTrash).slice(0, 10) : all.filter((message) => !isTrash(message));
  if (el.toggleTrash) el.toggleTrash.textContent = state.showTrash ? t.hideTrash : `${t.trash} ${all.filter(isTrash).length}`;
  if (!messages.length) {
    el.queueStatusList.innerHTML = `<p class="queue-empty">${escapeHtml(t.noMessages)}</p>`;
    return;
  }
  const recent = messages.slice(0, 8);
  el.queueStatusList.innerHTML = recent
    .map((message, index) => {
      const latest = message.latest_event || {};
      const status = message.effective_status || latest.status || "queued";
      const original = message.original_message || message.message || "";
      const runId = message.effective_run_id || latest.run_id || "";
      const events = message.queue_events || [];
      const detail = queueDetail(status, latest.detail || "");
      const canEditQueue = status === "queued";
      return `
        <article class="queue-item" data-message-id="${escapeHtml(message.id || "")}">
          <div class="queue-item-head">
            <span class="queue-status ${escapeHtml(statusClass(status))}">${escapeHtml(statusLabel(status))}</span>
            <time>${escapeHtml(formatKoreanTime(latest.timestamp || message.created_at || ""))}</time>
          </div>
          <p>${escapeHtml(original)}</p>
          <small>${escapeHtml(detail)}</small>
          ${
            canEditQueue
              ? `<div class="queue-actions">
                  <button data-queue-action="up" data-index="${index}" type="button"${index === 0 ? " disabled" : ""}>${escapeHtml(t.queueMoveUp)}</button>
                  <button data-queue-action="down" data-index="${index}" type="button"${index === recent.length - 1 ? " disabled" : ""}>${escapeHtml(t.queueMoveDown)}</button>
                  <button data-queue-action="edit" type="button">${escapeHtml(t.queueEdit)}</button>
                  <button data-queue-action="steer" type="button">${escapeHtml(t.queueSteer)}</button>
                  <button data-queue-action="remove" type="button">${escapeHtml(t.queueRemove)}</button>
                </div>`
              : `<div class="queue-actions-readonly">처리된 기록입니다. 실행 상세는 run 버튼에서 확인하세요.</div>`
          }
          ${runId ? `<button class="queue-run-link" data-run-id="${escapeHtml(runId)}" type="button">${escapeHtml(runId)}</button>` : ""}
          ${events.length ? `<div class="queue-steps">${events.map((event) => `<span>${escapeHtml(statusLabel(event.status))}</span>`).join("")}</div>` : ""}
        </article>
      `;
    })
    .join("");
  bindDetailsPersistence(el.queueStatusList);
  el.queueStatusList.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => loadRun(button.dataset.runId));
  });
  el.queueStatusList.querySelectorAll("[data-queue-action]").forEach((button) => {
    button.addEventListener("click", () => handleQueueAction(button, recent));
  });
}

function queueDetail(status, detail) {
  if (status === "prepared_not_running" || status === "planning_ready") {
    return "이전 방식으로 생성된 기록입니다. 요청은 정제된 뒤 메인 큐에 전달된 단계까지만 수행됩니다.";
  }
  return detail;
}

async function handleQueueAction(button, visibleMessages) {
  const item = button.closest("[data-message-id]");
  const id = item?.dataset.messageId || "";
  const action = button.dataset.queueAction;
  const current = visibleMessages.find((message) => message.id === id);
  if (!id || !current) return;
  button.disabled = true;
  try {
    if (action === "edit") {
      const nextText = window.prompt(t.queueEditPrompt, current.original_message || current.message || "");
      if (nextText === null) return;
      await patchJson(`/api/messages?id=${encodeURIComponent(id)}`, {
        message: nextText,
        target: current.target || "main",
        target_thread_id: current.target_thread_id || "",
        priority: current.queue_priority || 1000,
      });
    } else if (action === "remove") {
      await deleteJson(`/api/messages?id=${encodeURIComponent(id)}`);
    } else if (action === "steer") {
      const nextTarget = window.prompt(t.queueSteerPrompt, current.target || "main");
      if (nextTarget === null) return;
      await postJson("/api/messages/steer", {
        id,
        target: nextTarget,
        target_thread_id: current.target_thread_id || "",
        note: "",
      });
    } else if (action === "up" || action === "down") {
      const index = Number(button.dataset.index || 0);
      const ordered = visibleMessages.map((message) => message.id);
      const swapWith = action === "up" ? index - 1 : index + 1;
      if (swapWith < 0 || swapWith >= ordered.length) return;
      [ordered[index], ordered[swapWith]] = [ordered[swapWith], ordered[index]];
      await postJson("/api/messages/reorder", { ids: ordered });
    }
    await refreshLiveStatus();
  } finally {
    button.disabled = false;
  }
}

function renderCommandStrip(payload) {
  const host = document.getElementById("command-strip");
  if (!host) return;
  const items = payload?.work_items || [];
  const current = items.find((item) => item.status === "running") || items.find((item) => item.bucket === "active") || items[0];
  if (!current) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  const live = payload?.live_preflight?.effective_mode || "";
  const stepText = statusLabel(current.status) || current.status || "-";
  const routeText = current.route || "-";
  const blocked = current.gate_status || "";
  const blockedText = blocked || "없음";
  const nextText = current.detail || current.title || "-";
  host.hidden = false;
  host.innerHTML = `
    <span class="cs-cell"><b>단계</b> ${escapeHtml(stepText)}</span>
    <span class="cs-cell"><b>경로</b> ${escapeHtml(routeText)}</span>
    <span class="cs-cell ${blocked ? "warn" : ""}"><b>막힘</b> ${escapeHtml(blockedText)}</span>
    <span class="cs-cell"><b>정제</b> ${escapeHtml(live || "-")}</span>
    <span class="cs-cell"><b>다음</b> ${escapeHtml(nextText)}</span>`;
}

function renderWorkBoard(payload) {
  const items = payload?.work_items || [];
  const agents = payload?.agents || [];
  const active = items.filter((item) => item.bucket === "active");
  const prepared = items.filter((item) => item.bucket === "prepared");
  const archive = items.filter((item) => item.bucket === "archive").slice(0, 6);
  el.workBoard.innerHTML = `
    <div class="work-board-head">
      <div>
        <h3>${escapeHtml(t.dashboardTitle)}</h3>
        <p>${escapeHtml(t.dashboardBody)}</p>
      </div>
      <button id="requeue-historical" class="agent-chip ghost" type="button">${escapeHtml(t.requeueHistorical)}</button>
    </div>
    ${renderOperationsConsole(payload, state.selectedRun)}
    ${renderOrchestrationFlowMap(payload, state.selectedRun)}
    <div class="work-columns">
      ${renderWorkColumn(t.activeWork, active, t.noActiveWork)}
      ${renderWorkColumn(t.preparedWork, prepared, "")}
      ${renderWorkColumn(t.archivedWork, archive, "")}
    </div>
    <details${detailOpenAttr("operator-usage-guide")} data-details-key="operator-usage-guide" class="collapsible-section compact-details operator-usage">
      <summary>${escapeHtml(t.cleanGuideTitle)}</summary>
      <p>${escapeHtml(t.cleanGuide)}</p>
    </details>
    ${renderLifecycle(payload)}
    ${renderSharedWorkspace(payload)}
    <details${detailOpenAttr("work-execution-details")} data-details-key="work-execution-details" class="collapsible-section compact-details">
      <summary>${escapeHtml(t.details)}: ${escapeHtml(t.executionTitle)} / ${escapeHtml(t.agentRoster)}</summary>
      ${renderExecutionStrip(payload?.execution_environment)}
      <div class="agent-roster detail-roster">
        ${agents
          .map((agent) => `<button class="agent-chip ${escapeHtml(statusClass(agent.status))}" type="button" title="${escapeHtml(agent.detail || "")}">${escapeHtml(agent.name)} · ${escapeHtml(agentStatusLabel(agent.status, agent.id))}</button>`)
          .join("")}
      </div>
    </details>
  `;
  el.workBoard.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => loadRun(button.dataset.runId));
  });
  bindStageMap(el.workBoard);
  const requeueButton = document.getElementById("requeue-historical");
  if (requeueButton) {
    requeueButton.addEventListener("click", async () => {
      requeueButton.disabled = true;
      requeueButton.textContent = "처리 중";
      try {
        await postJson("/api/requeue-historical", {});
        await refreshLiveStatus();
      } finally {
        requeueButton.disabled = false;
        requeueButton.textContent = t.requeueHistorical;
      }
    });
  }
  bindDetailsPersistence(el.workBoard);
}

function stageStatusFromArtifacts(stage, artifacts, gateStatus, events) {
  const has = (name) => artifacts.has(name);
  const eventText = events.map((event) => `${event.speaker || ""} ${event.recipient || ""} ${event.event_type || ""}`).join(" ");
  if (stage.blockedWhen?.(gateStatus, artifacts)) return "blocked";
  if (stage.doneWhen(artifacts, gateStatus, eventText)) return "done";
  if (stage.activeWhen?.(gateStatus, artifacts, eventText)) return "active";
  return "waiting";
}

function orchestrationStages(run) {
  const gateStatus = run?.plan?.review_gate?.status || run?.plan?.main_decision?.status || "";
  const events = run?.events || [];
  const base = [
    {
      id: "raw",
      label: "원문",
      detail: "사용자 원문 보존",
      artifacts: ["orchestration-plan.json"],
      doneWhen: () => Boolean(run?.plan?.operator_message?.original_message || run?.events?.length),
    },
    {
      id: "preflight",
      label: "정제",
      detail: "Prompt Preflight Agent",
      artifacts: ["prompt-preflight.json"],
      doneWhen: (a) => a.has("prompt-preflight.json"),
    },
    {
      id: "prompt-validation",
      label: "프롬프트 검증",
      detail: "Prompt Validator / Reviewer",
      artifacts: ["prompt-validation.json"],
      doneWhen: (a) => a.has("prompt-validation.json"),
      activeWhen: (_g, _a, text) => text.includes("prompt-validator-agent"),
    },
    {
      id: "issue-memory",
      label: "이슈 메모리",
      detail: "반복 실패/리스크 검색",
      artifacts: ["issue-gate.json"],
      doneWhen: (a) => a.has("issue-gate.json"),
    },
    {
      id: "acceptance-gate",
      label: "Acceptance Gate",
      detail: "관련 이슈를 조건으로 승격",
      artifacts: ["issue-gate.json", "work-scope-acceptance.json"],
      doneWhen: (a) => a.has("issue-gate.json") && a.has("work-scope-acceptance.json"),
    },
    {
      id: "main",
      label: "메인 판단",
      detail: "목표/범위/라우팅 결정",
      artifacts: ["orchestrator-decision.json"],
      doneWhen: (a) => a.has("orchestrator-decision.json"),
    },
    {
      id: "routing",
      label: "라우팅",
      detail: "Codex/Claude/OpenAI/Gemini 경로 선택",
      artifacts: ["worker-dispatch.json", "agents-sdk-handoff-graph.json"],
      doneWhen: (a) => a.has("worker-dispatch.json") && a.has("agents-sdk-handoff-graph.json"),
    },
    {
      id: "worker",
      label: "작업자",
      detail: "Codex worker result/evidence/report pack",
      artifacts: ["worker-result.json", "d-drive-report-pack.json"],
      doneWhen: (a) => a.has("worker-result.json"),
      activeWhen: (g, a) => a.has("worker-dispatch.json") && !a.has("worker-result.json") && !String(g).includes("blocked"),
    },
    {
      id: "validators",
      label: "엄격 검증",
      detail: "3+ validator council",
      artifacts: ["validator-code-result.json", "validator-contract-result.json", "validator-ui-state-result.json", "validator-issue-gate-result.json", "validator-result.json"],
      doneWhen: (a) =>
        a.has("validator-code-result.json") &&
        a.has("validator-contract-result.json") &&
        a.has("validator-ui-state-result.json") &&
        a.has("validator-issue-gate-result.json") &&
        a.has("validator-result.json"),
    },
    {
      id: "review",
      label: "반박 검토",
      detail: "Claude/product/reviewer challenge",
      artifacts: ["supervisor-auto-review-routing.json", "product-review-result.json", "claude-review-result.json", "e2e-html-verification.json"],
      doneWhen: (a) => (a.has("product-review-result.json") || a.has("claude-review-result.json")) && a.has("e2e-html-verification.json"),
      activeWhen: (g, a) => a.has("validator-result.json") && !a.has("product-review-result.json") && !a.has("claude-review-result.json") && String(g).includes("review"),
    },
    {
      id: "closure",
      label: "Closure",
      detail: "완료/재시도/차단 판단",
      artifacts: ["review-gate.json", "closure-packet.json"],
      doneWhen: (a) => a.has("closure-packet.json"),
      activeWhen: (g, a) => a.has("review-gate.json") && String(g).startsWith("ready_for_closure_review"),
      blockedWhen: (g) => String(g).includes("blocked"),
    },
  ];
  return base;
}

function renderOrchestrationFlowMap(payload, run) {
  if (!run || !run.id) {
    return `
      <section class="stage-map loading">
        <div class="stage-map-head">
          <div>
            <h3>${escapeHtml(t.flowMapTitle)}</h3>
            <p>선택 실행을 불러오면 단계별 상태가 표시됩니다.</p>
          </div>
          <span>로딩</span>
        </div>
      </section>
    `;
  }
  const artifacts = new Set(run?.artifacts || []);
  const gateStatus = run?.plan?.review_gate?.status || run?.plan?.main_decision?.status || "";
  const events = run?.events || [];
  const stages = orchestrationStages(run).map((stage) => ({
    ...stage,
    status: stageStatusFromArtifacts(stage, artifacts, gateStatus, events),
  }));
  const first = stages.find((stage) => stage.status === "active") || stages.find((stage) => stage.status === "waiting") || stages[stages.length - 1];
  return `
    <section class="stage-map" data-stage-map>
      <div class="stage-map-head">
        <div>
          <h3>${escapeHtml(t.flowMapTitle)}</h3>
          <p>${escapeHtml(t.flowMapBody)}</p>
        </div>
        <span>${escapeHtml(gateStatusLabel(gateStatus))}</span>
      </div>
      <div class="stage-rail">
        ${stages
          .map(
            (stage, index) => `
              <button class="stage-node ${escapeHtml(stage.status)}${stage.id === first.id ? " selected" : ""}" type="button" data-stage-id="${escapeHtml(stage.id)}">
                <small>${index + 1}</small>
                <strong>${escapeHtml(stage.label)}</strong>
              </button>
            `,
          )
          .join("")}
      </div>
      <div class="stage-detail" data-stage-detail>
        ${renderStageDetail(first, artifacts, events, gateStatus)}
      </div>
    </section>
  `;
}

function renderStageDetail(stage, artifacts, events, gateStatus) {
  if (!stage) return "";
  const stageArtifacts = (stage.artifacts || []).map((name) => ({ name, exists: artifacts.has(name) }));
  const relevantEvents = (events || [])
    .filter((event) => {
      const text = `${event.speaker || ""} ${event.recipient || ""} ${event.event_type || ""} ${event.artifact || ""}`.toLowerCase();
      return text.includes(stage.id.replaceAll("-", "")) || stageArtifacts.some((item) => item.name && text.includes(item.name.toLowerCase())) || text.includes(stage.label.toLowerCase());
    })
    .slice(-5);
  return `
    <div>
      <strong>${escapeHtml(stage.label)} · ${escapeHtml(stageStatusLabel(stage.status))}</strong>
      <p>${escapeHtml(stage.detail || "")}</p>
      <p>Gate: ${escapeHtml(gateStatusLabel(gateStatus))}</p>
    </div>
    <div class="stage-artifacts">
      ${stageArtifacts.map((item) => `<span class="${item.exists ? "exists" : "missing"}">${escapeHtml(item.name)} ${item.exists ? "OK" : "대기"}</span>`).join("")}
    </div>
    ${
      relevantEvents.length
        ? `<div class="stage-events">${relevantEvents
            .map((event) => `<p><b>${escapeHtml(event.speaker || "?")}</b> → ${escapeHtml(event.recipient || "?")} · ${escapeHtml(event.event_type || "")}<br>${escapeHtml(String(event.message || "").slice(0, 180))}</p>`)
            .join("")}</div>`
        : `<p class="stage-empty">이번 실행에서 이 단계에 연결된 transcript 이벤트가 아직 없습니다.</p>`
    }
  `;
}

function stageStatusLabel(status) {
  if (status === "done") return "완료";
  if (status === "active") return "진행중";
  if (status === "blocked") return "차단";
  return "대기";
}

function bindStageMap(root) {
  const map = root.querySelector("[data-stage-map]");
  if (!map || map.dataset.bound === "1") return;
  map.dataset.bound = "1";
  const detail = map.querySelector("[data-stage-detail]");
  const artifacts = new Set(state.selectedRun?.artifacts || []);
  const events = state.selectedRun?.events || [];
  const gateStatus = state.selectedRun?.plan?.review_gate?.status || state.selectedRun?.plan?.main_decision?.status || "";
  const stages = orchestrationStages(state.selectedRun).map((stage) => ({
    ...stage,
    status: stageStatusFromArtifacts(stage, artifacts, gateStatus, events),
  }));
  map.querySelectorAll("[data-stage-id]").forEach((button) => {
    button.addEventListener("click", () => {
      map.querySelectorAll("[data-stage-id]").forEach((node) => node.classList.toggle("selected", node === button));
      const stage = stages.find((item) => item.id === button.dataset.stageId);
      if (detail) detail.innerHTML = renderStageDetail(stage, artifacts, events, gateStatus);
    });
  });
}

function renderOperationsConsole(payload, run) {
  const lifecycle = payload?.execution_lifecycle || {};
  const queueProcessor = payload?.queue_processor || {};
  const agents = payload?.agents || [];
  const plan = run?.plan || {};
  const gate = plan.review_gate || {};
  const artifacts = new Set(run?.artifacts || []);
  const loopPolicy = gate.loop_policy || plan.main_decision?.loop_policy || lifecycle.loop_policy || payload?.execution_environment?.short_loop_policy || {};
  const adapterHealth = payload?.adapter_health || payload?.execution_environment?.adapter_health || {};
  const callableAdapters = Object.values(adapterHealth).filter((item) => item && item.callable).length;
  const totalAdapters = Object.keys(adapterHealth).length;
  const activeAgents = agents.filter((agent) => agent.status === "active").length;
  const pendingAgents = agents.filter((agent) => agent.status === "pending").length;
  const availableAgents = agents.filter((agent) => agent.status === "available").length;
  const currentTitle = lifecycle.current_main_prompt?.title || run?.plan?.operator_message?.title || run?.id || t.noCurrentPrompt;
  const currentPrompt = lifecycle.current_main_prompt || {};
  const nextPrepared = lifecycle.next_prepared_prompt || {};
  const flowSubject = currentPrompt?.id ? currentPrompt : nextPrepared;
  const flow = currentFlow(flowSubject, queueProcessor);
  const reportPack = plan.d_drive_report_pack || {};
  const unityRenderedEvidence = plan.unity_rendered_evidence || {};
  const reviewArtifact = artifacts.has("claude-review-result.json")
    ? "claude-review-result.json"
    : artifacts.has("product-review-result.json")
      ? "product-review-result.json"
      : "";
  const primaryEvidence = [
    artifacts.has("closure-packet.json") ? ["closure-packet.json", "종료 packet"] : null,
    reviewArtifact ? [reviewArtifact, "실제/대체 검토"] : null,
    artifacts.has("d-drive-report-pack.json") ? ["d-drive-report-pack.json", reportPack.output_dir || "D드라이브 보고서 pack"] : null,
    artifacts.has("unity-rendered-evidence.json")
      ? [
          "unity-rendered-evidence.json",
          `${unityRenderedEvidence.ready_marker || unityRenderedEvidence.status || "Unity evidence"} · ${unityRenderedEvidence.bytes || 0} bytes`,
        ]
      : null,
  ].filter(Boolean);
  const checks = [
    ["worker-result.json", artifacts.has("worker-result.json"), "작업자"],
    ["validator-result.json", artifacts.has("validator-result.json"), "검증"],
    ["validator-issue-gate-result.json", artifacts.has("validator-issue-gate-result.json"), "이슈"],
    ["e2e-html-verification.json", artifacts.has("e2e-html-verification.json"), "화면"],
    ["claude-review-result.json", artifacts.has("claude-review-result.json") || artifacts.has("product-review-result.json"), "Claude"],
    ["d-drive-report-pack.json", artifacts.has("d-drive-report-pack.json"), "보고서"],
    ["report-pack-judgment.json", artifacts.has("report-pack-judgment.json"), "판정"],
  ];
  const validatorLanes = [
    ["validator-code-result.json", "코드"],
    ["validator-contract-result.json", "계약"],
    ["validator-ui-state-result.json", "화면상태"],
    ["validator-issue-gate-result.json", "이슈"],
  ];
  const validatorPassed = validatorLanes.filter(([artifact]) => artifacts.has(artifact)).length;
  const ready = String(gate.status || "").startsWith("ready_for_closure_review");
  const gateLabel = gateStatusLabel(gate.status || "");
  const visibleAgents = agents.filter((agent) => ["active", "pending", "available", "dispatch_blocked"].includes(agent.status)).slice(0, 8);
  return `
    <section class="ops-console">
      <div class="ops-console-main">
        <p class="eyebrow">현재 판단</p>
        <h3>명령 상태와 다음 액션</h3>
        ${renderCurrentCommandCard({
          title: currentTitle,
          currentPrompt,
          nextPrepared,
          operatorMessage: plan.operator_message || {},
          promptValidation: plan.prompt_validation || {},
          issueGate: plan.issue_gate || {},
          gate,
          ready,
          gateLabel,
          flow,
        })}
        ${
          primaryEvidence.length
            ? `<div class="ops-primary-evidence" aria-label="핵심 산출물">
                ${primaryEvidence
                  .map(
                    ([artifact, detail]) => `
                      <span title="${escapeHtml(detail)}">
                        <strong>${escapeHtml(artifact)}</strong>
                        <small>${escapeHtml(detail)}</small>
                      </span>
                    `,
                  )
                  .join("")}
              </div>`
            : ""
        }
        ${renderAdvisoryCouncil(plan, artifacts)}
        ${flow ? `<div class="ops-flow">${renderFlowSteps(flow)}</div>` : ""}
        <p class="loop-policy-line">${escapeHtml(
          `루프 정책: 목표 달성까지 짧은 iteration 반복, 결과마다 최소 ${loopPolicy.minimum_validator_lanes_per_result || 4}개 검증 레인`
        )}</p>
      </div>
      <div class="ops-metrics">
        <div class="ops-metric ${ready ? "ready" : "waiting"}">
          <span>Closure</span>
          <strong title="${escapeHtml(gate.status || "")}">${escapeHtml(gateLabel || "run 선택 필요")}</strong>
        </div>
        <div class="ops-metric">
          <span>큐</span>
          <strong>${escapeHtml(queueProcessor.autorun ? "자동 처리" : "수동 처리")}</strong>
        </div>
        <div class="ops-metric">
          <span>작업자</span>
          <strong>${activeAgents} active / ${pendingAgents} pending / ${availableAgents} ready</strong>
        </div>
        <div class="ops-metric ${validatorPassed >= validatorLanes.length ? "ready" : "waiting"}">
          <span>검증 레인</span>
          <strong>${validatorPassed}/${validatorLanes.length}</strong>
        </div>
        <div class="ops-metric ${callableAdapters ? "ready" : "waiting"}">
          <span>Adapter</span>
          <strong>${callableAdapters}/${totalAdapters || 4} 호출 가능</strong>
        </div>
      </div>
      <div class="ops-agent-strip" aria-label="현재 작업자 상태">
        <strong>${escapeHtml(t.agentOpsCompactTitle)}</strong>
        <div>
          ${
            visibleAgents.length
              ? visibleAgents
                  .map(
                    (agent) => `
                      <span class="${escapeHtml(statusClass(agent.status))}" title="${escapeHtml(agent.detail || "")}">
                        ${escapeHtml(agent.name || agent.id)} · ${escapeHtml(agentStatusLabel(agent.status, agent.id))}
                      </span>
                    `,
                  )
                  .join("")
              : `<span>${escapeHtml(t.none)}</span>`
          }
        </div>
      </div>
      <div class="ops-checks" aria-label="선택 실행 핵심 증거">
        ${checks
          .map(
            ([artifact, ok, label]) => `
              <span class="${ok ? "passed" : "missing"}" title="${escapeHtml(artifact)}">
                ${escapeHtml(label)} ${ok ? "OK" : "대기"}
              </span>
            `,
          )
          .join("")}
      </div>
      <div class="ops-validator-lanes" aria-label="결과별 검증 레인">
        ${validatorLanes
          .map(
            ([artifact, label]) => `
              <span class="${artifacts.has(artifact) ? "passed" : "missing"}" title="${escapeHtml(artifact)}">
                ${escapeHtml(label)} ${artifacts.has(artifact) ? "OK" : "대기"}
              </span>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function promptHighlights(text) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const bullets = lines
    .filter((line) => line.startsWith("- "))
    .map((line) => line.replace(/^-+\s*/, ""))
    .filter((line) => !line.toLowerCase().includes("api key"))
    .slice(0, 4);
  if (bullets.length) return bullets;
  return lines.filter((line) => !line.endsWith(":")).slice(0, 3);
}

function renderCurrentCommandCard({ title, currentPrompt, nextPrepared, operatorMessage, promptValidation, issueGate, gate, ready, gateLabel, flow }) {
  const original = operatorMessage.original_message || currentPrompt.title || nextPrepared.title || title || t.noCurrentPrompt;
  const refined = operatorMessage.refined_message || currentPrompt.message || nextPrepared.message || "";
  const status = gateLabel || statusLabel(currentPrompt.status || nextPrepared.status || "");
  const route = currentPrompt.route || currentPrompt.target || operatorMessage.handled_by || "prompt-preflight-agent";
  const runId = currentPrompt.run_id || nextPrepared.run_id || "";
  const updatedAt = currentPrompt.updated_at || nextPrepared.updated_at || gate.updated_at || "";
  const issueCount = Array.isArray(issueGate.promoted_acceptance_gates) ? issueGate.promoted_acceptance_gates.length : 0;
  const validationStatus = promptValidation.status || "확인 필요";
  const nextAction = gate.next_action || flow?.nextAction || "메시지를 넣으면 사전 검증 후 메인 오케스트레이터가 작업자와 검토자를 배정합니다.";
  const highlights = promptHighlights(refined);
  return `
    <section class="current-command-card" aria-label="현재 명령">
      <header>
        <div>
          <span>현재 명령</span>
          <strong>${escapeHtml(original)}</strong>
        </div>
        <em class="${ready ? "ready" : "waiting"}">${escapeHtml(status)}</em>
      </header>
      <div class="command-meta">
        <span>경로: ${escapeHtml(route)}</span>
        <span>검증: ${escapeHtml(statusLabel(validationStatus))}</span>
        <span>승격 이슈: ${escapeHtml(String(issueCount))}</span>
        ${runId ? `<span>run: ${escapeHtml(runId)}</span>` : ""}
        ${updatedAt ? `<span>${escapeHtml(formatKoreanTime(updatedAt))}</span>` : ""}
      </div>
      <div class="command-next">
        <span>다음 액션</span>
        <p>${escapeHtml(nextAction)}</p>
      </div>
      ${
        highlights.length
          ? `<div class="command-highlights">
              <span>정제 프롬프트 핵심</span>
              <ul>${highlights.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
            </div>`
          : ""
      }
      ${
        refined
          ? `<details class="command-refined">
              <summary>정제 프롬프트 전체 보기</summary>
              <pre>${escapeHtml(refined)}</pre>
            </details>`
          : ""
      }
    </section>
  `;
}

function renderAdvisoryCouncil(plan, artifacts) {
  const council = plan?.main_advisory_council || {};
  const deliberation = plan?.cerberus_deliberation || {};
  if (!council || !council.final_owner) {
    return `
      <div class="ops-advisory missing">
        <header><strong>메인 판단 보좌관</strong><span>아직 없음</span></header>
        <p>새 run 또는 다음 advance에서 Claude 판단 보좌관과 OpenAI/Codex API 보좌관 계약이 생성되어야 합니다.</p>
      </div>
    `;
  }
  const advisors = Array.isArray(council.advisors) ? council.advisors : [];
  const rounds = Array.isArray(deliberation.rounds) ? deliberation.rounds : [];
  const queueDecision = council.queue_routing_decision || plan?.queue_routing_decision || {};
  return `
    <div class="ops-advisory">
      <header>
        <strong>메인 판단 보좌관</strong>
        <span>최종 결정: ${escapeHtml(council.final_owner || "main-orchestrator")}</span>
      </header>
      <p>${escapeHtml(council.final_owner_rule || "보좌관은 반박과 구조화 판단을 공급하고 최종 판단은 메인이 기록합니다.")}</p>
      ${
        rounds.length
          ? `<div class="ops-deliberation">
              <strong>케르베로스 숙의 ${rounds.length}라운드</strong>
              ${rounds
                .slice(0, 4)
                .map((round) => {
                  const messages = Array.isArray(round.messages) ? round.messages : [];
                  return `
                    <section>
                      <span>Round ${escapeHtml(String(round.round || ""))} · ${escapeHtml(round.topic || "")}</span>
                      ${messages.slice(0, 3).map((msg) => `<p><b>${escapeHtml(msg.speaker || "")}</b>: ${escapeHtml(msg.message || "")}</p>`).join("")}
                    </section>
                  `;
                })
                .join("")}
            </div>`
          : `<p class="ops-deliberation-empty">숙의 라운드 artifact가 아직 없습니다. 다음 advance에서 cerberus-deliberation.json이 생성되어야 합니다.</p>`
      }
      <div class="ops-advisor-grid">
        ${advisors
          .map((advisor) => {
            const requestOk = advisor.required_artifact ? artifacts.has(advisor.required_artifact) : false;
            const resultOk = advisor.result_artifact ? artifacts.has(advisor.result_artifact) : false;
            const cls = resultOk ? "ready" : requestOk ? "waiting" : "missing";
            return `
              <article class="${cls}">
                <strong>${escapeHtml(advisor.agent || "")}</strong>
                <span>${escapeHtml(advisor.route || "")} · ${escapeHtml(advisor.status || "")}</span>
                <small>${escapeHtml(advisor.result_artifact || advisor.required_artifact || "")} ${resultOk ? "결과 있음" : requestOk ? "요청 준비" : "대기"}</small>
              </article>
            `;
          })
          .join("")}
      </div>
      <div class="ops-queue-decision">
        <span>큐 판정</span>
        <strong>${escapeHtml(queueDecision.mode || "확인 필요")}</strong>
        <p>${escapeHtml(queueDecision.reason || "순차 작업인지 steering인지 메인 보좌관 council이 판단해야 합니다.")}</p>
      </div>
    </div>
  `;
}

function renderSharedWorkspace(payload) {
  const personas = payload?.agent_personas || {};
  const lanes = payload?.review_lanes || [];
  const shared = payload?.shared_workspace || {};
  const sdk = payload?.agents_sdk_pattern || {};
  const sdkManifest = payload?.agents_sdk_manifest || {};
  const mainContext = payload?.main_orchestrator_context || {};
  const concepts = sdk?.contract?.concepts || [];
  const sdkAlt = sdk?.alternative_runtimes || [];
  const personaEntries = Object.entries(personas);
  return `
    <details${detailOpenAttr("shared-workspace")} data-details-key="shared-workspace" class="collapsible-section shared-workspace">
      <summary>${escapeHtml(t.sharedWorkspaceTitle)}: ${personaEntries.length} agents / ${lanes.length} review lanes</summary>
      <div class="shared-grid">
        <section>
          <h4>${escapeHtml(t.agentIdentityTitle)}</h4>
          ${personaEntries
            .map(([id, persona]) => `
              <article class="identity-card">
                <strong>${escapeHtml(persona.name || id)} ${persona.review_only ? `· ${escapeHtml(t.reviewOnly)}` : ""}</strong>
                <span>${escapeHtml(id)} · ${escapeHtml(persona.route || "")}</span>
                <p>${escapeHtml(persona.identity || "")}</p>
                <small>${escapeHtml((persona.must_read || []).join(" / "))}</small>
              </article>
            `)
            .join("")}
        </section>
        <section>
          <h4>${escapeHtml(t.reviewLanesTitle)}</h4>
          ${lanes
            .map((lane) => `
              <article class="identity-card review-lane">
                <strong>${escapeHtml(lane.name || lane.id)}</strong>
                <span>${escapeHtml(lane.owner || "")} · ${escapeHtml(lane.state || "")}</span>
                ${lane.thread_id ? `<small>${escapeHtml(lane.thread_id)}</small>` : ""}
                <p>${escapeHtml(lane.rule || "")}</p>
              </article>
            `)
            .join("")}
          <h4>${escapeHtml(t.sharedSourcesTitle)}</h4>
          <div class="shared-source-list">
            ${(shared.source_of_truth || []).map((source) => `<span>${escapeHtml(source)}</span>`).join("")}
          </div>
          <h4>${escapeHtml(t.mainContextTitle)}</h4>
          <div class="sdk-pattern-list main-context-list">
            <span>소유자: ${escapeHtml(mainContext.owner || "main-orchestrator")}</span>
            <span>active ${escapeHtml(String(mainContext.current_load?.active ?? 0))} / prepared ${escapeHtml(String(mainContext.current_load?.prepared ?? 0))}</span>
            <span>SDK pattern required: ${escapeHtml(String(mainContext.agents_sdk_usage?.pattern_required ?? true))}</span>
            <span>live SDK importable: ${escapeHtml(String(mainContext.agents_sdk_usage?.live_sdk_importable ?? false))}</span>
            <span>handoffs ${escapeHtml(String(mainContext.agents_sdk_usage?.handoffs ?? 0))} / guardrails ${escapeHtml(String(mainContext.agents_sdk_usage?.guardrails ?? 0))} / tools ${escapeHtml(String(mainContext.agents_sdk_usage?.tools ?? 0))}</span>
            ${(mainContext.must_read_before_dispatch || []).map((item) => `<span>읽기: ${escapeHtml(item)}</span>`).join("")}
          </div>
          <h4>${escapeHtml(t.dispatchContractTitle)}</h4>
          <div class="shared-source-list">
            ${(mainContext.dispatch_contract || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          </div>
          <h4>${escapeHtml(t.sdkPatternTitle)}</h4>
          <div class="sdk-pattern-list">
            <span>SDK 설치: ${escapeHtml(String(sdk.installed ?? false))}</span>
            <span>SDK import 가능: ${escapeHtml(String(sdk.importable ?? false))}</span>
            <span>기본 라이브 호출: ${escapeHtml(String(sdk.live_call_default ?? false))}</span>
            <span>Python: ${escapeHtml(String(sdk.runtime?.python || "확인 필요"))}</span>
            <span>Agent manifest: ${escapeHtml(String((sdkManifest.agents || []).length))}</span>
            <span>Handoff manifest: ${escapeHtml(String((sdkManifest.handoffs || []).length))}</span>
            <span>Guardrail manifest: ${escapeHtml(String((sdkManifest.guardrails || []).length))}</span>
            <span>Tool manifest: ${escapeHtml(String((sdkManifest.tools || []).length))}</span>
            ${sdkAlt.map((runtime) => `<span>대체 런타임 ${escapeHtml(runtime.runtime || "")}: import ${escapeHtml(String(runtime.importable ?? false))}</span>`).join("")}
            ${sdk.import_error ? `<span class="warn">import 오류: ${escapeHtml(sdk.import_error)}</span>` : ""}
            ${concepts.map((concept) => `<span>${escapeHtml(concept.id)} → ${escapeHtml(concept.local_mapping || "")}</span>`).join("")}
          </div>
        </section>
      </div>
    </details>
  `;
}

function renderLifecycle(payload) {
  const lifecycle = payload?.execution_lifecycle || {};
  const current = lifecycle?.current_main_prompt || {};
  const nextPrepared = lifecycle?.next_prepared_prompt || {};
  const roster = payload?.agents || [];
  const sdk = payload?.agents_sdk_pattern || {};
  const sdkManifest = payload?.agents_sdk_manifest || {};
  const mainContext = payload?.main_orchestrator_context || {};
  const queueProcessor = payload?.queue_processor || {};
  const flowSubject = current?.id ? current : nextPrepared;
  const flow = currentFlow(flowSubject, queueProcessor);
  return `
    <details${detailOpenAttr("lifecycle-details")} data-details-key="lifecycle-details" class="collapsible-section compact-details lifecycle-details">
      <summary>${escapeHtml(t.details)}: ${escapeHtml(t.lifecycleTitle)} / ${escapeHtml(t.agentOperationsTitle)}</summary>
    <section class="lifecycle-strip">
      <div>
        <h4>${escapeHtml(t.lifecycleTitle)}</h4>
        <strong>${escapeHtml(t.currentPrompt)}</strong>
        ${current.status ? `<span class="current-status-badge ${escapeHtml(statusClass(current.status))}">${escapeHtml(statusLabel(current.status))}</span>` : ""}
        <p>${escapeHtml(current.title || t.noCurrentPrompt)}</p>
        ${nextPrepared?.title ? `<strong>${escapeHtml(t.nextPreparedPrompt)}</strong><p>${escapeHtml(nextPrepared.title)}</p>` : ""}
        <div class="flow-panel">
          <h4>${escapeHtml(t.flowTitle)}</h4>
          ${flow ? renderFlowSteps(flow) : `<p>${escapeHtml(t.flowEmpty)}</p>`}
        </div>
        <div class="flow-panel">
          <h4>${escapeHtml(t.queueProcessorState)}</h4>
          <p>${escapeHtml(queueProcessor.enabled ? (queueProcessor.autorun ? t.queueAutorunOn : t.queueAutorunOff) : t.routeDisabled)}</p>
          <p>max per tick: ${escapeHtml(String(queueProcessor.max_per_tick || 0))}</p>
          <p>${escapeHtml(queueProcessor.status_file || "")}</p>
        </div>
      </div>
      <div>
        ${renderSdkStatus(sdk, sdkManifest, mainContext)}
        ${renderAgentOperations(roster)}
        ${flow ? `<div class="next-action"><strong>${escapeHtml(t.nextActionTitle)}</strong><p>${escapeHtml(flow.nextAction)}</p></div>` : ""}
      </div>
    </section>
    </details>
  `;
  bindDetailsPersistence(el.knowledgeHub);
}

function renderSdkStatus(sdk, sdkManifest, mainContext = {}) {
  return `
    <section class="sdk-status-panel">
      <div>
        <h4>${escapeHtml(t.sdkStatusTitle)}</h4>
        <p>${escapeHtml(t.sdkUsePolicy)}</p>
      </div>
      <div class="sdk-status-metrics">
        <span>import ${escapeHtml(String(sdk.importable ?? false))}</span>
        <span>live default ${escapeHtml(String(sdk.live_call_default ?? false))}</span>
        <span>agents ${(sdkManifest.agents || []).length}</span>
        <span>handoffs ${(sdkManifest.handoffs || []).length}</span>
        <span>guardrails ${(sdkManifest.guardrails || []).length}</span>
        <span>owner ${escapeHtml(mainContext.owner || "main-orchestrator")}</span>
      </div>
    </section>
  `;
}

function renderAgentOperations(agents) {
  if (!agents.length) return "";
  const groups = [
    { key: "active", title: t.agentGroupActive, items: agents.filter((agent) => agent.status === "active") },
    { key: "pending", title: t.agentGroupPending, items: agents.filter((agent) => agent.status === "pending") },
    { key: "available", title: t.agentGroupAvailable, items: agents.filter((agent) => agent.status === "available") },
    { key: "disabled", title: t.agentGroupDisabled, items: agents.filter((agent) => !["active", "pending", "available"].includes(agent.status)) },
  ];
  return `
    <div class="agent-ops">
      <h4>${escapeHtml(t.agentOperationsTitle)}</h4>
      <div class="agent-lane-grid">
        ${groups
          .map((group) => `
            <section class="agent-lane ${escapeHtml(group.key)}">
              <header>
                <strong>${escapeHtml(group.title)}</strong>
                <span>${group.items.length}</span>
              </header>
              ${
                group.items.length
                  ? group.items.map((agent) => renderAgentCard(agent)).join("")
                  : `<p class="agent-lane-empty">${escapeHtml(t.none)}</p>`
              }
            </section>
          `)
          .join("")}
      </div>
    </div>
  `;
}

function renderAgentCard(agent) {
  const activeCount = Number(agent.active_count || 0);
  const preparedCount = Number(agent.prepared_count || 0);
  return `
    <article class="agent-ops-card ${escapeHtml(statusClass(agent.status))}">
      <div>
        <span class="queue-status ${escapeHtml(statusClass(agent.status))}">${escapeHtml(agentStatusLabel(agent.status, agent.id))}</span>
        <strong>${escapeHtml(agent.name || agent.id)}</strong>
      </div>
      <small>${escapeHtml(agent.model || "")}</small>
      <p>${escapeHtml(agent.detail || "")}</p>
      <footer>
        <span>${escapeHtml(t.agentCardActive)} ${activeCount}</span>
        <span>${escapeHtml(t.agentCardPrepared)} ${preparedCount}</span>
      </footer>
    </article>
  `;
}

function currentFlow(current, queueProcessor) {
  if (!current || !current.id) return null;
  const events = current.events || [];
  const statuses = new Set(events.map((event) => event.status));
  const currentStatus = current.status || "queued";
  const steps = [
    { id: "queued", label: t.flowQueued, done: statuses.has("queued") || currentStatus === "queued" },
    { id: "preflight_refining", label: t.flowPreflight, done: statuses.has("preflight_refining") || currentStatus === "preflight_refining" },
    { id: "sent_to_main", label: t.flowMain, done: statuses.has("sent_to_main") || currentStatus === "sent_to_main" || currentStatus === "prepared_not_running" },
    { id: "dispatch", label: t.flowDispatch, done: ["dispatch_ready", "dispatch_blocked", "running", "reviewing", "done"].includes(currentStatus) },
    { id: "review", label: t.flowReview, done: ["reviewing", "done"].includes(currentStatus) },
  ];
  let nextAction = "큐 프로세서가 자동으로 사전 검증 후 메인 큐 기록을 만듭니다.";
  if (currentStatus === "queued" && queueProcessor.autorun === false) {
    nextAction = "자동 처리가 꺼져 있습니다. 오른쪽의 다음 처리를 누르면 사전 검증과 메인 전달이 진행됩니다.";
  } else if (currentStatus === "queued") {
    nextAction = "자동 처리가 켜져 있습니다. 잠시 후 사전 검증과 메인 전달 이벤트가 붙어야 합니다.";
  } else if (currentStatus === "preflight_refining") {
    nextAction = "프롬프트 검증/정제 중입니다. 완료되면 메인 큐 전달 이벤트와 run id가 생깁니다.";
  } else if (currentStatus === "sent_to_main" || currentStatus === "prepared_not_running") {
    nextAction = "메인 큐 기록은 만들어졌습니다. 아직 실제 Codex/Claude worker 자동 dispatch는 켜져 있지 않습니다.";
  } else if (currentStatus === "dispatch_ready") {
    nextAction = "메인 오케스트레이터가 Codex/Claude 구독 작업자에게 줄 dispatch 계약을 만들었습니다. worker-result.json과 review-gate 증거가 다음 완료 조건입니다.";
  } else if (currentStatus === "dispatch_blocked") {
    nextAction = "메인 오케스트레이터가 worker 배정과 증거 계약을 만들었지만 실제 worker connector가 없어 차단 상태입니다.";
  } else if (currentStatus === "canceled") {
    nextAction = "운영자가 취소한 항목입니다. 다시 하려면 새 메시지로 넣거나 재큐잉해야 합니다.";
  }
  return {
    currentStatus,
    runId: current.run_id || "",
    updatedAt: current.updated_at || "",
    detail: current.detail || "",
    steps,
    nextAction,
  };
}

function renderFlowSteps(flow) {
  return `
    <div class="flow-steps">
      ${flow.steps.map((step) => `<span class="${step.done ? "done" : ""}">${escapeHtml(step.label)}</span>`).join("")}
    </div>
    <p>${escapeHtml(flow.detail || statusLabel(flow.currentStatus))}</p>
    ${flow.runId ? `<button class="queue-run-link" data-run-id="${escapeHtml(flow.runId)}" type="button">${escapeHtml(flow.runId)}</button>` : ""}
  `;
}

function renderExecutionStrip(env) {
  const scope = env?.automatic_scope || "";
  return `
    <section class="execution-strip">
      <div class="execution-title">
        <strong>${escapeHtml(t.executionTitle)}</strong>
        <span>${escapeHtml(t.executionNoWorkers)}</span>
      </div>
      <div class="execution-item">
        <span>${escapeHtml(t.executionServer)}</span>
        <strong>${escapeHtml(env?.viewer_url || "http://127.0.0.1:8766")}</strong>
      </div>
      <div class="execution-item">
        <span>${escapeHtml(t.executionEntrypoint)}</span>
        <strong>${escapeHtml(env?.server_entrypoint || "viewer_server.py")}</strong>
      </div>
      <div class="execution-item">
        <span>${escapeHtml(t.executionScope)}</span>
        <strong>${escapeHtml(scope || t.executionOpenAiOnly)}</strong>
      </div>
      <div class="execution-item wide">
        <span>${escapeHtml(t.executionStateDir)}</span>
        <strong>${escapeHtml(env?.state_directory || "")}</strong>
      </div>
    </section>
  `;
}

function agentStatusLabel(status, id) {
  if (status === "available") return t.routeAvailable;
  if (status === "disabled") return t.routeDisabled;
  if (id === "openai_agents_sdk" && status === "idle") return t.executionOpenAiOnly;
  if (status === "active") return t.routeActive;
  if (status === "pending") return t.routePending;
  if (status === "idle") return t.routeIdle;
  return status || t.unknown;
}

function renderWorkColumn(title, items, emptyText) {
  return `
    <section class="work-column">
      <h4>${escapeHtml(title)} <span>${items.length}</span></h4>
      ${
        items.length
          ? items
              .slice(0, 5)
              .map((item) => {
                const disabled = item.run_id ? "" : " disabled";
                return `
                  <button class="work-item" data-run-id="${escapeHtml(item.run_id || "")}" type="button"${disabled}>
                    <span class="queue-status ${escapeHtml(statusClass(item.status))}">${escapeHtml(statusLabel(item.status))}</span>
                    <strong>${escapeHtml(item.title || item.id)}</strong>
                    <small>${escapeHtml(item.detail || item.route || "")}</small>
                  </button>
                `;
              })
              .join("")
          : `<p class="work-empty">${escapeHtml(emptyText || t.none)}</p>`
      }
    </section>
  `;
}

function renderMilestones(payload) {
  if (!el.milestones) return;
  const lifecycle = payload?.execution_lifecycle || {};
  const running = Number(lifecycle.running_count || 0);
  const prepared = Number(lifecycle.prepared_count || 0);
  const sdk = payload?.agents_sdk_pattern || {};
  const issueMemory = payload?.issue_memory || {};
  const permissionRiskCount = (issueMemory.permission_risks || []).length;
  const selectedPlan = state.selectedRun?.plan || {};
  const selectedArtifacts = new Set(state.selectedRun?.artifacts || []);
  const selectedGate = state.selectedRun?.plan?.review_gate || {};
  const closureReady = String(selectedGate.status || "").startsWith("ready_for_closure_review");
  const council = selectedPlan.main_advisory_council || {};
  const advisorCount = Array.isArray(council.advisors) ? council.advisors.length : 0;
  const hasAdvisoryCouncil =
    selectedArtifacts.has("main-advisory-council.json") &&
    selectedArtifacts.has("claude-advisor-request.md") &&
    selectedArtifacts.has("openai-codex-advisor-request.json");
  const queueDecision = selectedPlan.queue_routing_decision || council.queue_routing_decision || {};
  const hasQueueDecision = selectedArtifacts.has("queue-routing-decision.json") && Boolean(queueDecision.mode);
  const hasWorkerLoop =
    selectedArtifacts.has("worker-result.json") &&
    selectedArtifacts.has("validator-code-result.json") &&
    selectedArtifacts.has("validator-contract-result.json") &&
    selectedArtifacts.has("validator-ui-state-result.json") &&
    selectedArtifacts.has("validator-issue-gate-result.json");
  const reviewIterationCount = [...selectedArtifacts].filter((artifact) => artifact.startsWith("review-iteration-") && artifact.endsWith(".json")).length;
  const hasSharedIssueGate = selectedArtifacts.has("issue-gate.json") && selectedArtifacts.has("validator-issue-gate-result.json");
  const hasBrowserEvidence = selectedArtifacts.has("e2e-html-verification.json") && selectedArtifacts.has("e2e-dashboard-screenshot.png");
  const hasClaudeClosure = selectedArtifacts.has("claude-review-result.json") && closureReady;
  const milestones = [
    {
      priority: "P0",
      title: "메인 판단 보좌관 2명 강제",
      status: hasAdvisoryCouncil ? `${advisorCount}/2 계약됨` : "누락",
      why: "메인은 1명이 최종 판단하되 Claude와 OpenAI/Codex API가 같은 시점에 반박/구조화 판단을 보좌해야 하위 세션 느낌이 줄어듭니다.",
      evidence: hasAdvisoryCouncil ? "main-advisory-council.json, claude-advisor-request.md, openai-codex-advisor-request.json" : "선택 run에 advisory council artifact 필요",
      next: hasAdvisoryCouncil ? "실제 advisor 결과 artifact 연결과 live 호출 가능 상태를 계속 노출" : "다음 advance 또는 새 run 생성으로 council artifact 생성",
    },
    {
      priority: "P0",
      title: "큐 순차/스티어링 판정",
      status: hasQueueDecision ? queueDecision.mode : "판정 없음",
      why: "큐가 쌓였을 때 새 작업으로 순차 처리할지, 현재 목표를 바꾸는 steering으로 끼워 넣을지 메인이 판단해야 합니다.",
      evidence: hasQueueDecision ? "queue-routing-decision.json이 선택 run에 연결됨" : "큐 메시지마다 queue-routing-decision.json 필요",
      next: hasQueueDecision ? queueDecision.reason || "판정 사유를 유지" : "큐 프로세서가 메시지 처리 전에 steering 여부를 기록",
    },
    {
      priority: "P0",
      title: "실제 worker dispatch 연결",
      status: hasWorkerLoop ? `검증됨 · 반복 ${reviewIterationCount}회` : running > 0 ? "진행중" : prepared > 0 ? "대기/미연결" : "대기 없음",
      why: "메인 큐에 전달된 뒤 실제 Codex/Claude 작업자가 움직여야 작업장입니다.",
      evidence: hasWorkerLoop ? `선택 run에 worker-result, 4개 validator lane, review-iteration ${reviewIterationCount}개가 있음` : "run transcript에 main-orchestrator -> codex/claude 실제 호출과 worker 응답이 기록됨",
      next: hasWorkerLoop && reviewIterationCount >= 3 ? "반복 검증 기준 충족. blocker가 없을 때만 closure 판단 가능" : hasWorkerLoop ? "최소 3회 review-iteration이 쌓일 때까지 advance 반복" : prepared > 0 ? "메인 대기 항목을 실제 worker adapter로 넘기고 결과를 transcript에 저장" : "새 큐 항목 발생 시 dispatch 계약 검증",
    },
    {
      priority: "P0",
      title: "이슈 메모리 즉시 공유",
      status: hasSharedIssueGate ? "검증됨" : permissionRiskCount ? "권한 리스크" : "기록 가능",
      why: "같은 실패를 다른 모델/작업자가 반복하지 않게 하는 핵심 장치입니다.",
      evidence: hasSharedIssueGate ? "issue-gate.json과 validator-issue-gate-result.json이 선택 run의 closure gate에 연결됨" : "memory/issues_log와 viewer 이슈/공유정보 탭에 발견/해결/방지책이 동시에 보임",
      next: hasSharedIssueGate ? "반복 이슈가 생기면 즉시 discovered/resolved와 gate 승격을 유지" : permissionRiskCount ? "권한 실패 항목을 운영 리스크로 고정하고 state 파일 권한을 정리" : "최근 이슈를 다음 worker 입력에 자동 포함",
    },
    {
      priority: "P0",
      title: "홈 화면 정보 구조 정리",
      status: closureReady ? "검증됨" : "개선중",
      why: "상태, 대화, 기록, 라우팅, 공유정보가 섞이면 운영자가 다음 결정을 못 합니다.",
      evidence: closureReady ? "상태 탭 운영 콘솔에서 closure/evidence/작업자 상태가 즉시 표시됨" : "각 탭이 단일 목적을 갖고 Playwright에서 탭 전환/내용 표시가 검증됨",
      next: "상태 탭은 결론/다음 행동, 대화 탭은 왕복 대화, 기록 탭은 원본 로그로 유지",
    },
    {
      priority: "P0",
      title: "화면 E2E와 closure review",
      status: hasBrowserEvidence && hasClaudeClosure ? "검증됨" : hasBrowserEvidence ? "Claude 대기" : "증거 필요",
      why: "사용자가 로그를 뒤지지 않고 HTML에서 실제 진행 상태를 믿을 수 있어야 합니다.",
      evidence: hasBrowserEvidence ? "e2e-html-verification.json, DOM snapshot, screenshot hash가 선택 run에 있음" : "브라우저 검증 artifact 필요",
      next: hasClaudeClosure ? "다음 작업 프롬프트를 넣고 진행 상태를 관찰" : "화면 E2E와 Claude 검토를 실행",
    },
    {
      priority: "P1",
      title: "Agents SDK 적극 사용 기준 명확화",
      status: sdk.importable ? "사용 가능" : "확인 필요",
      why: "API를 무조건 피하는 게 아니라 handoff/guardrail/trace/eval에 맞게 써야 합니다.",
      evidence: "SDK import 가능, manifest/guardrail/handoff 수, 사용 조건이 라우팅 탭과 상태 탭에 표시됨",
      next: "작은 구조화 판단이나 trace-ready 기록이 필요한 run에서 SDK 사용 이벤트를 남김",
    },
    {
      priority: "P1",
      title: "큐 조작 기능 검증",
      status: "검증됨",
      why: "편집/제거/취소/휴지통/다음 처리 버튼이 의미 없이 있으면 안 됩니다.",
      evidence: "smoke_test_viewer.py가 html 대상 테스트 메시지로 편집/스티어/재정렬/취소/제거 API를 실제 HTTP로 검증하고, Playwright DOM에서 버튼/휴지통/접힘 보존을 확인",
      next: "다음 실제 작업 프롬프트에서도 큐가 맨 위 1개씩 처리되고 취소/제거가 화면에 즉시 반영되는지 계속 관찰",
    },
    {
      priority: "P2",
      title: "Gemini 및 추가 검토 레인",
      status: "키 대기",
      why: "세 번째 관점 검토는 유용하지만 기본 운영 경로가 안정된 뒤 붙이는 게 맞습니다.",
      evidence: "Gemini 키/로그인 상태와 실제 검토 transcript가 표시됨",
      next: "키 제공 후 provider_routing에서 활성화하고 reviewer lane에 연결",
    },
  ];
  el.milestones.innerHTML = `
    <div class="section-heading">
      <div>
        <p class="eyebrow">${escapeHtml(t.milestonesTitle)}</p>
        <h3>${escapeHtml(t.milestonesSubtitle)}</h3>
      </div>
      <span>${milestones.length}${escapeHtml(t.countSuffix)}</span>
    </div>
    <div class="milestone-grid">
      ${milestones.map((item) => renderMilestoneCard(item)).join("")}
    </div>
  `;
}

function renderMilestoneCard(item) {
  return `
    <article class="milestone-card ${escapeHtml(item.priority.toLowerCase())}">
      <header>
        <span>${escapeHtml(item.priority)}</span>
        <strong>${escapeHtml(item.title)}</strong>
      </header>
      <dl>
        <dt>${escapeHtml(t.status)}</dt><dd>${escapeHtml(item.status)}</dd>
        <dt>${escapeHtml(t.why)}</dt><dd>${escapeHtml(item.why)}</dd>
        <dt>${escapeHtml(t.evidence)}</dt><dd>${escapeHtml(item.evidence)}</dd>
        <dt>${escapeHtml(t.nextAction)}</dt><dd>${escapeHtml(item.next)}</dd>
      </dl>
    </article>
  `;
}

function renderIssueImport(issueImport) {
  if (!issueImport?.available) {
    return `
      <section class="issue-import-panel">
        <h4>작업 관련 이슈</h4>
        <p>${escapeHtml(issueImport?.message || "통합 이슈 인덱스가 아직 없습니다.")}</p>
      </section>
    `;
  }
  const summary = issueImport.summary || {};
  const topRelevant = issueImport.top_relevant || [];
  const agentViews = issueImport.agent_views || [];
  return `
    <section class="issue-import-panel">
      <div class="issue-import-head">
        <div>
          <h4>작업 관련 이슈</h4>
          <p>전체 기록을 그대로 보여주는 곳이 아니라, 현재 작업과 각 에이전트 역할에 걸릴 만한 반복 실패를 우선순위로 뽑습니다.</p>
        </div>
        <div class="issue-import-metrics">
          <span>원 후보 ${escapeHtml(String(summary.raw_candidate_count || 0))}</span>
          <span>대표 ${escapeHtml(String(summary.unique_issue_count || 0))}</span>
          <span>중복 ${escapeHtml(String(summary.duplicate_candidate_count || 0))}</span>
          <span>열림 ${escapeHtml(String(summary.open_or_review_count || 0))}</span>
        </div>
      </div>
      <div class="issue-import-paths">
        <span>전체: ${escapeHtml(issueImport.index_path || "")}</span>
        <span>화면용: ${escapeHtml(issueImport.compact_index_path || "")}</span>
        <span>${escapeHtml(issueImport.markdown_path || "")}</span>
      </div>
      <div class="issue-relevance-grid">
        <section>
          <h5>현재 작업 기준 상위 이슈</h5>
          ${renderIssueList(topRelevant)}
        </section>
        <section>
          <h5>에이전트별 사전 체크</h5>
          <div class="agent-issue-list">
            ${agentViews
              .slice(0, 8)
              .map(
                (view) => `
                  <details${detailOpenAttr(`agent-issues-${view.agent}`)} data-details-key="agent-issues-${escapeHtml(view.agent)}" class="agent-issue-group">
                    <summary>${escapeHtml(view.agent)} · ${escapeHtml(String(view.issue_count || 0))}개 후보</summary>
                    ${renderIssueList(view.issues || [])}
                  </details>
                `
              )
              .join("")}
          </div>
        </section>
      </div>
    </section>
  `;
}

function renderIssueList(issues) {
  if (!issues.length) return `<p class="muted-small">${escapeHtml(t.none)}</p>`;
  return issues
    .slice(0, 12)
    .map(
      (issue) => `
        <article class="issue-hit ${escapeHtml(issue.severity || "normal")}">
          <header>
            <strong>${escapeHtml(issue.id || "")} ${escapeHtml(issue.title || "")}</strong>
            <span>${escapeHtml(issue.severity || "")} · score ${escapeHtml(String(issue.score || 0))}</span>
          </header>
          <p>${escapeHtml(issue.snippet || "")}</p>
          <small>${escapeHtml(issue.first_source?.file || "")}:${escapeHtml(String(issue.first_source?.line || ""))} · 중복 ${escapeHtml(String(issue.duplicate_count || 0))}</small>
        </article>
      `
    )
    .join("");
}

function renderSelectedIssueGate(run) {
  const issueGate = run?.plan?.issue_gate || {};
  const gates = Array.isArray(issueGate.promoted_acceptance_gates) ? issueGate.promoted_acceptance_gates : [];
  if (!Object.keys(issueGate).length) {
    return `
      <section class="issue-import-panel selected-issue-gate">
        <h4>선택 run 이슈 게이트</h4>
        <p class="muted-small">선택한 실행에 issue-gate.json이 아직 연결되지 않았습니다.</p>
      </section>
    `;
  }
  return `
    <section class="issue-import-panel selected-issue-gate">
      <div class="issue-import-head">
        <div>
          <h4>선택 run 이슈 게이트</h4>
          <p>이 실행의 worker/reviewer가 closure 전에 반드시 다시 확인해야 하는 반복 실패 방지 조건입니다.</p>
        </div>
        <div class="issue-import-metrics">
          <span>${escapeHtml(issueGate.status || "확인 필요")}</span>
          <span>승격 ${escapeHtml(String(gates.length))}</span>
          <span>closure 전 필수 ${issueGate.required_before_closure ? "예" : "아니오"}</span>
        </div>
      </div>
      <div class="issue-relevance-grid">
        ${gates
          .slice(0, 8)
          .map(
            (gate) => `
              <article class="issue-hit high">
                <header>
                  <strong>${escapeHtml(gate.source_issue || "")} ${escapeHtml(gate.title || "")}</strong>
                  <span>승격된 이슈 게이트</span>
                </header>
                <p>${escapeHtml(gate.gate || "")}</p>
                <small>통과 기준: ${(gate.binary_pass_criteria || []).map(escapeHtml).join(" · ")}</small>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderKnowledgeHub(payload) {
  if (!el.knowledgeHub) return;
  const shared = payload?.shared_workspace || {};
  const issueMemory = payload?.issue_memory || {};
  const issueImport = payload?.issue_import || {};
  const mainContext = payload?.main_orchestrator_context || {};
  const recent = issueMemory.recent || [];
  const permissionRisks = issueMemory.permission_risks || [];
  el.knowledgeHub.innerHTML = `
    <div class="section-heading">
      <div>
        <p class="eyebrow">${escapeHtml(t.knowledgeTitle)}</p>
        <h3>${escapeHtml(t.knowledgeSubtitle)}</h3>
      </div>
      <span>${escapeHtml(issueMemory.issue_table_state_status || "확인 필요")}</span>
    </div>
    <div class="knowledge-grid">
      <section class="knowledge-card">
        <h4>${escapeHtml(t.workerReadOrder)}</h4>
        ${(issueMemory.worker_read_order || shared.source_of_truth || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </section>
      <section class="knowledge-card">
        <h4>${escapeHtml(t.originalRequirements)}</h4>
        ${(issueMemory.original_operator_requirements || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </section>
      <section class="knowledge-card risk">
        <h4>${escapeHtml(t.permissionRisks)}</h4>
        <p>issue table state: ${escapeHtml(issueMemory.issue_table_state_path || "")}</p>
        ${
          permissionRisks.length
            ? permissionRisks.map((item) => `<p>${escapeHtml(item)}</p>`).join("")
            : `<p>${escapeHtml(t.none)}</p>`
        }
      </section>
      <section class="knowledge-card">
        <h4>${escapeHtml(t.mainContextTitle)}</h4>
        <p>owner: ${escapeHtml(mainContext.owner || "main-orchestrator")}</p>
        <p>handoffs: ${escapeHtml(String(mainContext.agents_sdk_usage?.handoffs ?? 0))}</p>
        <p>guardrails: ${escapeHtml(String(mainContext.agents_sdk_usage?.guardrails ?? 0))}</p>
        <p>tools: ${escapeHtml(String(mainContext.agents_sdk_usage?.tools ?? 0))}</p>
        ${(mainContext.must_read_before_dispatch || []).slice(0, 6).map((item) => `<p>읽기: ${escapeHtml(item)}</p>`).join("")}
      </section>
      <section class="knowledge-card">
        <h4>${escapeHtml(t.dispatchContractTitle)}</h4>
        ${(mainContext.dispatch_contract || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </section>
    </div>
    ${renderSelectedIssueGate(state.selectedRun)}
    ${renderIssueImport(issueImport)}
    <section class="recent-issues">
      <h4>${escapeHtml(t.recentIssues)}</h4>
      ${
        recent.length
          ? recent.map((issue) => `<article><strong>${escapeHtml(issue.file)}</strong><pre>${escapeHtml(issue.tail)}</pre></article>`).join("")
          : `<p>${escapeHtml(t.none)}</p>`
      }
    </section>
  `;
}

function renderLatestQueuedMessage(payload) {
  const messages = payload?.messages || [];
  const last = messages[messages.length - 1];
  if (!last || !last.prompt_preflight) return;
  const preflight = last.prompt_preflight || {};
  const warnings = preflight.warnings || [];
  const questions = preflight.clarifying_questions || [];
  el.promptPreview.hidden = false;
  el.promptPreview.innerHTML = `
    <details${detailOpenAttr("last-queued-message")} data-details-key="last-queued-message" class="collapsible-section">
      <summary>${escapeHtml(t.lastQueuedMessage)}</summary>
    <div class="preflight-meta">
      <span>${escapeHtml(t.preflightMode)}: ${escapeHtml(preflight.mode || "")}</span>
      ${preflight.model ? `<span>${escapeHtml(t.preflightModel)}: ${escapeHtml(preflight.model)}</span>` : ""}
    </div>
    ${last.original_message ? `<p><strong>Original</strong><br>${escapeHtml(last.original_message)}</p>` : ""}
    ${warnings.length ? `<p><strong>${escapeHtml(t.promptWarnings)}</strong><br>${escapeHtml(warnings.slice(0, 3).join(" / "))}${warnings.length > 3 ? " ..." : ""}</p>` : ""}
    ${questions.length ? `<p><strong>${escapeHtml(t.clarifyingQuestions)}</strong><br>${escapeHtml(questions.slice(0, 2).join(" / "))}${questions.length > 2 ? " ..." : ""}</p>` : ""}
    <pre>${escapeHtml(last.message || "")}</pre>
    </details>
  `;
  bindDetailsPersistence(el.promptPreview);
}

function routeLabel(routeName) {
  if (routeName === "openai_agents_sdk") return t.openaiRoute;
  if (routeName === "claude_collaborator") return t.claudeRoute;
  if (routeName === "codex_subscription_worker") return t.codexRoute;
  if (routeName === "gemini_collaborator") return "Gemini 3 Pro";
  return routeName;
}

function renderProviderRouting(config, adapterHealth = {}) {
  if (!config || !config.routes) {
    el.providerRouting.innerHTML = "";
    return;
  }
  const routeNames = Object.keys(config.routes).sort((a, b) => {
    const left = Number(config.routes[a]?.priority || 99);
    const right = Number(config.routes[b]?.priority || 99);
    return left - right;
  });
  el.providerRouting.innerHTML = `
    <details${detailOpenAttr("provider-routing", true)} data-details-key="provider-routing" class="collapsible-section">
      <summary>${escapeHtml(t.providerRoutingTitle)}</summary>
    <div class="provider-heading">
      <h3>${escapeHtml(t.providerRoutingTitle)}</h3>
      <p>${escapeHtml(t.providerRoutingBody)}</p>
    </div>
    ${renderQuotaLinks(config.quota_visibility || {})}
    <div class="provider-grid">
      ${routeNames
        .map((name) => {
          const route = config.routes[name] || {};
          const enabled = route.enabled !== false;
          const health = adapterHealth[name] || {};
          const callable = Boolean(health.callable);
          const model = route.default_model || route.effective_model || "";
          const isDefault = config.default_route === name;
          const bestFor = (route.best_for || []).slice(0, 3).join(", ");
          return `
            <article class="provider-card">
              <div class="provider-status-row">
                <span class="provider-status ${enabled ? "enabled" : "disabled"}">${escapeHtml(isDefault ? t.routeDefault : enabled ? t.routeEnabled : t.routeDisabled)}</span>
                <span class="provider-status ${callable ? "enabled" : "disabled"}">${escapeHtml(callable ? "호출 가능" : "호출 대기")}</span>
              </div>
              <h4>${escapeHtml(routeLabel(name))}</h4>
              <p><strong>${escapeHtml(t.routePriority)}</strong>: ${escapeHtml(route.priority || "")}</p>
              <p><strong>${escapeHtml(t.routeBilling)}</strong>: ${escapeHtml(route.billing || "")}</p>
              <p><strong>${escapeHtml(t.routeSurface)}</strong>: ${escapeHtml(route.surface || "")}</p>
              <p><strong>${escapeHtml(t.routeModel)}</strong>: ${escapeHtml(model)}</p>
              <p><strong>Adapter</strong>: ${escapeHtml(health.mode || "상태 확인 필요")}</p>
              ${health.import_error ? `<p><strong>Import</strong>: ${escapeHtml(health.import_error)}</p>` : ""}
              ${health.installed === false ? `<p><strong>Install</strong>: ${escapeHtml("패키지 미설치 또는 감지 불가")}</p>` : ""}
              <p class="provider-truth">${escapeHtml(health.truth || "실제 호출 상태가 아직 기록되지 않았습니다.")}</p>
              <p>${escapeHtml(bestFor)}</p>
            </article>
          `;
        })
        .join("")}
    </div>
    </details>
  `;
  bindDetailsPersistence(el.providerRouting);
}

function renderQuotaLinks(links) {
  const entries = Object.values(links || {});
  if (!entries.length) return "";
  return `
    <div class="quota-links">
      <strong>${escapeHtml(t.quotaTitle)}</strong>
      ${entries.map((entry) => `<a href="${escapeHtml(entry.url || "#")}" target="_blank" rel="noreferrer">${escapeHtml(entry.label || entry.url || "")}</a>`).join("")}
    </div>
  `;
}

function labelEventType(type) {
  return eventTypeLabels[type] || type || t.unknown;
}

function runBadges(run) {
  const badges = [];
  if (run.is_current) badges.push(t.currentRun);
  badges.push(t.sdkNotLive);
  if (run.has_chatkit) badges.push(t.chatkit);
  if (run.has_claude_response) badges.push(t.liveClaude);
  else if (run.has_claude_prompt) badges.push(t.promptOnly);
  if (!run.has_chatkit && !run.has_claude_prompt) badges.push(t.sampleOnly);
  return badges;
}

function renderRuns() {
  el.runs.innerHTML = state.runs
    .map((run) => {
      const active = (state.pendingRunId || state.selectedRun?.id) === run.id ? " active" : "";
      const badges = runBadges(run);
      return `
        <button class="run-item${active}" data-run-id="${escapeHtml(run.id)}" type="button">
          <span class="run-title">${escapeHtml(run.title || run.id)}</span>
          <span class="run-name">${escapeHtml(run.id)}</span>
          <span class="run-stats">
            <span>${escapeHtml(t.eventCount)} ${run.event_count || 0}${escapeHtml(t.countSuffix)}</span>
            ${badges.map((badge) => `<span>${escapeHtml(badge)}</span>`).join("")}
          </span>
        </button>
      `;
    })
    .join("");

  el.runs.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => loadRun(button.dataset.runId));
  });
}

async function loadRun(runId) {
  state.pendingRunId = runId;
  renderRuns();
  let data;
  try {
    data = await fetchJson(`/api/run?id=${encodeURIComponent(runId)}`);
  } catch (error) {
    if (state.pendingRunId === runId) state.pendingRunId = "";
    renderRuns();
    throw error;
  }
  if (state.pendingRunId !== runId) return;
  state.pendingRunId = "";
  state.selectedRun = data;
  state.selectedEventIndex = null;
  renderRuns();
  renderRunHeader(data);
  renderRunSummary(data);
  renderAgentConversation(data);
  renderTimeline(data.events || []);
  renderTranscriptDetailsSummary(data);
  renderInspector(null);
  renderWorkBoard(state.queueStatus || {});
  renderMilestones(state.queueStatus || {});
  renderKnowledgeHub(state.queueStatus || {});
}

function renderRunHeader(run) {
  const events = run.events || [];
  const displayTitle = run.plan?.goal?.goal_id || run.plan?.operator_message?.title || run.title || t.transcript;
  el.runId.textContent = run.id;
  el.runTitle.textContent = displayTitle;
  const meta = [
    `${t.eventCount} ${events.length}${t.countSuffix}`,
    ...(run.plan?.handoff_contract?.status ? [run.plan.handoff_contract.status] : []),
    ...(run.plan ? [t.plan] : []),
    ...(run.chatkit ? [t.chatkit] : []),
    ...(run.artifacts?.length ? [`${t.artifacts} ${run.artifacts.length}${t.countSuffix}`] : []),
  ];
  el.runMeta.innerHTML = meta.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("");
}

function renderRunSummary(run) {
  const plan = run.plan || {};
  const goal = plan.goal || {};
  const gates = plan.gate_requirements || {};
  const issueMemory = plan.issue_memory_preflight || {};
  const openIssues = issueMemory.matching_open_issues || [];
  const surfaces = goal.affected_surfaces || [];
  const evidence = gates.required_evidence || [];
  const plannedFiles = goal.planned_files || [];
  const artifacts = run.artifacts || [];
  const rows = [
    [t.blocker, goal.blocker_id || t.unknown],
    [t.classification, gates.classification || goal.work_type || t.unknown],
    [t.surfaces, surfaces.length ? surfaces.join(", ") : t.unknown],
    [t.evidenceRequired, evidence.length ? `${evidence.length}${t.countSuffix}` : t.unknown],
    [t.openIssues, `${openIssues.length}${t.countSuffix}`],
    [t.plannedFiles, plannedFiles.length ? plannedFiles.join(", ") : t.unknown],
    [t.artifacts, artifacts.length ? `${artifacts.length}${t.countSuffix}` : t.unknown],
  ];
  el.runSummary.innerHTML = `
    <section class="raw-transcript-note">
      <strong>${escapeHtml(t.rawTranscriptNoteTitle)}</strong>
      <p>${escapeHtml(t.rawTranscriptNoteBody)}</p>
    </section>
    ${renderDispatchPreview(plan.main_dispatch_preview)}
    ${renderAutomaticUsePolicy(plan)}
    ${renderCompletionChecklist(run)}
    <h3>${escapeHtml(t.summaryTitle)}</h3>
    <div class="summary-grid">
      ${rows
        .map(
          ([label, value]) => `
            <div class="summary-card">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderCompletionChecklist(run) {
  const plan = (run && run.plan) || {};
  const artifacts = new Set(run.artifacts || []);
  const gate = plan.review_gate || {};
  const reportPack = plan.d_drive_report_pack || {};
  const reportJudgment = plan.report_pack_judgment || {};
  const reportEvidenceAudit = plan.report_evidence_audit || {};
  const goalCompletionAudit = plan.goal_completion_audit || {};
  const unityRenderedEvidence = plan.unity_rendered_evidence || {};
  const reportFiles = reportPack.files && typeof reportPack.files === "object" ? Object.entries(reportPack.files) : [];
  const reportContextCoverage =
    reportJudgment.context_coverage && typeof reportJudgment.context_coverage === "object"
      ? Object.entries(reportJudgment.context_coverage)
      : [];
  const reportContextLabels = {
    unity_project_path: "Unity 프로젝트 경로",
    active_operating_state: "active operating state",
    active_blocker: "현재 active blocker",
    not_sellable_boundary: "NOT_SELLABLE/완료 금지 경계",
    latest_executable_or_rendered_evidence: "실행 파일/렌더링 증거 언급",
  };
  const checks = [
    ["worker-result.json", artifacts.has("worker-result.json"), "Codex worker result"],
    ["validator-result.json", artifacts.has("validator-result.json"), "Validator result"],
    ["validator-code-result.json", artifacts.has("validator-code-result.json"), "Code validator lane"],
    ["validator-contract-result.json", artifacts.has("validator-contract-result.json"), "Contract validator lane"],
    ["validator-ui-state-result.json", artifacts.has("validator-ui-state-result.json"), "UI-state validator lane"],
    ["validator-issue-gate-result.json", artifacts.has("validator-issue-gate-result.json"), "Issue-memory validator lane"],
    ["issue-gate.json", artifacts.has("issue-gate.json"), "Issue-memory gate"],
    ["e2e-html-verification.json", artifacts.has("e2e-html-verification.json"), "Browser E2E evidence"],
    ["claude-review-result.json", artifacts.has("claude-review-result.json") || artifacts.has("product-review-result.json"), "Claude/product review"],
    ["agents-sdk-run-contract.json", artifacts.has("agents-sdk-run-contract.json"), "Agents SDK run contract"],
    ["agents-sdk-handoff-graph.json", artifacts.has("agents-sdk-handoff-graph.json"), "Agents SDK handoff graph"],
    ["agents-sdk-guardrails.json", artifacts.has("agents-sdk-guardrails.json"), "Agents SDK guardrails"],
    ["review-iteration-001.json", artifacts.has("review-iteration-001.json"), "반복 review 1"],
    ["review-iteration-002.json", artifacts.has("review-iteration-002.json"), "반복 review 2"],
    ["review-iteration-003.json", artifacts.has("review-iteration-003.json"), "반복 review 3"],
    ["d-drive-report-pack.json", artifacts.has("d-drive-report-pack.json"), "D드라이브 보고서 pack"],
    ["report-pack-judgment.json", artifacts.has("report-pack-judgment.json"), "보고서 판정"],
    ["report-evidence-audit.json", artifacts.has("report-evidence-audit.json"), "Unity evidence 인용 감사"],
    ["goal-completion-audit.json", artifacts.has("goal-completion-audit.json"), "목표 완료 감사"],
    ["unity-rendered-evidence.json", artifacts.has("unity-rendered-evidence.json"), "새 Unity 렌더링 증거"],
  ];
  const ready = String(gate.status || "").startsWith("ready_for_closure_review");
  const gateLabel = gateStatusLabel(gate.status || "");
  return `
    <section class="dispatch-preview completion-preview">
      <div class="dispatch-head">
        <h3>완료/검증 체크</h3>
        <span title="${escapeHtml(gate.status || "")}">${escapeHtml(gateLabel)}</span>
      </div>
      <p>${escapeHtml(gate.next_action || "worker, validator, Claude/product review 결과가 모두 있어야 closure 검토로 넘어갑니다.")}</p>
      <div class="dispatch-routes">
        ${checks
          .map(
            ([artifact, ok, label]) => `
              <article class="dispatch-route ${ok ? "passed" : "blocked"}">
                <span>${ok ? "있음" : "없음"}</span>
                <strong>${escapeHtml(label)}</strong>
                <small>${escapeHtml(artifact)}</small>
              </article>
            `,
          )
          .join("")}
        <article class="dispatch-route ${ready ? "passed" : "blocked"}">
          <span>${ready ? "준비됨" : "대기"}</span>
          <strong>Closure review</strong>
          <small title="${escapeHtml(gate.status || "")}">${escapeHtml(gateLabel)}</small>
        </article>
      </div>
      ${
        reportFiles.length
          ? `<div class="report-pack-summary">
              <strong>평문 요청으로 생성된 D드라이브 보고서</strong>
              <div class="report-pack-artifacts">
                <span>d-drive-report-pack.json</span>
                <span>report-pack-judgment.json</span>
                <span>report-evidence-audit.json</span>
                <span>goal-completion-audit.json</span>
                <span>unity-rendered-evidence.json</span>
              </div>
              <p>${escapeHtml(reportPack.output_dir || "")}</p>
              ${
                reportJudgment.status
                  ? `<div class="report-pack-verdict ${escapeHtml(reportJudgment.completion_evidence_sufficient ? "passed" : "limited")}">
                      <b>판정: ${escapeHtml(reportJudgment.status)}</b>
                      <span>${escapeHtml(reportJudgment.summary || "")}</span>
                      ${
                        reportJudgment.retry_prompt_artifact || (reportJudgment.status && !reportJudgment.completion_evidence_sufficient)
                          ? `<em>다음 평문 입력 artifact: ${escapeHtml(reportJudgment.retry_prompt_artifact || "report-pack-retry-prompt.md")}</em>`
                          : ""
                      }
                    </div>`
                  : ""
              }
              ${
                reportContextCoverage.length
                  ? `<div class="report-context-coverage" aria-label="보고서 Unity 근거 반영 상태">
                      <strong>Unity 근거 반영</strong>
                      ${reportContextCoverage
                        .map(
                          ([key, value]) => `
                            <span class="${value ? "passed" : "blocked"}">
                              ${value ? "확인" : "누락"} · ${escapeHtml(reportContextLabels[key] || key)}
                            </span>
                          `,
                        )
                        .join("")}
                    </div>`
                  : ""
              }
              ${
                reportEvidenceAudit.status
                  ? `<div class="report-evidence-audit ${reportEvidenceAudit.evidence_reference_sufficient_for_report ? "passed" : "limited"}">
                      <strong>Unity evidence 인용 감사</strong>
                      <b>${escapeHtml(reportEvidenceAudit.status || "")}</b>
                      <span>${escapeHtml(reportEvidenceAudit.summary || "")}</span>
                      <div>
                        <small>존재 확인 ${escapeHtml(String(reportEvidenceAudit.verified_existing_count || 0))}</small>
                        <small>렌더링 증거 ${escapeHtml(String(reportEvidenceAudit.rendered_evidence_reference_count || 0))}</small>
                        <small>active state 일치 ${escapeHtml(String(reportEvidenceAudit.active_state_match_count || 0))}</small>
                        <small>누락 ${escapeHtml(String(reportEvidenceAudit.missing_count || 0))}</small>
                      </div>
                    </div>`
                  : ""
              }
              ${
                goalCompletionAudit.status
                  ? `<div class="goal-completion-audit ${goalCompletionAudit.completion_allowed ? "passed" : "limited"}">
                      <strong>목표 완료 감사</strong>
                      <b>${escapeHtml(goalCompletionAudit.status || "")}</b>
                      <span>${escapeHtml(goalCompletionAudit.summary || "")}</span>
                      <div class="goal-requirements">
                        ${(goalCompletionAudit.requirements || [])
                          .map(
                            (item) => `
                              <span class="${escapeHtml(item.status || "unknown")}">
                                ${escapeHtml(item.status || "unknown")} · ${escapeHtml(item.label || item.id || "")}
                              </span>
                            `,
                          )
                          .join("")}
                      </div>
                    </div>`
                  : ""
              }
              ${
                unityRenderedEvidence.status
                  ? `<div class="unity-rendered-evidence ${unityRenderedEvidence.status === "passed" ? "passed" : "limited"}">
                      <strong>새 Unity 렌더링 증거</strong>
                      <b>${escapeHtml(unityRenderedEvidence.status || "")} · ${escapeHtml(unityRenderedEvidence.surface || "")}</b>
                      <span>${escapeHtml(unityRenderedEvidence.screenshot || "")}</span>
                      <small>${escapeHtml(String(unityRenderedEvidence.ready_marker || ""))} · ${escapeHtml(String(unityRenderedEvidence.bytes || 0))} bytes</small>
                    </div>`
                  : ""
              }
              <div class="report-pack-files">
                ${reportFiles
                  .map(([label, path]) => `<span title="${escapeHtml(path)}">${escapeHtml(label)} · ${escapeHtml(String(path))}</span>`)
                  .join("")}
              </div>
              <small>${escapeHtml(reportPack.evidence_boundary || "보고서 산출물 경계 확인 필요")}</small>
            </div>`
          : ""
      }
    </section>
  `;
}

function renderAutomaticUsePolicy(plan) {
  const decision = plan.main_decision || {};
  const policy = plan.automatic_beneficial_use_policy || decision.automatic_beneficial_use_policy || {};
  const claude = decision.claude_validation_policy || {};
  const sdk = decision.agents_sdk_policy || {};
  const reviewGate = plan.review_gate || {};
  if (!Object.keys(policy).length && !Object.keys(claude).length && !Object.keys(sdk).length) return "";
  const alwaysApply = Array.isArray(policy.always_apply) ? policy.always_apply.slice(0, 4) : [];
  const liveApiWhen = Array.isArray(policy.live_api_use_when) ? policy.live_api_use_when.slice(0, 3) : [];
  const mandatoryReviewers = Array.isArray(reviewGate.mandatory_reviewers) ? reviewGate.mandatory_reviewers.join(", ") : "";
  return `
    <section class="dispatch-preview policy-preview">
      <div class="dispatch-head">
        <h3>자동 모델/SDK 사용 정책</h3>
        <span>${escapeHtml(policy.rule || "명시하지 않아도 이득이면 메인이 자동 배정")}</span>
      </div>
      <div class="summary-grid">
        <div class="summary-card">
          <span>Agents SDK 방식</span>
          <strong>${escapeHtml(sdk.pattern_required ? "항상 적용" : "확인 필요")}</strong>
          <small>${escapeHtml((sdk.used_for || []).slice(0, 3).join(" / ") || "handoff / guardrail / trace")}</small>
        </div>
        <div class="summary-card">
          <span>Claude 검증</span>
          <strong>${escapeHtml(claude.required ? "완료 전 필수" : "확인 필요")}</strong>
          <small>${escapeHtml(claude.completion_blocker || mandatoryReviewers || "review artifact 필요")}</small>
        </div>
        <div class="summary-card">
          <span>기본 실행 경로</span>
          <strong>${escapeHtml((policy.default_order || []).slice(0, 3).join(" → ") || "Codex/Claude MAX 우선")}</strong>
          <small>${escapeHtml(alwaysApply.join(" / "))}</small>
        </div>
        <div class="summary-card">
          <span>OpenAI API live call</span>
          <strong>${escapeHtml(sdk.live_call_required ? "필수" : "필요 시만")}</strong>
          <small>${escapeHtml(liveApiWhen.join(" / ") || "작은 구조화/가드레일 판단에 한정")}</small>
        </div>
      </div>
    </section>
  `;
}

function renderDispatchPreview(dispatch) {
  if (!dispatch) return "";
  const routes = dispatch.routes || [];
  return `
    <section class="dispatch-preview">
      <div class="dispatch-head">
        <h3>${escapeHtml(t.dispatchTitle)}</h3>
        <span>${escapeHtml(t.dispatchActual)}: ${escapeHtml(dispatchStatusLabel(dispatch.actual_dispatch_status))}</span>
      </div>
      <p>${escapeHtml(dispatch.note || "")}</p>
      <div class="dispatch-routes">
        ${routes
          .map(
            (route) => `
              <article class="dispatch-route ${escapeHtml(statusClass(route.status))}">
                <span>${escapeHtml(route.status || "")}</span>
                <strong>${escapeHtml(route.agent || "")}</strong>
                <small>${escapeHtml(route.route || "")}</small>
                <p>${escapeHtml(route.reason || "")}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function dispatchStatusLabel(status) {
  if (status === "not_dispatched_yet") return t.dispatchNotYet;
  if (status === "dispatch_ready") return t.statusDispatchReady;
  if (status === "dispatch_blocked") return t.statusDispatchBlocked;
  return status || t.unknown;
}

function renderAgentConversation(run) {
  if (!el.agentConversation) return;
  const messages = buildVisibleConversation(run);
  const rawCount = ((run && run.events) || []).length;
  el.agentConversation.innerHTML = `
    <div class="conversation-head">
      <div>
        <p class="eyebrow">${escapeHtml(t.conversationTitle)}</p>
        <h3># agent-dialogue</h3>
      </div>
      <span>${messages.length}${escapeHtml(t.countSuffix)}</span>
    </div>
    <p class="conversation-subtitle">${escapeHtml(t.conversationSubtitle)}</p>
    <div class="conversation-feed">
      ${
        messages.length
          ? messages.map((event, index) => renderConversationMessage(event, index)).join("")
          : `<p class="conversation-empty">${escapeHtml(t.noConversation)}</p>`
      }
    </div>
  `;
  el.agentConversation.querySelectorAll("[data-event-index]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedEventIndex = Number(node.dataset.eventIndex);
      const selectedMessage = messages[state.selectedEventIndex];
      renderTimeline(state.selectedRun.events || []);
      renderInspector(selectedMessage);
    });
  });
}

function renderConversationRunContext(run, visibleCount, rawCount) {
  const plan = (run && run.plan) || {};
  const operatorMessage = plan.operator_message || {};
  const gate = plan.review_gate || {};
  const artifacts = new Set((run && run.artifacts) || []);
  const original = operatorMessage.original_message || operatorMessage.title || "";
  const hiddenCount = Math.max(0, Number(rawCount || 0) - Number(visibleCount || 0));
  const evidence = [
    artifacts.has("claude-review-result.json") ? "실제 Claude 검토 있음" : artifacts.has("product-review-result.json") ? "자동 product 검토만 있음" : "Claude/product 검토 없음",
    artifacts.has("worker-result.json") ? "worker-result 있음" : "worker-result 없음",
    artifacts.has("validator-result.json") ? "validator-result 있음" : "validator-result 없음",
    artifacts.has("closure-packet.json") ? "closure packet 있음" : "closure packet 없음",
  ];
  return `
    <section class="conversation-run-context">
      <div>
        <span>선택 실행</span>
        <strong>${escapeHtml((run && run.id) || "선택 없음")}</strong>
      </div>
      <div>
        <span>현재 판정</span>
        <strong title="${escapeHtml(gate.status || "")}">${escapeHtml(gateStatusLabel(gate.status || "") || "확인 필요")}</strong>
      </div>
      <div>
        <span>표시 기준</span>
        <strong>agent 발화 ${Number(visibleCount || 0)}개 / 원본 ${Number(rawCount || 0)}개</strong>
      </div>
      <p><strong>사용자 원문</strong><br>${escapeHtml(original || "이 실행에 저장된 사용자 원문을 찾지 못했습니다.")}</p>
      <p><strong>증거 상태</strong><br>${evidence.map(escapeHtml).join(" · ")} · 숨긴 plumbing ${hiddenCount}개</p>
    </section>
  `;
}

function renderTranscriptDetailsSummary(run) {
  if (!el.transcriptDetails) return;
  const summary = el.transcriptDetails.querySelector("summary");
  if (!summary) return;
  const rawCount = ((run && run.events) || []).length;
  summary.textContent = `선택한 실행 기록: 실제 transcript ${rawCount}개`;
}

function renderMainStatusBanner(run) {
  const plan = (run && run.plan) || {};
  const handoff = plan.handoff_contract || {};
  const decision = plan.main_decision || {};
  const workerDispatch = plan.worker_dispatch || {};
  const assignments = Array.isArray(workerDispatch.assignments) ? workerDispatch.assignments : [];
  const routes = plan.provider_routes?.routes || {};
  const defaultRoute = plan.provider_routes?.default_route || decision.selected_route || handoff.route || "";
  if (!Object.keys(plan).length) return "";
  const codexEnabled = routes.codex_subscription_worker?.enabled !== false;
  const claudeEnabled = routes.claude_collaborator?.enabled !== false;
  const candidates = [
    defaultRoute ? `기본: ${defaultRoute}` : "",
    codexEnabled ? "Codex MAX" : "",
    claudeEnabled ? "Claude MAX" : "",
  ].filter(Boolean);
  const statusText = decision.status
    ? statusLabel(decision.status)
    : handoff.status === "sent_to_main"
      ? t.mainStatusSentOnly
      : `상태: ${handoff.status || "확인 필요"}`;
  const assignedWorkers = assignments
    .filter((item) => ["queued_for_subscription_worker", "review_queued_for_subscription_reviewer", "prepared", "blocked_until_worker_result"].includes(item.status))
    .map((item) => `${item.agent}: ${item.status}`)
    .slice(0, 4)
    .join(" / ");
  return `
    <section class="main-status-banner">
      <div>
        <span>${escapeHtml(t.mainStatusTitle)}</span>
        <strong>${escapeHtml(statusText)}</strong>
      </div>
      <div>
        <span>${escapeHtml(t.mainStatusWorkerNone)}</span>
        <strong>${escapeHtml(assignedWorkers || handoff.actual_worker || "없음")}</strong>
      </div>
      <div>
        <span>${escapeHtml(t.mainStatusNext)}</span>
        <strong>${escapeHtml(candidates.join(" / ") || "확인 필요")}</strong>
      </div>
    </section>
  `;
}

function buildVisibleConversation(run) {
  const visibleResultTypes = new Set(["worker_result", "review_result", "response", "blocked", "final_status", "closure_packet"]);
  const hiddenPlumbingSpeakers = new Set(["operator", "prompt-preflight-agent", "prompt-validator-agent", "queue-processor"]);
  const transcriptEvents = ((run && run.events) || []).filter(
    (event) =>
      event &&
      !event.synthetic &&
      (event.message || event.speaker || event.recipient) &&
      visibleResultTypes.has(event.event_type || "") &&
      !hiddenPlumbingSpeakers.has(event.speaker || "") &&
      event.speaker !== event.recipient,
  );
  return transcriptEvents;
}

function buildMainOrchestratorMessages(run) {
  return [];
}

function renderConversationMessage(event, index) {
  const speaker = event.speaker || "unknown";
  const recipient = event.recipient || "";
  const type = labelEventType(event.event_type);
  const artifact = event.artifact || "";
  const hint = roleHints[speaker] || "";
  return `
    <article class="discord-message${event.synthetic ? " synthetic" : ""}" data-event-index="${index}">
      <div class="discord-avatar ${escapeHtml(statusClass(speaker))}">${escapeHtml(speakerInitials(speaker))}</div>
      <div class="discord-content">
        <header>
          <strong>${escapeHtml(speaker)}</strong>
          <span>${escapeHtml(formatKoreanTime(event.timestamp))}</span>
          <span class="discord-type ${escapeHtml(statusClass(event.event_type))}">${escapeHtml(type)}</span>
          ${event.synthetic ? `<span class="discord-type">${escapeHtml(t.recordedSummary)}</span>` : ""}
          ${recipient ? `<span class="discord-recipient">${escapeHtml(t.recipientLabel)}: ${escapeHtml(recipient)}</span>` : ""}
        </header>
        ${hint ? `<p class="discord-role">${escapeHtml(hint)}</p>` : ""}
        <p class="discord-text">${escapeHtml(event.message || "")}</p>
        ${artifact ? `<div class="discord-attachment">${escapeHtml(t.attachmentLabel)} · ${escapeHtml(artifact)}</div>` : ""}
      </div>
    </article>
  `;
}

function speakerInitials(speaker) {
  const cleaned = String(speaker || "?").replace(/[-_]/g, " ").trim();
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
  return cleaned.slice(0, 2).toUpperCase() || "?";
}

function formatKoreanTime(timestamp) {
  if (!timestamp) return "";
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return `${parsed.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })} KST`;
}

function renderTimeline(events) {
  el.timeline.innerHTML = events
    .map((event, index) => {
      const active = state.selectedEventIndex === index ? " active" : "";
      const roleHint = roleHints[event.speaker] || "";
      return `
        <article class="event${active}" data-event-index="${index}">
          <div class="event-route">
            <strong>${escapeHtml(event.speaker)}</strong><br />
            ${escapeHtml(event.recipient)}
            <span class="event-type">${escapeHtml(labelEventType(event.event_type))}</span>
            ${roleHint ? `<span class="role-hint">${escapeHtml(roleHint)}</span>` : ""}
          </div>
          <div class="event-body">
            <p class="event-message">${escapeHtml(event.message)}</p>
          </div>
        </article>
      `;
    })
    .join("");

  el.timeline.querySelectorAll("[data-event-index]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedEventIndex = Number(node.dataset.eventIndex);
      renderTimeline(state.selectedRun.events || []);
      renderInspector((state.selectedRun.events || [])[state.selectedEventIndex]);
    });
  });
}

function renderInspector(event) {
  if (!event) {
    el.inspector.className = "inspector-empty";
    el.inspector.textContent = t.selectEvent;
    return;
  }
  el.inspector.className = "inspector";
  const speakerHint = roleHints[event.speaker] || "";
  el.inspector.innerHTML = `
    <dl>
      <dt>${escapeHtml(t.speaker)}</dt>
      <dd>${escapeHtml(event.speaker)}${speakerHint ? `<p class="hint">${escapeHtml(speakerHint)}</p>` : ""}</dd>
      <dt>${escapeHtml(t.recipient)}</dt>
      <dd>${escapeHtml(event.recipient)}</dd>
      <dt>${escapeHtml(t.type)}</dt>
      <dd>${escapeHtml(labelEventType(event.event_type))}</dd>
      <dt>${escapeHtml(t.time)}</dt>
      <dd>${escapeHtml(formatKoreanTime(event.timestamp))}</dd>
      <dt>${escapeHtml(t.artifact)}</dt>
      <dd>${escapeHtml(event.artifact || t.none)}</dd>
      <dt>${escapeHtml(t.message)}</dt>
      <dd><pre>${escapeHtml(event.message)}</pre></dd>
    </dl>
  `;
}

el.refresh.addEventListener("click", loadRuns);
if (el.processNext) {
  el.processNext.addEventListener("click", async () => {
    el.processNext.disabled = true;
    try {
      await postJson("/api/queue/process", { count: 1 });
      await refreshLiveStatus();
      await loadRuns();
    } finally {
      el.processNext.disabled = false;
    }
  });
}
if (el.cancelAll) {
  el.cancelAll.addEventListener("click", async () => {
    if (!window.confirm(t.cancelAllConfirm)) return;
    el.cancelAll.disabled = true;
    try {
      await postJson("/api/messages/cancel", { reason: "operator canceled from dashboard" });
      await refreshLiveStatus();
      await loadRuns();
    } finally {
      el.cancelAll.disabled = false;
    }
  });
}
if (el.toggleTrash) {
  el.toggleTrash.addEventListener("click", async () => {
    state.showTrash = !state.showTrash;
    renderQueueStatus(state.queueStatus || {});
  });
}
async function selectRunForMessage(messageId, attempts = 6) {
  if (!messageId) return;
  for (let i = 0; i < attempts; i += 1) {
    const data = await fetchJson("/api/messages").catch(() => null);
    const msg = (data?.messages || []).find((m) => m.id === messageId);
    const runId = msg?.effective_run_id || msg?.run_id || "";
    if (runId) {
      await loadRun(runId);
      setActiveTab("status");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

el.sendMessage.addEventListener("click", async () => {
  el.messageStatus.textContent = "";
  el.promptPreview.hidden = true;
  el.promptPreview.innerHTML = "";
  if (!el.messageText.value.trim()) {
    el.messageStatus.textContent = t.emptyMessage;
    return;
  }
  try {
    const payload = {
      target: el.messageTarget.value,
      target_thread_id: el.messageThread.value,
      run_id: state.selectedRun?.id || "",
      message: el.messageText.value,
    };
    const data = await postJson("/api/messages", payload);
    el.messageStatus.textContent = `${t.queued}: ${data.message.id}`;
    el.messageText.value = "";
    await refreshLiveStatus();
    const newRunId = data.created_run_id || data.message.effective_run_id || "";
    if (newRunId) {
      await loadRun(newRunId);
    } else {
      await selectRunForMessage(data.message.id);
    }
    const preflight = data.message.prompt_preflight || {};
    const warnings = preflight.warnings || [];
    const questions = preflight.clarifying_questions || [];
    el.promptPreview.hidden = false;
    el.promptPreview.innerHTML = `
      <h3>${escapeHtml(t.promptPreviewTitle)}</h3>
      <div class="preflight-meta">
        <span>${escapeHtml(t.preflightMode)}: ${escapeHtml(preflight.mode || "")}</span>
        ${preflight.model ? `<span>${escapeHtml(t.preflightModel)}: ${escapeHtml(preflight.model)}</span>` : ""}
        ${preflight.live_api_state ? `<span class="pf-badge ${preflight.live_api_state === "deferred" ? "warn" : ""}">live: ${escapeHtml(preflight.live_api_state)}</span>` : ""}
      </div>
      ${warnings.length ? `<p><strong>${escapeHtml(t.promptWarnings)}</strong><br>${escapeHtml(warnings.slice(0, 4).join(" / "))}${warnings.length > 4 ? " ..." : ""}</p>` : ""}
      ${questions.length ? `<p><strong>${escapeHtml(t.clarifyingQuestions)}</strong><br>${escapeHtml(questions.slice(0, 3).join(" / "))}${questions.length > 3 ? " ..." : ""}</p>` : ""}
      <details>
        <summary>${escapeHtml(t.promptPreviewSummary)}</summary>
        <pre>${escapeHtml(data.message.message || "")}</pre>
      </details>
    `;
  } catch (error) {
    el.messageStatus.textContent = error.message;
  }
});

if (el.toggleLivePreflight) {
  el.toggleLivePreflight.addEventListener("change", async () => {
    try {
      const data = await postJson("/api/preflight/toggle", { live_enabled: el.toggleLivePreflight.checked });
      renderPreflightBanner(data.live_preflight);
    } catch (error) {
      el.toggleLivePreflight.checked = !el.toggleLivePreflight.checked;
      if (el.messageStatus) el.messageStatus.textContent = error.message;
    }
  });
}

if (el.submitResult) {
  el.submitResult.addEventListener("click", async () => {
    el.resultStatusMessage.textContent = "";
    const runId = state.selectedRun?.id || "";
    if (!runId) {
      el.resultStatusMessage.textContent = "먼저 실행 기록을 선택하세요.";
      return;
    }
    if (!el.resultSummary.value.trim()) {
      el.resultStatusMessage.textContent = "결과 요약을 입력하세요.";
      return;
    }
    el.submitResult.disabled = true;
    try {
      const payload = {
        run_id: runId,
        result_type: el.resultType.value,
        role: el.resultRole.value,
        status: el.resultStatus.value,
        summary: el.resultSummary.value,
        evidence: el.resultEvidence.value,
        risks: el.resultRisks.value,
      };
      const data = await postJson("/api/run/result", payload);
      el.resultStatusMessage.textContent = `기록됨: ${data.artifact}`;
      state.selectedRun = data.run;
      renderRuns();
      renderRunHeader(data.run);
      renderRunSummary(data.run);
      renderAgentConversation(data.run);
      renderTimeline(data.run.events || []);
      renderTranscriptDetailsSummary(data.run);
      renderInspector(null);
      await refreshLiveStatus();
    } catch (error) {
      el.resultStatusMessage.textContent = error.message;
    } finally {
      el.submitResult.disabled = false;
    }
  });
}

if (el.advanceRun) {
  el.advanceRun.addEventListener("click", async () => {
    el.resultStatusMessage.textContent = "";
    const runId = state.selectedRun?.id || "";
    if (!runId) {
      el.resultStatusMessage.textContent = "먼저 실행 기록을 선택하세요.";
      return;
    }
    el.advanceRun.disabled = true;
    try {
      const data = await postJson("/api/run/advance", { run_id: runId });
      el.resultStatusMessage.textContent = `진행됨: ${data.advanced}${data.artifact ? ` / ${data.artifact}` : ""}`;
      state.selectedRun = data.run;
      renderRuns();
      renderRunHeader(data.run);
      renderRunSummary(data.run);
      renderAgentConversation(data.run);
      renderTimeline(data.run.events || []);
      renderTranscriptDetailsSummary(data.run);
      renderInspector(null);
      await refreshLiveStatus();
    } catch (error) {
      el.resultStatusMessage.textContent = error.message;
    } finally {
      el.advanceRun.disabled = false;
    }
  });
}

if (el.runClaudeReview) {
  el.runClaudeReview.addEventListener("click", async () => {
    el.resultStatusMessage.textContent = "";
    const runId = state.selectedRun?.id || "";
    if (!runId) {
      el.resultStatusMessage.textContent = "먼저 실행 기록을 선택하세요.";
      return;
    }
    el.runClaudeReview.disabled = true;
    el.resultStatusMessage.textContent = "Claude 검토 실행 중입니다. 오래 걸릴 수 있습니다.";
    try {
      const data = await postJson("/api/run/claude-review", { run_id: runId });
      el.resultStatusMessage.textContent = `Claude 기록됨: ${data.artifact} / ${data.claude_ok ? "passed" : "blocked"}`;
      state.selectedRun = data.run;
      renderRuns();
      renderRunHeader(data.run);
      renderRunSummary(data.run);
      renderAgentConversation(data.run);
      renderTimeline(data.run.events || []);
      renderTranscriptDetailsSummary(data.run);
      renderInspector(null);
      await refreshLiveStatus();
    } catch (error) {
      el.resultStatusMessage.textContent = error.message;
    } finally {
      el.runClaudeReview.disabled = false;
    }
  });
}

function collectBrowserE2eChecks() {
  const artifacts = new Set(state.selectedRun?.artifacts || []);
  const bodyText = document.body.innerText || "";
  const summaryText = document.getElementById("run-summary")?.innerText || "";
  const visibleText = `${bodyText}\n${summaryText}`;
  const runId = state.selectedRun?.id || "";
  const selectedRunVisible = Boolean(runId && visibleText.includes(runId.slice(0, 16)));
  const hasCompletionChecklist = visibleText.includes("완료/검증 체크");
  const hasKoreanOperatorUi = visibleText.includes("에이전트 실행") && visibleText.includes("작업자/검토 결과 기록");
  const checks = [
    {
      id: "selected_run_visible",
      label: "선택한 실행 ID가 화면에 보임",
      passed: selectedRunVisible,
      detail: runId,
    },
    {
      id: "completion_checklist_visible",
      label: "완료/검증 체크 섹션이 보임",
      passed: hasCompletionChecklist,
      detail: "run summary DOM text",
    },
    {
      id: "worker_result_visible",
      label: "worker-result.json 상태가 화면에서 추적됨",
      passed: artifacts.has("worker-result.json") && visibleText.includes("worker-result.json"),
      detail: "worker artifact + checklist text",
    },
    {
      id: "multiple_validator_lanes_visible",
      label: "여러 검증 세션 lane이 화면에서 추적됨",
      passed:
        artifacts.has("validator-code-result.json") &&
        artifacts.has("validator-contract-result.json") &&
        artifacts.has("validator-ui-state-result.json") &&
        artifacts.has("validator-issue-gate-result.json") &&
        visibleText.includes("Issue-memory validator lane"),
      detail: "code / contract / UI-state / issue-memory lanes",
    },
    {
      id: "claude_gate_visible",
      label: "Claude/product 검토 게이트가 화면에 보임",
      passed: visibleText.includes("Claude/product review") || visibleText.includes("Claude 검토 실행"),
      detail: "closure gate UI",
    },
    {
      id: "korean_operator_controls_visible",
      label: "한국어 운영자 컨트롤이 보임",
      passed: hasKoreanOperatorUi,
      detail: "Korean UI labels",
    },
  ];
  return checks;
}

if (el.recordE2e) {
  el.recordE2e.addEventListener("click", async () => {
    el.resultStatusMessage.textContent = "";
    const runId = state.selectedRun?.id || "";
    if (!runId) {
      el.resultStatusMessage.textContent = "먼저 실행 기록을 선택하세요.";
      return;
    }
    el.recordE2e.disabled = true;
    try {
      const checks = collectBrowserE2eChecks();
      const data = await postJson("/api/run/e2e-verification", {
        run_id: runId,
        checks,
        evidence: [
          window.location.href,
          `artifact_count=${(state.selectedRun?.artifacts || []).length}`,
          `checked_at=${new Date().toISOString()}`,
        ],
        dom_snapshot: document.body.innerText.slice(0, 12000),
      });
      el.resultStatusMessage.textContent = `화면 E2E 기록됨: ${data.artifact} / ${data.result.status}`;
      state.selectedRun = data.run;
      renderRuns();
      renderRunHeader(data.run);
      renderRunSummary(data.run);
      renderAgentConversation(data.run);
      renderTimeline(data.run.events || []);
      renderTranscriptDetailsSummary(data.run);
      renderInspector(null);
      await refreshLiveStatus();
    } catch (error) {
      el.resultStatusMessage.textContent = error.message;
    } finally {
      el.recordE2e.disabled = false;
    }
  });
}

setStaticText();
loadRuns().catch((error) => {
  el.runs.innerHTML = `<p class="inspector-empty">${escapeHtml(error.message)}</p>`;
});
function startLiveStream() {
  try {
    if (state.eventSource) { try { state.eventSource.close(); } catch (_) {} }
    const source = new EventSource("/api/events");
    source.addEventListener("status", () => { refreshLiveStatus(); });
    source.onerror = () => {
      source.close();
      if (!state.sseReconnectTimer) {
        state.sseReconnectTimer = window.setTimeout(() => { state.sseReconnectTimer = null; startLiveStream(); }, 5000);
      }
    };
    state.eventSource = source;
  } catch (_) {
    if (!state.statusTimer) state.statusTimer = window.setInterval(refreshLiveStatus, 3000);
  }
}
refreshLiveStatus();
startLiveStream();
if (!state.backupPollTimer) state.backupPollTimer = window.setInterval(refreshLiveStatus, 15000);
