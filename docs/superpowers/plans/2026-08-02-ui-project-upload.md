# UI Project Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户启动前后端后，可以在前端选择项目目录并通过现有 Folder JSON API 上传，分析完成后自动进入面试会话。

**Architecture:** 保留后端现有 `POST /projects/upload` 契约，不引入 multipart 或新依赖。浏览器使用目录选择器读取文本文件，转换为现有 `source.type = "folder"` descriptor；上传成功后复用现有状态、知识和会话 API。项目 ID 由前端生成并持久化到 `localStorage`，因此刷新后仍能恢复最近项目。

**Tech Stack:** React 19、Vite、原生 File API、现有 Python HTTP API、Node test runner。

## 执行状态（2026-08-02）

本计划已落地。目录选择、Folder JSON descriptor、上传状态机、项目 ID 持久化、分析结果加载和自动创建面试会话均已实现。验证命令 `npm test` 和 `npm run build` 已通过；当前边界仍是只支持 UTF-8 文本目录上传，不支持 ZIP、multipart 或二进制文件。

---

### Task 1: 接入项目目录上传页面

**Files:**

- Create: `frontend/src/upload.js`
- Create: `frontend/tests/upload.test.mjs`
- Modify: `frontend/src/api.js`（保持现有 `uploadProject`，必要时仅补充测试所需边界）
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/project-flow.test.mjs`
- Modify: `docs/demo/project-intelligence-demo.md`
- Modify: `README.md`

- [x] **Step 1: 写目录 descriptor 的失败测试**

覆盖三个行为：移除目录选择器返回的顶层目录、读取文件文本并保留相对路径、生成包含数字 `project_id`/项目名/Folder source 的 descriptor；空目录和读取失败必须返回可显示的错误。

- [x] **Step 2: 运行前端上传测试确认失败**

运行：

```powershell
cd frontend
node --test tests/upload.test.mjs
```

预期：因 `src/upload.js` 尚不存在而失败。

- [x] **Step 3: 实现最小上传转换函数**

`frontend/src/upload.js` 提供：

```js
export function relativeUploadPath(file) { /* remove top-level directory */ }
export async function createFolderUploadDescriptor(files, { projectId, projectName }) { /* read text */ }
```

函数只接受浏览器 File-like 对象，保留 UTF-8 文本内容，不实现 ZIP 二进制上传；失败时抛出包含文件名的错误。

- [x] **Step 4: 运行上传测试确认通过**

运行同一条 `node --test tests/upload.test.mjs`，预期全部通过。

- [x] **Step 5: 为 App 写启动和上传接入测试**

在 `frontend/tests/project-flow.test.mjs` 增加静态契约检查：App 导入 `uploadProject` 和 descriptor helper；存在目录选择器、项目 ID 持久化、上传后重新加载 status/knowledge/session；没有项目 ID 时展示上传入口。

- [x] **Step 6: 实现 App 上传状态机**

在 `frontend/src/App.jsx` 中：

1. 启动时优先读取 `VITE_PROJECT_ID`，其次读取 `localStorage` 的最近项目 ID。
2. 无项目 ID 且未开启 fixture 时仍展示 Agent 工作台壳层；上传入口放在项目资料/空项目状态中，不把上传页作为首屏。
3. 目录选择器读取 `FileList`，收集项目名、候选人 ID，生成数字项目 ID。
4. 调用现有 `uploadProject`，随后调用 status、knowledge、session API。
5. 上传成功后保存项目 ID，进入现有面试工作台；失败时展示具体错误并允许重试。

- [x] **Step 7: 添加上传页面样式**

在现有 `styles.css` 中增加与 status card 一致的上传卡片、文件摘要、输入框、错误状态和按钮样式；不改变现有 Evidence-first 工作台布局。

- [x] **Step 8: 运行前端完整验证**

运行：

```powershell
cd frontend
npm test
npm run test:api
npm run test:sites
npm run build
```

预期：全部通过，构建产物成功生成。

- [x] **Step 9: 更新使用说明**

README 和 Demo 文档说明：启动后端/前端后可选择项目目录；当前上传的是文本 Folder JSON descriptor；ZIP 直传和二进制文件上传仍未实现；刷新会读取最近项目 ID。

- [x] **Step 10: 复查需求边界**

确认没有新增依赖、没有把上传逻辑放入 Tauri Rust 壳层、没有声称支持浏览器 ZIP/multipart，并保留 `VITE_PROJECT_ID` 作为可选的自动启动配置。
