# Project Intelligence Engine + Domain Review Agent 实施规划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前可运行的本地面试工作流，演进为“项目/作品智能理解引擎 + 领域复盘智能体”，先完成 Java 后端项目的证据驱动面试闭环，同时保留 Python、前端、设计和视频等输入类型的扩展边界。

**Architecture:** 输入先经过 `ProjectSource` 统一落入隔离的 Workspace，再由 Analyzer 插件输出可序列化的 `UniversalProjectModel`。领域 Review Policy 消费统一模型，负责主题选择、问题生成、评价、追问和能力画像；现有 `QuestionGenerator`、`Evaluator`、项目仓库、会话存储和 `InterviewGraph` 继续作为可替换边界。

**Tech Stack:** 现有 Python 领域核心、SQLite 持久化、标准库 HTTP API、React + Vite + Tauri 前端；第一阶段不引入 LangGraph、PostgreSQL、向量数据库或多 Agent 框架。只有当当前接口被测试证明不足时，才单独评估新增依赖。

## 执行状态（2026-08-02）

本计划的 MVP 任务已落地。Universal Project Model、输入隔离、Scanner/Analyzer Registry、Java/Python/Frontend Analyzer、分析 API、证据驱动技术面试、三层 Memory、Evidence-first 前端和扩展指南均已有实现与测试。后端 178 项测试、前端 25 项测试及生产构建已通过。

当前保留的产品边界：Java Analyzer 仅支持 Maven；Portfolio/Defense Review 仅识别模式但尚未实现；没有 Git、multipart、LLM、RAG、LangGraph 或向量数据库；浏览器端只支持 UTF-8 文本目录上传。

---

## 规划结论

引用对话中的方向成立，但需要按当前代码实际情况收敛：

1. 产品定位是 `Project Intelligence Engine + Domain Review Agent`，不是只服务 Java 的聊天面试助手。
2. Java 是第一个 Analyzer Adapter，不是通用模型的边界；未来输入包括 Python、前端、数据分析、设计和视频/剪辑作品。
3. Analyzer 只提取可回溯事实和证据；“项目设计得好不好”由 Domain Review Agent 结合领域策略判断。
4. 当前代码已经有稳定的替换点，先在现有轻量工作流上验证业务闭环，再决定是否接 LangGraph。
5. 结构化项目事实优先存 SQLite/JSON；项目规模真正需要检索时再引入向量库，当前不做 RAG。

## 目标闭环

```text
ZIP / 本地文件夹 / Git URL
          ↓
ProjectSource + Workspace
          ↓
ProjectScanner
          ↓
Analyzer Registry
          ↓
UniversalProjectModel
          ↓
Review Policy
          ↓
Topic → Question → Answer → Evaluation → Follow-up
          ↓
Session Memory + Candidate Profile
```

## MVP 验收标准

- 给定一个包含 `pom.xml`、Spring 注解和典型分层代码的 Java 项目，系统能生成项目身份、技术栈、组件、依赖关系、核心流程主题和来源证据。
- 面试问题能指向具体文件、组件、注解、依赖或流程，而不是只生成通用 Java 定义题。
- 评分低于 60、60–80、高于 80 时，分别产生基础澄清、项目实现深入、架构权衡三类下一步策略。
- ZIP 和浏览器上传的本地文件夹都能进入同一 Workspace；恶意路径不能逃逸 Workspace，文件大小有明确限制。
- 面试会话、评价、证据引用和候选人能力画像可序列化并在服务重启后恢复。
- 现有 Python 测试继续通过；涉及前端时 `npm run build` 和相关前端测试通过。

## 明确不纳入本轮

- 不实现完整通用 Agent Runtime、多 Agent 协作或模型训练。
- 不在 Java MVP 中承诺完整业务语义理解、完整调用图或自动架构设计。
- 不同时实现 Python、前端、视频等全部 Analyzer；本轮只定义扩展契约，并把 Java 做成第一个可用 Adapter。
- 不为了“看起来像 Agent”提前接入 LangGraph、PostgreSQL、Neo4j、Qdrant 或复杂异步任务系统。

---

### Task 1: 固化现有边界与 Universal Project Model 契约

**Files:**
- Create: `docs/architecture/project-intelligence.md`
- Create: `interview_agent/intelligence/__init__.py`
- Create: `interview_agent/intelligence/models.py`
- Create: `interview_agent/analyzers/__init__.py`
- Create: `interview_agent/analyzers/base.py`
- Modify: `interview_agent/models.py`
- Test: `tests/test_intelligence_models.py`

- [x] **Step 1: 记录现有可替换接口和兼容策略**

在架构文档中明确保留以下接口：

```python
class QuestionGenerator(Protocol): ...
class Evaluator(Protocol): ...
class ProjectRepository(Protocol): ...
class SessionStore(Protocol): ...
class InterviewGraph: ...
```

`ProjectKnowledge` 暂时继续作为现有面试流程的兼容输入；新增的 `UniversalProjectModel` 作为分析器输出，通过显式转换函数进入旧流程，避免一次性重写 `InterviewAgent`。

- [x] **Step 2: 写 UniversalProjectModel 的失败测试**

测试至少覆盖身份、结构、技术、流程、洞察和证据都能构造，并且 `dataclasses.asdict()` 后只包含 JSON 可序列化值。证据对象必须包含 `source_path`、`locator`、`excerpt`、`confidence` 和 `kind`，保证问题可回溯到项目内容。

- [x] **Step 3: 定义最小可序列化模型**

在 `interview_agent/intelligence/models.py` 中定义以下 dataclass 边界：

```python
@dataclass(frozen=True)
class Evidence:
    source_path: str
    locator: str
    excerpt: str
    kind: str
    confidence: float

@dataclass(frozen=True)
class ProjectComponent:
    name: str
    component_type: str
    source_path: str
    evidence_ids: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class ProjectRelation:
    source: str
    target: str
    relation_type: str
    evidence_ids: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class UniversalProjectModel:
    schema_version: int
    project_id: int
    identity: dict[str, str]
    structure: dict[str, object]
    technologies: list[dict[str, object]]
    components: list[ProjectComponent]
    relations: list[ProjectRelation]
    flows: list[dict[str, object]]
    insights: list[dict[str, object]]
    evidence: dict[str, Evidence]
```

- [x] **Step 4: 定义 Analyzer 协议和兼容转换**

`interview_agent/analyzers/base.py` 只规定：

```python
class ArtifactAnalyzer(Protocol):
    analyzer_id: str

    def supports(self, structure: dict[str, object]) -> bool: ...
    def analyze(self, artifact_root: Path, *, project_id: int) -> UniversalProjectModel: ...
```

在 `models.py` 或独立转换模块中增加 `project_model_to_knowledge()`，只把当前面试所需的 topics、components、evidence、dependencies 映射到 `ProjectKnowledge`。

- [x] **Step 5: 运行单元测试**

运行：`python -m unittest tests.test_intelligence_models -v`

预期：模型序列化、兼容转换和缺省字段测试全部通过。

### Task 2: 建立 ProjectSource 与 Workspace 输入层

**Files:**
- Create: `interview_agent/ingestion/__init__.py`
- Create: `interview_agent/ingestion/sources.py`
- Create: `interview_agent/ingestion/workspace.py`
- Create: `interview_agent/ingestion/service.py`
- Create: `tests/test_ingestion.py`
- Create: `tests/fixtures/ingestion/sample-project/README.md`

- [x] **Step 1: 写来源统一接口的失败测试**

测试 `ZipSource`、`FolderSource` 都能将输入准备为一个项目根目录；Analyzer 只接收准备后的目录，不读取上传方式。FolderSource 的服务层输入使用带相对路径的 `(relative_path, bytes)` 集合，确保同名文件不会丢失。

- [x] **Step 2: 定义 Workspace 目录和生命周期**

`WorkspaceManager` 固定返回：

```text
workspace/projects/{project_id}/source/
workspace/projects/{project_id}/analysis/
```

项目状态按 `CREATED → SOURCE_READY → SCANNING → ANALYZING → READY/FAILED` 变化；状态值必须可通过 SQLite JSON 持久化。

- [x] **Step 3: 实现安全 ZIP 解压和文件夹写入**

`ZipSource.prepare()` 在写入前对每个成员的 `resolve()` 路径校验必须位于目标目录内，拒绝 `../`、绝对路径和符号链接逃逸。统一限制压缩包总大小、单文件大小和文件数量，并在测试中验证 Zip Slip 会抛出明确的 `ValueError`。

`FolderSource.prepare()` 必须保留浏览器传来的相对路径，并拒绝空路径、绝对路径和目标目录外路径。

- [x] **Step 4: 实现 IngestionService**

服务只负责：创建 Workspace、调用 Source、返回标准化项目根目录和源信息；不负责 Java 解析或面试逻辑。

- [x] **Step 5: 运行输入层测试**

运行：`python -m unittest tests.test_ingestion -v`

预期：ZIP、文件夹、路径穿越、大小/数量限制和 Workspace 目录测试全部通过。

### Task 3: 实现 Scanner、Analyzer Registry 和 Java Analyzer V1

**Files:**
- Create: `interview_agent/analyzers/registry.py`
- Create: `interview_agent/analyzers/scanner.py`
- Create: `interview_agent/analyzers/java.py`
- Create: `interview_agent/analyzers/java_rules.py`
- Create: `tests/test_project_scanner.py`
- Create: `tests/test_java_analyzer.py`
- Create: `tests/fixtures/java_project/pom.xml`
- Create: `tests/fixtures/java_project/src/main/java/demo/OrderController.java`
- Create: `tests/fixtures/java_project/src/main/java/demo/OrderService.java`
- Create: `tests/fixtures/java_project/src/main/java/demo/OrderRepository.java`
- Create: `tests/fixtures/java_project/src/main/resources/application.yml`

- [x] **Step 1: 写 Scanner 的失败测试**

对固定 fixture 断言扫描结果至少包含 Maven、Java 文件数量、配置文件、源码根目录和候选项目类型。Scanner 不读取源码语义，只返回文件结构事实。

- [x] **Step 2: 实现确定性的 ProjectScanner**

`ProjectScanner.scan(root)` 输出可序列化结构，检测 `pom.xml`、`build.gradle`、`build.gradle.kts`、Java/Python/JS/TS 文件计数及常见配置文件。检测逻辑保持通用，不能在 Scanner 中硬编码 Spring 面试策略。

- [x] **Step 3: 写 Java Analyzer 的失败测试**

对 fixture 断言能够提取：

```text
@RestController → CONTROLLER
@Service        → SERVICE
@Repository     → REPOSITORY
字段类型依赖    → DEPENDS_ON
@GetMapping     → API flow
@Transactional  → Transaction topic evidence
```

每个 topic 必须带 evidence id，evidence 必须能定位到具体文件和行/符号位置。

- [x] **Step 4: 实现 JavaAnalyzer 的提取器边界**

`JavaAnalyzer` 只负责协调 `java_rules.py` 中的事实提取规则、依赖映射和模型组装。V1 先覆盖 Spring Boot + Maven 的常见结构；解析器细节封装在规则模块内，后续可替换为完整 AST parser，不把解析库类型泄漏到 UniversalProjectModel。

- [x] **Step 5: 实现 AnalyzerRegistry**

注册 `JavaAnalyzer`，根据 Scanner 结果选择唯一支持的 Analyzer；没有支持者时返回可解释错误，不回退到“让 LLM 猜项目类型”。

- [x] **Step 6: 运行分析器测试**

运行：`python -m unittest tests.test_project_scanner tests.test_java_analyzer -v`

预期：fixture 能输出 Spring Boot、组件、依赖、流程和证据，且所有事实都可序列化。

### Task 4: 将分析结果接入项目服务、SQLite 和 HTTP API

**Files:**
- Modify: `interview_agent/models.py`
- Modify: `interview_agent/service.py`
- Modify: `interview_agent/sqlite_store.py`
- Modify: `interview_agent/http_api.py`
- Modify: `interview_agent/server.py`
- Create: `tests/test_project_analysis_api.py`
- Modify: `tests/test_service_api.py`
- Modify: `tests/test_sqlite_persistence.py`

- [x] **Step 1: 写分析生命周期的失败测试**

测试从 Source 创建项目后，项目经历 `SOURCE_READY → SCANNING → ANALYZING → READY`，分析结果包含 `schema_version`、Analyzer id 和 UniversalProjectModel；失败时状态为 `FAILED` 且保留可读错误。

- [x] **Step 2: 扩展项目持久化载荷**

SQLite 项目记录增加 `source_type`、`workspace_path`、`analysis_status` 和版本化的 `knowledge_payload`。旧的只包含 `ProjectKnowledge` 的 JSON 仍然可以读取，缺少新字段时使用兼容默认值。

- [x] **Step 3: 增加分析服务边界**

`InterviewService` 新增 `ingest_project(source)` 和 `analyze_project(project_id)`；方法内部调用 IngestionService、Scanner 和 AnalyzerRegistry，完成后将 UniversalProjectModel 转为当前 InterviewAgent 可用的 ProjectKnowledge。

- [x] **Step 4: 增加 HTTP 入口**

保留现有 `POST /projects` 的 JSON 注册接口，新增项目上传/分析状态/知识查询接口：

```text
POST /projects/upload
GET  /projects/{project_id}/status
GET  /projects/{project_id}/knowledge
```

ZIP 和文件夹上传都映射到 ProjectSource；协议层只负责解析请求和返回状态，不能在 Handler 中写解析规则或面试策略。

- [x] **Step 5: 运行后端回归测试**

运行：`python -m unittest discover -s tests -v`

预期：现有项目注册、会话、回答、SQLite 重启恢复测试继续通过，并新增上传、状态、知识查询测试通过。

### Task 5: 将 Domain Review Policy 接入现有 InterviewAgent

**Files:**
- Create: `interview_agent/review/__init__.py`
- Create: `interview_agent/review/policy.py`
- Create: `interview_agent/review/technical.py`
- Modify: `interview_agent/agent.py`
- Modify: `interview_agent/models.py`
- Modify: `interview_agent/tools.py`
- Create: `tests/test_review_policy.py`
- Modify: `tests/test_interview_agent.py`

- [x] **Step 1: 写三类领域模式的失败测试**

定义 `ReviewMode`：`TECHNICAL_INTERVIEW`、`PORTFOLIO_REVIEW`、`DEFENSE_REVIEW`。先实现 `TechnicalInterviewPolicy`，测试它能根据 UniversalProjectModel 的 evidence、relation 和 candidate weakness 选择主题；其他两种模式先验证能被识别并返回明确的未实现策略错误，不复制 Analyzer。

- [x] **Step 2: 抽取 ReviewPolicy 协议**

```python
class ReviewPolicy(Protocol):
    mode: str

    def select_topic(self, project, profile, history) -> Topic: ...
    def next_direction(self, score: int, current_level: int) -> tuple[str, int]: ...
```

让 `InterviewAgent` 默认使用技术面试策略，但保留现有构造方式，已有调用方不需要传入 policy。

- [x] **Step 3: 固化问题与评价的证据输入**

扩展 `QuestionGenerator.generate()` 和 `Evaluator.evaluate()` 的上下文时，使用向后兼容的可选参数；问题必须优先引用当前 topic 的 evidence，评价结果保留 `evidence_ids`、covered_points 和 missing_points。不能让 UI 自己拼装评分逻辑。

- [x] **Step 4: 固化分数阈值策略**

保持并测试以下规则：低于 60 走基础澄清，60–80 深入项目实现，高于 80 进入容量、稳定性和架构权衡；追问主题优先来自当前项目，不足时才使用通用领域知识。

- [x] **Step 5: 增强项目工具查询**

在现有 `ProjectTools` 上增加按 evidence id、组件、技术主题和依赖关系查询的确定性方法；工具只返回项目事实，不直接生成自然语言答案。

- [x] **Step 6: 运行 Agent 回归测试**

运行：`python -m unittest tests.test_review_policy tests.test_interview_agent -v`

预期：旧的高/中/低分行为不变，新增测试验证问题和评价均能回溯证据。

### Task 6: 完善三层 Memory 与能力画像持久化

**Files:**
- Create: `interview_agent/memory/__init__.py`
- Create: `interview_agent/memory/profile_store.py`
- Modify: `interview_agent/profile.py`
- Modify: `interview_agent/service.py`
- Modify: `interview_agent/sqlite_store.py`
- Modify: `interview_agent/models.py`
- Create: `tests/test_memory.py`
- Modify: `tests/test_sqlite_persistence.py`

- [x] **Step 1: 写 Memory 分层测试**

测试明确区分：当前回答上下文属于 `InterviewState`，一次面试的 history 属于 Session Store，跨会话的 topic score/trend 属于 Candidate Profile Store。重建 Service 后，session 和 profile 都能恢复。

- [x] **Step 2: 扩展 CandidateProfile 数据结构**

保留现有 `SkillSnapshot(score, trend)`，增加最近评分、样本数和弱项集合；更新规则仍由 Evaluation 驱动，不在前端计算。

- [x] **Step 3: 实现 SQLite Profile Store**

增加版本化 JSON 表或记录，主键使用 candidate/user id；每次评价后通过 `ProfileUpdater` 写入，避免把 profile 作为 Agent 的易失内存。

- [x] **Step 4: 将历史弱点接入 Planner**

主题选择优先级按“项目重要性 + 当前证据丰富度 + 候选人薄弱程度”组合，使用确定性规则实现第一版，确保可以测试和解释。

- [x] **Step 5: 运行 Memory 测试**

运行：`python -m unittest tests.test_memory tests.test_sqlite_persistence -v`

预期：同一主题多次回答能得到正确趋势，服务重启后历史和能力画像不丢失。

### Task 7: 将前端从硬编码 Demo 迁移到真实项目与证据数据

**Files:**
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/api.test.mjs`
- Modify: `frontend/tests/layout.test.mjs`
- Create: `frontend/tests/project-flow.test.mjs`

- [x] **Step 1: 写前端 API 流程测试**

测试上传/加载项目、查询状态、获取 knowledge、开始 session、提交 answer 的请求路径和字段与后端契约一致；API 错误要展示在现有状态卡片中。

- [x] **Step 2: 用真实知识模型替代硬编码项目数据**

保留 Evidence-first Interview Studio 的三栏信息层级，但项目名称、主题、进度、证据文件、代码片段、解释和评分全部来自 API 返回；没有证据时显示明确空状态，不伪造代码证据。

- [x] **Step 3: 保持桌面壳职责单一**

Tauri 只负责目录选择、窗口和 sidecar 能力；项目分析、问题策略、评分和记忆继续由 Python 后端负责。不得把领域逻辑写入 `frontend/src-tauri/src/*.rs`。

- [x] **Step 4: 运行前端验证**

运行：`cd frontend; npm run test:api; npm run test:sites; npm run build`

预期：API、Sites worker、布局测试通过，构建产物保留 `dist/client/index.html`、`dist/server/index.js` 和 Sites hosting 配置。

### Task 8: 设计并验证非 Java Analyzer 扩展路线

**Files:**
- Create: `docs/architecture/analyzer-extension-guide.md`
- Create: `tests/test_analyzer_registry.py`
- Modify: `interview_agent/analyzers/registry.py`
- Create: `interview_agent/analyzers/python.py`
- Create: `interview_agent/analyzers/frontend.py`

- [x] **Step 1: 先测试插件注册契约**

用假的 Analyzer 验证 Registry 能按 Scanner 结果选择插件，新增插件不需要修改 ReviewPolicy 或 InterviewAgent。

- [x] **Step 2: 实现低风险的 Python/Frontend 最小 Adapter**

只提取通用结构事实：Python 模块、入口、依赖文件；前端组件、路由、API 调用和构建工具。输出仍必须是 UniversalProjectModel，不增加 Java 字段。

- [x] **Step 3: 编写扩展指南**

明确新 Analyzer 必须实现 `supports()`、`analyze()`，必须提供 evidence 和 confidence，不能把领域问题写进 Analyzer；Portfolio/Defense 只新增 ReviewPolicy。

- [x] **Step 4: 为视频/设计保留输入而不提前实现复杂解析**

文档定义 `MediaArtifact` 可表达素材、时间线、脚本、导出文件和制作流程，但本轮不引入 Premiere/After Effects 专有解析依赖；先用 manifest/导出元数据作为未来输入契约。

- [x] **Step 5: 运行扩展性测试**

运行：`python -m unittest tests.test_analyzer_registry -v`

预期：注册 Python/Frontend Adapter 不改变 Java 分析和技术面试测试。

### Task 9: 完成 MVP 演示、文档和验收

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/project-intelligence.md`
- Create: `tests/fixtures/demo-order-system/README.md`
- Create: `docs/demo/project-intelligence-demo.md`

- [x] **Step 1: 写端到端验收测试**

使用 demo fixture 验证：输入项目 → 生成 UniversalProjectModel → 开始技术面试 → 提交回答 → 得到带 evidence id 的评价和追问 → 持久化后恢复。

- [x] **Step 2: 编写可复现 Demo**

文档给出从测试命令、HTTP 请求到返回 JSON 的完整链路，明确哪些输出是确定性规则，哪些输出在未来接入真实 LLM 后替换。

- [x] **Step 3: 更新 README 产品定位和当前边界**

将旧的“项目理解型技术面试 Agent”说明升级为 Project Intelligence Engine + Domain Review Agent，并保留现有本地启动命令；注明当前仍使用 SQLite/轻量工作流。

- [x] **Step 4: 执行最终验证**

运行：

```powershell
python -m unittest discover -s tests -v
cd frontend
npm run test:api
npm run test:sites
npm run build
```

预期：后端和前端测试全部通过，Demo 文档中的请求可复现，且没有破坏 Tauri 启动链路。

---

## 执行顺序与阶段出口

| 阶段 | 包含任务 | 出口 |
|---|---|---|
| A. 事实层 | Task 1–3 | Java 项目可生成带证据的 UniversalProjectModel |
| B. 产品闭环 | Task 4–6 | 上传/分析/面试/评价/画像可持久化恢复 |
| C. 交互闭环 | Task 7 | Evidence-first UI 展示真实项目数据 |
| D. 扩展与交付 | Task 8–9 | 插件扩展契约稳定，Demo 可复现 |

每个 Task 以测试先行；阶段之间不跨越未验证的模型或 API 契约。LangGraph、真实 LLM、PostgreSQL 和向量库只有在阶段 B 的现有接口遇到可复现瓶颈后，作为独立技术评估进入新计划。

## 规划自检

- **需求覆盖：** 项目通用化、Java MVP、ZIP/文件夹输入、UniversalProjectModel、证据、动态追问、三层 Memory、Tool 查询、前端 Evidence-first 和未来非 Java 扩展均有对应任务。
- **范围控制：** 没有把视频、完整 AST、RAG、多 Agent 或云数据库混入第一阶段验收；复杂能力被保留在明确的接口或后续阶段。
- **类型一致性：** Analyzer 输出 `UniversalProjectModel`，通过 `project_model_to_knowledge()` 进入现有 `ProjectKnowledge`；ReviewPolicy 消费该模型，InterviewAgent 继续消费兼容知识模型；Persistence 只保存可序列化 dataclass 载荷。
- **安全性：** 输入层包含 Zip Slip、绝对路径、符号链接、文件大小、文件数量和 Workspace 隔离测试。
- **验证闭环：** 每个阶段都有单元/集成测试，最终执行现有后端测试、前端测试、Sites 测试和构建。
