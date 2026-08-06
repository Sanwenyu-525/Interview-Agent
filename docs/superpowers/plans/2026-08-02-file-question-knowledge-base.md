# 文件提问与知识库入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Agent 聊天框内提供文件夹选择，并让用户明确选择“针对文件提问”或“存入知识库”，两条路径都能得到可理解的结果反馈。

**Architecture:** 复用现有浏览器目录选择器、项目分析和 SQLite 项目知识持久化。两种模式共享文件读取与分析链路；“针对文件提问”完成分析后进入现有面试会话，“存入知识库”完成同样的持久化后以知识库成功状态进入可继续提问的 Agent 会话。第一阶段不引入向量库、远程存储、5 万文件分片上传或 Agnes Provider。

**Tech Stack:** React + Vite, existing folder JSON upload API, existing ProjectAnalysis/Universal Project Model, Node test runner.

---

### Task 1: 为上传菜单增加意图选择

**Files:**
- Modify: `frontend/src/App.jsx` (`ProjectUploadControl`)
- Modify: `frontend/src/styles.css` (mode selector and result status)
- Test: `frontend/tests/project-flow.test.mjs`

- [x] **Step 1: Write the failing test**

断言上传菜单存在两个互斥模式、提交文案随模式变化，并将模式传入上传流程。

- [x] **Step 2: Run the focused test to verify it fails**

Run: `node --test tests/project-flow.test.mjs`

Expected: 新增模式断言失败，因为当前菜单没有 `uploadMode`、`ask` 和 `knowledge`。

- [x] **Step 3: Implement the minimal UI state**

增加 `uploadMode`，默认 `ask`；在选择文件后显示两个 radio-style buttons：

```jsx
<div className="upload-mode-switch" role="radiogroup" aria-label="文件处理方式">
  <button type="button" role="radio" aria-checked={uploadMode === "ask"} onClick={() => setUploadMode("ask")}>针对文件提问</button>
  <button type="button" role="radio" aria-checked={uploadMode === "knowledge"} onClick={() => setUploadMode("knowledge")}>存入知识库</button>
</div>
```

模式选择必须位于文件夹选择结果和候选人 ID 之间；当前模式在提交按钮和状态说明中可见。

- [x] **Step 4: Run focused tests to verify they pass**

Run: `node --test tests/project-flow.test.mjs`

Expected: 所有项目流程测试通过。

### Task 2: 让两种模式复用同一项目知识链路

**Files:**
- Modify: `frontend/src/App.jsx` (`ProjectUploadControl`, upload copy and completion state)
- Modify: `frontend/src/api.js` only if the mode metadata needs an explicit request field
- Test: `frontend/tests/project-flow.test.mjs`

- [x] **Step 1: Write the failing test**

断言“针对文件提问”仍调用 `uploadProject → status/knowledge → startInterviewSession`；“存入知识库”显示知识库成功提示，并继续使用同一项目 ID 作为可恢复知识上下文。

- [x] **Step 2: Run the focused test to verify it fails**

Run: `node --test tests/project-flow.test.mjs`

Expected: 知识库模式文案和完成状态断言失败。

- [x] **Step 3: Implement the minimal flow**

不复制上传逻辑：两种模式都使用现有 `createFolderUploadDescriptor` 和 `uploadProject`。区别只体现在用户意图和完成反馈：

```jsx
const completionCopy = uploadMode === "knowledge"
  ? "项目已存入知识库，Agent 可以基于项目结构和证据继续提问。"
  : "项目已准备完成，可以开始针对文件提问。";
```

保留现有 `saveProjectId(projectId)`，确保知识库项目刷新后仍可恢复；继续由后端返回的 `knowledge` 和 `evidence` 作为 Agent 上下文，不在前端复制分析逻辑。

- [x] **Step 4: Run focused tests to verify they pass**

Run: `node --test tests/project-flow.test.mjs`

Expected: 所有项目流程测试通过。

### Task 3: 验证完整前端闭环

**Files:**
- Modify: `frontend/tests/project-flow.test.mjs` only if regression coverage needs tightening

- [x] **Step 1: Run all frontend tests**

Run: `npm test`

Expected: 全部前端测试通过。

- [x] **Step 2: Build the Sites artifacts**

Run: `npm run build`

Expected: 生成 `dist/client/index.html`、`dist/server/index.js` 和 `dist/.openai/hosting.json`。

- [x] **Step 3: Check the UI manually**

启动 Vite 预览，确认附件菜单在桌面和窄屏下都能看到模式选择；上传等待时仍显示阶段状态，成功后不会丢失项目知识上下文。

## Boundary for the next phase

- 5 万文件：需要分片/流式上传和后台分析任务，不在本轮只改常量。
- Agnes：先保持模型接入独立，后续增加后端 Provider；本轮不把 API Key 或远程模型调用放进前端。
- 自由问答：当前会话接口仍是面试回答协议；真正的“用户任意提问 → 知识库检索 → Agent 回答”需要单独设计问答 API。
