import assert from "node:assert/strict";
import test from "node:test";

import {
  activateLLMProfile,
  completeSession,
  createLLMProfile,
  createPosition,
  createResume,
  createAgent,
  deletePosition,
  deleteResume,
  deleteSession,
  deleteLLMProfile,
  deleteAgent,
  getAgents,
  getLLMProfiles,
  getLLMModels,
  getLLMSettings,
  getProjectKnowledge,
  getProjectStatus,
  getProjects,
  getPositions,
  getResume,
  getResumePdf,
  getResumes,
  getSessionReport,
  getSessions,
  getCandidateProfile,
  getSession,
  openProjectDirectory,
  ocrPositionJd,
  pickProjectDirectory,
  reusePromise,
  renameSession,
  regeneratePositionQuestions,
  reorderResumes,
  saveLLMSettings,
  startInterviewSession,
  submitAnswer,
  submitAnswerStream,
  testLLMConnection,
  testLLMProfile,
  updateAgent,
  updateResume,
  updateLLMProfile,
  updatePosition,
  uploadProject,
  uploadResume,
} from "../src/api.js";

const project = {
  project_id: 1,
  project_name: "Backend system",
  topics: [{ name: "Performance", score: 90 }],
};

test("uploadProject posts the source descriptor to the upload endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  const descriptor = {
    project_id: 26,
    project_name: "Real project",
    source: { type: "folder", files: [{ path: "pom.xml", content: "<project />" }] },
  };
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ project_id: 26, analysis_status: "READY" }), { status: 201 });
  };

  try {
    const result = await uploadProject(descriptor);
    assert.equal(result.analysis_status, "READY");
    assert.equal(request.url, "http://127.0.0.1:8000/projects/upload");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), descriptor);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("API errors expose the stable backend error contract", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({
      error: "会话版本冲突",
      code: "version_conflict",
      retryable: true,
      request_id: "request-1",
    }),
    { status: 409, headers: { "X-Request-ID": "request-1" } },
  );

  try {
    await assert.rejects(
      () => getSession("session-1"),
      (error) => {
        assert.equal(error.message, "会话版本冲突");
        assert.equal(error.status, 409);
        assert.equal(error.code, "version_conflict");
        assert.equal(error.retryable, true);
        assert.equal(error.requestId, "request-1");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("project status, knowledge, and session use their read endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ project_id: 26, analysis_status: "READY" }), { status: 200 });
  };

  try {
    await getProjectStatus(26);
    await getProjectKnowledge(26);
    await getSession("session-1");
    await getSessionReport("session-1");
    await getCandidateProfile("candidate-1");
    assert.deepEqual(requests.map(({ url }) => url), [
      "http://127.0.0.1:8000/projects/26/status",
      "http://127.0.0.1:8000/projects/26/knowledge",
      "http://127.0.0.1:8000/sessions/session-1",
      "http://127.0.0.1:8000/sessions/session-1/report",
      "http://127.0.0.1:8000/candidates/candidate-1/profile",
    ]);
    assert.deepEqual(requests.map(({ options }) => options.headers), [
      { "Content-Type": "application/json" },
      { "Content-Type": "application/json" },
      { "Content-Type": "application/json" },
      { "Content-Type": "application/json" },
      { "Content-Type": "application/json" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getSessions reads server-backed history with project and candidate filters", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ sessions: [], count: 0 }), { status: 200 });
  };

  try {
    const result = await getSessions({ projectId: 26, candidateId: "alice", limit: 10 });
    assert.deepEqual(result, { sessions: [], count: 0 });
    assert.equal(
      request.url,
      "http://127.0.0.1:8000/sessions?project_id=26&candidate_id=alice&limit=10",
    );
    assert.deepEqual(request.options.headers, { "Content-Type": "application/json" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("position preparation API supports list, create, update, regenerate, and delete", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ position_id: "position-1", positions: [], count: 0, deleted: true }), { status: 200 });
  };

  try {
    await getPositions({ candidateId: "alice", limit: 10 });
    await createPosition({ title: "后端工程师", jd_text: "熟悉数据库" });
    await updatePosition("position-1", { status: "interviewing" });
    await regeneratePositionQuestions("position-1");
    await deletePosition("position-1");
    assert.deepEqual(requests.map(({ url, options }) => [url, options?.method || "GET"]), [
      ["http://127.0.0.1:8000/positions?candidate_id=alice&limit=10", "GET"],
      ["http://127.0.0.1:8000/positions", "POST"],
      ["http://127.0.0.1:8000/positions/position-1", "PATCH"],
      ["http://127.0.0.1:8000/positions/position-1/questions", "POST"],
      ["http://127.0.0.1:8000/positions/position-1", "DELETE"],
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ocrPositionJd posts the image to the OCR endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ text: "岗位职责：开发", chars: 8 }), { status: 200 });
  };

  try {
    const result = await ocrPositionJd("QUJD", "image/png");
    assert.deepEqual(result, { text: "岗位职责：开发", chars: 8 });
    assert.equal(request.url, "http://127.0.0.1:8000/positions/ocr");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), {
      image_base64: "QUJD",
      mime_type: "image/png",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("resume library API supports list, create, get, update, and delete", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ resume_id: "resume-1", resumes: [], count: 0 }), { status: 200 });
  };

  try {
    await getResumes({ candidateId: "alice", limit: 10 });
    await createResume({ name: "林澈", resume_text: "负责订单链路" });
    await getResume("resume-1");
    await updateResume("resume-1", { role: "后端工程师" });
    await deleteResume("resume-1");
    await reorderResumes(["resume-b", "resume-1"]);
    assert.deepEqual(requests.map(({ url, options }) => [url, options?.method || "GET"]), [
      ["http://127.0.0.1:8000/resumes?candidate_id=alice&limit=10", "GET"],
      ["http://127.0.0.1:8000/resumes", "POST"],
      ["http://127.0.0.1:8000/resumes/resume-1", "GET"],
      ["http://127.0.0.1:8000/resumes/resume-1", "PATCH"],
      ["http://127.0.0.1:8000/resumes/resume-1", "DELETE"],
      ["http://127.0.0.1:8000/resumes/order", "PUT"],
    ]);
    assert.deepEqual(JSON.parse(requests.at(-1).options.body), { resume_ids: ["resume-b", "resume-1"] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("uploadResume posts the base64 PDF to the upload endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ resume_id: "resume-pdf-1", name: "张三", status: "extracted" }), { status: 201 });
  };

  try {
    const result = await uploadResume({ name: "张三", role: "后端工程师", file_base64: "JVBERi0xLjQK" });
    assert.equal(result.resume_id, "resume-pdf-1");
    assert.equal(request.url, "http://127.0.0.1:8000/resumes/upload");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), { name: "张三", role: "后端工程师", file_base64: "JVBERi0xLjQK" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getResumePdf downloads the resume PDF as bytes with a JSON error contract", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  const encoder = new TextEncoder();
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(encoder.encode("%PDF-1.4 fake"), { status: 200, headers: { "Content-Type": "application/pdf" } });
  };

  try {
    const bytes = await getResumePdf("resume-1");
    assert.ok(bytes instanceof ArrayBuffer);
    assert.equal(new TextDecoder().decode(bytes), "%PDF-1.4 fake");
    assert.equal(requests[0].url, "http://127.0.0.1:8000/resumes/resume-1/pdf");
    assert.equal(requests[0].options, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getResumePdf surfaces backend errors from the PDF endpoint", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({ error: "resume pdf not found", code: "resume_not_found", retryable: false, request_id: "r1" }),
    { status: 404, headers: { "X-Request-ID": "r1" } },
  );

  try {
    await assert.rejects(
      () => getResumePdf("missing"),
      (error) => {
        assert.equal(error.status, 404);
        assert.equal(error.code, "resume_not_found");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("completeSession ends the active session without a request body", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ session_id: "session-1", state: { status: "completed" } }), { status: 200 });
  };

  try {
    const result = await completeSession("session-1");
    assert.equal(result.state.status, "completed");
    assert.equal(request.url, "http://127.0.0.1:8000/sessions/session-1/complete");
    assert.equal(request.options.method, "POST");
    assert.equal(request.options.body, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("session rename and delete use the session resource", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ session_id: "session-1", state: { title: "联调复盘" }, deleted: true }), { status: 200 });
  };

  try {
    const renamed = await renameSession("session-1", "联调复盘");
    const deleted = await deleteSession("session-1");

    assert.equal(renamed.state.title, "联调复盘");
    assert.deepEqual(requests.map(({ url }) => url), [
      "http://127.0.0.1:8000/sessions/session-1",
      "http://127.0.0.1:8000/sessions/session-1",
    ]);
    assert.deepEqual(requests.map(({ options }) => options.method), ["PATCH", "DELETE"]);
    assert.deepEqual(JSON.parse(requests[0].options.body), { title: "联调复盘" });
    assert.equal(requests[1].options.body, undefined);
    assert.equal(deleted.deleted, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("LLM settings use backend read, save, and connection-test endpoints", async () => {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ configured: true, api_key_set: true, ok: true }), { status: 200 });
  };
  const payload = {
    provider: "openai_compatible",
    base_url: "https://example.test/v1",
    api_key: "secret",
    model: "demo-model",
  };

  try {
    await getLLMSettings();
    await saveLLMSettings(payload);
    await testLLMConnection(payload);
    assert.deepEqual(requests.map(({ url, options }) => [url, options.method || "GET"]), [
      ["http://127.0.0.1:8000/settings/llm", "GET"],
      ["http://127.0.0.1:8000/settings/llm", "POST"],
      ["http://127.0.0.1:8000/settings/llm/test", "POST"],
    ]);
    assert.deepEqual(JSON.parse(requests[1].options.body), payload);
    assert.deepEqual(JSON.parse(requests[2].options.body), payload);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("LLM model discovery posts credentials without saving settings", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ models: ["deepseek-v4-flash"] }), { status: 200 });
  };

  try {
    const result = await getLLMModels({
      provider: "openai_compatible",
      base_url: "https://api.deepseek.com",
      api_key: "secret",
    });
    assert.deepEqual(result.models, ["deepseek-v4-flash"]);
    assert.equal(request.url, "http://127.0.0.1:8000/settings/llm/models");
    assert.equal(request.options.method, "POST");
    assert.deepEqual(JSON.parse(request.options.body), {
      provider: "openai_compatible",
      base_url: "https://api.deepseek.com",
      api_key: "secret",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("LLM profile API uses CRUD, activation, and saved-profile test endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ id: "p1", profiles: [], ok: true }), { status: 200 });
  };

  try {
    await getLLMProfiles();
    await createLLMProfile({ name: "Agnes", model: "agnes-model" });
    await updateLLMProfile("p1", { name: "Agnes 生产" });
    await activateLLMProfile("p1");
    await testLLMProfile("p1");
    await deleteLLMProfile("p1");
    assert.deepEqual(requests.map(({ url, options }) => [url, options?.method || "GET"]), [
      ["http://127.0.0.1:8000/settings/llm/profiles", "GET"],
      ["http://127.0.0.1:8000/settings/llm/profiles", "POST"],
      ["http://127.0.0.1:8000/settings/llm/profiles/p1", "PUT"],
      ["http://127.0.0.1:8000/settings/llm/profiles/p1/activate", "POST"],
      ["http://127.0.0.1:8000/settings/llm/profiles/p1/test", "POST"],
      ["http://127.0.0.1:8000/settings/llm/profiles/p1", "DELETE"],
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("startInterviewSession starts a titled project session with candidate, review mode, and topic", async () => {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ session_id: "session-1", state: { question: "First question" } }), { status: 201 });
  };

  try {
    const result = await startInterviewSession(26, "alice", "portfolio_review", "作品集练习", "Transaction");
    assert.equal(result.sessionId, "session-1");
    assert.equal(result.state.question, "First question");
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "http://127.0.0.1:8000/sessions");
    assert.equal(requests[0].options.method, "POST");
    assert.deepEqual(JSON.parse(requests[0].options.body), { project_id: 26, candidate_id: "alice", review_mode: "portfolio_review", title: "作品集练习", topic: "Transaction" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("startInterviewSession carries position and question linkage", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ session_id: "session-1", state: {} }), { status: 201 });
  };
  try {
    await startInterviewSession(26, "alice", "technical_interview", "岗位练习", undefined, "position-1", "question-1");
    assert.deepEqual(JSON.parse(request.options.body), {
      project_id: 26,
      candidate_id: "alice",
      review_mode: "technical_interview",
      title: "岗位练习",
      position_id: "position-1",
      position_question_id: "question-1",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("startInterviewSession carries agent mode and agent ids", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ session_id: "session-1", state: {} }), { status: 201 });
  };
  try {
    await startInterviewSession(
      26,
      "alice",
      "technical_interview",
      undefined,
      undefined,
      undefined,
      undefined,
      "multi",
      { questioner: "builtin-stress", evaluator: "builtin-evaluator", director: "builtin-director" },
    );
    assert.deepEqual(JSON.parse(request.options.body), {
      project_id: 26,
      candidate_id: "alice",
      review_mode: "technical_interview",
      agent_mode: "multi",
      agent_ids: { questioner: "builtin-stress", evaluator: "builtin-evaluator", director: "builtin-director" },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("agent CRUD helpers hit the settings/agents endpoints", async () => {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ agents: [] }), { status: 200 });
  };

  try {
    await getAgents();
    await createAgent({ name: "x", role: "questioner", persona: "p" });
    await updateAgent("custom-1", { name: "y" });
    await deleteAgent("custom-1");
    assert.deepEqual(requests.map((item) => [item.url, item.options?.method || "GET"]), [
      ["http://127.0.0.1:8000/settings/agents", "GET"],
      ["http://127.0.0.1:8000/settings/agents", "POST"],
      ["http://127.0.0.1:8000/settings/agents/custom-1", "PUT"],
      ["http://127.0.0.1:8000/settings/agents/custom-1", "DELETE"],
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("startInterviewSession keeps the legacy project object registration path", async () => {
  const requests = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    const payload = url.endsWith("/projects")
      ? project
      : { session_id: "session-legacy", state: { question: "Legacy question" } };
    return new Response(JSON.stringify(payload), { status: 201 });
  };

  try {
    const result = await startInterviewSession(project);
    assert.equal(result.sessionId, "session-legacy");
    assert.equal(requests.length, 2);
    assert.equal(requests[0].url, "http://127.0.0.1:8000/projects");
    assert.equal(requests[1].url, "http://127.0.0.1:8000/sessions");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitAnswer sends the answer to the active session", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(
      JSON.stringify({
        session_id: "session-1",
        state: { evaluation: { score: 80 }, question: "Next question" },
      }),
      { status: 200 },
    );
  };

  try {
    const result = await submitAnswer("My answer", { sessionId: "session-1" });
    assert.equal(request.url, "http://127.0.0.1:8000/sessions/session-1/answers");
    assert.deepEqual(JSON.parse(request.options.body), { answer: "My answer" });
    assert.equal(result.state.question, "Next question");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitAnswerStream parses status, chunks, and the final session state", async () => {
  const originalFetch = globalThis.fetch;
  const events = [];
  const encoder = new TextEncoder();
  const frames = [
    'event: status\ndata: {"message":"正在评价回答"}\n\n',
    'event: progress\ndata: {"message":"正在评价回答（已等待 5 秒）","elapsed":5}\n\n',
    'event: eval_chunk\ndata: {"text":"先比对证据"}\n\n',
    'event: eval_chunk\ndata: {"text":"，再给评分"}\n\n',
    'event: usage\ndata: {"prompt_tokens":120,"completion_tokens":30,"total_tokens":150}\n\n',
    'event: chunk\ndata: {"text":"参考回答"}\n\n',
    'event: done\ndata: {"session_id":"session-1","state":{"question":"Next question"}}\n\n',
  ];
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      frames.forEach((frame) => controller.enqueue(encoder.encode(frame)));
      controller.close();
    },
  }), { status: 200, headers: { "Content-Type": "text/event-stream" } });

  try {
    const result = await submitAnswerStream("My answer", { sessionId: "session-1" }, (event, payload) => {
      events.push([event, payload]);
    });
    assert.equal(result.state.question, "Next question");
    assert.deepEqual(events.map(([event]) => event), ["status", "progress", "eval_chunk", "eval_chunk", "usage", "chunk", "done"]);
    assert.equal(events[2][1].text, "先比对证据");
    assert.equal(events[4][1].total_tokens, 150);
    assert.equal(events[5][1].text, "参考回答");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("submitAnswerStream forwards an abort signal to fetch", async () => {
  const originalFetch = globalThis.fetch;
  let receivedOptions = null;
  globalThis.fetch = async (_url, options) => {
    receivedOptions = options;
    return new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: done\ndata: {"session_id":"session-1","state":{"question":"Next"}}\n\n'));
        controller.close();
      },
    }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
  const controller = new AbortController();

  try {
    const result = await submitAnswerStream("My answer", { sessionId: "session-1" }, () => {}, controller.signal);
    assert.equal(result.state.question, "Next");
    assert.strictEqual(receivedOptions.signal, controller.signal);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reusePromise calls the startup loader once for a shared ref", async () => {
  const ref = { current: null };
  let calls = 0;
  const loader = async () => {
    calls += 1;
    return "startup";
  };

  const first = reusePromise(ref, loader);
  const second = reusePromise(ref, loader);

  assert.strictEqual(first, second);
  assert.equal(await second, "startup");
  assert.equal(calls, 1);
});

test("openProjectDirectory invokes the Tauri native command", async () => {
  const calls = [];
  const invoke = async (...args) => calls.push(args);

  await openProjectDirectory("..", invoke);

  assert.deepEqual(calls, [["open_project_directory", { path: ".." }]]);
});

test("pickProjectDirectory opens the native dialog and remembers the last path", async () => {
  const invoke = async () => null;
  let dialogRequest;
  const dialog = {
    open: async (options) => {
      dialogRequest = { options };
      return "C:\\projects\\demo";
    },
  };

  const originalStorage = globalThis.localStorage;
  const stored = {};
  globalThis.localStorage = {
    getItem: (key) => stored[key] ?? null,
    setItem: (key, value) => { stored[key] = String(value); },
    removeItem: (key) => { delete stored[key]; },
  };

  try {
    const result = await pickProjectDirectory({ invoke, dialog });
    assert.equal(result, "C:\\projects\\demo");
    assert.equal(stored.last_project_dir, "C:\\projects\\demo");
    assert.equal(dialogRequest.options.directory, true);
    assert.equal(dialogRequest.options.defaultPath, undefined);

    dialog.open = async (options) => {
      dialogRequest = { options };
      return "C:\\projects\\second";
    };
    await pickProjectDirectory({ invoke, dialog });
    assert.equal(dialogRequest.options.defaultPath, "C:\\projects\\demo");
  } finally {
    globalThis.localStorage = originalStorage;
  }
});

test("pickProjectDirectory returns null when the dialog is cancelled", async () => {
  const invoke = async () => null;
  const dialog = { open: async () => null };

  const result = await pickProjectDirectory({ invoke, dialog });

  assert.equal(result, null);
});

test("pickProjectDirectory rejects calls outside Tauri", async () => {
  await assert.rejects(
    () => pickProjectDirectory({ invoke: null }),
    /not running in Tauri/,
  );
});

test("getProjects fetches the project summary list", async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ projects: [{ project_id: 1, project_name: "支付系统" }], count: 1 }), { status: 200 });
  };

  try {
    const result = await getProjects();
    assert.equal(result.count, 1);
    assert.equal(result.projects[0].project_name, "支付系统");
    assert.equal(request.url, "http://127.0.0.1:8000/projects");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
