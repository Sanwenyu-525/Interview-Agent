import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookmarkSimple,
  ChatCircleText,
  CheckCircle,
  Code,
  Cube,
  DotsThree,
  FileCode,
  FolderSimple,
  GearSix,
  GitBranch,
  ListBullets,
  MagnifyingGlass,
  Minus,
  Moon,
  Plus,
  ShieldWarning,
  Sparkle,
  Square,
  Sun,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useAutoDismiss } from "./useAutoDismiss.js";
import usePanelResize from "./usePanelResize.js";
import { EvidencePanel } from "./components/interview/EvidencePanel.jsx";
import { InterviewComposer } from "./components/interview/InterviewComposer.jsx";
import { InterviewThread } from "./components/interview/InterviewThread.jsx";
import { PageHeader } from "./components/PageHeader.jsx";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  activateLLMProfile,
  completeSession,
  createAgent,
  createLLMProfile,
  deleteAgent,
  deleteSession,
  deleteLLMProfile,
  getAgents,
  getLLMProfiles,
  getSession,
  getSessionReport,
  getCandidateProfile,
  getLLMSettings,
  getProjectKnowledge,
  getProjectStatus,
  getSessions,
  openProjectDirectory,
  pickProjectDirectory,
  reusePromise,
  renameSession,
  saveLLMSettings,
  startInterviewSession,
  submitAnswerStream,
  testLLMConnection,
  testLLMProfile,
  updateAgent,
  updateLLMProfile,
  uploadProject,
} from "./api";
import {
  CandidateProfileView,
  InterviewContextRail,
  PositionPreparationView,
  PrimarySidebar,
  ResumeLibraryView,
  reviewModeLabel,
  SessionReportView,
  SessionSetupView,
} from "./StitchPages";
import {
  createDirectoryUploadDescriptor,
  createFolderUploadDescriptor,
  folderNameFromPath,
  generateProjectId,
  normalizeProjectId,
  selectedFolderName,
} from "./upload";

const PROJECT_STORAGE_KEY = "interview-agent.project-id";
const TASK_STORAGE_PREFIX = "interview-agent.tasks";
const THEME_STORAGE_KEY = "interview-agent.theme";
const THEME_OPTIONS = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];
const DEFAULT_CANDIDATE_ID = "default";
const MAX_INTERVIEW_DIRECTIONS = 5;
const DEFAULT_CONTEXT_RAIL_WIDTH = 216;
const DEFAULT_EVIDENCE_PANEL_WIDTH = 372;
const MIN_CONTEXT_RAIL_WIDTH = 176;
const MAX_CONTEXT_RAIL_WIDTH = 360;
const MIN_EVIDENCE_PANEL_WIDTH = 280;
const MAX_EVIDENCE_PANEL_WIDTH = 520;
const MIN_CHAT_WIDTH = 360;
const MOBILE_PAGE_LABELS = {
  interview: "面试工作台",
  positions: "岗位准备",
  project: "项目资料",
  resumes: "简历库",
  report: "会话报告",
  profile: "能力画像",
  settings: "应用设置",
  "session-new": "新建复盘",
};

function readThemePreference() {
  try {
    const saved = globalThis.localStorage?.getItem(THEME_STORAGE_KEY);
    return THEME_OPTIONS.some((option) => option.value === saved) ? saved : "system";
  } catch {
    return "system";
  }
}

function resolveTheme(theme) {
  if (theme !== "system") return theme;
  return globalThis.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

function defaultContextRailWidth() {
  return (globalThis.innerWidth || 1440) <= 1220 ? 192 : DEFAULT_CONTEXT_RAIL_WIDTH;
}

function defaultEvidencePanelWidth() {
  return (globalThis.innerWidth || 1440) <= 1220 ? 310 : DEFAULT_EVIDENCE_PANEL_WIDTH;
}

const EMPTY_LLM_SETTINGS = {
  provider: "openai_compatible",
  provider_name: "custom",
  base_url: "",
  api_key: "",
  model: "",
  api_mode: "chat_completions",
  timeout: "60",
  temperature: "0.2",
};
const LLM_PROVIDER_PRESETS = {
  agnes: {
    provider: "openai_compatible",
    provider_name: "Agnes",
    base_url: "https://api.agnes-ai.cn/v1",
    models: ["agnes-2.0-flash", "agnes-2.5-flash", "agnes-2.5-pro", "agnes-2.5-pro-alpha"],
    description: "适合通用对话、编码和 Agent 工作流",
  },
  deepseek: {
    provider: "openai_compatible",
    provider_name: "DeepSeek",
    base_url: "https://api.deepseek.com",
    models: ["deepseek-v4-flash", "deepseek-v4-pro"],
    description: "适合代码理解、推理和项目复盘",
  },
  custom: {
    provider: "openai_compatible",
    provider_name: "自定义",
    base_url: "",
    models: [],
    model: "",
    description: "填写任意 OpenAI 兼容接口",
  },
};

const AGENT_ROLE_LABELS = {
  generalist: "全能面试官",
  questioner: "出题官",
  evaluator: "评分官",
  director: "策略官",
};

const UPLOAD_PHASES = {
  reading: { step: 1, label: "正在读取项目文件", detail: "检查文本文件和项目目录结构。" },
  uploading: { step: 2, label: "正在上传项目", detail: "把项目内容发送到本地分析服务。" },
  analyzing: { step: 3, label: "正在分析项目", detail: "提取项目结构、技术栈和关键证据。" },
  session: { step: 4, label: "正在建立面试会话", detail: "准备首个问题和项目上下文。" },
};
const UPLOAD_STEP_LABELS = ["读取文件", "上传项目", "分析项目", "建立会话"];

const DEV_FIXTURE = {
  project_id: 1,
  project_name: "开发模式项目",
  topics: [{ name: "项目理解", score: 0, evidence: [] }],
  components: {},
  evidence: {},
};

function CustomTitleBar({ resolvedTheme, onThemeChange }) {
  const [isTauriWindow, setIsTauriWindow] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [windowNotice, setWindowNotice] = useState("");
  const longPressTimerRef = useRef(null);
  const suppressClickRef = useRef(false);

  useEffect(() => {
    const desktopWindow = Boolean(globalThis.__TAURI_INTERNALS__);
    setIsTauriWindow(desktopWindow);
    if (!desktopWindow) return undefined;

    const currentWindow = getCurrentWindow();
    let unlistenResize;
    const syncMaximizedState = () => currentWindow.isMaximized().then(setIsMaximized);

    syncMaximizedState();
    currentWindow.onResized(syncMaximizedState).then((unlisten) => {
      unlistenResize = unlisten;
    });
    return () => unlistenResize?.();
  }, []);

  function restoreSystemTheme() {
    onThemeChange("system");
    setWindowNotice("已恢复跟随系统主题");
  }

  function handleThemePointerDown() {
    suppressClickRef.current = false;
    longPressTimerRef.current = setTimeout(() => {
      suppressClickRef.current = true;
      restoreSystemTheme();
    }, 600);
  }

  function clearLongPress() {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }

  function handleThemeClick() {
    clearLongPress();
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onThemeChange(resolvedTheme === "dark" ? "light" : "dark");
  }

  function handleThemeContextMenu(event) {
    event.preventDefault();
    clearLongPress();
    restoreSystemTheme();
  }

  async function handleWindowMinimize() {
    try {
      await getCurrentWindow().minimize();
    } catch (error) {
      setWindowNotice(`窗口操作失败：${error?.message || "请重启桌面应用"}`);
    }
  }

  async function handleWindowMaximize() {
    try {
      const currentWindow = getCurrentWindow();
      await currentWindow.toggleMaximize();
      setIsMaximized(await currentWindow.isMaximized());
    } catch (error) {
      setWindowNotice(`窗口操作失败：${error?.message || "请重启桌面应用"}`);
    }
  }

  async function handleWindowClose() {
    try {
      await getCurrentWindow().close();
    } catch (error) {
      setWindowNotice(`窗口操作失败：${error?.message || "请重启桌面应用"}`);
    }
  }

  return (
    <header className="app-titlebar">
      <div className="titlebar-brand">
        <span className="titlebar-mark"><Sparkle size={13} weight="duotone" /></span>
        <strong>Interview Agent</strong>
        <span>Evidence-first Interview Studio</span>
      </div>
      <div className="titlebar-drag-region" data-tauri-drag-region>{windowNotice && <span className="titlebar-notice" role="status">{windowNotice}</span>}</div>
      <div className="window-controls" aria-label="窗口控制">
        <button
          className="window-control window-control-theme"
          type="button"
          title={resolvedTheme === "dark" ? "切换到浅色主题（长按或右键恢复跟随系统）" : "切换到深色主题（长按或右键恢复跟随系统）"}
          aria-label={resolvedTheme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          onClick={handleThemeClick}
          onContextMenu={handleThemeContextMenu}
          onPointerDown={handleThemePointerDown}
          onPointerUp={clearLongPress}
          onPointerLeave={clearLongPress}
          onPointerCancel={clearLongPress}
        >
          {resolvedTheme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        {isTauriWindow && (
          <>
            <button className="window-control" type="button" aria-label="最小化窗口" onClick={handleWindowMinimize}><Minus size={15} /></button>
            <button className="window-control" type="button" aria-label={isMaximized ? "还原窗口" : "最大化窗口"} onClick={handleWindowMaximize}><Square size={12} /></button>
            <button className="window-control window-control-close" type="button" aria-label="关闭窗口" onClick={handleWindowClose}><X size={15} /></button>
          </>
        )}
      </div>
    </header>
  );
}

function AppWindow({ resolvedTheme, onThemeChange, children }) {
  return <div className="window-shell"><CustomTitleBar resolvedTheme={resolvedTheme} onThemeChange={onThemeChange} />{children}</div>;
}

function directionLabel(direction) {
  return {
    basic: "基础追问",
    deep: "深入追问",
    architecture: "架构追问",
  }[direction] || direction || "继续追问";
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "") ?? "";
}

function projectComponents(project) {
  if (Array.isArray(project?.components)) {
    return project.components.map((component) => ({
      name: firstValue(component.name, component.id, component.path),
      description: firstValue(component.description, component.kind),
      path: component.path || "",
      evidenceIds: component.evidence_ids || [],
    }));
  }
  return Object.entries(project?.components || {}).map(([name, description]) => ({
    name,
    description: typeof description === "string" ? description : "",
    path: "",
    evidenceIds: [],
  }));
}

function projectTopics(project) {
  return Array.isArray(project?.topics) ? project.topics : [];
}

function evidenceIdsForState(state, topic) {
  const questionEvidenceIds = state.question_evidence_ids;
  const ids = firstValue(
    questionEvidenceIds,
    state?.evidence_ids,
    state?.evaluation?.evidence_ids,
    topic?.evidence,
    topic?.evidence_ids,
  );
  return Array.isArray(ids) ? ids : ids ? [ids] : [];
}

function evidenceForState(state, project, topic, evidenceIds) {
  const evidenceMap = project?.evidence && typeof project.evidence === "object"
    ? project.evidence
    : {};
  const stateEvidence = Array.isArray(state?.evidence) ? state.evidence : [];
  const entries = evidenceIds
    .map((id) => evidenceMap[id] || stateEvidence.find((item) => item.id === id))
    .filter(Boolean);
  if (entries.length > 0) return entries[0];
  if (topic?.name && evidenceMap[topic.name]) return evidenceMap[topic.name];
  return null;
}

function languageFromPath(path) {
  const ext = String(path || "").split(".").pop()?.toLowerCase() || "";
  const byExtension = {
    java: "Java",
    py: "Python",
    js: "JavaScript",
    jsx: "React JSX",
    ts: "TypeScript",
    tsx: "React TSX",
    go: "Go",
    rs: "Rust",
    c: "C",
    h: "C 头文件",
    cpp: "C++",
    hpp: "C++ 头文件",
    cs: "C#",
    kt: "Kotlin",
    vue: "Vue",
    html: "HTML",
    css: "CSS",
    scss: "SCSS",
    less: "Less",
    json: "JSON",
    xml: "XML",
    yml: "YAML",
    yaml: "YAML",
    md: "Markdown",
    sql: "SQL",
    sh: "Shell",
    bat: "Batch",
    gradle: "Gradle",
  };
  return byExtension[ext] || "";
}

function normalizeEvidence(raw, evidenceIds) {
  if (!raw) {
    return { available: false, ids: evidenceIds, file: "", language: "", lines: [], explanation: "", locator: "", lineStart: 1 };
  }
  const excerpt = firstValue(raw.excerpt, raw.code, raw.content);
  const locator = firstValue(raw.locator, raw.location);
  const lineMatch = String(locator).match(/(?:line|lines?)\s*(\d+)/i)
    || String(locator).match(/(?:^|\D)(\d+)(?:\s*[-:]\s*\d+)?/);
  const lines = Array.isArray(raw.lines)
    ? raw.lines
    : excerpt
      ? String(excerpt).split("\n")
      : [];
  const file = firstValue(raw.source_path, raw.file, raw.path);
  return {
    available: true,
    ids: evidenceIds,
    file,
    language: firstValue(raw.language, raw.metadata?.language, languageFromPath(file)),
    lines,
    explanation: firstValue(raw.explanation, raw.description, raw.locator, raw.kind),
    locator,
    lineStart: Number(lineMatch?.[1] || 1),
    confidence: raw.confidence,
  };
}

function confidenceLabel(value) {
  const confidence = Number(value);
  if (!Number.isFinite(confidence)) return "";
  return confidence <= 1 ? confidence.toFixed(2) : String(confidence);
}

function processStepsForRecord(record) {
  const evaluation = record?.evaluation || {};
  const evidenceIds = Array.isArray(evaluation.evidence_ids) ? evaluation.evidence_ids : [];
  const score = Number.isFinite(Number(evaluation.score)) ? `${evaluation.score} 分` : "完成评价";
  return [
    evidenceIds.length > 0 ? `关联 ${evidenceIds.length} 条项目证据` : "读取当前问题和项目上下文",
    `完成回答评价（${score}）`,
    evaluation.reference_answer ? "整理基于项目证据的参考回答" : "回答达到满分，未生成参考回答",
    "生成下一道追问",
  ];
}

function toUiSession(sessionId, state = {}, knowledge = null, status = null) {
  let project = state.project || knowledge || {};
  if (knowledge && knowledge.project_id && state.project?.project_id === knowledge.project_id) {
    // 项目重新分析后，用最新知识库的证据覆盖会话快照中的旧证据。
    const mergedEvidence = { ...(state.project.evidence || {}), ...(knowledge.evidence || {}) };
    project = { ...state.project, evidence: mergedEvidence };
  }
  const topic = state.current_topic || {};
  const history = Array.isArray(state.history) ? state.history : [];
  const evidenceIds = evidenceIdsForState(state, topic);
  const rawEvidence = evidenceForState(state, project, topic, evidenceIds);
  const progress = firstValue(
    state.progress,
    state.completed_questions,
    state.progress_count,
    history.length,
  );
  const totalQuestions = firstValue(
    state.total_questions,
    state.question_total,
  );
  const metadata = [
    status?.source_type,
    status?.analyzer_id,
    project.identity?.artifact_type,
  ].filter(Boolean).join(" · ");

  return {
    sessionId,
    title: state.title || "",
    project,
    status,
    projectName: firstValue(project.project_name, project.identity?.name, status?.project_name),
    projectMeta: metadata,
    projectPath: firstValue(status?.workspace_path, project.project_path),
    progress,
    totalQuestions,
    topic: topic.name || "",
    topicScore: topic.score,
    questionNumber: firstValue(state.question_number, state.current_question_number),
    question: state.question || "",
    context: firstValue(state.context, topic.description),
    instruction: firstValue(state.instruction, state.question_guidance),
    questionAnalysis: state.question_analysis || "",
    evidence: normalizeEvidence(rawEvidence, evidenceIds),
    evidenceIds,
    evaluation: state.evaluation || null,
    history,
    nextDirection: state.next_direction || "",
    candidateId: state.candidate_id || DEFAULT_CANDIDATE_ID,
    reviewMode: state.review_mode || "technical_interview",
    sessionState: state.status || "waiting_answer",
    completedAt: state.completed_at || "",
    resumeClaims: Array.isArray(state.resume_claims) ? state.resume_claims : [],
    capabilityHints: [
      ...(Array.isArray(state.evaluation?.strengths) ? state.evaluation.strengths : []),
      ...(Array.isArray(state.evaluation?.weaknesses) ? state.evaluation.weaknesses : []),
      ...(Array.isArray(project.weaknesses) ? project.weaknesses : []),
    ],
  };
}

function errorMessage(error) {
  return error?.details?.error || error?.message || "未知错误";
}

function providerPresetKey(settings) {
  const providerName = String(settings?.provider_name || "").toLowerCase();
  const baseUrl = String(settings?.base_url || "").toLowerCase();
  if (providerName === "agnes" || baseUrl.includes("agnes-ai")) return "agnes";
  if (providerName === "deepseek" || baseUrl.includes("deepseek.com")) return "deepseek";
  return "custom";
}

function readStoredProjectId() {
  try {
    return globalThis.localStorage?.getItem(PROJECT_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function clearStoredProjectId() {
  try {
    globalThis.localStorage?.removeItem(PROJECT_STORAGE_KEY);
  } catch {
    // localStorage may be unavailable in private or restricted browser contexts.
  }
}

function saveProjectId(projectId) {
  try {
    globalThis.localStorage?.setItem(PROJECT_STORAGE_KEY, String(projectId));
  } catch {
    // localStorage may be unavailable in private or restricted browser contexts.
  }
}

function sessionProjectId(session) {
  return firstValue(session?.project?.project_id, session?.status?.project_id);
}

function taskStorageKey(projectId) {
  return `${TASK_STORAGE_PREFIX}.${projectId}`;
}

function readStoredTasks(projectId) {
  if (!projectId) return [];
  try {
    const raw = globalThis.localStorage?.getItem(taskStorageKey(projectId));
    const tasks = raw ? JSON.parse(raw) : [];
    return Array.isArray(tasks)
      ? tasks.filter((task) => task?.id && task?.name).slice(0, 50)
      : [];
  } catch {
    return [];
  }
}

function saveStoredTasks(projectId, tasks) {
  if (!projectId) return;
  try {
    globalThis.localStorage?.setItem(taskStorageKey(projectId), JSON.stringify(tasks.slice(0, 50)));
  } catch {
    // localStorage may be unavailable in private or restricted browser contexts.
  }
}

function taskFromSessionSummary(summary, index) {
  const modeLabels = {
    technical_interview: "技术面试",
    portfolio_review: "作品集评审",
    defense_review: "项目答辩",
  };
  const count = Number(summary?.question_count || 0);
  const mode = modeLabels[summary?.review_mode] || "复盘会话";
  return {
    id: summary?.session_id || "",
    name: summary?.title || `${mode} · ${count > 0 ? `${count} 题` : `任务 ${index + 1}`}`,
    createdAt: summary?.updated_at || "",
    summary,
  };
}

function tasksFromSessionList(payload) {
  return Array.isArray(payload?.sessions)
    ? payload.sessions
      .map((summary, index) => taskFromSessionSummary(summary, index))
      .filter((task) => task.id)
    : [];
}

function recoverStoredProjectFailure(cause) {
  clearStoredProjectId();
  return {
    needsUpload: true,
    configError: `已保存项目恢复失败：${errorMessage(cause)}`,
  };
}

async function loadInterviewSession(projectIdOverride = "", candidateIdOverride = "") {
  const candidateId = firstValue(
    candidateIdOverride,
    import.meta.env?.VITE_CANDIDATE_ID,
    DEFAULT_CANDIDATE_ID,
  );
  const fixtureEnabled = import.meta.env?.DEV && import.meta.env?.VITE_ENABLE_FIXTURE_FALLBACK === "true";
  const hasOverride = projectIdOverride !== undefined
    && projectIdOverride !== null
    && String(projectIdOverride).trim() !== "";
  const envProjectId = import.meta.env?.VITE_PROJECT_ID;
  const hasEnvProjectId = envProjectId !== undefined
    && envProjectId !== null
    && String(envProjectId).trim() !== "";
  let projectId = null;
  let projectIdSource = "none";

  if (hasOverride) {
    projectId = normalizeProjectId(projectIdOverride);
    if (projectId === null) return { needsUpload: true, configError: "项目 ID 必须是正整数。" };
    projectIdSource = "override";
  } else if (hasEnvProjectId) {
    projectId = normalizeProjectId(envProjectId);
    if (projectId === null) return { needsUpload: true, configError: "VITE_PROJECT_ID 必须是正整数。" };
    projectIdSource = "env";
  } else {
    const storedProjectId = readStoredProjectId();
    if (storedProjectId) {
      projectId = normalizeProjectId(storedProjectId);
      if (projectId === null) {
        clearStoredProjectId();
        return { needsUpload: true };
      }
      projectIdSource = "storage";
    }
  }

  if (!projectId) {
    if (fixtureEnabled) {
      const result = await startInterviewSession(DEV_FIXTURE, candidateId);
      return { ...result, knowledge: DEV_FIXTURE, status: { analysis_status: "READY", source_type: "fixture" } };
    }
    return { needsUpload: true };
  }

  try {
    const status = await getProjectStatus(projectId);
    if (status?.analysis_status && status.analysis_status !== "READY") {
      throw new Error(`项目分析状态为 ${status.analysis_status}${status.error ? `：${status.error}` : ""}`);
    }
    const knowledge = await getProjectKnowledge(projectId);
    const sessionList = await getSessions({ projectId, candidateId });
    const recentSession = sessionList?.sessions?.[0];
    if (recentSession?.session_id) {
      const existing = await getSession(recentSession.session_id);
      return {
        sessionId: recentSession.session_id,
        state: existing.state,
        knowledge,
        status,
        sessions: sessionList.sessions,
      };
    }
    const result = await startInterviewSession(projectId, candidateId);
    if (!result?.sessionId) throw new Error("面试会话创建失败：响应缺少 session_id");
    return { ...result, knowledge, status, sessions: [] };
  } catch (cause) {
    if (projectIdSource === "storage") return recoverStoredProjectFailure(cause);
    throw cause;
  }
}

function ProjectUploadControl({ onUploaded, onCreateTask = null, canCreateTask = false, workspaceName = "", initialError = "", initialCompletion = "", defaultOpen = false, pickProjectRef = null }) {
  const [files, setFiles] = useState([]);
  const [directoryPath, setDirectoryPath] = useState("");
  const [projectName, setProjectName] = useState("");
  const [candidateId, setCandidateId] = useState(
    firstValue(import.meta.env?.VITE_CANDIDATE_ID, DEFAULT_CANDIDATE_ID),
  );
  const [uploadMode, setUploadMode] = useState("ask");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadPhase, setUploadPhase] = useState("");
  const [uploadError, setUploadError] = useState(initialError);
  const [uploadCompletion, setUploadCompletion] = useState(initialCompletion);
  const [isOpen, setIsOpen] = useState(Boolean(initialError || defaultOpen));
  const attachmentRef = useRef(null);
  const fileInputRef = useRef(null);
  const isDesktop = Boolean(globalThis.__TAURI_INTERNALS__?.invoke);

  useEffect(() => {
    if (pickProjectRef) pickProjectRef.current = requestProjectPick;
  });

  function requestProjectPick() {
    if (isUploading) return;
    if (isDesktop) handlePickDirectory();
    else fileInputRef.current?.click();
  }

  useEffect(() => {
    if (!isOpen) return undefined;

    function handlePointerDown(event) {
      if (!attachmentRef.current?.contains(event.target)) setIsOpen(false);
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") setIsOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  function handleFileChange(event) {
    const selectedFiles = Array.from(event.target.files || []);
    setFiles(selectedFiles);
    setDirectoryPath("");
    setProjectName(selectedFolderName(selectedFiles));
    setUploadError("");
    setUploadCompletion("");
    setIsOpen(true);
    event.target.value = "";
  }

  async function handlePickDirectory() {
    if (isUploading) return;
    try {
      const selectedPath = await pickProjectDirectory();
      if (!selectedPath) return;
      setDirectoryPath(selectedPath);
      setFiles([]);
      setProjectName(folderNameFromPath(selectedPath));
      setUploadError("");
      setUploadCompletion("");
      setIsOpen(true);
    } catch (cause) {
      setUploadError(errorMessage(cause));
    }
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (isUploading) {
      setUploadError("上传正在进行中，请稍候。");
      return;
    }
    if (files.length === 0 && !directoryPath) {
      setUploadError("请先选择包含文本文件的项目目录。");
      return;
    }

    const projectId = generateProjectId();
    const normalizedCandidateId = candidateId.trim() || DEFAULT_CANDIDATE_ID;
    setIsUploading(true);
    setUploadPhase("reading");
    setUploadError("");
    setUploadCompletion("");
    try {
      const descriptor = directoryPath
        ? createDirectoryUploadDescriptor(directoryPath, { projectId, projectName })
        : await createFolderUploadDescriptor(files, { projectId, projectName });
      const skippedFiles = descriptor.source.skipped_files || [];
      setUploadPhase("uploading");
      await uploadProject(descriptor);
      setUploadPhase("analyzing");
      const loaded = await loadInterviewSession(projectId, normalizedCandidateId);
      if (loaded.needsUpload || !loaded.sessionId) {
        throw new Error(loaded.configError || "项目分析或面试会话创建未完成，请重试。" );
      }
      setUploadPhase("session");
      saveProjectId(projectId);
      const completionMessage = skippedFiles.length > 0
        ? `${completionCopy} 已跳过 ${skippedFiles.length} 个二进制文件。`
        : completionCopy;
      setUploadCompletion(completionMessage);
      setIsOpen(true);
      setFiles([]);
      setDirectoryPath("");
      onUploaded(loaded, completionMessage);
    } catch (cause) {
      setUploadError(errorMessage(cause));
    } finally {
      setIsUploading(false);
      setUploadPhase("");
    }
  }

  const currentUploadPhase = UPLOAD_PHASES[uploadPhase] || UPLOAD_PHASES.reading;
  const currentUploadStep = currentUploadPhase.step;
  const uploadModeLabel = uploadMode === "knowledge" ? "存入知识库" : "针对文件提问";
  const completionCopy = uploadMode === "knowledge"
    ? "项目已存入知识库，Agent 可以基于项目结构和证据继续提问。"
    : "项目已准备完成，可以开始针对文件提问。";

  return (
    <div className="attachment-control" ref={attachmentRef}>
      <button
        className="composer-icon-button"
        type="button"
        aria-label="添加项目附件"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        <Plus size={19} weight="bold" />
      </button>
      {isOpen && (
        <div className="attachment-menu" role="dialog" aria-label="添加项目上下文，管理工作区和任务">
          <div className="attachment-menu-header">
            <div>
              <strong>工作区和任务</strong>
              <small>{workspaceName ? `当前工作区：${workspaceName}` : "选择一个文件夹，让 Agent 在同一工作区内管理多个任务。"}</small>
            </div>
            <button className="icon-button" type="button" aria-label="关闭附件菜单" onClick={() => setIsOpen(false)}><X size={17} /></button>
          </div>
          <div className="attachment-actions">
            {isDesktop ? (
              <button className="attachment-option" type="button" disabled={isUploading} onClick={handlePickDirectory}>
                <FolderSimple size={22} weight="duotone" />
                <span>
                  <strong>{directoryPath ? folderNameFromPath(directoryPath) : "选择文件夹作为工作区"}</strong>
                  <small>{directoryPath ? directoryPath : "通过系统对话框选择包含源码、配置和文档的文件夹"}</small>
                </span>
                <ArrowRight size={16} />
              </button>
            ) : (
              <label className="attachment-option">
                <input
                  className="upload-input"
                  type="file"
                  webkitdirectory=""
                  multiple
                  disabled={isUploading}
                  onChange={handleFileChange}
                  ref={fileInputRef}
                />
                <FolderSimple size={22} weight="duotone" />
                <span>
                  <strong>{files.length ? `已选择 ${files.length} 个文件` : "选择文件夹作为工作区"}</strong>
                  <small>{files.length ? "可以重新选择目录" : "选择包含源码、配置和文档的文件夹"}</small>
                </span>
                <ArrowRight size={16} />
              </label>
            )}
            <button className="attachment-option attachment-task-option" type="button" disabled={!canCreateTask || isUploading} onClick={() => { setIsOpen(false); onCreateTask?.(); }}>
              <ChatCircleText size={22} weight="duotone" />
              <span>
                <strong>新建任务</strong>
                <small>{canCreateTask ? "在当前工作区开启一个新的 Agent 会话" : "先选择一个工作区"}</small>
              </span>
              <Plus size={16} />
            </button>
          </div>
          {uploadCompletion && <div className="upload-completion" role="status" aria-live="polite"><CheckCircle size={17} weight="fill" /><span>{uploadCompletion}</span></div>}
          {(files.length > 0 || directoryPath) && (
            <form className="attachment-form" onSubmit={handleUpload}>
              <div className="attachment-selection"><FolderSimple size={18} /><span><strong>{projectName || "未命名项目"}</strong><small>{directoryPath || `${files.length} 个文件`} · 单文件 10MB · 总计 100MB</small></span></div>
              <label className="upload-field">
                <span>项目名称</span>
                <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="默认使用目录名称" />
              </label>
              <div className="upload-mode-field">
                <span className="upload-field-label">文件处理方式</span>
                <div className="upload-mode-switch" role="radiogroup" aria-label="文件处理方式">
                  <button className={uploadMode === "ask" ? "is-selected" : ""} type="button" role="radio" value="ask" aria-checked={uploadMode === "ask"} onClick={() => setUploadMode("ask")} disabled={isUploading}>针对文件提问</button>
                  <button className={uploadMode === "knowledge" ? "is-selected" : ""} type="button" role="radio" value="knowledge" aria-checked={uploadMode === "knowledge"} onClick={() => setUploadMode("knowledge")} disabled={isUploading}>存入知识库</button>
                </div>
                <small className="upload-mode-current">当前模式：{uploadModeLabel}</small>
              </div>
              <label className="upload-field">
                <span>面试者 ID</span>
                <input value={candidateId} onChange={(event) => setCandidateId(event.target.value)} placeholder={DEFAULT_CANDIDATE_ID} />
              </label>
              {isUploading && (
                <div className="upload-progress" role="status" aria-live="polite">
                  <span className="upload-spinner" aria-hidden="true" />
                  <span className="upload-progress-copy"><strong>{currentUploadPhase.label}</strong><small>{uploadModeLabel}：{currentUploadPhase.detail}</small></span>
                  <span className="upload-progress-step">{currentUploadStep} / {UPLOAD_STEP_LABELS.length}</span>
                </div>
              )}
              {isUploading && <div className="upload-steps" aria-label="项目上传进度">{UPLOAD_STEP_LABELS.map((label, index) => <span className={currentUploadStep > index + 1 ? "is-done" : currentUploadStep === index + 1 ? "is-current" : ""} key={label}>{index + 1}. {label}</span>)}</div>}
              {uploadError && <div className="form-error"><WarningCircle size={17} /> {uploadError}</div>}
              <button className="primary-button attachment-submit" type="submit" disabled={isUploading}>
                {isUploading ? `${uploadModeLabel}：读取并分析中...` : `${uploadModeLabel}并开始面试`} <ArrowRight size={18} weight="bold" />
              </button>
            </form>
          )}
          {uploadError && files.length === 0 && !directoryPath && <div className="form-error"><WarningCircle size={17} /> {uploadError}</div>}
          <p className="upload-note">{isDesktop ? "服务端直接读取所选目录中的 UTF-8 文本文件，二进制文件自动忽略；限制与浏览器上传一致。" : "支持 UTF-8 文本文件；ZIP、multipart 和二进制文件仍不在浏览器上传范围内。"}</p>
        </div>
      )}
    </div>
  );
}

function EmptyInterviewView({ onUploaded, initialError }) {
  const pickProjectRef = useRef(null);
  return (
    <section className="workspace empty-workspace" aria-label="面试工作台">
      <header className="workspace-header">
        <div className="question-breadcrumb"><span className="workspace-marker" />面试工作台</div>
        <div className="header-actions"><div className="engine-status"><span className="status-dot" />面试引擎在线</div></div>
      </header>
      <div className="workspace-content agent-workspace-content">
        <div className="agent-thread">
          <div className="agent-thread-heading"><span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span><span><strong>Interview Agent</strong><small>项目理解与面试教练</small></span><span className="thread-state">等待项目上下文</span></div>
                     <div className="agent-message-list">
  <article className="agent-message agent-message-agent">
              <span className="agent-avatar"><Sparkle size={17} weight="duotone" /></span>
              <div className="agent-message-body"><span className="message-meta">Interview Agent · 现在</span><div className="message-bubble"><p>你好，我会先理解你的项目结构、技术选择和关键流程，再围绕真实证据开始面试。</p><p>添加项目目录后，我会提取结构、技术栈、流程和证据，再开始提问。</p></div></div>
            </article>
            <div className="agent-system-message empty-project-action"><FolderSimple size={18} /><span><strong>还没有项目上下文</strong><small>添加项目后，这里会出现分析进度、首个问题和追问记录。</small><small className="empty-project-capability">支持源码、配置和 UTF-8 文本文档</small></span><button className="primary-button empty-add-project-button" type="button" onClick={() => pickProjectRef.current?.()}><FolderSimple size={16} /> 添加项目目录</button></div>
          </div>
        </div>
        <InterviewComposer disabled placeholder="先添加项目，再告诉 Agent 你想重点准备什么…" uploadControl={<ProjectUploadControl onUploaded={onUploaded} pickProjectRef={pickProjectRef} initialError={initialError} />} />
      </div>
    </section>
  );
}

function ProjectView({ session, onAddProject = () => {} }) {
  const [isOpeningDirectory, setIsOpeningDirectory] = useState(false);
  const [directoryError, setDirectoryError] = useState("");
  const [projectSearch, setProjectSearch] = useState("");
  const [activeProjectTab, setActiveProjectTab] = useState("overview");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState("");
  const [selectedProjectItem, setSelectedProjectItem] = useState("");
  const universalModel = session.status?.universal_model || {};
  const projectSource = Array.isArray(universalModel.components) ? universalModel : session.project;
  const topicSource = Array.isArray(universalModel.topics) ? universalModel : session.project;
  const components = projectComponents(projectSource);
  const topics = projectTopics(topicSource);
  const structureNodes = Array.isArray(universalModel.structure) ? universalModel.structure : [];
  const technologies = Array.isArray(universalModel.technologies) ? universalModel.technologies : [];
  const relations = Array.isArray(universalModel.relations) ? universalModel.relations : [];
  const flows = Array.isArray(universalModel.flows) ? universalModel.flows : [];
  const insights = Array.isArray(universalModel.insights) ? universalModel.insights : [];
  const analysisStatus = String(firstValue(
    session.status?.analysis_status,
    session.project?.project_id ? "READY" : "WAITING_FOR_PROJECT",
  )).toUpperCase();
  const isProjectReady = analysisStatus === "READY";
  const analysisStatusCopy = {
    WAITING_FOR_PROJECT: { label: "等待项目", title: "尚未添加项目", detail: "添加项目目录后，系统会提取结构、技术栈、流程和可追溯证据。" },
    ANALYZING: { label: "正在分析", title: "项目分析进行中", detail: "项目结构和证据准备完成后，这里会显示可复盘的项目资料。" },
    FAILED: { label: "分析失败", title: "项目分析未完成", detail: session.status?.error || "请检查项目内容后重试分析。" },
  }[analysisStatus] || { label: analysisStatus, title: "项目资料暂不可用", detail: "项目资料准备完成后，这里会显示结构、知识和证据。" };

  if (!isProjectReady) {
    return (
      <div className="project-intelligence" data-project-ready="false">
        <section className={`project-status-state is-${analysisStatus.toLowerCase()}`} aria-live="polite">
          <span className="project-status-icon"><FolderSimple size={24} /></span>
          <h2>{analysisStatusCopy.title}</h2>
          <p>{analysisStatusCopy.detail}</p>
          {analysisStatus === "WAITING_FOR_PROJECT" && (
            <>
              <button className="primary-button project-add-project-button" type="button" onClick={onAddProject}><FolderSimple size={16} /> 添加项目目录</button>
              <small>支持源码、配置和 UTF-8 文本文档</small>
            </>
          )}
          {analysisStatus === "FAILED" && <button className="primary-button project-add-project-button" type="button" onClick={onAddProject}>回到面试工作台重试</button>}
        </section>
      </div>
    );
  }

  const fallbackStructure = components.map((component, index) => ({
    id: component.name || `component-${index}`,
    name: component.name,
    path: component.path,
    kind: "component",
    evidence_ids: component.evidenceIds,
  }));
  const visibleStructure = structureNodes.length > 0 ? structureNodes : fallbackStructure;
  const normalizedSearch = projectSearch.trim().toLowerCase();
  const filteredStructure = visibleStructure.filter((item) => {
    if (!normalizedSearch) return true;
    return [item.name, item.path, item.kind].some((value) => String(value || "").toLowerCase().includes(normalizedSearch));
  });
  const legacyEvidence = Object.entries(session.project?.evidence || {}).map(([id, value]) => ({
    id,
    ...(value && typeof value === "object" ? value : {}),
  }));
  const evidenceEntries = Array.isArray(universalModel.evidence) && universalModel.evidence.length > 0
    ? universalModel.evidence
    : legacyEvidence;
  const currentEvidenceId = selectedEvidenceId;
  const selectedEvidenceRaw = currentEvidenceId
    ? evidenceEntries.find((item) => item.id === currentEvidenceId) || null
    : null;
  const selectedEvidence = normalizeEvidence(selectedEvidenceRaw, currentEvidenceId ? [currentEvidenceId] : []);
  const selectedComponent = components.find((component) => component.name === selectedProjectItem);
  const activeFlow = flows[0] || null;
  const dependencyEntries = Object.entries(session.project?.dependencies || {});
  const flowSteps = activeFlow?.component_ids?.length
    ? activeFlow.component_ids
    : dependencyEntries[0]
      ? [dependencyEntries[0][0], ...dependencyEntries[0][1]]
      : [];
  const risk = isProjectReady && (insights.find((item) => ["risk", "weakness", "gap"].includes(String(item.kind || "").toLowerCase()))?.summary
    || session.project?.weaknesses?.[0]
    || "");
  const linkedFacts = [
    ...components
      .filter((component) => component.evidenceIds.includes(currentEvidenceId))
      .map((component) => ({ label: component.name, kind: component.description || "组件" })),
    ...topics
      .filter((topic) => (topic.evidence_ids || topic.evidence || []).includes(currentEvidenceId))
      .map((topic) => ({ label: topic.name, kind: "可提问主题" })),
  ];
  const artifactType = firstValue(universalModel.identity?.artifact_type, session.projectMeta);
  const analyzerId = firstValue(session.status?.analyzer_id, "未指定");
  const schemaVersion = firstValue(session.status?.schema_version, "未指定");

  async function handleOpenDirectory() {
    if (!session.projectPath) {
      setDirectoryError("API 未提供项目目录路径。");
      return;
    }
    setIsOpeningDirectory(true);
    setDirectoryError("");
    try {
      await openProjectDirectory(session.projectPath);
    } catch (error) {
      setDirectoryError(errorMessage(error));
    } finally {
      setIsOpeningDirectory(false);
    }
  }

  function selectProjectEvidence(evidenceIds = [], label = "") {
    setSelectedProjectItem(label);
    if (evidenceIds[0]) setSelectedEvidenceId(evidenceIds[0]);
  }

  return (
    <div className="project-intelligence" data-project-ready={isProjectReady ? "true" : "false"}>
      <PageHeader
        kicker="项目资料"
        title={session.projectName || universalModel.identity?.name || "未命名项目"}
        description={`${artifactType || "项目类型未知"} · ${evidenceEntries.length} 条可追溯证据`}
        actions={(
          <>
            <details className="project-technical-details">
              <summary>技术详情</summary>
              <span>分析器：{analyzerId}</span><span>模型版本：{schemaVersion}</span>
            </details>
            <button className="project-open-button ui-button ui-button-secondary" type="button" onClick={handleOpenDirectory} disabled={isOpeningDirectory}>
              <ArrowUpRight size={16} /> {isOpeningDirectory ? "正在打开" : "打开项目目录"}
            </button>
          </>
        )}
      />
      {directoryError && <div className="form-error project-directory-error"><WarningCircle size={15} /> {directoryError}</div>}
      <aside className="project-structure-pane" aria-label="项目结构">
        <div className="project-structure-heading">
          <div><strong>项目结构</strong><small>{visibleStructure.length} 个节点</small></div>
          <span className={`analysis-ready is-${analysisStatus.toLowerCase()}`}><span className="status-dot" />{isProjectReady ? "已就绪" : analysisStatusCopy.label}</span>
        </div>
          <label className="project-search ui-field">
          <MagnifyingGlass size={15} />
          <input value={projectSearch} onChange={(event) => setProjectSearch(event.target.value)} placeholder="搜索项目结构" />
        </label>
        <div className="project-tree" role="tree" aria-label="项目文件和结构节点">
          {filteredStructure.length === 0 ? <div className="empty-state">没有匹配的结构节点</div> : filteredStructure.map((item) => {
            const itemLabel = firstValue(item.name, item.path, item.id);
            const itemEvidence = item.evidence_ids || [];
            const isSelected = selectedProjectItem === itemLabel;
            return (
              <button
                className={`project-tree-item ${isSelected ? "is-selected" : ""}`}
                type="button"
                role="treeitem"
                aria-selected={isSelected}
                key={item.id || itemLabel}
                onClick={() => selectProjectEvidence(itemEvidence, itemLabel)}
              >
                {String(item.kind || "").includes("directory") ? <FolderSimple size={15} /> : <FileCode size={15} />}
                <span><strong>{itemLabel}</strong><small>{item.path || item.kind || "结构节点"}</small></span>
              </button>
            );
          })}
        </div>
        <div className="project-structure-footer"><span>{visibleStructure.length} 个结构节点</span><span>{evidenceEntries.length} 条证据</span></div>
      </aside>

      <main className="project-knowledge-pane">
        {directoryError && <div className="form-error project-directory-error"><WarningCircle size={15} /> {directoryError}</div>}
        <nav className={`project-tabs ${isProjectReady ? "" : "is-hidden"}`} aria-label="项目智能资料视图">
          {[
            ["overview", "概览"],
            ["components", "组件"],
            ["flows", "调用链"],
            ["topics", "风险与主题"],
          ].map(([value, label]) => (
            <button className={activeProjectTab === value ? "is-active" : ""} type="button" key={value} onClick={() => setActiveProjectTab(value)}>{label}</button>
          ))}
        </nav>

        <div className={`project-tab-content ${isProjectReady ? "" : "is-hidden"}`}>
          {activeProjectTab === "overview" && (
            <>
              <section className={`project-risk-banner ${risk ? "" : "is-clear"} ui-status`} data-tone={risk ? "warning" : "success"}>
                {risk ? <ShieldWarning size={18} weight="duotone" /> : <CheckCircle size={18} />}
                <span><strong>{risk ? "识别到项目风险" : "暂无明确风险"}</strong><small>{risk || "当前项目知识中没有可展示的风险事实。"}</small></span>
              </section>
              <div className="project-overview-grid">
                <section className="project-fact-section">
                  <div className="project-section-heading"><span><GitBranch size={17} /> 核心调用链</span><small>{flows.length || dependencyEntries.length} 条</small></div>
                  {flowSteps.length === 0 ? <div className="empty-state">暂无调用链数据</div> : (
                    <>
                      <strong className="project-flow-name">{activeFlow?.name || dependencyEntries[0]?.[0] || "项目依赖"}</strong>
                      <div className="project-flow-chain">
                        {flowSteps.map((step, index) => <span key={`${step}-${index}`}><code>{step}</code>{index < flowSteps.length - 1 && <ArrowRight size={13} />}</span>)}
                      </div>
                      {activeFlow?.description && <p>{activeFlow.description}</p>}
                    </>
                  )}
                </section>
                <section className="project-fact-section">
                  <div className="project-section-heading"><span><Cube size={17} /> 已识别组件</span><small>{components.length} 个</small></div>
                  {components.length === 0 ? <div className="empty-state">暂无组件数据</div> : <div className="project-component-chips">{components.slice(0, 8).map((component) => <button type="button" className={selectedComponent?.name === component.name ? "is-selected" : ""} key={component.name} onClick={() => selectProjectEvidence(component.evidenceIds, component.name)}>{component.name}</button>)}</div>}
                </section>
              </div>
              <section className="project-fact-section project-tech-section">
                <div className="project-section-heading"><span><Code size={17} /> 技术栈与依赖</span><small>{technologies.length} 项</small></div>
                {technologies.length === 0 ? <div className="empty-state">暂无技术栈数据</div> : <div className="project-technology-list">{technologies.map((technology) => <button type="button" key={`${technology.category}-${technology.name}`} onClick={() => selectProjectEvidence(technology.evidence_ids || [], technology.name)}><span className="tech-dot" /><strong>{technology.name}</strong>{technology.version && <small>{technology.version}</small>}</button>)}</div>}
              </section>
            </>
          )}

          {activeProjectTab === "components" && (
            <section className="project-fact-section">
              <div className="project-section-heading"><span><Cube size={17} /> 项目组件</span><small>{components.length} 个</small></div>
              {components.length === 0 ? <div className="empty-state">暂无组件数据</div> : <div className="project-component-list">{components.map((component) => <button type="button" key={component.name} onClick={() => selectProjectEvidence(component.evidenceIds, component.name)}><FileCode size={17} /><span><strong>{component.name}</strong><small>{component.path || component.description || "暂无说明"}</small></span><span>{component.evidenceIds.length} 条证据</span></button>)}</div>}
            </section>
          )}

          {activeProjectTab === "flows" && (
            <div className="project-flow-list">
              {flows.length === 0 && relations.length === 0 ? <div className="empty-state">暂无调用链或关系数据</div> : (
                <>
                  {flows.map((flow) => <button type="button" className="project-flow-row" key={flow.id || flow.name} onClick={() => selectProjectEvidence(flow.evidence_ids || [], flow.name)}><GitBranch size={18} /><span><strong>{flow.name}</strong><small>{flow.description || (flow.component_ids || []).join(" → ") || "暂无说明"}</small></span><span>{(flow.evidence_ids || []).length} 条证据</span></button>)}
                  {relations.map((relation, index) => <button type="button" className="project-flow-row" key={`${relation.source_id}-${relation.target_id}-${index}`} onClick={() => selectProjectEvidence(relation.evidence_ids || [], relation.description)}><ArrowRight size={18} /><span><strong>{relation.source_id} → {relation.target_id}</strong><small>{relation.description || relation.kind || "项目关系"}</small></span><span>{(relation.evidence_ids || []).length} 条证据</span></button>)}
                </>
              )}
            </div>
          )}

          {activeProjectTab === "topics" && (
            <div className="project-topic-board">
              <section className="project-fact-section">
                <div className="project-section-heading"><span><ListBullets size={17} /> 可提问主题</span><small>{topics.length} 个</small></div>
                {topics.length === 0 ? <div className="empty-state">暂无项目主题</div> : topics.map((topic) => <button className="project-topic-item" type="button" key={topic.name} onClick={() => selectProjectEvidence(topic.evidence_ids || topic.evidence || [], topic.name)}><span><strong>{topic.name}</strong><small>{(topic.evidence_ids || topic.evidence || []).join(" · ") || "暂无证据映射"}</small></span><b>{topic.score ?? "—"}</b></button>)}
              </section>
              <section className="project-fact-section">
                <div className="project-section-heading"><span><ShieldWarning size={17} /> 风险与薄弱点</span><small>{session.project?.weaknesses?.length || 0} 项</small></div>
                {(session.project?.weaknesses || []).length === 0 ? <div className="empty-state">暂无项目风险</div> : <ul className="project-risk-list">{session.project.weaknesses.map((item) => <li key={item}>{item}</li>)}</ul>}
              </section>
            </div>
          )}
        </div>
      </main>

      <aside className="project-evidence-pane" aria-label="证据追溯">
        <div className="project-evidence-heading">
          <div><span className="view-kicker">证据追溯</span><h2>{selectedEvidence.available ? (selectedEvidence.file || selectedProjectItem || "已选证据") : "选择证据查看来源"}</h2></div>
          {confidenceLabel(selectedEvidence.confidence) && <span className="confidence-badge">置信度 {confidenceLabel(selectedEvidence.confidence)}</span>}
        </div>
        {selectedEvidence.available ? (
          <>
            <div className="project-evidence-meta"><span>{selectedEvidence.locator || "未提供定位"}</span><span>{selectedEvidence.language || selectedEvidenceRaw?.kind || "文本"}</span></div>
            {selectedEvidence.lines.length > 0 ? <div className="code-block project-code-block">{selectedEvidence.lines.map((line, index) => <div className={line.includes("//") ? "code-line comment" : "code-line"} key={`${line}-${index}`}><span>{String(selectedEvidence.lineStart + index).padStart(2, "0")}</span><code>{line}</code></div>)}</div> : <div className="empty-state">证据没有可展示的摘录</div>}
            <p className="project-evidence-description">{selectedEvidence.explanation || "暂无证据说明"}</p>
            <section className="linked-facts">
              <div className="project-section-heading"><span>关联事实</span><small>{linkedFacts.length} 项</small></div>
              {linkedFacts.length === 0 ? <div className="empty-state">暂无关联事实</div> : linkedFacts.map((fact) => <div className="linked-fact" key={`${fact.kind}-${fact.label}`}><span>{fact.kind}</span><strong>{fact.label}</strong></div>)}
            </section>
            <details className="project-technical-details evidence-technical-details"><summary>技术详情</summary><span>Evidence ID</span><code>{currentEvidenceId || "—"}</code></details>
          </>
        ) : <div className="project-evidence-empty"><FileCode size={21} /><strong>从结构树或事实中选择一项</strong><p>选择后，这里会显示文件、位置、摘要和关联事实。</p></div>}
      </aside>
    </div>
  );
}

function SettingsView({ settings, profiles, profilesLoading, isLoading, isSaving, isTesting, notice, error, onSave, onTest, onCreateProfile, onUpdateProfile, onDeleteProfile, onActivateProfile, onTestProfile, agents, agentsLoading, agentNotice, agentError, isAgentSaving, onCreateAgent, onUpdateAgent, onDeleteAgent, theme, onThemeChange }) {
  const [form, setForm] = useState(EMPTY_LLM_SETTINGS);
  const [selectedProvider, setSelectedProvider] = useState("custom");
  const [editingProfileId, setEditingProfileId] = useState("");
  const [profileName, setProfileName] = useState("");
  const [profileActionId, setProfileActionId] = useState("");
  const [formError, setFormError] = useState("");
  const [profileTestResult, setProfileTestResult] = useState(null);
  const [editingAgent, setEditingAgent] = useState(null);
  const [agentForm, setAgentForm] = useState({ name: "", role: "questioner", persona: "", profile_id: "" });
  const [agentFormError, setAgentFormError] = useState("");
  const [agentActionId, setAgentActionId] = useState("");
  const [settingsTab, setSettingsTab] = useState("llm");
  const [profileFormOpen, setProfileFormOpen] = useState(false);
  const [formBaseline, setFormBaseline] = useState(() => JSON.stringify({ ...EMPTY_LLM_SETTINGS, profile_name: "" }));

  useEffect(() => {
    if (!settings) return;
    const nextForm = {
      ...EMPTY_LLM_SETTINGS,
      ...settings,
      api_key: "",
      timeout: String(settings.timeout ?? 60),
      temperature: String(settings.temperature ?? 0.2),
    };
    setForm(nextForm);
    setSelectedProvider(providerPresetKey(settings));
    if (!editingProfileId) {
      setProfileName("");
      setFormBaseline(JSON.stringify({ ...nextForm, profile_name: "" }));
    }
  }, [settings]);

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
    if (["provider", "base_url", "api_key"].includes(name)) {
      setFormError("");
    }
  }

  function applyProviderPreset(providerKey) {
    const preset = LLM_PROVIDER_PRESETS[providerKey];
    if (!preset) return;
    const nextForm = {
      ...form,
      ...preset,
      model: "",
      api_key: form.api_key,
      api_mode: "chat_completions",
    };
    setSelectedProvider(providerKey);
    setForm(nextForm);
  }

  function startNewProfile() {
    setEditingProfileId("");
    setProfileName("");
    setForm(EMPTY_LLM_SETTINGS);
    setSelectedProvider("custom");
    setFormError("");
    setProfileTestResult(null);
    setProfileFormOpen(true);
    setFormBaseline(JSON.stringify({ ...EMPTY_LLM_SETTINGS, profile_name: "" }));
  }

  function cancelProfileForm() {
    setEditingProfileId("");
    setProfileName("");
    setForm(EMPTY_LLM_SETTINGS);
    setSelectedProvider("custom");
    setFormError("");
    setProfileTestResult(null);
    setProfileFormOpen(false);
  }

  function startEditProfile(profile) {
    const nextForm = {
      ...EMPTY_LLM_SETTINGS,
      ...profile,
      api_key: "",
      timeout: String(profile.timeout ?? 60),
      temperature: String(profile.temperature ?? 0.2),
    };
    setEditingProfileId(profile.id);
    setProfileName(profile.name || "");
    setForm(nextForm);
    setSelectedProvider(providerPresetKey(profile));
    setFormError("");
    setProfileTestResult(null);
    setProfileFormOpen(true);
    setFormBaseline(JSON.stringify({ ...nextForm, profile_name: profile.name || "" }));
  }

  function payload() {
    const next = {
      ...form,
      timeout: Number(form.timeout),
      temperature: Number(form.temperature),
    };
    if (!next.api_key.trim()) delete next.api_key;
    return next;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const nextPayload = { ...payload(), name: profileName.trim() };
    if (!nextPayload.name) {
      setFormError("请先填写配置名称。");
      return;
    }
    if (editingProfileId) {
      await onUpdateProfile(editingProfileId, nextPayload);
      cancelProfileForm();
    } else {
      await onCreateProfile(nextPayload);
      cancelProfileForm();
    }
  }

  async function handleTest() {
    await onTest(payload());
  }

  async function handleProfileAction(action, profileId) {
    setProfileActionId(profileId);
    try {
      await action(profileId);
    } finally {
      setProfileActionId("");
    }
  }

  async function handleProfileTest(profileId) {
    setProfileActionId(profileId);
    setProfileTestResult(null);
    try {
      const result = await onTestProfile(profileId);
      setProfileTestResult({ profileId, status: "success", message: result.message || "连接测试成功。" });
    } catch (cause) {
      setProfileTestResult({ profileId, status: "error", message: `连接测试失败：${errorMessage(cause)}` });
    } finally {
      setProfileActionId("");
    }
  }

  async function handleDelete(profileId) {
    if (!globalThis.confirm?.("确定删除这个大模型配置吗？")) return;
    await handleProfileAction(onDeleteProfile, profileId);
    if (editingProfileId === profileId) startNewProfile();
  }

  function startNewAgent() {
    setEditingAgent(null);
    setAgentForm({ name: "", role: "questioner", persona: "", profile_id: "" });
    setAgentFormError("");
  }

  function startEditAgent(agent) {
    setEditingAgent(agent);
    setAgentForm({ name: agent.name, role: agent.role, persona: agent.persona, profile_id: agent.profile_id || "" });
    setAgentFormError("");
  }

  async function handleAgentSubmit(event) {
    event.preventDefault();
    const next = { ...agentForm, name: agentForm.name.trim(), persona: agentForm.persona.trim() };
    if (!next.name || !next.persona) {
      setAgentFormError("请填写 Agent 名称和角色设定。");
      return;
    }
    if (editingAgent) {
      await onUpdateAgent(editingAgent.id, next);
      setEditingAgent(null);
      startNewAgent();
    } else {
      await onCreateAgent(next);
      startNewAgent();
    }
  }

  async function handleAgentDelete(agent) {
    if (!globalThis.confirm?.(`确定删除自定义 Agent“${agent.name}”吗？`)) return;
    setAgentActionId(agent.id);
    try {
      await onDeleteAgent(agent.id);
      if (editingAgent?.id === agent.id) startNewAgent();
    } finally {
      setAgentActionId("");
    }
  }

  const busy = isSaving || isTesting;
  const presetModels = LLM_PROVIDER_PRESETS[selectedProvider]?.models || [];
  const formDirty = JSON.stringify({ ...form, profile_name: profileName }) !== formBaseline;
  return (
    <div className="secondary-view settings-view">
      <PageHeader
        kicker={<><GearSix size={16} /> 应用设置</>}
        title="应用设置"
        description="配置驱动项目理解和面试评价的大模型。"
        actions={(
          <div className="theme-control" role="group" aria-label="界面主题">
            <span className="theme-control-label">界面主题</span>
            <div className="theme-control-options" role="radiogroup" aria-label="选择界面主题">
              {THEME_OPTIONS.map((option) => (
                <button className={theme === option.value ? "is-active" : ""} type="button" role="radio" aria-checked={theme === option.value} onClick={() => onThemeChange(option.value)} key={option.value}>{option.label}</button>
              ))}
            </div>
          </div>
        )}
      />
      <div className="settings-tabs" role="tablist" aria-label="设置分类">
        <button className={settingsTab === "llm" ? "is-active" : ""} type="button" role="tab" aria-selected={settingsTab === "llm"} onClick={() => setSettingsTab("llm")}>配置大模型</button>
        <button className={settingsTab === "agent" ? "is-active" : ""} type="button" role="tab" aria-selected={settingsTab === "agent"} onClick={() => setSettingsTab("agent")}>Agent 管理</button>
      </div>
      {settingsTab === "llm" && (
      <section className={`settings-panel llm-settings-card ${editingProfileId || profileFormOpen ? "is-editing" : ""}`}>
        <div className="settings-section-heading">
          <div><span className="view-kicker">模型服务</span><h2>大模型配置</h2></div>
          <span className={`setting-value ${settings?.configured ? "is-online" : ""}`}><span className="status-dot" />{settings?.configured ? "已配置" : "未配置"}</span>
        </div>
        <div className="configured-model-section">
          <div className="settings-subheading"><span>已配置的大模型</span><button className="settings-inline-action" type="button" onClick={startNewProfile} disabled={isSaving}>＋ 新增配置</button></div>
          {profilesLoading ? <div className="configured-model-empty">正在读取配置档案…</div> : profiles?.profiles?.length ? (
            <div className="configured-model-list">
              {profiles.profiles.map((profile) => (
                <div className={`configured-model-card ${profile.active ? "is-active" : ""}`} data-profile-id={profile.id} key={profile.id}>
                  <div className="configured-model-icon"><Sparkle size={18} weight="duotone" /></div>
                  <div className="configured-model-copy"><strong>{profile.name}</strong><span>{profile.provider_name} · {profile.model}</span><small>{profile.base_url} · {profile.api_key_set ? "API Key 已配置" : "API Key 未配置"}</small></div>
                  <span className="configured-model-status">{profile.active ? "当前使用" : "未启用"}</span>
                  <div className="configured-model-actions">
                    {!profile.active && <button type="button" onClick={() => handleProfileAction(onActivateProfile, profile.id)} disabled={isSaving || profileActionId === profile.id}>设为当前</button>}
                    <button type="button" onClick={() => handleProfileTest(profile.id)} disabled={isTesting || profileActionId === profile.id}>测试</button>
                    <button type="button" onClick={() => startEditProfile(profile)} disabled={isSaving}>编辑</button>
                    <details className="ui-more-menu settings-more-menu">
                      <summary aria-label={`更多配置操作：${profile.name}`}><DotsThree size={17} /></summary>
                      <div><button className="is-danger" type="button" onClick={() => handleDelete(profile.id)} disabled={isSaving || profileActionId === profile.id}>删除配置</button></div>
                    </details>
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="configured-model-empty">尚未配置大模型。未配置时由内置规则生成器与评价器兜底，仍可运行；配置后可获得更高质量的评价与追问。</div>}
          {profileTestResult && (() => {
            const testedProfile = profiles?.profiles?.find((profile) => profile.id === profileTestResult.profileId);
            return <div className={`settings-feedback profile-test-feedback ${profileTestResult.status === "error" ? "is-error" : "is-success"}`} role={profileTestResult.status === "error" ? "alert" : "status"} aria-live="polite">
              {profileTestResult.status === "error" ? <WarningCircle size={17} /> : <CheckCircle size={17} />}
              <span>{testedProfile?.name ? `${testedProfile.name}：` : ""}{profileTestResult.message}</span>
            </div>;
          })()}
        </div>
        <div className="provider-picker-section">
          <div className="settings-subheading"><span>选择大模型厂商</span><small>选择后自动填充接口信息</small></div>
          <div className="provider-preset-grid" role="listbox" aria-label="大模型厂商">
            {Object.entries(LLM_PROVIDER_PRESETS).map(([providerKey, preset]) => (
              <button className={`provider-preset ${selectedProvider === providerKey ? "is-selected" : ""}`} data-provider={providerKey} type="button" role="option" aria-selected={selectedProvider === providerKey} onClick={() => applyProviderPreset(providerKey)} disabled={busy} key={providerKey}>
                <span className="provider-preset-topline"><strong>{preset.provider_name}</strong>{selectedProvider === providerKey && <CheckCircle size={15} weight="fill" />}</span>
                <small>{preset.description}</small>
                {providerKey !== "custom" && <code>本地预设模型</code>}
              </button>
            ))}
          </div>
        </div>
        {isLoading ? <div className="settings-loading" role="status">正在读取大模型配置…</div> : (
          <form className="llm-settings-form" onSubmit={handleSubmit}>
            <div className="settings-form-heading"><strong>{editingProfileId ? "编辑大模型配置" : "新增大模型配置"}</strong></div>
            <label className="settings-field">
              <span>配置名称</span>
              <input name="profile_name" value={profileName} onChange={(event) => setProfileName(event.target.value)} disabled={busy} placeholder="例如：DeepSeek 生产模型" autoComplete="off" />
            </label>
            <label className="settings-field">
              <span>服务类型</span>
              <select name="provider" value={form.provider} onChange={handleChange} disabled={busy}>
                <option value="openai_compatible">OpenAI 兼容接口</option>
              </select>
              <small>Agnes、OpenAI、DeepSeek 和本地模型都可通过兼容接口接入。</small>
            </label>
            <label className="settings-field">
              <span>Base URL</span>
              <input name="base_url" value={form.base_url} onChange={handleChange} disabled={busy} placeholder="https://api.example.com/v1" autoComplete="url" />
            </label>
            <label className="settings-field">
              <span>模型名称</span>
              <div className="model-input-row">
                <input name="model" value={form.model} onChange={handleChange} disabled={busy || form.provider !== "openai_compatible"} placeholder="输入模型名称，例如：gpt-4.1" list="preset-models" autoComplete="off" />
                <datalist id="preset-models">
                  {presetModels.map((model) => <option value={model} key={model} />)}
                </datalist>
              </div>
              <small>候选项来自本地预设，也可以直接输入其他模型名称。</small>
              {formError && <small className="settings-form-error">{formError}</small>}
            </label>
            <label className="settings-field">
              <span>API Key</span>
              <input name="api_key" type="password" value={form.api_key} onChange={handleChange} disabled={busy} placeholder={settings?.api_key_set ? "已配置，留空保持不变" : "输入服务商 API Key"} autoComplete="new-password" />
              <small>密钥只提交给后端保存，不会返回到前端。</small>
            </label>
            <div className="settings-field-grid">
              <div className="settings-field settings-temperature-field">
                <div className="settings-field-label-row"><span>温度</span><b>{form.temperature}</b></div>
                <input name="temperature" type="range" min="0" max="2" step="0.1" value={form.temperature} onChange={handleChange} disabled={busy} aria-label="温度" />
                <div className="settings-temperature-scale"><span>精准 (0)</span><span>创造性 (2)</span></div>
              </div>
              <label className="settings-field"><span>超时（秒）</span><input name="timeout" type="number" min="1" step="1" value={form.timeout} onChange={handleChange} disabled={busy} /></label>
            </div>
            <div className="settings-form-actions">
              <small className="settings-dirty-hint">{!formDirty ? (editingProfileId ? "没有需要保存的修改" : "填写配置后即可保存") : ""}</small>
              <button className="secondary-action" type="button" onClick={handleTest} disabled={busy}>{isTesting ? "正在测试…" : "测试连接"}</button>
              <button className="primary-action" type="submit" disabled={busy || !formDirty}>{isSaving ? "正在保存…" : "保存配置"}<ArrowRight size={16} /></button>
              {profileFormOpen && <button className="secondary-action" type="button" onClick={cancelProfileForm} disabled={busy}>取消</button>}
            </div>
          </form>
        )}
        {notice && <div className="settings-feedback is-success" role="status" aria-live="polite"><CheckCircle size={17} />{notice}</div>}
        {error && <div className="settings-feedback is-error" role="alert"><WarningCircle size={17} />{error}</div>}
      </section>
      )}
      {settingsTab === "agent" && (
      <section className="settings-panel agent-settings-card">
        <div className="settings-section-heading">
          <div><span className="view-kicker">Agent 角色</span><h2>Agent 管理</h2></div>
          <span className="setting-value">{agentsLoading ? "读取中…" : `${agents.length} 个角色`}</span>
        </div>
        <div className="settings-subheading agent-list-heading"><span>角色列表</span><small>内置角色不可修改，自定义角色可在新建复盘会话中选用</small></div>
        {agentsLoading ? <div className="configured-model-empty">正在读取 Agent 列表…</div> : agents.length ? (
          <div className="agent-list">
            {agents.map((agent) => (
              <div className={`agent-card ${editingAgent?.id === agent.id ? "is-editing" : ""}`} key={agent.id}>
                <div className="agent-card-head">
                  <strong>{agent.name}</strong>
                  <div className="configured-model-actions">
                    {!agent.builtin && (
                      <>
                        <button type="button" onClick={() => startEditAgent(agent)} disabled={isAgentSaving}>编辑</button>
                        <details className="ui-more-menu settings-more-menu">
                          <summary aria-label={`更多 Agent 操作：${agent.name}`}><DotsThree size={17} /></summary>
                          <div><button className="is-danger" type="button" onClick={() => handleAgentDelete(agent)} disabled={isAgentSaving || agentActionId === agent.id}>删除 Agent</button></div>
                        </details>
                      </>
                    )}
                  </div>
                </div>
                <div className="agent-card-copy">
                  <span>{AGENT_ROLE_LABELS[agent.role] || agent.role}{agent.builtin ? " · 内置" : ""}</span>
                  <small>{agent.persona}</small>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="configured-model-empty">当前没有自定义 Agent，可在下方创建。</div>}
        <div className="settings-subheading agent-form-heading"><span>{editingAgent ? "编辑自定义 Agent" : "新增自定义 Agent"}</span></div>
        <form className="agent-settings-form" onSubmit={handleAgentSubmit}>
          <label className="settings-field">
            <span>名称</span>
            <input value={agentForm.name} onChange={(event) => setAgentForm((current) => ({ ...current, name: event.target.value }))} disabled={isAgentSaving} placeholder="例如：压力出题官" autoComplete="off" />
          </label>
          <label className="settings-field">
            <span>角色</span>
            <select value={agentForm.role} onChange={(event) => setAgentForm((current) => ({ ...current, role: event.target.value }))} disabled={isAgentSaving}>
              {Object.entries(AGENT_ROLE_LABELS).map(([role, label]) => <option value={role} key={role}>{label}</option>)}
            </select>
          </label>
          <label className="settings-field">
            <span>角色设定（persona）</span>
            <textarea rows={3} value={agentForm.persona} onChange={(event) => setAgentForm((current) => ({ ...current, persona: event.target.value }))} disabled={isAgentSaving} placeholder="描述这个 Agent 的风格与职责；只替换角色描述，JSON 输出契约由后端固定" />
          </label>
          <label className="settings-field">
            <span>绑定模型档案</span>
            <select value={agentForm.profile_id} onChange={(event) => setAgentForm((current) => ({ ...current, profile_id: event.target.value }))} disabled={isAgentSaving}>
              <option value="">跟随当前激活配置</option>
              {(profiles?.profiles || []).map((profile) => <option value={profile.id} key={profile.id}>{profile.name}（{profile.model}）</option>)}
            </select>
            <small>不绑定则使用设置页当前激活的大模型配置。</small>
          </label>
          {agentFormError && <small className="settings-form-error">{agentFormError}</small>}
          <div className="settings-form-actions">
            <button className="primary-action" type="submit" disabled={isAgentSaving}>{isAgentSaving ? "正在保存…" : editingAgent ? "保存修改" : "创建 Agent"}<ArrowRight size={16} /></button>
            {editingAgent && <button className="secondary-action" type="button" onClick={startNewAgent} disabled={isAgentSaving}>取消编辑</button>}
          </div>
        </form>
        {agentNotice && <div className="settings-feedback is-success" role="status" aria-live="polite"><CheckCircle size={17} />{agentNotice}</div>}
        {agentError && <div className="settings-feedback is-error" role="alert"><WarningCircle size={17} />{agentError}</div>}
      </section>
      )}
      <section className="settings-panel settings-runtime-panel">
        <div className="settings-row"><span><strong>面试引擎</strong><small>Python API + SQLite 本地会话</small></span><span className="setting-value is-online"><span className="status-dot" /> 在线</span></div>
        <div className="settings-row"><span><strong>提交回答</strong><small>评分和下一题由后端返回；Ctrl / ⌘ + Enter 换行</small></span><kbd>Enter</kbd></div>
        <div className="settings-row"><span><strong>数据存储</strong><small>项目、会话和应用配置由后端管理</small></span><span className="setting-value">SQLite</span></div>
      </section>
      <div className="settings-note"><Sparkle size={18} weight="duotone" /><span>保存后当前后端会立即切换模型；重启后从 SQLite 恢复配置。</span></div>
    </div>
  );
}

function App() {
  const [session, setSession] = useState(null);
  const [activeView, setActiveView] = useState("interview");
  const [theme, setTheme] = useState(readThemePreference);
  const [resolvedTheme, setResolvedTheme] = useState(() => resolveTheme(readThemePreference()));
  const [answer, setAnswer] = useState("");
  const [evaluation, setEvaluation] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [bootError, setBootError] = useState("");
  const [startupUploadError, setStartupUploadError] = useState("");
  const [uploadCompletion, setUploadCompletion] = useState("");
  const [needsUpload, setNeedsUpload] = useState(false);
  const [workspaceMeta, setWorkspaceMeta] = useState({ projectId: "", name: "", path: "" });
  const [tasks, setTasks] = useState([]);
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [busyTaskId, setBusyTaskId] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingAnswer, setPendingAnswer] = useState("");
  const [isCompletingSession, setIsCompletingSession] = useState(false);
  const [streamingReply, setStreamingReply] = useState("");
  const [streamingStatus, setStreamingStatus] = useState("");
  const [streamingSteps, setStreamingSteps] = useState([]);
  const [streamingEval, setStreamingEval] = useState("");
  const [tokenUsage, setTokenUsage] = useState(null);
  const [isEvidenceOpen, setIsEvidenceOpen] = useState(false);
  const [isEvidenceCollapsed, setIsEvidenceCollapsed] = useState(false);
  const [contextRailWidth, setContextRailWidth] = useState(defaultContextRailWidth);
  const [evidencePanelWidth, setEvidencePanelWidth] = useState(defaultEvidencePanelWidth);
  const [isRubricOpen, setIsRubricOpen] = useState(false);
  const [isQuestionMarked, setIsQuestionMarked] = useState(false);
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const [isNavOpen, setIsNavOpen] = useState(false);
  const [selectedStructureItem, setSelectedStructureItem] = useState("");
  const [interactionNotice, showInteractionNotice] = useAutoDismiss();
  const [llmSettings, setLlmSettings] = useState(null);
  const [llmProfiles, setLlmProfiles] = useState({ active_id: null, profiles: [] });
  const [isLLMProfilesLoading, setIsLLMProfilesLoading] = useState(true);
  const [agents, setAgents] = useState([]);
  const [isAgentsLoading, setIsAgentsLoading] = useState(true);
  const [agentNotice, setAgentNotice] = useState("");
  const [agentError, setAgentError] = useState("");
  const [isAgentSaving, setIsAgentSaving] = useState(false);
  const [isLLMSettingsLoading, setIsLLMSettingsLoading] = useState(true);
  const [isLLMSettingsSaving, setIsLLMSettingsSaving] = useState(false);
  const [isLLMSettingsTesting, setIsLLMSettingsTesting] = useState(false);
  const [llmSettingsNotice, showLlmSettingsNotice] = useAutoDismiss();
  const [llmSettingsError, setLlmSettingsError] = useState("");
  const [sessionReport, setSessionReport] = useState(null);
  const [reportFocusIndex, setReportFocusIndex] = useState(null);
  const [isSessionReportLoading, setIsSessionReportLoading] = useState(false);
  const [sessionReportError, setSessionReportError] = useState("");
  const [candidateProfile, setCandidateProfile] = useState(null);
  const [isCandidateProfileLoading, setIsCandidateProfileLoading] = useState(false);
  const [candidateProfileError, setCandidateProfileError] = useState("");
  const startupPromiseRef = useRef(null);
  const moreMenuRef = useRef(null);
  const streamAbortRef = useRef(null);
  const messageListRef = useRef(null);

  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const mediaQuery = globalThis.matchMedia?.("(prefers-color-scheme: dark)");
    const syncTheme = () => {
      const nextTheme = resolveTheme(theme);
      setResolvedTheme(nextTheme);
      document.documentElement.dataset.theme = nextTheme;
      document.documentElement.style.colorScheme = nextTheme;
    };
    syncTheme();
    mediaQuery?.addEventListener?.("change", syncTheme);
    return () => mediaQuery?.removeEventListener?.("change", syncTheme);
  }, [theme]);

  function handleThemeChange(nextTheme) {
    if (!THEME_OPTIONS.some((option) => option.value === nextTheme)) return;
    setTheme(nextTheme);
    try {
      globalThis.localStorage?.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // Theme remains available for the current session when storage is unavailable.
    }
  }

  function adoptLoadedSession(loaded) {
    if (loaded.needsUpload) {
      setNeedsUpload(true);
      setStartupUploadError(loaded.configError || "");
      setSession(toUiSession("", {}, {}, { analysis_status: "WAITING_FOR_PROJECT", source_type: "upload" }));
      setWorkspaceMeta({ projectId: "", name: "", path: "" });
      setTasks([]);
      setEvaluation(null);
      setHistory([]);
      return;
    }
    const state = loaded.state || {};
    const nextSession = toUiSession(loaded.sessionId, state, loaded.knowledge, loaded.status);
    const projectId = sessionProjectId(nextSession);
    const hasServerSessions = Array.isArray(loaded.sessions);
    const existingTasks = hasServerSessions
      ? tasksFromSessionList({ sessions: loaded.sessions })
      : readStoredTasks(projectId);
    const nextTasks = existingTasks.some((task) => task.id === loaded.sessionId)
      ? existingTasks
      : [{ id: loaded.sessionId, name: nextSession.title || `任务 ${existingTasks.length + 1}`, createdAt: new Date().toISOString() }, ...existingTasks];
    setNeedsUpload(false);
    setStartupUploadError("");
    setSession(nextSession);
    setWorkspaceMeta({ projectId, name: nextSession.projectName || "未命名工作区", path: nextSession.projectPath || "" });
    setTasks(nextTasks);
    saveStoredTasks(projectId, nextTasks);
    setEvaluation(state.evaluation || null);
    setHistory(state.history || []);
    setSelectedStructureItem(state.current_topic?.name || "");
  }

  useEffect(() => {
    let cancelled = false;
    // StrictMode re-runs this effect after cleanup. Share the request promise;
    // cleanup only suppresses state updates from the previous effect run.
    reusePromise(startupPromiseRef, loadInterviewSession)
      .then((loaded) => {
        if (cancelled) return;
        adoptLoadedSession(loaded);
      })
      .catch((cause) => {
        if (!cancelled) setBootError(`无法加载项目或面试会话：${errorMessage(cause)}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getLLMProfiles()
      .then((profiles) => {
        if (!cancelled) setLlmProfiles(profiles);
      })
      .catch((cause) => {
        if (!cancelled) setLlmSettingsError(`无法读取大模型配置档案：${errorMessage(cause)}`);
      })
      .finally(() => {
        if (!cancelled) setIsLLMProfilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAgents()
      .then((result) => {
        if (!cancelled) setAgents(result?.agents || []);
      })
      .catch((cause) => {
        if (!cancelled) setAgentError(`无法读取 Agent 列表：${errorMessage(cause)}`);
      })
      .finally(() => {
        if (!cancelled) setIsAgentsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

      useEffect(() => {
        if (!isMoreMenuOpen) return undefined;

        function handlePointerDown(event) {
          if (!moreMenuRef.current?.contains(event.target)) setIsMoreMenuOpen(false);
        }

        function handleMenuKeyDown(event) {
          if (event.key === "Escape") setIsMoreMenuOpen(false);
        }

        document.addEventListener("pointerdown", handlePointerDown);
        document.addEventListener("keydown", handleMenuKeyDown);
        return () => {
          document.removeEventListener("pointerdown", handlePointerDown);
          document.removeEventListener("keydown", handleMenuKeyDown);
        };
      }, [isMoreMenuOpen]);

      useEffect(() => {
        if (!isNavOpen) return undefined;

        function handleNavKeyDown(event) {
          if (event.key === "Escape") setIsNavOpen(false);
        }

        document.addEventListener("keydown", handleNavKeyDown);
        return () => document.removeEventListener("keydown", handleNavKeyDown);
      }, [isNavOpen]);

  useEffect(() => {
    const list = messageListRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [history, isSubmitting, streamingReply, streamingEval, streamingStatus, session]);

  useEffect(() => {
    let cancelled = false;
    getLLMSettings()
      .then((settings) => {
        if (!cancelled) setLlmSettings(settings);
      })
      .catch((cause) => {
        if (!cancelled) setLlmSettingsError(`无法读取大模型配置：${errorMessage(cause)}`);
      })
      .finally(() => {
        if (!cancelled) setIsLLMSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadSessionReport() {
    if (!session?.sessionId) return;
    setIsSessionReportLoading(true);
    setSessionReportError("");
    try {
      setSessionReport(await getSessionReport(session.sessionId));
    } catch (cause) {
      setSessionReportError(`无法读取会话报告：${errorMessage(cause)}`);
    } finally {
      setIsSessionReportLoading(false);
    }
  }

  async function loadCandidateProfile() {
    const candidateId = session?.candidateId || DEFAULT_CANDIDATE_ID;
    setIsCandidateProfileLoading(true);
    setCandidateProfileError("");
    try {
      setCandidateProfile(await getCandidateProfile(candidateId));
    } catch (cause) {
      setCandidateProfileError(`无法读取能力画像：${errorMessage(cause)}`);
    } finally {
      setIsCandidateProfileLoading(false);
    }
  }

  useEffect(() => {
    if (activeView === "report" && session?.sessionId) loadSessionReport();
  }, [activeView, session?.sessionId]);

  useEffect(() => {
    if (activeView === "profile" && session?.candidateId) loadCandidateProfile();
  }, [activeView, session?.candidateId]);

  const questionProgress = useMemo(() => {
    if (!session || !Number(session.totalQuestions) || session.progress === "") return 0;
    return Math.round((Number(session.progress) / Number(session.totalQuestions)) * 100);
  }, [session]);

  const structure = useMemo(() => {
    if (!session) return [];
    const topicNames = projectTopics(session.project)
      .map((topic) => String(topic.name || "").trim())
      .filter(Boolean);
    const directions = [...new Set([session.topic, ...topicNames].filter(Boolean))];
    if (directions.length === 0) return [];
    return [{
      label: "核心方向",
      active: true,
      children: directions.slice(0, MAX_INTERVIEW_DIRECTIONS),
      totalCount: directions.length,
    }];
  }, [session]);

  const currentQuestionNumber = session ? Number(session.questionNumber) || history.length + 1 : 1;
  const questionProgressLabel = session?.totalQuestions
    ? `${Math.min(currentQuestionNumber, Number(session.totalQuestions))} / ${session.totalQuestions}`
    : `第 ${currentQuestionNumber} 题`;

  function resizeLimit(side) {
    const viewportWidth = globalThis.innerWidth || 1440;
    const otherPanelWidth = side === "left"
      ? (isEvidenceCollapsed ? 40 : evidencePanelWidth)
      : contextRailWidth;
    const available = viewportWidth - 176 - otherPanelWidth - MIN_CHAT_WIDTH;
    const minimum = side === "left" ? MIN_CONTEXT_RAIL_WIDTH : MIN_EVIDENCE_PANEL_WIDTH;
    const maximum = side === "left" ? MAX_CONTEXT_RAIL_WIDTH : MAX_EVIDENCE_PANEL_WIDTH;
    return Math.max(minimum, Math.min(maximum, available));
  }

  const leftResize = usePanelResize({
    value: contextRailWidth,
    onChange: (width) => setContextRailWidth(Math.max(MIN_CONTEXT_RAIL_WIDTH, Math.min(resizeLimit("left"), Math.round(width)))),
    min: MIN_CONTEXT_RAIL_WIDTH,
    max: MAX_CONTEXT_RAIL_WIDTH,
    direction: 1,
    onReset: () => setContextRailWidth(defaultContextRailWidth()),
  });
  const rightResize = usePanelResize({
    value: evidencePanelWidth,
    onChange: (width) => setEvidencePanelWidth(Math.max(MIN_EVIDENCE_PANEL_WIDTH, Math.min(resizeLimit("right"), Math.round(width)))),
    min: MIN_EVIDENCE_PANEL_WIDTH,
    max: MAX_EVIDENCE_PANEL_WIDTH,
    direction: -1,
    onReset: () => setEvidencePanelWidth(defaultEvidencePanelWidth()),
  });

  function handleEvidenceToggle() {
    if (globalThis.matchMedia?.("(max-width: 1279px)").matches) {
      setIsEvidenceCollapsed(false);
      setIsEvidenceOpen((open) => !open);
      return;
    }
    setIsEvidenceCollapsed((collapsed) => !collapsed);
  }

  function handleBackToProject() {
    setIsNavOpen(false);
    setIsEvidenceOpen(false);
    setIsRubricOpen(false);
    setIsMoreMenuOpen(false);
    setActiveView("project");
  }

  function handleToggleQuestionMark() {
    setIsMoreMenuOpen(false);
    setIsQuestionMarked((marked) => {
      showInteractionNotice(marked ? "已取消当前问题的标记。" : "已标记当前问题。 ");
      return !marked;
    });
  }

  async function handleStructureSelection(child) {
    if (!child || isCreatingTask) return;
    setSelectedStructureItem(child);
    setActiveView("interview");
    if (child === session.topic) {
      showInteractionNotice("");
      return;
    }
    const created = await handleCreateReviewSession({
      candidateId: session.candidateId || DEFAULT_CANDIDATE_ID,
      reviewMode: session.reviewMode,
      title: `${child} · ${reviewModeLabel(session.reviewMode)}`.slice(0, 80),
      topic: child,
    });
    if (!created) setSelectedStructureItem(session.topic || "");
  }

  function handleMoreNavigation(view) {
    setIsNavOpen(false);
    setIsMoreMenuOpen(false);
    setIsEvidenceOpen(false);
    setIsRubricOpen(false);
    setActiveView(view);
  }

  function handleOpenProjectKnowledge() {
    setIsEvidenceOpen(false);
    setIsRubricOpen(false);
    setIsMoreMenuOpen(false);
    setActiveView("project");
  }

  async function handleSubmit() {
    if (!answer.trim() || isSubmitting) {
      setError("先写下你的思路，再提交回答。");
      return;
    }
    const submittedAnswer = answer.trim();
    setError("");
    setAnswer("");
    setPendingAnswer(submittedAnswer);
    setIsSubmitting(true);
    setStreamingReply("");
    setStreamingStatus("正在评价回答");
    setStreamingSteps([]);
    setStreamingEval("");
    setTokenUsage(null);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      const result = await submitAnswerStream(submittedAnswer, session, (event, payload) => {
        if (event === "status") {
          const message = payload.message || "正在处理回答";
          setStreamingStatus(message);
          setStreamingSteps((current) => current.includes(message) ? current : [...current, message]);
        }
        if (event === "progress") setStreamingStatus(payload.message || "正在评价回答");
        if (event === "eval_chunk") setStreamingEval((current) => current + (payload.text || ""));
        if (event === "usage") setTokenUsage(payload);
        if (event === "chunk") setStreamingReply((current) => current + (payload.text || ""));
      }, controller.signal);
      const state = result.state || {};
      setEvaluation(state.evaluation || null);
      setHistory(state.history || []);
      setSession(toUiSession(session.sessionId, state, session.project, session.status));
      setSessionReport(null);
      setCandidateProfile(null);
      setSelectedStructureItem(state.current_topic?.name || "");
    } catch (cause) {
      if (cause?.name === "AbortError") {
        setAnswer(submittedAnswer);
        setError("");
      } else {
        setError(`提交失败：${errorMessage(cause)}`);
      }
    } finally {
      setIsSubmitting(false);
      setStreamingReply("");
      setStreamingStatus("");
      setStreamingSteps([]);
      setStreamingEval("");
      setPendingAnswer("");
      streamAbortRef.current = null;
    }
  }

  function handleStopAnswer() {
    streamAbortRef.current?.abort();
  }

  async function handleCompleteSession() {
    if (!session?.sessionId || isCompletingSession) return;
    if (history.length === 0) {
      showInteractionNotice("至少完成一次回答后才能结束会话。");
      return;
    }
    setIsCompletingSession(true);
    setIsMoreMenuOpen(false);
    showInteractionNotice("");
    try {
      const result = await completeSession(session.sessionId);
      const state = result.state || {};
      setSession(toUiSession(session.sessionId, state, session.project, session.status));
      setEvaluation(state.evaluation || null);
      setHistory(state.history || []);
      setSessionReport(null);
      const projectId = sessionProjectId(session);
      try {
        const sessionList = await getSessions({ projectId, candidateId: state.candidate_id });
        const nextTasks = tasksFromSessionList(sessionList);
        setTasks(nextTasks);
        saveStoredTasks(projectId, nextTasks);
      } catch {
        showInteractionNotice("会话已结束；历史列表将在下次刷新时更新。");
      }
      setReportFocusIndex(null);
      setActiveView("report");
    } catch (cause) {
      showInteractionNotice(`结束会话失败：${errorMessage(cause)}`, { persist: true });
    } finally {
      setIsCompletingSession(false);
    }
  }

  function adoptTaskSession(sessionId, state) {
    setSession(toUiSession(sessionId, state, session.project, session.status));
    setEvaluation(state.evaluation || null);
    setHistory(state.history || []);
    setSelectedStructureItem(state.current_topic?.name || "");
    setAnswer("");
    setError("");
    setIsQuestionMarked(false);
    setIsEvidenceOpen(false);
    setActiveView("interview");
  }

  async function handleSelectTask(task) {
    if (!task?.id || task.id === session?.sessionId) return;
    showInteractionNotice("");
    try {
      const result = await getSession(task.id);
      adoptTaskSession(task.id, result.state || {});
    } catch (cause) {
      showInteractionNotice(`无法打开任务“${task.name}”：${errorMessage(cause)}`, { persist: true });
    }
  }

  async function handleRenameTask(task, title) {
    setBusyTaskId(task.id);
    showInteractionNotice("");
    try {
      const result = await renameSession(task.id, title);
      const renamedTitle = result.state?.title || title;
      const nextTasks = tasks.map((item) => (
        item.id === task.id ? { ...item, name: renamedTitle } : item
      ));
      setTasks(nextTasks);
      saveStoredTasks(sessionProjectId(session), nextTasks);
      if (task.id === session.sessionId) {
        setSession(toUiSession(task.id, result.state || {}, session.project, session.status));
      }
      showInteractionNotice(`会话已重命名为“${renamedTitle}”。`);
      return true;
    } catch (cause) {
      showInteractionNotice(`重命名失败：${errorMessage(cause)}`, { persist: true });
      return false;
    } finally {
      setBusyTaskId("");
    }
  }

  async function handleDeleteTask(task) {
    setBusyTaskId(task.id);
    showInteractionNotice("");
    try {
      await deleteSession(task.id);
      const nextTasks = tasks.filter((item) => item.id !== task.id);
      setTasks(nextTasks);
      saveStoredTasks(sessionProjectId(session), nextTasks);
      if (task.id === session.sessionId) {
        const fallback = nextTasks[0];
        if (fallback) {
          const result = await getSession(fallback.id);
          adoptTaskSession(fallback.id, result.state || {});
        } else {
          setSession((current) => ({
            ...current,
            sessionId: "",
            title: "",
            question: "",
            sessionState: "not_started",
          }));
          setEvaluation(null);
          setHistory([]);
          setActiveView("session-new");
        }
      }
      showInteractionNotice(`已删除会话“${task.name}”。`);
      return true;
    } catch (cause) {
      showInteractionNotice(`删除失败：${errorMessage(cause)}`, { persist: true });
      return false;
    } finally {
      setBusyTaskId("");
    }
  }

  async function handleOpenWeaknessSource(source) {
    if (!source?.session_id) return;
    setCandidateProfileError("");
    try {
      const result = await getSession(source.session_id);
      const state = result.state || {};
      const sourceProject = state.project || {};
      const sameProject = sessionProjectId(session) === state.project_id;
      setSession(toUiSession(
        source.session_id,
        state,
        sourceProject,
        sameProject ? session.status : { analysis_status: "READY", project_name: sourceProject.project_name },
      ));
      setEvaluation(state.evaluation || null);
      setHistory(state.history || []);
      setSelectedStructureItem(state.current_topic?.name || "");
      setSessionReport(null);
      setSessionReportError("");
      setReportFocusIndex(source.record_index);
      setWorkspaceMeta((current) => ({
        projectId: state.project_id,
        name: sourceProject.project_name || String(state.project_id || ""),
        path: sameProject ? current.path : "",
      }));
      setActiveView("report");
    } catch (cause) {
      setCandidateProfileError(`无法打开薄弱项来源：${errorMessage(cause)}`);
    }
  }

  function handleCreateTask() {
    if (!sessionProjectId(session)) return;
    setIsNavOpen(false);
    setActiveView("session-new");
    showInteractionNotice("");
  }

  async function handlePositionPractice(position, question) {
    const projectId = question?.project_id;
    if (!projectId) throw new Error("岗位题目尚未关联项目");
    const candidateId = position?.candidate_id || session.candidateId || DEFAULT_CANDIDATE_ID;
    const title = `${position.company ? `${position.company} · ` : ""}${position.title}`;
    const [created, knowledge, status] = await Promise.all([
      startInterviewSession(
        projectId,
        candidateId,
        "technical_interview",
        title,
        undefined,
        position.position_id,
        question.question_id,
      ),
      getProjectKnowledge(projectId),
      getProjectStatus(projectId),
    ]);
    const sessionList = await getSessions({ projectId, candidateId });
    const loaded = {
      ...created,
      knowledge,
      status,
      sessions: sessionList.sessions || [],
    };
    saveProjectId(question.project_id);
    startupPromiseRef.current = Promise.resolve(loaded);
    adoptLoadedSession(loaded);
    setActiveView("interview");
  }

  function handlePrimaryNavigation(view) {
    setIsNavOpen(false);
    if (view === "report") setReportFocusIndex(null);
    setActiveView(view);
  }

  async function handleCreateReviewSession({ candidateId, reviewMode, title = "", topic = "", agentMode = "single", agentIds = null }) {
    const projectId = sessionProjectId(session);
    if (!projectId || isCreatingTask) return;
    setIsCreatingTask(true);
    showInteractionNotice(topic ? `正在为主题“${topic}”创建新会话…` : "", { persist: true });
    try {
      const defaultTitle = title || `任务 ${tasks.length + 1}`;
      const created = await startInterviewSession(projectId, candidateId, reviewMode, defaultTitle, topic, undefined, undefined, agentMode, agentIds);
      const state = created.state || {};
      const sessionList = await getSessions({ projectId, candidateId });
      const serverTasks = tasksFromSessionList(sessionList);
      const nextTask = { id: created.sessionId, name: state.title || defaultTitle, createdAt: new Date().toISOString() };
      const nextTasks = serverTasks.some((task) => task.id === created.sessionId)
        ? serverTasks
        : [nextTask, ...serverTasks];
      setTasks(nextTasks);
      saveStoredTasks(projectId, nextTasks);
      adoptTaskSession(created.sessionId, state);
      showInteractionNotice(topic
        ? `已为主题“${topic}”创建新会话。`
        : `已在“${workspaceMeta.name || "当前工作区"}”创建${nextTask.name}。`);
      return true;
    } catch (cause) {
      showInteractionNotice(`${topic ? "切换主题" : "新建任务"}失败：${errorMessage(cause)}`, { persist: true });
      return false;
    } finally {
      setIsCreatingTask(false);
    }
  }

  async function handleSaveLLMSettings(payload) {
    setIsLLMSettingsSaving(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const saved = await saveLLMSettings(payload);
      setLlmSettings(saved);
      showLlmSettingsNotice("大模型配置已保存，当前后端已切换。 ");
    } catch (cause) {
      setLlmSettingsError(`保存失败：${errorMessage(cause)}`);
    } finally {
      setIsLLMSettingsSaving(false);
    }
  }

  async function handleTestLLMConnection(payload) {
    setIsLLMSettingsTesting(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const result = await testLLMConnection(payload);
      showLlmSettingsNotice(result.message || "连接测试成功。 ");
    } catch (cause) {
      setLlmSettingsError(`连接测试失败：${errorMessage(cause)}`);
    } finally {
      setIsLLMSettingsTesting(false);
    }
  }

  async function refreshLLMProfiles() {
    const profiles = await getLLMProfiles();
    setLlmProfiles(profiles);
    return profiles;
  }

  async function handleCreateLLMProfile(payload) {
    setIsLLMSettingsSaving(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const created = await createLLMProfile(payload);
      await refreshLLMProfiles();
      showLlmSettingsNotice("大模型配置档案已新增。 ");
      return created;
    } catch (cause) {
      setLlmSettingsError(`新增失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsLLMSettingsSaving(false);
    }
  }

  async function handleUpdateLLMProfile(profileId, payload) {
    setIsLLMSettingsSaving(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const updated = await updateLLMProfile(profileId, payload);
      await refreshLLMProfiles();
      if (updated.active) setLlmSettings(updated);
      showLlmSettingsNotice("大模型配置档案已更新。 ");
      return updated;
    } catch (cause) {
      setLlmSettingsError(`更新失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsLLMSettingsSaving(false);
    }
  }

  async function handleActivateLLMProfile(profileId) {
    setIsLLMSettingsSaving(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const active = await activateLLMProfile(profileId);
      setLlmSettings(active);
      await refreshLLMProfiles();
      showLlmSettingsNotice("已切换当前使用的大模型。 ");
      return active;
    } catch (cause) {
      setLlmSettingsError(`切换失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsLLMSettingsSaving(false);
    }
  }

  async function handleDeleteLLMProfile(profileId) {
    setIsLLMSettingsSaving(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const result = await deleteLLMProfile(profileId);
      setLlmProfiles(result);
      setLlmSettings(await getLLMSettings());
      showLlmSettingsNotice("大模型配置档案已删除。 ");
      return result;
    } catch (cause) {
      setLlmSettingsError(`删除失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsLLMSettingsSaving(false);
    }
  }

  async function handleTestLLMProfile(profileId) {
    setIsLLMSettingsTesting(true);
    showLlmSettingsNotice("");
    setLlmSettingsError("");
    try {
      const result = await testLLMProfile(profileId);
      return result;
    } catch (cause) {
      throw cause;
    } finally {
      setIsLLMSettingsTesting(false);
    }
  }

  async function refreshAgents() {
    const result = await getAgents();
    setAgents(result?.agents || []);
    return result;
  }

  async function handleCreateAgent(payload) {
    setIsAgentSaving(true);
    setAgentNotice("");
    setAgentError("");
    try {
      const created = await createAgent(payload);
      await refreshAgents();
      setAgentNotice("自定义 Agent 已创建。 ");
      return created;
    } catch (cause) {
      setAgentError(`新增失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsAgentSaving(false);
    }
  }

  async function handleUpdateAgent(agentId, payload) {
    setIsAgentSaving(true);
    setAgentNotice("");
    setAgentError("");
    try {
      const updated = await updateAgent(agentId, payload);
      await refreshAgents();
      setAgentNotice("自定义 Agent 已更新。 ");
      return updated;
    } catch (cause) {
      setAgentError(`更新失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsAgentSaving(false);
    }
  }

  async function handleDeleteAgent(agentId) {
    setIsAgentSaving(true);
    setAgentNotice("");
    setAgentError("");
    try {
      await deleteAgent(agentId);
      await refreshAgents();
      setAgentNotice("自定义 Agent 已删除。 ");
    } catch (cause) {
      setAgentError(`删除失败：${errorMessage(cause)}`);
      throw cause;
    } finally {
      setIsAgentSaving(false);
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      handleSubmit();
    }
  }

  function handleUploaded(loaded, completion = "") {
    startupPromiseRef.current = Promise.resolve(loaded);
    setUploadCompletion(completion);
    adoptLoadedSession(loaded);
  }

  if (bootError) {
    return (
      <AppWindow resolvedTheme={resolvedTheme} onThemeChange={handleThemeChange}>
        <main className="status-shell">
          <section className="status-card">
            <Sparkle size={28} weight="duotone" />
            <h1>项目或面试后端未就绪</h1>
            <p>{bootError}</p>
            <p>请确认项目已上传、分析完成，并检查 API 配置。</p>
            <button type="button" onClick={() => window.location.reload()}>重新连接</button>
          </section>
        </main>
      </AppWindow>
    );
  }

  if (!session) {
    return (
      <AppWindow resolvedTheme={resolvedTheme} onThemeChange={handleThemeChange}>
        <main className="status-shell">
          <section className="status-card">
            <Sparkle size={28} weight="duotone" />
            <h1>正在准备面试会话</h1>
            <p>正在加载项目状态、项目知识并连接面试引擎…</p>
          </section>
        </main>
      </AppWindow>
    );
  }

  return (
    <AppWindow resolvedTheme={resolvedTheme} onThemeChange={handleThemeChange}>
      <main
        className={`app-shell stitch-shell view-${activeView} ${needsUpload ? "is-empty-project" : ""} ${isEvidenceCollapsed ? "is-evidence-collapsed" : ""} ${leftResize.resizing || rightResize.resizing ? "is-resizing" : ""}`}
        style={{
          "--context-rail-width": `${contextRailWidth}px`,
          "--evidence-panel-width": isEvidenceCollapsed ? "40px" : `${evidencePanelWidth}px`,
        }}
      >
      <PrimarySidebar activeView={activeView} onNavigate={handlePrimaryNavigation} onNewSession={handleCreateTask} hasProject={Boolean(sessionProjectId(session))} isOpen={isNavOpen} onClose={() => setIsNavOpen(false)} />
      <div className="mobile-page-bar">
        <button className="mobile-nav-trigger" type="button" aria-label="打开应用导航" aria-controls="app-navigation" aria-expanded={isNavOpen} onClick={() => setIsNavOpen(true)}><ListBullets size={18} /><span>导航</span></button>
        <span className="mobile-page-title">{MOBILE_PAGE_LABELS[activeView] || "面试工作台"}</span>
      </div>
      {activeView === "interview" ? (
        needsUpload ? (
          <EmptyInterviewView onUploaded={handleUploaded} initialError={startupUploadError} />
        ) : (
          <>
              <InterviewContextRail workspace={workspaceMeta} session={session} tasks={tasks} structure={structure} progress={questionProgress} selectedItem={selectedStructureItem} onSelectTask={handleSelectTask} onSelectStructure={handleStructureSelection} onNewSession={handleCreateTask} onRenameTask={handleRenameTask} onDeleteTask={handleDeleteTask} busyTaskId={busyTaskId} isCreatingSession={isCreatingTask} onOpenResumeDetail={() => setActiveView("resumes")} />
              <section className="workspace interview-workspace" aria-label="面试工作台">
                <div className="workspace-resizer is-left" role="separator" aria-label="调整面试结构宽度" aria-orientation="vertical" aria-valuemin={MIN_CONTEXT_RAIL_WIDTH} aria-valuemax={MAX_CONTEXT_RAIL_WIDTH} aria-valuenow={contextRailWidth} tabIndex={0} {...leftResize.handlers} />
                <header className="workspace-header">
                  <nav className="question-breadcrumb" aria-label="当前位置">
                    <button className="crumb-link" type="button" title="返回项目资料" onClick={handleBackToProject}>{workspaceMeta.name || session.projectName || "项目资料"}</button>
                    <span className="crumb-sep" aria-hidden="true">/</span>
                    {session.topic && <button className="crumb-link" type="button" title={`回到面试结构：${session.topic}`} onClick={() => handleStructureSelection(session.topic)}>{session.topic}</button>}
                    {session.topic && <span className="crumb-sep" aria-hidden="true">/</span>}
                    <span className="crumb-current" aria-current="page">{questionProgressLabel}</span>
                  </nav>
                  <div className="header-actions">
                    <div className="engine-status"><span className="status-dot" />{session.sessionState === "completed" ? "会话已结束" : "面试引擎在线"}</div>
                    <button className={`text-button evidence-toggle ${isEvidenceOpen ? "is-active" : ""}`} type="button" aria-expanded={isEvidenceOpen} aria-controls="evidence-drawer" onClick={handleEvidenceToggle}><FileCode size={18} /> 证据</button>
                    <button className={`text-button ${isQuestionMarked ? "is-active" : ""}`} type="button" aria-pressed={isQuestionMarked} onClick={handleToggleQuestionMark}><BookmarkSimple size={18} weight={isQuestionMarked ? "fill" : "regular"} /> {isQuestionMarked ? "已标记" : "标记"}</button>
                    {session.sessionState === "completed"
                      ? <button className="text-button" type="button" onClick={() => setActiveView("report")}>查看报告</button>
                      : <button className="text-button" type="button" onClick={handleCompleteSession} disabled={history.length === 0 || isSubmitting || isCompletingSession}>{isCompletingSession ? "正在结束…" : "结束会话"}</button>}
                    <div className="more-actions" ref={moreMenuRef}><button className="icon-button" aria-label="更多操作" aria-haspopup="menu" aria-expanded={isMoreMenuOpen} type="button" onClick={() => setIsMoreMenuOpen((open) => !open)}><DotsThree size={22} weight="bold" /></button>{isMoreMenuOpen && <div className="more-menu" role="menu"><button type="button" role="menuitem" onClick={handleToggleQuestionMark}>{isQuestionMarked ? "取消标记当前问题" : "标记当前问题"}</button><button type="button" role="menuitem" onClick={() => handleMoreNavigation("project")}>查看项目资料</button><button type="button" role="menuitem" onClick={() => handleMoreNavigation("settings")}>打开应用设置</button></div>}</div>
                  </div>
                </header>
                {interactionNotice && <div className="workspace-feedback" role="status" aria-live="polite">{interactionNotice}</div>}
             <div className="workspace-content agent-workspace-content">
                <InterviewThread
                  session={{ ...session, questionProgressLabel }}
                  history={history}
                  isSubmitting={isSubmitting}
                  pendingAnswer={pendingAnswer}
                  streamingReply={streamingReply}
                  streamingEval={streamingEval}
                  streamingStatus={streamingStatus}
                  streamingSteps={streamingSteps}
                  tokenUsage={tokenUsage}
                  messageListRef={messageListRef}
                  directionLabel={directionLabel}
                  processStepsForRecord={processStepsForRecord}
                />
                {session.sessionState === "completed" ? (
                  <div className="agent-system-message session-completed-message"><CheckCircle size={18} weight="fill" /><span><strong>本次会话已结束</strong><small>回答已锁定，可以查看完整复盘报告。</small></span><button className="quiet-button" type="button" onClick={() => setActiveView("report")}>查看报告</button></div>
                ) : (
                  <InterviewComposer answer={answer} setAnswer={setAnswer} onKeyDown={handleKeyDown} onSubmit={handleSubmit} onStop={handleStopAnswer} isSubmitting={isSubmitting} error={error} uploadControl={<ProjectUploadControl onUploaded={handleUploaded} onCreateTask={handleCreateTask} canCreateTask={Boolean(sessionProjectId(session))} workspaceName={workspaceMeta.name} initialCompletion={uploadCompletion} />} />
                )}
             </div>
                {!isEvidenceCollapsed && <div className="workspace-resizer is-right" role="separator" aria-label="调整证据面板宽度" aria-orientation="vertical" aria-valuemin={MIN_EVIDENCE_PANEL_WIDTH} aria-valuemax={MAX_EVIDENCE_PANEL_WIDTH} aria-valuenow={evidencePanelWidth} tabIndex={0} {...rightResize.handlers} />}
          </section>

          <EvidencePanel
            session={session}
            evaluation={evaluation}
            tokenUsage={tokenUsage}
            isEvidenceOpen={isEvidenceOpen}
            isEvidenceCollapsed={isEvidenceCollapsed}
            isRubricOpen={isRubricOpen}
            onExpand={() => setIsEvidenceCollapsed(false)}
            onCollapse={() => setIsEvidenceCollapsed(true)}
            onClose={() => { setIsEvidenceOpen(false); setIsRubricOpen(false); }}
            onOpenProjectKnowledge={handleOpenProjectKnowledge}
            onToggleRubric={() => setIsRubricOpen((open) => !open)}
            onCloseRubric={() => setIsRubricOpen(false)}
            directionLabel={directionLabel}
            confidenceLabel={confidenceLabel}
          />
          </>
        )
      ) : activeView === "positions" ? (
        <PositionPreparationView candidateId={session.candidateId || DEFAULT_CANDIDATE_ID} currentProjectId={sessionProjectId(session)} onPractice={handlePositionPractice} />
      ) : activeView === "resumes" ? (
        <section className="workspace secondary-workspace stitch-resume-workspace" aria-label="简历库"><ResumeLibraryView /></section>
      ) : activeView === "project" ? (
        <section className="workspace secondary-workspace stitch-project-workspace" aria-label="项目资料"><ProjectView session={session} onAddProject={() => setActiveView("interview")} /></section>
      ) : activeView === "session-new" ? (
        <SessionSetupView session={session} candidateId={session.candidateId} isCreating={isCreatingTask} error={interactionNotice} onCreate={handleCreateReviewSession} />
      ) : activeView === "report" ? (
        <SessionReportView report={sessionReport} loading={isSessionReportLoading} error={sessionReportError} onRetry={loadSessionReport} onPractice={() => setActiveView("session-new")} focusedRecordIndex={reportFocusIndex} />
      ) : activeView === "profile" ? (
        <CandidateProfileView profile={candidateProfile} loading={isCandidateProfileLoading} error={candidateProfileError} onRetry={loadCandidateProfile} onPractice={() => setActiveView("session-new")} onOpenSource={handleOpenWeaknessSource} />
      ) : (
        <section className="workspace secondary-workspace stitch-settings-workspace" aria-label="应用设置"><SettingsView settings={llmSettings} profiles={llmProfiles} profilesLoading={isLLMProfilesLoading} isLoading={isLLMSettingsLoading} isSaving={isLLMSettingsSaving} isTesting={isLLMSettingsTesting} notice={llmSettingsNotice} error={llmSettingsError} onSave={handleSaveLLMSettings} onTest={handleTestLLMConnection} onCreateProfile={handleCreateLLMProfile} onUpdateProfile={handleUpdateLLMProfile} onDeleteProfile={handleDeleteLLMProfile} onActivateProfile={handleActivateLLMProfile} onTestProfile={handleTestLLMProfile} agents={agents} agentsLoading={isAgentsLoading} agentNotice={agentNotice} agentError={agentError} isAgentSaving={isAgentSaving} onCreateAgent={handleCreateAgent} onUpdateAgent={handleUpdateAgent} onDeleteAgent={handleDeleteAgent} theme={theme} onThemeChange={handleThemeChange} /></section>
      )}
      </main>
    </AppWindow>
  );
}

export default App;
export { App, normalizeEvidence, toUiSession };
