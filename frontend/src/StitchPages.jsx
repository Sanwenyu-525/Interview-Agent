import { useEffect, useMemo, useRef, useState } from "react";
import usePanelResize from "./usePanelResize.js";
import {
  ArrowRight,
  Brain,
  Briefcase,
  CaretDown,
  CaretRight,
  ChartBar,
  Check,
  CheckCircle,
  ClockCounterClockwise,
  Code,
  FilePdf,
  FileText,
  FolderSimple,
  GearSix,
  IdentificationCard,
  ImageSquare,
  ListBullets,
  MagnifyingGlass,
  Plus,
  PencilSimple,
  Presentation,
  Play,
  ArrowClockwise,
  Sparkle,
  Target,
  Trash,
  TrendUp,
  User,
  WarningCircle,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { useAutoDismiss } from "./useAutoDismiss.js";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  createPosition,
  deleteResume,
  deletePosition,
  getPositions,
  getResumes,
  getResume,
  getResumePdf,
  getSessions,
  ocrPositionJd,
  regeneratePositionQuestions,
  reorderResumes,
  updateResume,
  updatePosition,
  uploadResume,
} from "./api";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const REVIEW_MODES = [
  {
    id: "technical_interview",
    label: "技术面试",
    icon: Code,
    description: "围绕项目实现、技术选择、系统边界与工程权衡展开。",
  },
  {
    id: "portfolio_review",
    label: "作品集评审",
    icon: Briefcase,
    description: "关注作品目标、设计决策、叙事质量和最终影响。",
  },
  {
    id: "defense_review",
    label: "项目答辩",
    icon: Presentation,
    description: "验证目标、关键论证、风险识别与证据完整性。",
  },
];

// 简历库离线演示数据：后端不可用或尚无简历时回退展示，保持 Stitch 原稿的选择流程可用。
const RESUME_LIBRARY = [
  {
    id: "candidate-042",
    name: "林澈",
    role: "后端工程师",
    domain: "交易系统",
    status: "已提取",
    statusTone: "success",
    claims: 12,
    project: "OrderFlow Service",
    updated: "08-04",
  },
  {
    id: "candidate-041",
    name: "苏晚晴",
    role: "前端工程师",
    domain: "数据可视化",
    status: "已提取",
    statusTone: "success",
    claims: 9,
    project: "DataViz Portal",
    updated: "08-02",
  },
  {
    id: "candidate-038",
    name: "陈牧",
    role: "算法工程师",
    domain: "推荐系统",
    status: "分析中",
    statusTone: "pending",
    claims: 7,
    project: "RecRank",
    updated: "08-05",
  },
  {
    id: "candidate-035",
    name: "周屿",
    role: "后端工程师",
    domain: "交易系统",
    status: "待提取",
    statusTone: "draft",
    claims: 5,
    project: "OrderFlow Service",
    updated: "07-30",
  },
];

function reviewModeLabel(value) {
  return REVIEW_MODES.find((mode) => mode.id === value)?.label || value || "技术面试";
}

function resumeStatusLabel(value) {
  return { extracted: "已提取", analyzing: "分析中", pending: "待提取" }[value] || value;
}

export function PrimarySidebar({ activeView, onNavigate, onNewSession, hasProject }) {
  const nav = [
    ["interview", "面试工作台", ListBullets],
    ["positions", "岗位准备", Briefcase],
    ["project", "项目资料", FolderSimple],
    ["resumes", "简历库", IdentificationCard],
    ["report", "会话复盘", FileText],
    ["profile", "能力画像", ChartBar],
    ["settings", "应用设置", GearSix],
  ];
  return (
    <aside className="stitch-primary-sidebar" aria-label="应用导航">
      <button className="stitch-new-session" type="button" onClick={onNewSession} disabled={!hasProject}>
        <Plus size={15} weight="bold" /> 新建复盘
      </button>
      <nav>
        {nav.map(([id, label, Icon]) => (
          <button className={activeView === id ? "is-active" : ""} type="button" onClick={() => onNavigate(id)} key={id}>
            <Icon size={17} weight="duotone" /><span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="stitch-sidebar-footer">
        <button type="button" onClick={() => onNavigate("settings")}><GearSix size={16} /> 应用设置</button>
      </div>
    </aside>
  );
}

const POSITION_STATUS = {
  preparing: "准备中",
  applied: "已投递",
  interviewing: "面试中",
  archived: "已归档",
};

function positionError(cause) {
  return cause?.details?.error || cause?.message || String(cause);
}

function parseProjectIds(value) {
  if (!value.trim()) return [];
  const ids = value.split(/[，,\s]+/).filter(Boolean).map(Number);
  if (ids.some((id) => !Number.isInteger(id) || id < 1)) {
    throw new Error("关联项目 ID 必须是用逗号分隔的正整数");
  }
  return [...new Set(ids)];
}

export function PositionPreparationView({ candidateId = "default", currentProjectId = "", onPractice }) {
  const [positions, setPositions] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [sessions, setSessions] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [notice, showNotice] = useAutoDismiss();
  const [activeTab, setActiveTab] = useState("overview");
  const [draft, setDraft] = useState({
    title: "",
    company: "",
    source_url: "",
    project_ids: currentProjectId ? String(currentProjectId) : "",
    jd_text: "",
  });
  const selected = positions.find((position) => position.position_id === selectedId) || null;

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError("");
    getPositions({ candidateId })
      .then((result) => {
        if (cancelled) return;
        const next = result?.positions || [];
        setPositions(next);
        setSelectedId((current) => next.some((item) => item.position_id === current)
          ? current
          : next[0]?.position_id || "");
      })
      .catch((cause) => {
        if (!cancelled) setError(`无法读取岗位：${positionError(cause)}`);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [candidateId]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedId) {
      setSessions([]);
      return undefined;
    }
    getSessions({ candidateId, positionId: selectedId })
      .then((result) => {
        if (!cancelled) setSessions(result?.sessions || []);
      })
      .catch((cause) => {
        if (!cancelled) setError(`无法读取岗位练习记录：${positionError(cause)}`);
      });
    return () => { cancelled = true; };
  }, [candidateId, selectedId]);

  function patchSelected(next) {
    setPositions((current) => current.map((item) => (
      item.position_id === next.position_id ? next : item
    )));
  }

  async function handleCreate(event) {
    event.preventDefault();
    setBusyAction("create");
    setError("");
    showNotice("");
    try {
      const created = await createPosition({
        candidate_id: candidateId,
        title: draft.title,
        company: draft.company,
        source_url: draft.source_url,
        project_ids: parseProjectIds(draft.project_ids),
        jd_text: draft.jd_text,
      });
      setPositions((current) => [created, ...current]);
      setSelectedId(created.position_id);
      setIsCreating(false);
      setDraft({ title: "", company: "", source_url: "", project_ids: currentProjectId ? String(currentProjectId) : "", jd_text: "" });
      showNotice(`已生成 ${created.questions?.length || 0} 道岗位准备题。`);
      setActiveTab("questions");
    } catch (cause) {
      setError(`创建岗位失败：${positionError(cause)}`);
    } finally {
      setBusyAction("");
    }
  }

  async function handleTextFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 1024 * 1024) {
      setError("JD 文本文件不能超过 1MB。");
      return;
    }
    try {
      const text = await file.text();
      setDraft((current) => ({
        ...current,
        jd_text: text,
        title: current.title || file.name.replace(/\.[^.]+$/, ""),
      }));
      showNotice(`已读取 ${file.name}，请确认岗位信息后保存。`);
    } catch (cause) {
      setError(`无法读取 JD 文件：${positionError(cause)}`);
    }
  }

  async function readImageBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  async function runOcr(file) {
    if (busyAction === "ocr") return;
    if (!file.type.startsWith("image/")) {
      setError("OCR 仅支持图片文件。");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("JD 图片不能超过 10MB。");
      return;
    }
    setBusyAction("ocr");
    setError("");
    showNotice("正在识别图片中的 JD 文本…");
    try {
      const base64 = await readImageBase64(file);
      const result = await ocrPositionJd(base64, file.type);
      setDraft((current) => ({
        ...current,
        jd_text: result.text,
        title: current.title || file.name.replace(/\.[^.]+$/, ""),
      }));
      showNotice("已从图片识别出 JD 文本，请确认后保存。");
    } catch (cause) {
      setError(`图片识别失败：${positionError(cause)}`);
    } finally {
      setBusyAction("");
    }
  }

  function handleImageFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    runOcr(file);
  }

  function handleJdPaste(event) {
    const files = event.clipboardData?.files;
    const image = files && files.length > 0 ? files[0] : null;
    if (image && image.type.startsWith("image/")) {
      event.preventDefault();
      runOcr(image);
    }
  }

  async function handleStatusChange(status) {
    if (!selected) return;
    setBusyAction("status");
    setError("");
    try {
      patchSelected(await updatePosition(selected.position_id, { status }));
      showNotice("岗位状态已更新。");
    } catch (cause) {
      setError(`更新岗位失败：${positionError(cause)}`);
    } finally {
      setBusyAction("");
    }
  }

  async function handleRegenerate() {
    if (!selected) return;
    setBusyAction("regenerate");
    setError("");
    try {
      const updated = await regeneratePositionQuestions(selected.position_id);
      patchSelected(updated);
      showNotice(`已重新生成 ${updated.questions?.length || 0} 道题。`);
    } catch (cause) {
      setError(`重新生成失败：${positionError(cause)}`);
    } finally {
      setBusyAction("");
    }
  }

  async function handleDelete() {
    if (!selected || !globalThis.confirm?.(`确定删除岗位“${selected.title}”吗？已有面试会话不会被删除。`)) return;
    setBusyAction("delete");
    setError("");
    try {
      await deletePosition(selected.position_id);
      const next = positions.filter((item) => item.position_id !== selected.position_id);
      setPositions(next);
      setSelectedId(next[0]?.position_id || "");
      showNotice("岗位已删除。");
    } catch (cause) {
      setError(`删除岗位失败：${positionError(cause)}`);
    } finally {
      setBusyAction("");
    }
  }

  async function handlePractice(question) {
    if (!question.project_id) {
      setError("该题没有关联项目，请先在岗位信息中关联项目后重新生成题目。");
      return;
    }
    setBusyAction(question.question_id);
    setError("");
    try {
      await onPractice(selected, question);
    } catch (cause) {
      setError(`无法开始专项练习：${positionError(cause)}`);
      setBusyAction("");
    }
  }

  return (
    <section className="stitch-page position-page" aria-label="岗位准备">
      <header className="stitch-page-header position-page-header">
        <div><span>POSITION PREPARATION</span><h1>岗位准备</h1><p>集中管理多个目标岗位，让每道题都能追溯到 JD 要求和项目证据。</p></div>
        <button className="position-create-button" type="button" onClick={() => setIsCreating(true)}><Plus size={16} weight="bold" /> 添加岗位</button>
      </header>
      {(error || notice) && <div className={`position-feedback ${error ? "is-error" : "is-success"}`} role={error ? "alert" : "status"}>{error ? <WarningCircle size={17} /> : <CheckCircle size={17} weight="fill" />}<span>{error || notice}</span></div>}
      {isLoading ? <div className="position-page-state">正在加载岗位资料…</div> : (
        <div className="position-layout">
          <aside className="position-list-panel">
            <div className="position-list-heading"><span>目标岗位</span><b>{positions.length}</b></div>
            {positions.length === 0 && <div className="position-empty-list"><Briefcase size={25} weight="duotone" /><strong>还没有目标岗位</strong><p>添加一份 JD，系统会提取要求并生成对应题目。</p></div>}
            {positions.map((position) => (
              <button className={`position-list-item ${position.position_id === selectedId ? "is-active" : ""}`} type="button" onClick={() => { setSelectedId(position.position_id); setActiveTab("overview"); }} key={position.position_id}>
                <span className="position-list-title-row"><strong>{position.title}</strong><span className={`position-status-badge is-${position.status}`}>{POSITION_STATUS[position.status]}</span></span>
                <small className="position-list-company">{position.company || "未填写公司"}</small>
                <span className="position-list-questions"><Brain size={13} weight="duotone" />{position.questions?.length || 0} Questions</span>
              </button>
            ))}
          </aside>
          <main className="position-detail-panel">
            {selected ? (
              <>
                <div className="position-detail-hero">
                  <div><span className="position-kicker">{selected.company || "目标岗位"}</span><h2>{selected.title}</h2><p>{selected.project_ids.length} 个关联项目 · {selected.requirements.length} 项要求 · {selected.questions.length} 道题</p></div>
                  <div className="position-detail-actions">
                    <select aria-label="岗位状态" value={selected.status} onChange={(event) => handleStatusChange(event.target.value)} disabled={Boolean(busyAction)}>{Object.entries(POSITION_STATUS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>
                    <button type="button" onClick={handleDelete} disabled={Boolean(busyAction)}><Trash size={15} /> 删除</button>
                  </div>
                </div>
                <div className="position-tabs" role="tablist">
                  {[["overview", "岗位概览"], ["questions", `题库 ${selected.questions.length}`], ["history", `练习记录 ${sessions.length}`]].map(([id, label]) => <button className={activeTab === id ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === id} onClick={() => setActiveTab(id)} key={id}>{label}</button>)}
                </div>
                {activeTab === "overview" && <div className="position-overview">
                  <section className="position-summary-grid"><div><strong>{selected.requirements.length}</strong><span>已提取要求</span></div><div><strong>{selected.questions.length}</strong><span>准备题目</span></div><div><strong>{selected.project_ids.length}</strong><span>关联项目</span></div><div><strong>{sessions.filter((item) => item.question_count > 0).length}</strong><span>已练会话</span></div></section>
                  <section className="position-content-section"><div className="position-section-heading"><span><Target size={18} /> JD 要求</span><small>系统从原文中提取</small></div><ol className="position-requirement-list">{selected.requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ol></section>
                  <details className="position-jd-source"><summary>查看 JD 原文</summary><pre>{selected.jd_text}</pre>{selected.source_url && <a href={selected.source_url} target="_blank" rel="noreferrer">打开来源链接 <ArrowRight size={13} /></a>}</details>
                </div>}
                {activeTab === "questions" && <div className="position-question-view">
                  <div className="position-section-heading"><span><ListBullets size={18} /> 岗位题库</span><button type="button" onClick={handleRegenerate} disabled={Boolean(busyAction)}><ArrowClockwise size={15} /> {busyAction === "regenerate" ? "生成中…" : "重新生成"}</button></div>
                  <div className="position-question-list">{selected.questions.map((question, index) => <article className="position-question-card" key={question.question_id}><div className="position-question-index">{String(index + 1).padStart(2, "0")}</div><div><span className="position-question-meta">{question.category === "project_evidence" ? `项目 ${question.project_id} · 项目证据题` : "经历题"}</span><h3>{question.text}</h3><p>对应要求：{question.requirement}</p>{question.evidence_ids.length > 0 && <small>证据：{question.evidence_ids.join("、")}</small>}</div><button type="button" onClick={() => handlePractice(question)} disabled={Boolean(busyAction) || !question.project_id}>{busyAction === question.question_id ? "启动中…" : "开始练习"}<Play size={14} weight="fill" /></button></article>)}</div>
                </div>}
                {activeTab === "history" && <div className="position-history-view">
                  <div className="position-section-heading"><span><ClockCounterClockwise size={18} /> 练习记录</span><small>由岗位题目发起的会话</small></div>
                  {sessions.length === 0 ? <div className="position-page-state">还没有练习记录，从题库选择一道题开始。</div> : sessions.map((item) => <article className="position-history-item" key={item.session_id}><span><strong>{item.title}</strong><small>{item.project_name} · {item.question_count} 次回答</small></span><b>{item.average_score === null ? "待作答" : `${item.average_score} 分`}</b></article>)}
                </div>}
              </>
            ) : <div className="position-page-state">选择一个岗位查看准备内容，或添加新的岗位。</div>}
          </main>
        </div>
      )}
      {isCreating && <div className="position-create-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyAction) setIsCreating(false); }}><form className="position-create-dialog" onSubmit={handleCreate} aria-label="添加目标岗位"><div className="position-create-heading"><div><span>NEW POSITION</span><h2>添加目标岗位</h2><p>粘贴 JD 或导入 UTF-8 文本文件。</p></div><button type="button" aria-label="关闭" onClick={() => setIsCreating(false)} disabled={Boolean(busyAction)}><X size={18} /></button></div><div className="position-form-grid"><label><span>岗位名称 *</span><input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} required maxLength={120} placeholder="例如：Java 后端工程师" /></label><label><span>公司</span><input value={draft.company} onChange={(event) => setDraft((current) => ({ ...current, company: event.target.value }))} maxLength={120} placeholder="公司或团队名称" /></label><label><span>来源链接</span><input type="url" value={draft.source_url} onChange={(event) => setDraft((current) => ({ ...current, source_url: event.target.value }))} maxLength={2000} placeholder="https://…" /></label><label><span>关联项目 ID</span><input value={draft.project_ids} onChange={(event) => setDraft((current) => ({ ...current, project_ids: event.target.value }))} placeholder="多个 ID 用逗号分隔" /></label></div><label className="position-jd-field"><span>JD 原文 *</span><textarea value={draft.jd_text} onChange={(event) => setDraft((current) => ({ ...current, jd_text: event.target.value }))} onPaste={handleJdPaste} required maxLength={100000} placeholder="粘贴岗位职责、任职要求和加分项…，或直接粘贴 JD 截图" /><label className="position-file-import"><UploadSimple size={15} /><span>导入 .txt / .md / .json</span><input type="file" accept=".txt,.md,.json,text/plain,text/markdown,application/json" onChange={handleTextFile} /></label><label className="position-file-import"><ImageSquare size={15} /><span>{busyAction === "ocr" ? "识别中…" : "导入 JD 截图"}</span><input type="file" accept="image/*" onChange={handleImageFile} disabled={busyAction === "ocr"} /></label></label><div className="position-create-footer"><small>图片和 PDF OCR 需在应用设置中配置大模型（视觉模型）；保存后会自动提取要求并生成题目。</small><span><button type="button" onClick={() => setIsCreating(false)} disabled={Boolean(busyAction)}>取消</button><button type="submit" disabled={Boolean(busyAction)}>{busyAction === "create" ? "正在生成…" : "保存并生成题目"}<ArrowRight size={15} /></button></span></div></form></div>}
    </section>
  );
}

export function InterviewContextRail({ workspace, session, tasks, structure, progress, selectedItem, onSelectTask, onSelectStructure, onNewSession, onRenameTask, onDeleteTask, busyTaskId, isCreatingSession }) {
  const [editingTaskId, setEditingTaskId] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [collapsedFields, setCollapsedFields] = useState({ claims: false, structure: false, sessions: false });

  function toggleCollapse(key) {
    setCollapsedFields((current) => ({ ...current, [key]: !current[key] }));
  }

  function beginRename(task) {
    setEditingTaskId(task.id);
    setDraftTitle(task.name);
  }

  async function submitRename(event, task) {
    event.preventDefault();
    const title = draftTitle.trim();
    if (!title) return;
    const renamed = await onRenameTask(task, title);
    if (renamed === false) return;
    setEditingTaskId("");
    setDraftTitle("");
  }

  async function confirmDelete(task) {
    if (!globalThis.confirm?.(`确定删除会话“${task.name}”吗？此操作无法撤销。`)) return;
    const deleted = await onDeleteTask(task);
    if (deleted === false) return;
    if (editingTaskId === task.id) setEditingTaskId("");
  }

  return (
    <aside className="interview-context-rail" aria-label="当前面试结构">
      <div className="context-workspace-select">
        <small>当前工作区</small>
        <strong>{workspace.name || session.projectName || "未命名项目"}</strong>
        <span>{session.status?.analysis_status || "READY"}</span>
      </div>
      {session.resumeClaims?.length > 0 && (
        <section className="context-resume-claims" aria-label="面试者主张">
          <button className="context-collapse" type="button" aria-expanded={!collapsedFields.claims} onClick={() => toggleCollapse("claims")}>
            <small>面试者主张</small>
            <span>{session.resumeClaims.length} 条</span>
            {collapsedFields.claims ? <CaretRight size={12} /> : <CaretDown size={12} />}
          </button>
          {!collapsedFields.claims && <>
            {session.resumeClaims.slice(0, 5).map((claim, index) => (
              <div className="context-claim" key={`${claim}-${index}`}><span>{claim}</span></div>
            ))}
            {session.resumeClaims.length > 5 && <small className="context-group-more">其余 {session.resumeClaims.length - 5} 条在简历详情中</small>}
          </>}
        </section>
      )}
      <section className="context-structure" aria-busy={isCreatingSession}>
        <button className="context-collapse" type="button" aria-expanded={!collapsedFields.structure} onClick={() => toggleCollapse("structure")}>
          <small>面试结构</small>
          <span>点击主题新建会话</span>
          {collapsedFields.structure ? <CaretRight size={12} /> : <CaretDown size={12} />}
        </button>
        {!collapsedFields.structure && (structure.length === 0 ? <div className="context-empty">暂无项目知识</div> : structure.map((group) => (
          <div className="context-group" key={group.label}>
            <strong>{group.label}</strong>
            {group.children?.map((child) => (
              <button
                className={`${selectedItem === child || session.topic === child ? "is-active" : ""} ${isCreatingSession && selectedItem === child && session.topic !== child ? "is-pending" : ""}`.trim()}
                type="button"
                onClick={() => onSelectStructure(child)}
                disabled={isCreatingSession}
                aria-current={session.topic === child ? "true" : undefined}
                key={child}
              >
                <span>{child}</span>
                <span className="context-topic-action">{session.topic === child ? "当前" : isCreatingSession && selectedItem === child ? "创建中" : "新会话"}<ArrowRight size={11} /></span>
              </button>
            ))}
            {group.totalCount > group.children.length && <small className="context-group-more">其余 {group.totalCount - group.children.length} 个方向在项目资料中</small>}
          </div>
        )))}
      </section>
      <section className="context-session-list">
        <div className="context-session-heading">
          <button className="context-collapse context-collapse-text" type="button" aria-expanded={!collapsedFields.sessions} onClick={() => toggleCollapse("sessions")}>
            <small>最近会话</small>
            <span>{tasks.length}</span>
          </button>
          <button className="context-session-add" type="button" onClick={onNewSession} aria-label="新增会话"><Plus size={13} /></button>
          <button className="context-collapse-caret" type="button" aria-expanded={!collapsedFields.sessions} aria-label={collapsedFields.sessions ? "展开最近会话" : "收起最近会话"} onClick={() => toggleCollapse("sessions")}>
            {collapsedFields.sessions ? <CaretRight size={12} /> : <CaretDown size={12} />}
          </button>
        </div>
        {!collapsedFields.sessions && <div className="context-session-rows">
        {tasks.length === 0 && <div className="context-empty">暂无会话，点击 + 新建。</div>}
        {(() => {
          const rows = [];
          const current = tasks.find((task) => task.id === session.sessionId);
          if (current) rows.push(current);
          for (const task of tasks) {
            if (task === current) continue;
            rows.push(task);
          }
          return rows.map((task) => {
            const isCurrent = task === current;
            return (
              <div className={`context-session-row ${isCurrent ? "is-active is-current" : ""}`} key={task.id}>
                {editingTaskId === task.id ? (
                  <form className="context-session-edit" onSubmit={(event) => submitRename(event, task)}>
                    <input autoFocus maxLength={80} aria-label="会话名称" value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setEditingTaskId(""); }} disabled={busyTaskId === task.id} />
                    <button type="submit" aria-label="保存会话名称" disabled={!draftTitle.trim() || busyTaskId === task.id}><Check size={13} /></button>
                    <button type="button" aria-label="取消编辑" onClick={() => setEditingTaskId("")} disabled={busyTaskId === task.id}><X size={13} /></button>
                  </form>
                ) : (
                  <>
                    <button className="context-session-open" type="button" onClick={() => onSelectTask(task)} title={task.name}>
                      <span>{task.name}</span>
                      {isCurrent && (<>
                        <span className="context-current-meta">{reviewModeLabel(session.reviewMode)} · {session.topic || "等待首个主题"}</span>
                        <span className="context-progress-label"><span>项目进度</span><b>{session.progress || 0}{session.totalQuestions ? ` / ${session.totalQuestions}` : ""}</b></span>
                        <span className="context-progress"><span style={{ width: `${progress}%` }} /></span>
                      </>)}
                      <ArrowRight size={13} />
                    </button>
                    <div className="context-session-actions">
                      <button type="button" aria-label={`编辑会话名称：${task.name}`} onClick={() => beginRename(task)} disabled={busyTaskId === task.id}><PencilSimple size={13} /></button>
                      <button className="is-danger" type="button" aria-label={`删除会话：${task.name}`} onClick={() => confirmDelete(task)} disabled={busyTaskId === task.id}><Trash size={13} /></button>
                    </div>
                  </>
                )}
              </div>
            );
          });
        })()}
        </div>}
      </section>
    </aside>
  );
}

export function ResumeUploadDialog({ open, onClose, onCreated }) {
  const [step, setStep] = useState("create");
  const [resumeDraft, setResumeDraft] = useState({ name: "", role: "", domain: "" });
  const [pdfFile, setPdfFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [createdResume, setCreatedResume] = useState(null);
  const [claimSkips, setClaimSkips] = useState({});

  useEffect(() => {
    if (!open) return;
    setStep("create");
    setResumeDraft({ name: "", role: "", domain: "" });
    setPdfFile(null);
    setUploadError("");
    setCreatedResume(null);
    setClaimSkips({});
  }, [open]);

  if (!open) return null;

  async function readPdfBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  async function handleResumeFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("PDF 简历不能超过 10MB。");
      return;
    }
    try {
      const base64 = await readPdfBase64(file);
      setPdfFile({ name: file.name, base64 });
      setResumeDraft((current) => ({ ...current, name: current.name || file.name.replace(/\.[^.]+$/, "") }));
      setUploadError("");
    } catch (cause) {
      setUploadError(`无法读取 PDF 简历：${cause?.message || "未知错误"}`);
    }
  }

  async function handleCreateResume(event) {
    event.preventDefault();
    if (!pdfFile || uploading) return;
    setUploading(true);
    setUploadError("");
    try {
      const created = await uploadResume({
        name: resumeDraft.name.trim(),
        role: resumeDraft.role.trim(),
        domain: resumeDraft.domain.trim(),
        file_base64: pdfFile.base64,
      });
      setCreatedResume(created);
      setClaimSkips(Object.fromEntries(created.claims.map((claim) => [claim.claim_id, claim.skip])));
      setStep("review");
    } catch (cause) {
      setUploadError(cause?.details?.error || cause?.message || "创建简历失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleConfirmCreatedResume() {
    if (!createdResume) return;
    setUploading(true);
    setUploadError("");
    try {
      const skippedClaims = createdResume.claims
        .filter((claim) => Boolean(claimSkips[claim.claim_id]) !== claim.skip)
        .map((claim) => ({ claim_id: claim.claim_id, skip: Boolean(claimSkips[claim.claim_id]) }));
      if (skippedClaims.length > 0) {
        await updateResume(createdResume.resume_id, { claims: skippedClaims });
      }
      await onCreated?.(createdResume);
    } catch (cause) {
      setUploadError(cause?.details?.error || cause?.message || "保存简历失败");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="resume-picker-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !uploading) onClose(); }}>
      <div className="resume-picker-dialog" role="dialog" aria-modal="true" aria-label={step === "create" ? "上传新简历" : "已提取简历主张"}>
        <header>
          <div>
            <span className="resume-picker-kicker">{step === "create" ? "NEW RESUME" : "EXTRACTION COMPLETE"}</span>
            <h2>{step === "create" ? "上传新简历" : "已提取简历主张"}</h2>
            <p>
              {step === "create" && "上传 PDF 简历，系统会提取面试者主张。"}
              {step === "review" && `已从 ${createdResume?.name || "简历"} 中识别 ${createdResume?.claims?.length || 0} 条可用于项目复盘的主张。`}
            </p>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose} disabled={uploading}><X size={18} /></button>
        </header>
        {step === "create" && (
          <form className="resume-create-form" id="resume-create-form" onSubmit={handleCreateResume}>
            <label className="resume-file-import"><UploadSimple size={15} /><span>上传 PDF 简历</span><input type="file" accept=".pdf,application/pdf" onChange={handleResumeFile} /></label>
            {pdfFile && (
              <div className="resume-pdf-file">
                <FilePdf size={14} />
                <span>{pdfFile.name}</span>
                <button type="button" onClick={() => setPdfFile(null)} disabled={uploading} aria-label="移除所选 PDF 文件"><X size={13} /></button>
              </div>
            )}
            <div className="resume-form-grid">
              <label className="resume-field"><span>姓名</span><input value={resumeDraft.name} onChange={(event) => setResumeDraft((current) => ({ ...current, name: event.target.value }))} maxLength={64} placeholder="留空时尝试从首行识别" /></label>
              <label className="resume-field"><span>岗位</span><input value={resumeDraft.role} onChange={(event) => setResumeDraft((current) => ({ ...current, role: event.target.value }))} maxLength={64} placeholder="例如：后端工程师" /></label>
              <label className="resume-field"><span>领域</span><input value={resumeDraft.domain} onChange={(event) => setResumeDraft((current) => ({ ...current, domain: event.target.value }))} maxLength={64} placeholder="例如：交易系统" /></label>
            </div>
            {uploadError && <div className="resume-create-error" role="alert"><WarningCircle size={15} /> {uploadError}</div>}
            <p className="resume-create-note">仅支持含文本层的 PDF 简历；扫描件（图片型 PDF）无法提取文本。</p>
          </form>
        )}
        {step === "review" && createdResume && (
          <div className="resume-review-view">
            <div className="resume-review-summary">
              <span className="resume-avatar">{createdResume.name[0]}</span>
              <div><strong>{createdResume.name}</strong><small>ID: {createdResume.resume_id} · 已提取</small></div>
            </div>
            <div className="resume-review-list">
              <h4>待确认的面试者主张</h4>
              {createdResume.claims.length === 0 && <div className="resume-picker-empty">未能从简历中识别可追问的主张，确认后将保留简历。</div>}
              {createdResume.claims.map((claim, index) => (
                <div className="resume-review-item" key={claim.claim_id}>
                  <span className="resume-review-index">{String(index + 1).padStart(2, "0")}</span>
                  <p>{claim.text}</p>
                  <label className="resume-skip-toggle">
                    <input type="checkbox" checked={Boolean(claimSkips[claim.claim_id])} onChange={(event) => setClaimSkips((current) => ({ ...current, [claim.claim_id]: event.target.checked }))} />
                    <span>暂不用以提问</span>
                  </label>
                </div>
              ))}
            </div>
          </div>
        )}
        <footer className="resume-picker-footer">
          <small>{step === "create" ? "保存后会自动提取主张，可在下一步确认" : "可在详情页随时查看原文与已提取内容"}</small>
          <span>
            {step === "create" && <button type="button" onClick={onClose} disabled={uploading}>取消</button>}
            {step === "create" && <button className="resume-confirm" type="submit" form="resume-create-form" disabled={!pdfFile || uploading}>{uploading ? "正在提取…" : "提交并提取"}<ArrowRight size={15} /></button>}
            {step === "review" && <button type="button" onClick={() => { setStep("create"); setCreatedResume(null); setUploadError(""); }} disabled={uploading}>返回重新选择文件</button>}
            {step === "review" && <button className="resume-confirm" type="button" onClick={handleConfirmCreatedResume} disabled={uploading}>{uploading ? "正在保存…" : "确认并选中"}<ArrowRight size={15} /></button>}
          </span>
        </footer>
      </div>
    </div>
  );
}

export function ResumeEditDialog({ resume, onClose, onSaved }) {
  const [draft, setDraft] = useState({ name: "", role: "", domain: "" });
  const [pdfFile, setPdfFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!resume) return;
    setDraft({ name: resume.name, role: resume.role, domain: resume.domain });
    setPdfFile(null);
    setSaving(false);
    setError("");
  }, [resume]);

  if (!resume) return null;

  async function readPdfBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
  }

  async function handlePdfFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError("PDF 简历不能超过 10MB。");
      return;
    }
    try {
      const base64 = await readPdfBase64(file);
      setPdfFile({ name: file.name, base64 });
      setError("");
    } catch (cause) {
      setError(`无法读取 PDF 简历：${cause?.message || "未知错误"}`);
    }
  }

  async function handleSave(event) {
    event.preventDefault();
    if (saving) return;
    const changes = {};
    if (draft.name.trim() !== resume.name) changes.name = draft.name.trim();
    if (draft.role.trim() !== resume.role) changes.role = draft.role.trim();
    if (draft.domain.trim() !== resume.domain) changes.domain = draft.domain.trim();
    if (pdfFile) changes.file_base64 = pdfFile.base64;
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await updateResume(resume.id, changes);
      await onSaved?.({ ...updated, pdfChanged: Boolean(pdfFile) });
    } catch (cause) {
      setError(cause?.details?.error || cause?.message || "保存简历失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="resume-picker-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
      <div className="resume-picker-dialog" role="dialog" aria-modal="true" aria-label={`编辑简历 ${resume.name}`}>
        <header>
          <div>
            <span className="resume-picker-kicker">EDIT RESUME</span>
            <h2>编辑简历</h2>
            <p>修改面试者信息，或替换 PDF 原件重新提取主张。</p>
          </div>
          <button type="button" aria-label="关闭" onClick={onClose} disabled={saving}><X size={18} /></button>
        </header>
        <form className="resume-create-form" id="resume-edit-form" onSubmit={handleSave}>
          <label className="resume-file-import"><UploadSimple size={15} /><span>{pdfFile ? "已选择替换文件" : "替换 PDF 原件（可选）"}</span><input type="file" accept=".pdf,application/pdf" onChange={handlePdfFile} /></label>
          {pdfFile && (
            <div className="resume-pdf-file">
              <FilePdf size={14} />
              <span>{pdfFile.name}</span>
              <button type="button" onClick={() => setPdfFile(null)} disabled={saving} aria-label="移除所选 PDF 文件"><X size={13} /></button>
            </div>
          )}
          {pdfFile && <p className="resume-create-note">替换后主张将按新 PDF 文本重新提取，原有“暂不用以提问”设置会重置。</p>}
          <div className="resume-form-grid">
            <label className="resume-field"><span>姓名</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} maxLength={64} required placeholder="面试者姓名" /></label>
            <label className="resume-field"><span>岗位</span><input value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))} maxLength={64} placeholder="例如：后端工程师" /></label>
            <label className="resume-field"><span>领域</span><input value={draft.domain} onChange={(event) => setDraft((current) => ({ ...current, domain: event.target.value }))} maxLength={64} placeholder="例如：交易系统" /></label>
          </div>
          {error && <div className="resume-create-error" role="alert"><WarningCircle size={15} /> {error}</div>}
        </form>
        <footer className="resume-picker-footer">
          <small>不选 PDF 则仅更新姓名、岗位与领域</small>
          <span>
            <button type="button" onClick={onClose} disabled={saving}>取消</button>
            <button className="resume-confirm" type="submit" form="resume-edit-form" disabled={saving}>{saving ? "正在保存…" : "保存修改"}<ArrowRight size={15} /></button>
          </span>
        </footer>
      </div>
    </div>
  );
}

export function SessionSetupView({ session, candidateId, isCreating, error, onCreate }) {
  const isMounted = useRef(true);
  const [mode, setMode] = useState(session.reviewMode || "technical_interview");
  const [candidate, setCandidate] = useState(candidateId || "default");
  const [isResumePickerOpen, setIsResumePickerOpen] = useState(false);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerSelectedId, setPickerSelectedId] = useState("");
  const [resumes, setResumes] = useState(RESUME_LIBRARY);
  const [resumesLoading, setResumesLoading] = useState(false);
  const [resumesOffline, setResumesOffline] = useState(false);
  const project = session.status?.universal_model || {};
  const componentCount = project.components?.length || Object.keys(session.project?.components || {}).length;
  const topicCount = project.topics?.length || session.project?.topics?.length || 0;
  const evidenceCount = project.evidence?.length || Object.keys(session.project?.evidence || {}).length;
  const candidateRecord = resumes.find((item) => item.id === candidate || item.resume_id === candidate) || null;
  const filteredResumes = resumes.filter((item) => {
    const query = pickerQuery.trim().toLowerCase();
    if (!query) return true;
    return [item.name, item.role, item.domain, item.project, item.id, item.project_names?.join(" ")]
      .some((field) => field.toLowerCase().includes(query));
  });

  useEffect(() => {
    loadResumes();
    return () => { isMounted.current = false; };
  }, []);

  function openResumePicker() {
    setPickerQuery("");
    setPickerSelectedId(candidateRecord?.id || "");
    setIsResumePickerOpen(true);
    loadResumes();
  }

  function confirmResumeSelection() {
    if (!pickerSelectedId) return;
    setCandidate(pickerSelectedId);
    setIsResumePickerOpen(false);
  }

  async function loadResumes() {
    setResumesLoading(true);
    try {
      const result = await getResumes();
      const items = result?.resumes || [];
      if (items.length > 0) {
        setResumes(items.map((item) => ({
          id: item.resume_id,
          name: item.name,
          role: item.role,
          domain: item.domain,
          status: item.status,
          statusTone: item.status === "extracted" ? "success" : item.status === "analyzing" ? "pending" : "draft",
          claims: item.claims_count,
          project: item.project_names?.join("、") || "未关联项目",
          updated: item.updated_at ? item.updated_at.slice(5, 10) : "",
        })));
      }
      if (isMounted.current) setResumesOffline(false);
    } catch {
      if (isMounted.current) setResumesOffline(true);
    } finally {
      if (isMounted.current) setResumesLoading(false);
    }
  }

  return (
    <section className="stitch-page session-setup-page" aria-label="新建复盘会话">
      <header className="stitch-page-header">
        <div><span>NEW REVIEW</span><h1>新建复盘会话</h1><p>基于当前项目知识，选择领域模式并创建一段可追溯的复盘会话。</p></div>
      </header>
      <div className="session-setup-grid">
        <aside className="review-mode-rail">
          <small>REVIEW MODALITY</small>
          {REVIEW_MODES.map(({ id, label, icon: Icon, description }) => (
            <button className={mode === id ? "is-active" : ""} type="button" onClick={() => setMode(id)} key={id}>
              <Icon size={19} weight="duotone" />
              <span><strong>{label}</strong><small>{description}</small></span>
              {mode === id && <CheckCircle size={16} weight="fill" />}
            </button>
          ))}
        </aside>
        <main className="session-setup-main">
          <section className="session-candidate-card">
            <div className="candidate-avatar"><User size={22} /></div>
            <div className="candidate-copy">
              <strong>{candidateRecord?.name || "未选择面试者"}</strong>
              <small>{candidateRecord ? `ID: ${candidateRecord.id}` : "从简历库选择面试者"}</small>
            </div>
            <span className="candidate-mode">{reviewModeLabel(mode)}</span>
            <button className="candidate-swap" type="button" onClick={openResumePicker}>更换</button>
          </section>
          <section className="session-project-card">
            <div className="session-field-heading"><span>项目知识范围</span><small>{session.projectName}</small></div>
            <div className="session-scope-stats">
              <div><strong>{componentCount}</strong><span>组件</span></div>
              <div><strong>{topicCount}</strong><span>主题</span></div>
              <div><strong>{evidenceCount}</strong><span>证据</span></div>
            </div>
            <div className="session-scope-bar"><span style={{ width: `${Math.min(100, Math.max(18, evidenceCount / 5))}%` }} /></div>
            <p>问题会优先引用当前项目的结构、流程、技术事实和证据，不生成脱离项目上下文的通用题。</p>
          </section>
          <section className="session-mode-summary">
            <Target size={21} weight="duotone" />
            <div><strong>{reviewModeLabel(mode)}</strong><p>{REVIEW_MODES.find((item) => item.id === mode)?.description}</p></div>
          </section>
          {error && <div className="inline-error" role="alert"><WarningCircle size={17} /> {error}</div>}
          <div className="session-create-actions">
            <span>创建后会生成首个项目证据问题</span>
            <button type="button" onClick={() => onCreate({ candidateId: candidate.trim() || "default", reviewMode: mode })} disabled={isCreating}>
              {isCreating ? "正在创建…" : "开始复盘会话"}<ArrowRight size={16} />
            </button>
          </div>
        </main>
      </div>
      {isResumePickerOpen && (
        <div className="resume-picker-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setIsResumePickerOpen(false); }}>
          <div className="resume-picker-dialog" role="dialog" aria-modal="true" aria-label="选择简历">
            <header>
              <div>
                <span className="resume-picker-kicker">SELECT CANDIDATE</span>
                <h2>选择简历</h2>
                <p>从简历库选择面试者，系统将结合简历主张与项目知识生成复盘</p>
              </div>
              <button type="button" aria-label="关闭" onClick={() => setIsResumePickerOpen(false)}><X size={18} /></button>
            </header>
            <div className="resume-picker-search">
              <MagnifyingGlass size={16} />
              <input value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} placeholder="搜索姓名、岗位或项目" aria-label="搜索简历" />
              <span>{resumesLoading ? "加载中…" : `共 ${filteredResumes.length} 份简历`}</span>
            </div>
            {resumesOffline && <div className="resume-picker-offline">后端简历库不可用，当前展示离线演示数据。</div>}
            <div className="resume-picker-list">
              {filteredResumes.length === 0 && <div className="resume-picker-empty">没有匹配的简历，试试其他关键词。</div>}
              {filteredResumes.map((resume) => (
                <button className={`resume-picker-row ${pickerSelectedId === resume.id ? "is-selected" : ""}`} type="button" onClick={() => setPickerSelectedId(resume.id)} key={resume.id}>
                  <span className="resume-avatar">{resume.name[0]}</span>
                  <span className="resume-picker-copy">
                    <span className="resume-picker-name-row">
                      <strong>{resume.name}</strong>
                      <span>{resume.role}</span>
                      <span>· {resume.domain}</span>
                      <b className={`resume-badge is-${resume.statusTone}`}>{resumeStatusLabel(resume.status)}</b>
                      {resume.id === candidate && <b className="resume-badge is-current">当前已选</b>}
                    </span>
                    <small className="resume-meta">ID: {resume.id} · {resume.claims} 条主张 · 关联 {resume.project} · 更新于 {resume.updated}</small>
                  </span>
                  <span className="resume-radio">{pickerSelectedId === resume.id && <Check size={12} weight="bold" />}</span>
                </button>
              ))}
              <button className="resume-upload-row" type="button" onClick={() => setIsUploadDialogOpen(true)}>
                <Plus size={16} /> 上传新简历
              </button>
            </div>
            <footer className="resume-picker-footer">
              <small>可随时在简历库管理或补充简历</small>
              <span>
                <button type="button" onClick={() => setIsResumePickerOpen(false)}>取消</button>
                <button className="resume-confirm" type="button" onClick={confirmResumeSelection} disabled={!pickerSelectedId}>确认选择<ArrowRight size={15} /></button>
              </span>
            </footer>
          </div>
        </div>
      )}
      <ResumeUploadDialog
        open={isUploadDialogOpen}
        onClose={() => setIsUploadDialogOpen(false)}
        onCreated={async (resume) => {
          await loadResumes();
          setCandidate(resume.resume_id);
          setIsResumePickerOpen(false);
          setIsUploadDialogOpen(false);
        }}
      />
    </section>
  );
}

function normalizeResumeItem(item) {
  return {
    id: item.resume_id,
    name: item.name,
    role: item.role,
    domain: item.domain,
    status: item.status,
    statusTone: item.status === "extracted" ? "success" : item.status === "analyzing" ? "pending" : "draft",
    claims: item.claims_count,
    project: item.project_names?.join("、") || "未关联项目",
    updated: item.updated_at ? item.updated_at.slice(5, 10) : "",
  };
}

const RESUME_RAIL_MIN = 240;
const RESUME_RAIL_MAX = 480;
const RESUME_RAIL_DEFAULT = 340;
const RESUME_RAIL_KEY = "resume_rail_width";

function defaultResumeRailWidth() {
  const stored = Number(globalThis.localStorage?.getItem(RESUME_RAIL_KEY));
  return Number.isFinite(stored) && stored >= RESUME_RAIL_MIN && stored <= RESUME_RAIL_MAX ? stored : RESUME_RAIL_DEFAULT;
}

export function ResumeLibraryView() {
  const [resumes, setResumes] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, showNotice] = useAutoDismiss();
  const [query, setQuery] = useState("");
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [detailVersion, setDetailVersion] = useState(0);
  const [editingResume, setEditingResume] = useState(null);
  const [railWidth, setRailWidth] = useState(defaultResumeRailWidth);
  const [dragIndex, setDragIndex] = useState(null);
  const [overIndex, setOverIndex] = useState(null);

  const railResize = usePanelResize({
    value: railWidth,
    onChange: setRailWidth,
    min: RESUME_RAIL_MIN,
    max: RESUME_RAIL_MAX,
    direction: 1,
    storageKey: RESUME_RAIL_KEY,
    onReset: () => RESUME_RAIL_DEFAULT,
  });

  async function loadResumes() {
    setIsLoading(true);
    setError("");
    try {
      const result = await getResumes();
      setResumes((result?.resumes || []).map(normalizeResumeItem));
    } catch (cause) {
      setError(cause?.details?.error || cause?.message || "无法读取简历库");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadResumes();
  }, []);

  // 进入简历库或删除当前项后，自动选中最顶部一条（尊重用户已做的选择）。
  useEffect(() => {
    if (!isLoading && resumes.length > 0 && !selectedId) {
      setSelectedId(resumes[0].id);
    }
  }, [isLoading, resumes.length, selectedId]);

  const filtered = resumes.filter((item) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [item.name, item.role, item.domain, item.project, item.id]
      .some((field) => field.toLowerCase().includes(needle));
  });

  function handleDragStart(event, index) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(index));
    setDragIndex(index);
  }

  function handleDragOver(event, index) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (overIndex !== index) setOverIndex(index);
  }

  function resetDragState() {
    setDragIndex(null);
    setOverIndex(null);
  }

  async function handleDrop() {
    if (dragIndex === null || overIndex === null || dragIndex === overIndex) {
      resetDragState();
      return;
    }
    const previous = resumes;
    const next = [...resumes];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(overIndex, 0, moved);
    resetDragState();
    setResumes(next);
    showNotice("");
    try {
      await reorderResumes(next.map((item) => item.id));
      showNotice("简历顺序已保存。");
    } catch (cause) {
      setResumes(previous);
      setError(cause?.details?.error || cause?.message || "保存简历顺序失败");
    }
  }

  async function handleDeleteItem(item) {
    if (!globalThis.confirm?.(`确定删除简历“${item.name}”吗？此操作无法撤销。`)) return;
    setError("");
    try {
      await deleteResume(item.id);
      if (selectedId === item.id) setSelectedId("");
      showNotice("简历已删除。");
      await loadResumes();
    } catch (cause) {
      showNotice("");
      setError(`删除简历失败：${cause?.details?.error || cause?.message || "未知错误"}`);
    }
  }

  return (
    <section className="stitch-page resume-library-page two-column" style={{ gridTemplateColumns: `${railWidth}px minmax(0, 1fr)` }} aria-label="简历库">
      <aside className="resume-library-rail" aria-label="简历列表">
        <div className="resume-library-rail-head">
          <span>CANDIDATE CONTEXT</span>
          <h1>简历库</h1>
          <p>按目标岗位管理可用于复盘的简历版本。</p>
          <button className="resume-upload-button" type="button" onClick={() => setIsUploadOpen(true)}><UploadSimple size={15} /> 上传简历</button>
        </div>
        <div className="resume-library-search">
          <MagnifyingGlass size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索简历或岗位" aria-label="搜索简历" />
          <span>{filtered.length} / {resumes.length}</span>
        </div>
        <div className="resume-library-list">
          {(error || notice) && <div className={`resume-list-feedback ${error ? "is-error" : "is-success"}`} role={error ? "alert" : "status"}>{error ? <WarningCircle size={14} /> : <CheckCircle size={14} weight="fill" />}<span>{error || notice}</span></div>}
          {isLoading ? <div className="resume-list-state">正在加载简历库…</div> : resumes.length === 0 ? (
            <div className="resume-list-state"><strong>简历库还是空的</strong><p>上传一份简历，系统会提取面试者主张用于复盘提问。</p><button type="button" onClick={() => setIsUploadOpen(true)}><Plus size={14} /> 上传新简历</button></div>
          ) : filtered.length === 0 ? (
            <div className="resume-list-state"><strong>没有匹配的简历</strong><p>试试其他关键词。</p></div>
          ) : (
            filtered.map((resume, index) => (
              <div
                className={`resume-list-item ${selectedId === resume.id ? "is-active" : ""} ${dragIndex === index ? "is-dragging" : ""} ${overIndex === index && dragIndex !== null && dragIndex !== index ? "is-drop-target" : ""}`}
                key={resume.id}
                draggable={!query}
                onDragStart={(event) => handleDragStart(event, index)}
                onDragOver={(event) => handleDragOver(event, index)}
                onDragLeave={() => { if (overIndex === index) setOverIndex(null); }}
                onDrop={handleDrop}
                onDragEnd={resetDragState}
                title={query ? "清除搜索后可拖拽排序" : "拖拽可调整简历顺序"}
              >
                <button className="resume-list-select" type="button" onClick={() => setSelectedId(resume.id)}>
                  <FileText size={17} />
                  <span className="resume-list-copy">
                    <strong>{resume.name}</strong>
                    <small>
                      <b className={`resume-badge is-${resume.statusTone}`}>{resumeStatusLabel(resume.status)}</b>
                      <span>{resume.role}{resume.domain ? ` · ${resume.domain}` : ""} · 更新于 {resume.updated}</span>
                    </small>
                  </span>
                </button>
                <span className="resume-list-actions">
                  <button type="button" aria-label={`编辑 ${resume.name}`} title="编辑简历" onClick={() => setEditingResume(resume)}><PencilSimple size={13} /></button>
                  <button type="button" aria-label={`删除 ${resume.name}`} title="删除简历" onClick={() => handleDeleteItem(resume)}><Trash size={13} /></button>
                </span>
              </div>
            ))
          )}
        </div>
      </aside>
      <div
        className="workspace-resizer resume-library-resizer"
        role="separator"
        aria-label="调整简历列表宽度"
        aria-orientation="vertical"
        aria-valuemin={RESUME_RAIL_MIN}
        aria-valuemax={RESUME_RAIL_MAX}
        aria-valuenow={railWidth}
        tabIndex={0}
        style={{ left: railWidth }}
        {...railResize.handlers}
      />
      <main className="resume-library-detail">
        {selectedId ? (
          <ResumeDetailView
            key={detailVersion}
            embedded
            resumeId={selectedId}
            onDeleted={() => { setSelectedId(""); showNotice("简历已删除。"); loadResumes(); }}
          />
        ) : (
          <div className="resume-detail-empty-state"><FileText size={26} weight="duotone" /><strong>选择一份简历查看详情</strong><p>从左侧选择简历，查看提取的主张、标签与原文。</p></div>
        )}
      </main>
      <ResumeUploadDialog
        open={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onCreated={async () => {
          setIsUploadOpen(false);
          showNotice("简历已上传并提取主张。");
          await loadResumes();
        }}
      />
      <ResumeEditDialog
        resume={editingResume}
        onClose={() => setEditingResume(null)}
        onSaved={async (updated) => {
          setEditingResume(null);
          showNotice(updated.pdfChanged ? "简历信息与 PDF 原件已更新，主张已按新文本重新提取。" : "简历信息已保存。");
          setDetailVersion((version) => version + 1);
          await loadResumes();
        }}
      />
    </section>
  );
}

function ResumePdfPreview({ data }) {
  const pagesRef = useRef(null);
  const [status, setStatus] = useState("正在加载 PDF…");

  useEffect(() => {
    let cancelled = false;
    const container = pagesRef.current;
    if (!container) return undefined;
    container.replaceChildren();
    setStatus("正在加载 PDF…");
    (async () => {
      try {
        const pdf = await pdfjsLib.getDocument({ data: data.slice(0) }).promise;
        if (cancelled) return;
        for (let index = 1; index <= pdf.numPages; index += 1) {
          const page = await pdf.getPage(index);
          const viewport = page.getViewport({ scale: 1.5 });
          const canvas = document.createElement("canvas");
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
          if (cancelled) return;
          container.appendChild(canvas);
        }
        if (!cancelled) setStatus("");
      } catch (cause) {
        if (!cancelled) setStatus(`PDF 渲染失败：${cause?.message || "未知错误"}`);
      }
    })();
    return () => { cancelled = true; };
  }, [data]);

  return (
    <div className="resume-pdf-view">
      {status && <div className="resume-pdf-status"><FilePdf size={15} /> {status}</div>}
      <div className="resume-pdf-pages" ref={pagesRef} />
    </div>
  );
}

export function ResumeDetailView({ resumeId, onDeleted, embedded = false }) {
  const [resume, setResume] = useState(null);
  const [pdfData, setPdfData] = useState(null);
  const [pdfError, setPdfError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [savingId, setSavingId] = useState("");
  const [savedNotice, showSavedNotice] = useAutoDismiss();

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError("");
    setPdfData(null);
    setPdfError("");
    getResume(resumeId)
      .then((item) => { if (!cancelled) setResume(item); })
      .catch((cause) => { if (!cancelled) setError(cause?.details?.error || cause?.message || "无法读取简历"); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    getResumePdf(resumeId)
      .then((bytes) => { if (!cancelled) setPdfData(bytes); })
      .catch((cause) => {
        if (cancelled) return;
        setPdfError(cause?.status === 404 ? "该简历是历史数据，没有 PDF 原件。" : cause?.details?.error || cause?.message || "无法读取 PDF");
      });
    return () => { cancelled = true; };
  }, [resumeId]);

  async function toggleClaimSkip(claim, skip) {
    setSavingId(claim.claim_id);
    showSavedNotice("");
    setError("");
    try {
      const updated = await updateResume(resume.resume_id, { claims: [{ claim_id: claim.claim_id, skip }] });
      setResume(updated);
      showSavedNotice("主张设置已保存。");
    } catch (cause) {
      setError(`保存失败：${cause?.details?.error || cause?.message || "未知错误"}`);
    } finally {
      setSavingId("");
    }
  }

  async function handleDelete() {
    if (!resume || !globalThis.confirm?.(`确定删除简历“${resume.name}”吗？此操作无法撤销。`)) return;
    setError("");
    try {
      await deleteResume(resume.resume_id);
      onDeleted?.();
    } catch (cause) {
      setError(`删除简历失败：${cause?.details?.error || cause?.message || "未知错误"}`);
    }
  }

  return (
    <section className={`stitch-page resume-detail-page${embedded ? " is-embedded" : ""}`} aria-label="简历详情">
      {isLoading ? <div className="position-page-state">正在读取简历…</div> : error && !resume ? (
        <div className="position-page-state"><WarningCircle size={22} /> <p>{error}</p>{!embedded && <button type="button" onClick={() => onDeleted?.()}>返回简历库</button>}</div>
      ) : resume && (
        <>
          <header className="resume-detail-header">
            {!embedded && <button className="resume-detail-back" type="button" onClick={() => onDeleted?.()}><ArrowRight size={16} className="back-icon" /> 简历库</button>}
            <div className="resume-detail-title">
              <span className="resume-avatar is-large">{resume.name[0]}</span>
              <div><h1>{resume.name}</h1><p>{resume.role}{resume.domain ? ` · ${resume.domain}` : ""} · ID: {resume.resume_id} · {resumeStatusLabel(resume.status)}</p></div>
            </div>
            <button className="resume-library-delete is-text" type="button" onClick={handleDelete}><Trash size={15} /> 删除简历</button>
          </header>
          {(error || savedNotice) && <div className={`position-feedback ${error ? "is-error" : "is-success"}`} role={error ? "alert" : "status"}>{error ? <WarningCircle size={17} /> : <CheckCircle size={17} weight="fill" />}<span>{error || savedNotice}</span></div>}
          <div className="resume-detail-layout">
            <main>
              {pdfData ? (
                <ResumePdfPreview data={pdfData} />
              ) : (
                <div className="resume-detail-empty is-pdf-empty">
                  <FilePdf size={18} />
                  <p>{pdfError || "该简历没有可预览的 PDF 原件。"}</p>
                </div>
              )}
            </main>
            <aside className="resume-detail-aside">
              <section className="resume-detail-claims">
                <div className="resume-detail-heading"><strong>面试者主张</strong><span>{resume.claims.length} 条 · 关闭“暂不用以提问”后该主张不再进入复盘</span></div>
                {resume.claims.length === 0 && <div className="resume-detail-empty">未从该简历中识别出可追问的主张。</div>}
                {resume.claims.map((claim, index) => (
                  <article className="resume-detail-claim" key={claim.claim_id}>
                    <span className="resume-review-index">{String(index + 1).padStart(2, "0")}</span>
                    <div><p>{claim.text}</p><small>{claim.source}</small></div>
                    <label className="resume-skip-toggle">
                      <input type="checkbox" checked={Boolean(claim.skip)} disabled={savingId === claim.claim_id} onChange={(event) => toggleClaimSkip(claim, event.target.checked)} />
                      <span>{savingId === claim.claim_id ? "保存中…" : "暂不用以提问"}</span>
                    </label>
                  </article>
                ))}
              </section>
              <section><small>关联项目</small>{resume.project_ids.length === 0 ? <p>未关联项目</p> : <div className="resume-detail-projects">{resume.project_ids.map((id) => <span key={id}>项目 {id}</span>)}</div>}</section>
              <section><small>创建时间</small><strong className="resume-meta">{resume.created_at?.slice(0, 10) || "—"}</strong></section>
              <section><small>更新时间</small><strong className="resume-meta">{resume.updated_at?.slice(0, 10) || "—"}</strong></section>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}

export function SessionReportView({ report, loading, error, onRetry, onPractice, focusedRecordIndex = null }) {
  const [expanded, setExpanded] = useState(0);
  const focusedRecordRef = useRef(null);
  useEffect(() => {
    if (Number.isInteger(focusedRecordIndex) && focusedRecordIndex >= 0) {
      setExpanded(focusedRecordIndex);
    }
  }, [focusedRecordIndex, report?.session_id]);
  useEffect(() => {
    if (!report || !Number.isInteger(focusedRecordIndex)) return undefined;
    const frame = requestAnimationFrame(() => {
      focusedRecordRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [focusedRecordIndex, report?.session_id]);
  if (loading) return <PageState title="正在生成会话复盘" detail="读取回答、评价与证据引用…" />;
  if (error) return <PageState title="无法读取会话复盘" detail={error} action="重新读取" onAction={onRetry} />;
  if (!report) return <PageState title="暂无会话复盘" detail="完成至少一次回答后，这里会出现基于后端评价的复盘报告。" action="返回练习" onAction={onPractice} />;
  const score = report.average_score;
  return (
    <section className="stitch-page report-page" aria-label="会话复盘报告">
      <header className="report-header">
        <div><span>会话复盘报告</span><h1>{report.project_name}</h1><p>{reviewModeLabel(report.review_mode)} · {report.candidate_id} · {report.question_count} 次回答</p></div>
        <div className="report-header-stats"><div><strong>{report.question_count}</strong><small>QUESTIONS</small></div><div><strong>{report.evidence_ids.length}</strong><small>EVIDENCE</small></div></div>
      </header>
      <div className="report-layout">
        <main>
          <section className="report-score-card">
            <div className="report-score-title"><span>综合评估</span><strong>{score ?? "—"}<small>/100</small></strong></div>
            <div className="report-score-line"><span style={{ width: `${score || 0}%` }} /></div>
            <div className="report-feedback-grid">
              <div><strong>优势</strong>{report.strengths.length ? report.strengths.map((item) => <p key={item}><CheckCircle size={14} />{item}</p>) : <p>继续积累高质量回答样本。</p>}</div>
              <div><strong>待提升</strong>{report.weaknesses.length ? report.weaknesses.map((item) => <p key={item}><WarningCircle size={14} />{item}</p>) : <p>当前没有明确弱项。</p>}</div>
            </div>
          </section>
          <section className="report-records">
            <div className="report-section-heading"><strong>会话详情</strong><span>{report.records.length} 题</span></div>
            {report.records.map((record, index) => (
              <article ref={focusedRecordIndex === index ? focusedRecordRef : undefined} className={expanded === index ? "is-expanded" : ""} key={`${record.question}-${index}`}>
                <button type="button" onClick={() => setExpanded(expanded === index ? -1 : index)}>
                  <span>{String(index + 1).padStart(2, "0")}</span><strong>{record.topic}</strong><b>{record.evaluation.score}</b><ArrowRight size={14} />
                </button>
                {expanded === index && <div><h3>{record.question}</h3><blockquote>{record.answer}</blockquote><p>{record.evaluation.feedback}</p><div>{record.evaluation.evidence_ids.map((id) => <code key={id}>{id}</code>)}</div></div>}
              </article>
            ))}
          </section>
        </main>
        <aside className="report-aside">
          <section><small>证据覆盖</small><strong>{report.evidence_ids.length}</strong><div className="report-aside-bar"><span style={{ width: `${Math.min(100, report.evidence_ids.length * 16)}%` }} /></div></section>
          <section><small>主题分布</small>{report.topics.map((topic) => <div className="report-topic" key={topic.name}><span>{topic.name}</span><strong>{topic.average_score}</strong></div>)}</section>
          <section><small>下一轮练习</small><p>{report.next_direction ? `建议继续进行“${report.next_direction}”方向的项目追问。` : "继续完成当前项目的证据驱动练习。"}</p></section>
          <button type="button" onClick={onPractice}>开始针对性练习<ArrowRight size={16} /></button>
        </aside>
      </div>
    </section>
  );
}

export function CandidateProfileView({ profile, loading, error, onRetry, onPractice, onOpenSource }) {
  if (loading) return <PageState title="正在读取能力画像" detail="汇总面试者的跨会话主题表现…" />;
  if (error) return <PageState title="无法读取能力画像" detail={error} action="重新读取" onAction={onRetry} />;
  const skills = Object.entries(profile?.skills || {});
  if (skills.length === 0) return <PageState title="能力画像还没有样本" detail="完成一次回答后，后端会按主题保存分数、趋势、样本数和薄弱项。" action="开始练习" onAction={onPractice} />;
  const weaknesses = skills.flatMap(([topic, item]) => {
    const sources = new Map((item.weakness_sources || []).map((source) => [source.weakness, source]));
    return item.weaknesses.map((text) => ({ topic, text, source: sources.get(text) }));
  });
  return (
    <section className="stitch-page profile-page" aria-label="面试者能力画像">
      <header className="profile-header">
        <div className="candidate-avatar is-large"><User size={26} /></div>
        <div><h1>{profile.candidate_id}</h1><p>跨会话能力画像 · profile v{profile.version}</p></div>
        <div className="profile-summary"><div><strong>{skills.length}</strong><small>能力主题</small></div><div><strong>{skills.reduce((sum, [, item]) => sum + item.sample_count, 0)}</strong><small>样本</small></div></div>
        <button type="button" onClick={onPractice}>创建针对性会话</button>
      </header>
      <div className="profile-layout">
        <main>
          <section className="profile-quote"><Sparkle size={18} weight="duotone" /><p>画像只使用后端已保存的项目回答评价；样本少的主题会保留样本数，不制造虚假的精确趋势。</p></section>
          <section className="skill-matrix">
            <div className="report-section-heading"><strong>能力矩阵</strong><span>Based on real evidence</span></div>
            <div className="skill-grid">
              {skills.map(([name, skill]) => (
                <article key={name}>
                  <div><strong>{name}</strong><b>{skill.score}</b></div>
                  <small>{skill.trend} · {skill.sample_count} 个样本</small>
                  <div className="skill-bar"><span style={{ width: `${skill.score}%` }} /></div>
                  {skill.weaknesses[0] && <p>{skill.weaknesses[0]}</p>}
                </article>
              ))}
            </div>
          </section>
          <section className="profile-history-note"><ClockCounterClockwise size={18} /><div><strong>画像持续更新</strong><p>每次提交回答后，面试者的主题分数、最近表现、趋势和薄弱项都会由后端事务更新。</p></div></section>
        </main>
        <aside className="profile-aside">
          <section><div className="report-section-heading"><strong>能力趋势</strong><TrendUp size={16} /></div><div className="profile-bars">{skills.slice(0, 7).map(([name, skill]) => <span title={`${name} ${skill.score}`} style={{ height: `${Math.max(22, skill.score)}%` }} key={name} />)}</div></section>
          <section><div className="report-section-heading"><strong>重点薄弱点</strong><span>{weaknesses.length}</span></div>{weaknesses.length ? weaknesses.slice(0, 4).map((item) => <article key={`${item.topic}-${item.text}`}><strong>{item.topic}</strong><p>{item.text}</p>{item.source ? <button className="profile-source-link" type="button" title={`会话 ${item.source.session_id}`} onClick={() => onOpenSource?.(item.source)}><ClockCounterClockwise size={13} />第 {item.source.record_index + 1} 题 · {item.source.evidence_ids.length} 条证据<ArrowRight size={12} /></button> : <small className="profile-source-empty">历史画像暂无可追溯来源</small>}</article>) : <p className="profile-empty-copy">暂无明确薄弱项。</p>}</section>
          <button type="button" onClick={onPractice}><Target size={16} /> 创建针对性练习</button>
        </aside>
      </div>
    </section>
  );
}

function PageState({ title, detail, action, onAction }) {
  return (
    <section className="stitch-page-state" role="status">
      <span><Sparkle size={24} weight="duotone" /></span>
      <h1>{title}</h1><p>{detail}</p>
      {action && <button type="button" onClick={onAction}>{action}<ArrowRight size={15} /></button>}
    </section>
  );
}

export { REVIEW_MODES, reviewModeLabel };
