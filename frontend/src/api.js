const API_BASE = import.meta.env?.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options) {
  if (!API_BASE) return null;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = new Error(`API request failed: ${response.status}`);
    error.status = response.status;
    try {
      error.details = await response.json();
      error.code = error.details?.code || "unknown_error";
      error.retryable = Boolean(error.details?.retryable);
      error.requestId = error.details?.request_id || response.headers.get("X-Request-ID") || "";
      if (typeof error.details?.error === "string" && error.details.error) {
        error.message = error.details.error;
      }
    } catch {
      error.details = null;
      error.code = "invalid_error_response";
      error.retryable = false;
      error.requestId = response.headers.get("X-Request-ID") || "";
    }
    throw error;
  }
  return response.json();
}

async function streamRequest(path, options, onEvent = () => {}) {
  if (!API_BASE) return null;
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const error = new Error(`API request failed: ${response.status}`);
    error.status = response.status;
    try {
      error.details = await response.json();
      error.code = error.details?.code || "unknown_error";
      error.retryable = Boolean(error.details?.retryable);
      error.requestId = error.details?.request_id || response.headers.get("X-Request-ID") || "";
      if (typeof error.details?.error === "string" && error.details.error) {
        error.message = error.details.error;
      }
    } catch {
      error.details = null;
      error.code = "invalid_error_response";
      error.retryable = false;
      error.requestId = response.headers.get("X-Request-ID") || "";
    }
    throw error;
  }
  if (!response.body?.getReader) {
    throw new Error("面试回答流式响应不可用");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed;

  async function consumeFrames(flush = false) {
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = flush ? "" : (frames.pop() || "");
    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      if (!data) continue;
      const payload = JSON.parse(data);
      onEvent(event, payload);
      if (event === "chunk") await new Promise((resolve) => setTimeout(resolve, 0));
      if (event === "error") {
        const error = new Error(payload.error || "回答流式处理失败");
        Object.assign(error, payload);
        error.details = payload;
        throw error;
      }
      if (event === "done") completed = payload;
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    await consumeFrames();
  }
  buffer += decoder.decode();
  await consumeFrames(true);
  return completed;
}

export function uploadProject(sourceDescriptor) {
  return request("/projects/upload", {
    method: "POST",
    body: JSON.stringify(sourceDescriptor),
  });
}

export function getProjectStatus(projectId) {
  return request(`/projects/${projectId}/status`);
}

export function getProjectKnowledge(projectId) {
  return request(`/projects/${projectId}/knowledge`);
}

export function getPositions({ candidateId = "default", limit } = {}) {
  const params = new URLSearchParams();
  if (candidateId && String(candidateId).trim()) params.set("candidate_id", String(candidateId));
  if (limit !== undefined && limit !== null) params.set("limit", String(limit));
  const query = params.toString();
  return request(`/positions${query ? `?${query}` : ""}`);
}

export function createPosition(position) {
  return request("/positions", {
    method: "POST",
    body: JSON.stringify(position),
  });
}

export function updatePosition(positionId, changes) {
  return request(`/positions/${encodeURIComponent(positionId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deletePosition(positionId) {
  return request(`/positions/${encodeURIComponent(positionId)}`, { method: "DELETE" });
}

export function regeneratePositionQuestions(positionId) {
  return request(`/positions/${encodeURIComponent(positionId)}/questions`, { method: "POST" });
}

export function getResumes({ candidateId, limit } = {}) {
  const params = new URLSearchParams();
  if (candidateId && String(candidateId).trim()) params.set("candidate_id", String(candidateId));
  if (limit !== undefined && limit !== null) params.set("limit", String(limit));
  const query = params.toString();
  return request(`/resumes${query ? `?${query}` : ""}`);
}

export function createResume(resume) {
  return request("/resumes", {
    method: "POST",
    body: JSON.stringify(resume),
  });
}

export function uploadResume(resume) {
  return request("/resumes/upload", {
    method: "POST",
    body: JSON.stringify(resume),
  });
}

export function getResume(resumeId) {
  return request(`/resumes/${encodeURIComponent(resumeId)}`);
}

export async function getResumePdf(resumeId) {
  const response = await fetch(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}/pdf`);
  if (!response.ok) {
    const error = new Error(`API request failed: ${response.status}`);
    error.status = response.status;
    try {
      error.details = await response.json();
      error.code = error.details?.code || "unknown_error";
      error.retryable = Boolean(error.details?.retryable);
      error.requestId = error.details?.request_id || response.headers.get("X-Request-ID") || "";
      if (typeof error.details?.error === "string" && error.details.error) {
        error.message = error.details.error;
      }
    } catch {
      error.details = null;
      error.code = "invalid_error_response";
      error.retryable = false;
      error.requestId = response.headers.get("X-Request-ID") || "";
    }
    throw error;
  }
  return response.arrayBuffer();
}

export function updateResume(resumeId, changes) {
  return request(`/resumes/${encodeURIComponent(resumeId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deleteResume(resumeId) {
  return request(`/resumes/${encodeURIComponent(resumeId)}`, { method: "DELETE" });
}

export function reorderResumes(resumeIds) {
  return request("/resumes/order", {
    method: "PUT",
    body: JSON.stringify({ resume_ids: resumeIds }),
  });
}

export function getLLMSettings() {
  return request("/settings/llm");
}

export function getLLMProfiles() {
  return request("/settings/llm/profiles");
}

export function createLLMProfile(profile) {
  return request("/settings/llm/profiles", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

export function updateLLMProfile(profileId, profile) {
  return request(`/settings/llm/profiles/${profileId}`, {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}

export function deleteLLMProfile(profileId) {
  return request(`/settings/llm/profiles/${profileId}`, { method: "DELETE" });
}

export function activateLLMProfile(profileId) {
  return request(`/settings/llm/profiles/${profileId}/activate`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function testLLMProfile(profileId) {
  return request(`/settings/llm/profiles/${profileId}/test`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getLLMModels(settings) {
  return request("/settings/llm/models", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function saveLLMSettings(settings) {
  return request("/settings/llm", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function testLLMConnection(settings) {
  return request("/settings/llm/test", {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

export function getSession(sessionId) {
  return request(`/sessions/${sessionId}`);
}

export function renameSession(sessionId, title) {
  if (!sessionId) throw new Error("Missing interview session ID");
  return request(`/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteSession(sessionId) {
  if (!sessionId) throw new Error("Missing interview session ID");
  return request(`/sessions/${sessionId}`, { method: "DELETE" });
}

export function getSessions({ projectId, candidateId, positionId, limit } = {}) {
  const params = new URLSearchParams();
  if (projectId !== undefined && projectId !== null && String(projectId).trim()) {
    params.set("project_id", String(projectId));
  }
  if (candidateId !== undefined && candidateId !== null && String(candidateId).trim()) {
    params.set("candidate_id", String(candidateId));
  }
  if (positionId !== undefined && positionId !== null && String(positionId).trim()) {
    params.set("position_id", String(positionId));
  }
  if (limit !== undefined && limit !== null) params.set("limit", String(limit));
  const query = params.toString();
  return request(`/sessions${query ? `?${query}` : ""}`);
}

export function getSessionReport(sessionId) {
  return request(`/sessions/${sessionId}/report`);
}

export function completeSession(sessionId) {
  if (!sessionId) throw new Error("Missing interview session ID");
  return request(`/sessions/${sessionId}/complete`, { method: "POST" });
}

export function getCandidateProfile(candidateId) {
  return request(`/candidates/${encodeURIComponent(candidateId)}/profile`);
}

export function reusePromise(ref, factory) {
  if (!ref.current) ref.current = factory();
  return ref.current;
}

export function submitAnswer(answer, session) {
  if (!session.sessionId) throw new Error("Missing interview session ID");
  return request(`/sessions/${session.sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  });
}

export function submitAnswerStream(answer, session, onEvent) {
  if (!session.sessionId) throw new Error("Missing interview session ID");
  return streamRequest(`/sessions/${session.sessionId}/answers/stream`, {
    method: "POST",
    body: JSON.stringify({ answer }),
  }, onEvent);
}

export async function startInterviewSession(projectId, candidateId, reviewMode, title, topic, positionId, positionQuestionId) {
  let resolvedProjectId = projectId;

  // Keep the old object-based API working for callers that still register a
  // manually described project before starting a session.
  if (projectId && typeof projectId === "object") {
    const registered = await request("/projects", {
      method: "POST",
      body: JSON.stringify(projectId),
    });
    resolvedProjectId = registered.project_id ?? projectId.project_id;
  }

  const payload = { project_id: resolvedProjectId };
  if (candidateId !== undefined && candidateId !== null && String(candidateId).trim()) {
    payload.candidate_id = candidateId;
  }
  if (reviewMode !== undefined && reviewMode !== null && String(reviewMode).trim()) {
    payload.review_mode = reviewMode;
  }
  if (title !== undefined && title !== null && String(title).trim()) {
    payload.title = title;
  }
  if (topic !== undefined && topic !== null && String(topic).trim()) {
    payload.topic = topic;
  }
  if (positionId !== undefined && positionId !== null && String(positionId).trim()) {
    payload.position_id = positionId;
  }
  if (positionQuestionId !== undefined && positionQuestionId !== null && String(positionQuestionId).trim()) {
    payload.position_question_id = positionQuestionId;
  }
  const result = await request("/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { sessionId: result.session_id, state: result.state };
}

export function openProjectDirectory(path, invoke = globalThis.__TAURI_INTERNALS__?.invoke) {
  if (typeof invoke !== "function") throw new Error("This page is not running in Tauri desktop mode");
  return invoke("open_project_directory", { path });
}

const LAST_PROJECT_DIR_KEY = "last_project_dir";

export async function pickProjectDirectory({ invoke = globalThis.__TAURI_INTERNALS__?.invoke, dialog = null } = {}) {
  if (typeof invoke !== "function") throw new Error("This page is not running in Tauri desktop mode");
  const dialogApi = dialog || (await import("@tauri-apps/plugin-dialog"));
  const lastDirectory = (() => {
    try {
      return globalThis.localStorage?.getItem(LAST_PROJECT_DIR_KEY) || undefined;
    } catch {
      return undefined;
    }
  })();
  const selected = await dialogApi.open({
    directory: true,
    multiple: false,
    title: "选择项目文件夹作为工作区",
    defaultPath: lastDirectory,
  });
  if (typeof selected !== "string" || !selected.trim()) return null;
  try {
    globalThis.localStorage?.setItem(LAST_PROJECT_DIR_KEY, selected.trim());
  } catch {
    // localStorage 不可用时忽略，不影响本次选择
  }
  return selected.trim();
}
