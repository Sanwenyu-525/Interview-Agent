# 大模型配置档案管理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**目标：** 将当前单一大模型配置升级为可持久化的多配置档案，支持查询、新增、编辑、删除、测试连接和设为当前使用。

**架构：** 在现有 `LLMConfig` 之上增加 `LLMProfile` 档案层；SQLite 保存多个档案和 active profile id，旧的 `llm_config` 配置继续可读取并在首次访问时兼容迁移。服务层负责档案 CRUD 和运行时 Agent 切换，HTTP 层只返回脱敏配置。模型列表读取和未保存表单测试仍走临时配置，不写入档案。

**技术栈：** Python `sqlite3` / `unittest`、现有 HTTP API、React + Vite、原生 `select` 控件、Playwright 浏览器 smoke。

**状态：** 已完成实现与验收。后端 220 项测试、前端 41 项测试、Vite 构建和 Playwright 配置档案 CRUD smoke 均通过。

---

### Task 1：建立配置档案存储契约

**Files:**
- Modify: `interview_agent/settings.py`
- Modify: `interview_agent/service.py`
- Test: `tests/test_llm_settings.py`

- [ ] 写失败测试：档案可以新增、查询、更新、删除，并能标记 active。
- [ ] 写失败测试：SQLite 重启后档案、active id 和 API Key 仍保留，公开结果不包含 API Key。
- [ ] 写失败测试：旧 `llm_config` 能迁移成一个档案，未配置远程模型时仍使用本地规则引擎。
- [ ] 实现 `LLMProfile`、`InMemoryLLMProfileStore`、`SQLiteLLMProfileStore`，保存 `{id, name, config, active_id}`；复用现有 `LLMConfig` 校验和 `public_payload()`。
- [ ] 为 store 提供 `list() / get(id) / save(profile) / delete(id) / set_active(id)`，删除 active 档案时回退本地规则引擎。
- [ ] 在 `InterviewService` 增加 `list_llm_profiles`、`create_llm_profile`、`update_llm_profile`、`delete_llm_profile`、`activate_llm_profile`，每次激活都重新创建运行时 Agent。
- [ ] 运行：`python -m unittest tests.test_llm_settings -v`，确认新增测试通过。

### Task 2：增加档案 HTTP API

**Files:**
- Modify: `interview_agent/http_api.py`
- Modify: `tests/test_service_api.py`

- [ ] 写失败测试并实现以下接口：
  - `GET /settings/llm/profiles`：返回脱敏档案列表和 active id。
  - `POST /settings/llm/profiles`：新增档案。
  - `PUT /settings/llm/profiles/{id}`：编辑档案，空 API Key 复用原 Key。
  - `DELETE /settings/llm/profiles/{id}`：删除档案。
  - `POST /settings/llm/profiles/{id}/activate`：切换当前 Agent。
  - `POST /settings/llm/profiles/{id}/test`：测试已保存档案，不修改 active 状态。
- [ ] 保留现有 `/settings/llm` 读写接口作为兼容入口，但其保存动作应更新当前 active 档案或创建默认档案。
- [ ] 为不存在档案返回 404，为远程 LLM 错误返回 502，响应中不出现 API Key。
- [ ] 运行：`python -m unittest tests.test_service_api -v`。

### Task 3：接入前端 API 和配置档案状态

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`
- Test: `frontend/tests/api.test.mjs`

- [ ] 写失败测试覆盖档案列表、新增、编辑、删除、激活、档案测试连接的 HTTP 方法和路径。
- [ ] 在 `api.js` 增加对应函数，保留现有模型列表和临时配置测试函数。
- [ ] 在 `App` 加载 `/settings/llm/profiles`，保存、激活、删除和测试成功后刷新列表及当前配置状态。
- [ ] 将 `SettingsView` 的保存语义改为：无 `editingProfileId` 时新增，有 id 时更新；点击“设为当前”调用激活接口。
- [ ] API Key 输入框留空时不发送新 Key，后端复用已有密钥。
- [ ] 运行：`node --test frontend/tests/api.test.mjs`。

### Task 4：完成配置档案管理 UI

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/layout.test.mjs`

- [ ] 写失败静态测试：页面存在档案列表、添加、编辑、删除、测试、激活按钮和编辑状态。
- [ ] 用卡片列表展示厂商、模型、Base URL、API Key 已配置状态和“当前使用”状态；当前档案使用绿色状态标记。
- [ ] 增加“新增模型配置”动作，点击编辑将档案数据装载到同一表单，取消编辑恢复空白表单。
- [ ] 仅对非当前档案显示“设为当前”；删除前使用原生确认对话框，删除后刷新列表。
- [ ] 测试按钮展示“测试中 / 连接成功 / 连接失败”，不改变当前激活档案。
- [ ] 保持厂商预设只填 Base URL，模型名称继续来自 `/models` 下拉列表。
- [ ] 采用现有 borders-only 深度、8px 间距和数据字段使用等宽字体，不引入新 UI 依赖。
- [ ] 运行：`node --test frontend/tests/layout.test.mjs`。

### Task 5：全量验证和运行说明

**Files:**
- Modify: `docs/llm-config.md`
- Modify: `frontend/AGENTS.md`（如需补充持久化规则）

- [ ] 更新文档说明档案 CRUD、active profile、删除 active 的本地规则引擎回退和 API Key 脱敏行为。
- [ ] 运行后端：`python -m unittest discover -s tests -v`。
- [ ] 运行前端：`cd frontend; npm test` 和 `npm run build`。
- [ ] 用 Playwright 验证打开设置页、添加档案、编辑档案、测试连接、激活和删除路径；临时脚本验证后删除。
- [ ] 明确开发模式下后端需要重启，前端 Vite 支持热更新；Tauri 使用新构建产物需重启应用。
