import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const pages = await readFile(new URL("../src/StitchPages.jsx", import.meta.url), "utf8");
const upload = await readFile(new URL("../src/upload.js", import.meta.url), "utf8");

test("startup loads status and knowledge before creating a session", () => {
  assert.match(app, /getProjectStatus/);
  assert.match(app, /getProjectKnowledge/);
  assert.match(app, /startInterviewSession\(.*projectId/);
  assert.doesNotMatch(app, /startInterviewSession\(projectDefinition/);
});

test("missing project id keeps upload inside the Agent composer attachment menu", () => {
  assert.match(app, /ProjectUploadControl/);
  assert.match(app, /attachment-menu/);
  assert.match(app, /aria-label="添加项目附件"/);
  assert.match(app, /webkitdirectory/);
  assert.match(app, /uploadProject/);
  assert.match(app, /createFolderUploadDescriptor/);
  assert.match(app, /localStorage/);
  assert.doesNotMatch(app, /throw new Error\("未配置项目 ID/);
});

test("missing project keeps the Agent chat shell instead of rendering a standalone upload page", () => {
  assert.match(app, /EmptyInterviewView/);
  assert.match(app, /setSession\(toUiSession\("", \{\}, \{\}/);
  assert.match(app, /needsUpload \?[\s\S]*EmptyInterviewView/);
  assert.match(app, /function EmptyInterviewView[\s\S]*agent-message/);
  assert.match(app, /function EmptyInterviewView[\s\S]*chat-composer/);
  assert.doesNotMatch(app, /function EmptyInterviewView[\s\S]*status-card upload-card/);
});

test("interview composer exposes project attachment control for an existing session", () => {
  assert.match(app, /function ProjectUploadControl/);
  assert.match(app, /<InterviewComposer[\s\S]*onUploaded=\{handleUploaded\}/);
  assert.match(app, /<ProjectUploadControl onUploaded=\{onUploaded\}/);
  assert.match(app, /添加项目上下文/);
});

test("workspace supports multiple persisted agent tasks", () => {
  assert.match(app, /const TASK_STORAGE_PREFIX/);
  assert.match(app, /readStoredTasks/);
  assert.match(app, /saveStoredTasks/);
  assert.match(app, /getSession\(task\.id\)/);
  assert.match(app, /startInterviewSession\(projectId, candidateId\)/);
  assert.match(pages, /最近会话/);
  assert.match(pages, /新建复盘/);
  assert.match(app, /选择文件夹作为工作区/);
});

test("recent sessions expose server-backed create read rename and delete actions", () => {
  assert.match(app, /renameSession\(task\.id, title\)/);
  assert.match(app, /deleteSession\(task\.id\)/);
  assert.match(app, /handleRenameTask/);
  assert.match(app, /handleDeleteTask/);
  assert.match(pages, /编辑会话名称/);
  assert.match(pages, /删除会话/);
  assert.match(pages, /onNewSession/);
});

test("workspace restores server-backed session history before local cache", () => {
  assert.match(app, /getSessions\(\{ projectId, candidateId \}\)/);
  assert.match(app, /tasksFromSessionList/);
  assert.match(app, /hasServerSessions/);
  assert.match(app, /getSession\(recentSession\.session_id\)/);
});

test("completed sessions lock answers and open the server-backed report", () => {
  assert.match(app, /completeSession\(session\.sessionId\)/);
  assert.match(app, /session\.sessionState === "completed"/);
  assert.match(app, /setActiveView\("report"\)/);
  assert.match(app, /本次会话已结束/);
  assert.match(app, /回答已锁定/);
});

test("candidate weakness sources open the matching report record", () => {
  assert.match(pages, /weakness_sources/);
  assert.match(pages, /onOpenSource/);
  assert.match(pages, /source\.session_id/);
  assert.match(app, /handleOpenWeaknessSource/);
  assert.match(app, /getSession\(source\.session_id\)/);
  assert.match(app, /setReportFocusIndex\(source\.record_index\)/);
  assert.match(app, /setActiveView\("report"\)/);
  assert.match(pages, /focusedRecordIndex/);
  assert.match(pages, /scrollIntoView/);
});

test("upload flow refreshes project knowledge and starts a candidate session", () => {
  assert.match(app, /VITE_CANDIDATE_ID/);
  assert.match(app, /candidateId[\s\S]*default|default[\s\S]*candidateId/);
  assert.match(app, /getProjectStatus\(projectId/);
  assert.match(app, /getProjectKnowledge\(projectId/);
  assert.match(app, /startInterviewSession\(projectId, candidateId\)/);
  assert.match(app, /setItem\(/);
});

test("project id is persisted only after the full session load succeeds", () => {
  const uploadIndex = app.indexOf("await uploadProject(descriptor)");
  const loadIndex = app.indexOf("const loaded = await loadInterviewSession(projectId");
  const saveIndex = app.lastIndexOf("saveProjectId(projectId)");
  assert.ok(uploadIndex >= 0);
  assert.ok(loadIndex > uploadIndex);
  assert.ok(saveIndex > loadIndex);
});

test("startup validates and clears invalid stored project ids", () => {
  assert.match(app, /normalizeProjectId/);
  assert.match(app, /clearStoredProjectId/);
  assert.match(upload, /Number\.isSafeInteger/);
  assert.match(app, /setProjectName\(selectedFolderName\(selectedFiles\)\)/);
});

test("any stored project recovery failure clears storage and returns to upload state", () => {
  assert.match(app, /projectIdSource === "storage"/);
  assert.match(app, /recoverStoredProjectFailure/);
  assert.match(app, /analysis_status/);
  assert.match(app, /clearStoredProjectId\(\)[\s\S]*return \{ needsUpload: true, configError:/);
  assert.match(app, /catch \(cause\)[\s\S]*recoverStoredProjectFailure\(cause\)/);
  assert.doesNotMatch(app, /projectIdSource === "env"[\s\S]*clearStoredProjectId/);
});

test("startup effect shares one promise across StrictMode cleanup and rerun", () => {
  assert.match(app, /useRef/);
  assert.match(app, /const startupPromiseRef = useRef\(null\)/);
  assert.match(app, /reusePromise\(startupPromiseRef, loadInterviewSession\)/);
  assert.match(app, /cleanup only suppresses state updates/);
});

test("session UI mapping uses project state and evidence ids", () => {
  assert.match(app, /state\.project/);
  assert.match(app, /state\.current_topic/);
  assert.match(app, /state\.question_evidence_ids/);
  assert.match(app, /state\.history/);
  assert.match(app, /state\.evaluation/);
  assert.doesNotMatch(app, /const initialSession/);
  assert.doesNotMatch(app, /const projectDefinition/);
});

test("empty knowledge, evidence, and evaluation states are explicit", () => {
  assert.match(pages, /暂无项目知识/);
  assert.match(app, /暂无证据/);
  assert.match(app, /暂无评价/);
  assert.match(app, /bootError/);
});

test("project materials distinguish waiting, analyzing, failed, and ready states", () => {
  assert.match(app, /const analysisStatus = String\(firstValue\(/);
  assert.match(app, /WAITING_FOR_PROJECT: \{ label: "等待项目"/);
  assert.match(app, /ANALYZING: \{ label: "正在分析"/);
  assert.match(app, /FAILED: \{ label: "分析失败"/);
  assert.match(app, /data-project-ready=\{isProjectReady \? "true" : "false"\}/);
  assert.match(app, /isProjectReady && \(insights\.find/);
  assert.match(app, /project-status-state/);
  assert.match(app, /project-tab-content \$\{isProjectReady \? "" : "is-hidden"\}/);
});

test("project materials keep evidence selection explicit and technical metadata secondary", () => {
  assert.match(app, /const currentEvidenceId = selectedEvidenceId;/);
  assert.match(app, /选择证据查看来源/);
  assert.match(app, /从结构树或事实中选择一项/);
  assert.match(app, /className="project-technical-details"/);
  assert.match(app, /className="project-evidence-empty"/);
});

test("answer submission adopts backend state without calculating score or profile", () => {
  assert.match(app, /setEvaluation\(state\.evaluation/);
  assert.match(app, /setHistory\(state\.history/);
  assert.match(app, /setSession\(toUiSession\(session\.sessionId, state/);
  assert.doesNotMatch(app, /const score = serverEvaluation\.score/);
  assert.doesNotMatch(app, /initialSession\.progress \+/);
});

test("answer submission uses streamed agent feedback and preserves non-perfect reference answers", () => {
  assert.match(app, /submitAnswerStream/);
  assert.match(app, /event === "chunk"/);
  assert.match(app, /event === "eval_chunk"/);
  assert.match(app, /setStreamingEval/);
  assert.match(app, /event === "usage"/);
  assert.match(app, /setTokenUsage/);
  assert.match(app, /TokenUsageCircle/);
  assert.match(app, /reference_answer/);
  assert.match(app, /streaming-cursor/);
});

test("answer feedback exposes a collapsible safe process summary and completed evaluation", () => {
  assert.match(app, /streamingSteps/);
  assert.match(app, /className="process-details"/);
  assert.match(app, /处理过程/);
  assert.match(app, /className="history-evaluation"/);
  assert.match(app, /record\.evaluation\.feedback/);
});

test("composer does not expose an unused Markdown toolbar", () => {
  assert.doesNotMatch(app, /insertMarkdown/);
  assert.doesNotMatch(app, /handleToolbarAction/);
  assert.doesNotMatch(app, /markdown-label/);
  assert.doesNotMatch(app, /aria-label="加粗"/);
  assert.doesNotMatch(app, /aria-label="代码"/);
});

test("chat history renders submitted answers in the conversation stream", () => {
  assert.match(app, /history\.map\(/);
  assert.match(app, /agent-message-user/);
  assert.match(app, /record\.answer/);
});

test("composer exposes busy state, keeps textarea editable while submitting, and offers stop", () => {
  assert.match(app, /aria-busy=\{isSubmitting\}/);
  assert.match(app, /disabled=\{disabled \|\| isSubmitting\}/);
  assert.match(app, /disabled=\{disabled\} \/>/);
  assert.match(app, /正在分析/);
  assert.match(app, /onStop=\{handleStopAnswer\}/);
  assert.match(app, /streamAbortRef\.current\?\.abort\(\)/);
  assert.match(app, /停止回答/);
  assert.match(app, /new AbortController\(\)/);
  assert.match(app, /pendingAnswer/);
});

test("attachment menu closes from Escape and outside pointer interaction", () => {
  assert.match(app, /document\.addEventListener\("pointerdown"/);
  assert.match(app, /event\.key === "Escape"/);
  assert.match(app, /attachmentRef\.current\?\.contains\(event\.target\)/);
});

test("interview header and structure controls expose real interactions", () => {
  assert.match(app, /const \[isQuestionMarked, setIsQuestionMarked\] = useState\(false\)/);
  assert.match(app, /onClick=\{handleBackToProject\}/);
  assert.match(app, /aria-pressed=\{isQuestionMarked\}/);
  assert.match(app, /const \[isMoreMenuOpen, setIsMoreMenuOpen\] = useState\(false\)/);
  assert.match(app, /aria-expanded=\{isMoreMenuOpen\}/);
  assert.match(app, /className="more-menu"/);
  assert.match(app, /onSelectStructure=\{handleStructureSelection\}/);
  assert.match(app, /selectedItem=\{selectedStructureItem\}/);
});

test("selecting another topic creates a new session for that topic", () => {
  const start = app.indexOf("async function handleStructureSelection");
  const end = app.indexOf("function handleMoreNavigation", start);
  const selectionBlock = app.slice(start, end);
  assert.match(selectionBlock, /handleCreateReviewSession/);
  assert.match(selectionBlock, /topic: child/);
  assert.match(selectionBlock, /title: `\$\{child\} ·/);
  assert.doesNotMatch(selectionBlock, /暂不支持直接切换题目/);
});

test("interview structure stays coarse and excludes project components", () => {
  const start = app.indexOf("const structure = useMemo");
  const end = app.indexOf("function handleBackToProject", start);
  const structureBlock = app.slice(start, end);
  assert.match(app, /const MAX_INTERVIEW_DIRECTIONS = 5/);
  assert.match(structureBlock, /label: "核心方向"/);
  assert.match(structureBlock, /session\.topic/);
  assert.match(structureBlock, /slice\(0, MAX_INTERVIEW_DIRECTIONS\)/);
  assert.match(structureBlock, /totalCount/);
  assert.doesNotMatch(structureBlock, /projectComponents/);
});

test("evidence actions are bound and the evaluation rubric is collapsible", () => {
  const evidencePanel = app.slice(app.indexOf('id="evidence-drawer"'));
  assert.match(evidencePanel, /<button className="text-button" type="button" onClick=\{handleOpenProjectKnowledge\}>查看全部/);
  assert.match(evidencePanel, /aria-controls="evaluation-rubric"/);
  assert.match(evidencePanel, /onClick=\{\(\) => setIsRubricOpen\(\(open\) => !open\)\}/);
  assert.match(evidencePanel, /<button className="quiet-button" type="button" onClick=\{handleOpenProjectKnowledge\}>[\s\S]*查看项目知识/);
  assert.match(evidencePanel, /id="evaluation-rubric"/);
  assert.match(evidencePanel, /关闭评分标准/);
  assert.match(evidencePanel, /收起证据面板/);
  assert.match(evidencePanel, /展开证据面板/);
});

test("project upload exposes phase-based progress feedback while waiting", () => {
  assert.match(app, /uploadPhase/);
  assert.match(app, /setUploadPhase\("reading"\)/);
  assert.match(app, /setUploadPhase\("uploading"\)/);
  assert.match(app, /setUploadPhase\("analyzing"\)/);
  assert.match(app, /setUploadPhase\("session"\)/);
  assert.match(app, /className="upload-progress"/);
  assert.match(app, /role="status"/);
  assert.match(app, /aria-live="polite"/);
});

test("project upload exposes two explicit processing modes", () => {
  assert.match(app, /uploadMode/);
  assert.match(app, /useState\("ask"\)/);
  assert.match(app, /role="radiogroup"/);
  assert.match(app, /role="radio"/);
  assert.match(app, /aria-checked=\{uploadMode === "ask"\}/);
  assert.match(app, /aria-checked=\{uploadMode === "knowledge"\}/);
  assert.match(app, /针对文件提问/);
  assert.match(app, /存入知识库/);
});

test("upload mode is visible in submit and progress feedback", () => {
  const modeIndex = app.indexOf("upload-mode-switch");
  const candidateIndex = app.indexOf("面试者 ID");
  const submitIndex = app.indexOf("attachment-submit");
  assert.ok(modeIndex >= 0);
  assert.ok(candidateIndex > modeIndex);
  assert.ok(submitIndex > candidateIndex);
  assert.match(app, /uploadMode === "knowledge"/);
  assert.match(app, /针对文件提问/);
  assert.match(app, /存入知识库/);
});

test("project upload exposes an intent mode after file selection", () => {
  const uploadControl = app.slice(app.indexOf("function ProjectUploadControl"));
  assert.match(uploadControl, /const \[uploadMode, setUploadMode\] = useState\("ask"\)/);
  assert.match(uploadControl, /role="radiogroup"/);
  assert.match(uploadControl, /role="radio"/);
  assert.match(uploadControl, /aria-checked/);
  assert.match(uploadControl, /value="ask"/);
  assert.match(uploadControl, /value="knowledge"/);
  assert.match(uploadControl, /\u9488\u5bf9\u6587\u4ef6\u63d0\u95ee/);
  assert.match(uploadControl, /\u5b58\u5165\u77e5\u8bc6\u5e93/);
  assert.match(uploadControl, /uploadMode[\s\S]*(\u5f53\u524d\u6a21\u5f0f|\u6a21\u5f0f)/);
});

test("both upload modes show completion feedback and keep the shared session flow", () => {
  assert.match(app, /const completionCopy = uploadMode === "knowledge"/);
  assert.match(app, /项目已存入知识库/);
  assert.match(app, /项目已准备完成/);
  assert.match(app, /uploadCompletion/);
  assert.match(app, /onUploaded\(loaded, completionMessage\)/);
  assert.match(app, /initialCompletion=\{uploadCompletion\}/);
  assert.match(app, /className="upload-completion"/);

  const uploadIndex = app.indexOf("await uploadProject(descriptor)");
  const loadIndex = app.indexOf("const loaded = await loadInterviewSession(projectId");
  const saveIndex = app.lastIndexOf("saveProjectId(projectId)");
  const callbackIndex = app.indexOf("onUploaded(loaded, completionMessage)");
  assert.ok(uploadIndex >= 0);
  assert.ok(loadIndex > uploadIndex);
  assert.ok(saveIndex > loadIndex);
  assert.ok(callbackIndex > saveIndex);
});
