# Interview Agent 项目协作规范

## 1. 项目定位

本项目不是只面向 Java 的“AI 面试助手”，而是：

> **Project Intelligence Engine（项目/作品智能理解引擎） + Domain Review Agent（领域复盘智能体）**

系统先理解用户提供的项目或作品，再根据领域生成面试、作品集评审或答辩问题。

核心链路：

```text
User Artifact
    ↓
Analyzer Plugin System
    ↓
Universal Project Model
    ↓
Domain Review Agent
    ↓
Topic → Question → Answer → Evaluation → Follow-up
```

Java 后端是第一阶段的 MVP，不是最终的数据模型边界。未来应支持 Python、前端项目、数据分析项目、设计作品、视频剪辑项目等不同类型的输入。

## 2. 产品决策

### 2.1 复用 Agent 基础设施

不要从零实现通用 Agent Runtime、模型训练、复杂的多 Agent 调度或通用记忆系统。优先复用成熟框架和模型能力，把主要工程价值放在：

- Artifact Analyzer 插件体系
- Universal Project Model
- 证据与项目结构提取
- 领域问题生成、评价和追问策略
- 候选人能力画像与跨会话记忆

当前代码使用轻量、可替换的工作流实现，后续接入 LangGraph 等框架时，应保持业务模型和接口稳定。

### 2.2 领域与分析器解耦

分析器负责回答“这个项目/作品是什么、由什么组成、如何运作”；领域智能体负责回答“应该如何评审、提问和反馈”。

不要把 Java 解析逻辑写入通用 Agent、通用模型或 UI。Java、Python、前端、视频等差异必须隔离在各自的 Analyzer Adapter 中。

## 3. 核心抽象

### 3.1 Analyzer 插件

所有输入类型都应遵循统一能力边界：

```text
supports(artifact) → bool
analyze(artifact) → Universal Project Model
```

第一阶段可以使用 Python 实现 JavaAnalyzer；后续增加 PythonAnalyzer、FrontendAnalyzer、VideoAnalyzer 等，不应修改领域面试流程。

### 3.2 Universal Project Model

统一模型至少应能够表达以下层次：

1. **Identity**：名称、类型、目标、描述
2. **Structure**：目录、模块、角色、素材或组件组成
3. **Technology / Method**：技术栈、工具、方法、关键选择
4. **Flow**：核心调用链、制作流程、数据流或任务流
5. **Insights**：关键决策、证据、风险、可优化点和可提问主题

模型中应保留来源证据和置信度，使 Agent 的问题和评价可以回溯到项目内容，而不是只生成泛化问题。

### 3.3 领域模式

同一个 Universal Project Model 可以驱动不同的评审模式：

- Technical Interview：技术面试
- Portfolio Review：作品集评审
- Defense Review：项目答辩

领域模式只改变问题生成、评价维度和追问策略，不改变 Artifact Analyzer 的输出契约。

## 4. 面试 Agent 行为

标准流程：

```text
Project Knowledge
  → Topic Selection
  → Question Generation
  → Candidate Answer
  → Evaluation
  → Difficulty Decision
  → Follow-up
```

默认难度策略：

- 分数低于 60：补基础概念、澄清事实和术语
- 60–80：深入项目实现、关键流程和具体证据
- 高于 80：追问权衡、容量、稳定性和系统架构

追问必须优先来自当前项目的证据、依赖关系、核心流程和候选人弱项，避免连续生成脱离项目上下文的通用题。

记忆分为：

- 当前回答上下文
- 当前面试会话记录
- 跨会话的候选人能力画像、薄弱项和趋势

## 5. 当前代码结构

```text
interview_agent/       Python 领域核心、工作流、工具和 HTTP API
tests/                 Python 单元测试
frontend/src/          React + Vite UI
frontend/src-tauri/    Tauri 桌面壳
frontend/scripts/      前端构建与 Tauri 启动辅助脚本
```

当前 Python 核心使用可替换接口：

- `QuestionGenerator`
- `Evaluator`
- 项目仓库
- 会话存储

接入真实 LLM、RAG 或 LangGraph 时，优先替换这些边界，不要让模型调用散落到 UI 或数据模型中。

## 6. 开发命令

后端测试：

```powershell
python -m unittest discover -s tests -v
```

启动本地 HTTP API：

```powershell
python -m interview_agent.server
```

前端浏览器开发：

```powershell
cd frontend
npm run dev
```

Tauri 桌面开发：

```powershell
cd frontend
npm run tauri dev
```

当前工作区路径包含空格，Windows MinGW 的链接工具会因此失败。以下文件是启动链路的一部分，不要随意删除或改回 MSVC 配置而不重新验证：

- `frontend/rust-toolchain.toml`
- `frontend/.cargo/config.toml`
- `frontend/scripts/tauri.mjs`

Tauri 构建产物：

```powershell
cd frontend
npm run tauri build
```

Sites 原型验证：

```powershell
cd frontend
npm run build
npm run test:sites
```

## 7. 实现约束

- 通用层不得硬编码 Java、Spring 或某一个行业。
- 新增输入类型时，优先新增 Analyzer，而不是修改现有领域流程。
- 新增领域模式时，优先新增 Review Policy、问题生成器或评价策略，而不是复制 Analyzer。
- 问题、评价和追问应尽量关联结构节点、技术证据、流程或候选人历史弱项。
- 业务状态必须可序列化，便于会话持久化和未来迁移到数据库。
- 前端负责展示和交互；项目分析、问题策略、评分和记忆属于后端领域层。
- Tauri 只负责桌面能力和窗口容器；不要把领域逻辑写进 Rust 壳层。
- 不为未来场景提前引入大型依赖。先用现有接口验证业务闭环，再引入 LangGraph、向量库或多 Agent 框架。
- 修改后至少运行受影响层的测试；涉及前端时运行 `npm run build`，涉及 Tauri 配置时再运行 `cargo build --manifest-path src-tauri/Cargo.toml`。

## 8. UI 方向

当前 UI 采用 Evidence-first Interview Studio：项目导航、当前问题/回答、代码或项目证据、评价结果并列展示。

UI 的优先级是：

1. 让用户知道问题来自项目哪里
2. 让用户清楚当前面试进度和能力变化
3. 让评价、薄弱点和下一轮追问可执行

新增 UI 不应退化为脱离项目内容的通用聊天窗口。`frontend/AGENTS.md` 中的 Product Design 原型约束仍然适用于前端目录。

界面层级不得依赖密集横线、竖线或重复边框。普通内容优先通过留白、排版、缩进、gutter 和表面明度组织；分栏控制、独立滚动边界、代码/数据基准及焦点状态等具有明确语义的线除外。

## 9. 前后端规范入口

可执行规范统一从 `docs/standards/README.md` 进入：

- HTTP 路径、请求、响应和错误字段以 `docs/api/openapi.json` 为唯一事实源。
- 后端分层、校验、持久化、安全和运行约束见 `docs/standards/backend.md`。
- 前端架构、设计系统、交互状态、响应式和无障碍约束见 `docs/standards/frontend.md`。

接口变化必须同步修改 OpenAPI、后端测试和 `frontend/src/api.js` 测试。当前能力变化必须同步更新 README；历史计划文档只记录当时决策，不作为当前契约。
