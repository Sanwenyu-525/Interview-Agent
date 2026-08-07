# Interview Agent

## Agent 工作流框架

当前面试工作流已接入 LangGraph `StateGraph`。`InterviewGraph` 负责路由开始会话和提交回答两个入口，具体的问题生成、评价、Review Policy 和面试者画像逻辑仍由现有领域代码提供。

开始面试路径依次经过 `load_project`、`select_initial_topic`、`generate_initial_question` 和 `assemble_initial_state`；提交回答路径依次经过 `validate_answer`、`evaluate_answer`、`update_profile`、`decide_follow_up`、`generate_follow_up_question` 和 `assemble_follow_up`。节点只计算结果，数据库写入和失败回滚仍由 `InterviewService` 负责。

`InterviewGraph` 支持可选 `checkpointer` 和 `thread_id`，可用于检查点、状态历史和恢复实验。`InterviewService` 通过 `workflow_checkpointer` 参数暴露该能力，但默认不启用；默认会话事实源仍是现有 `SessionStore`。SQLite Checkpointer 需要额外安装 `langgraph-checkpoint-sqlite`，当前未纳入默认依赖。

第一阶段不启用 LangGraph checkpoint：`SessionStore` 仍是会话状态的唯一事实源，因此保留现有 SQLite 持久化、版本校验和失败回滚行为。LLM 交互已通过 LangChain 接入：`ChatOpenAI` 负责与 OpenAI 兼容端点通信，问题生成与评价使用 `ChatPromptTemplate` 组装提示词、`JsonOutputParser` 解析结构化输出；提示词、模型调用和流式协议不再手写。向量数据库和多 Agent Runtime 当前未接入。

Interview Agent 当前是一个 **Project Intelligence Engine + Domain Review Agent** 的最小可运行实现：先理解用户提交的项目/作品，再把结构化事实交给领域复盘流程，生成问题、评价和追问。

```text
ProjectSource → Workspace → ProjectScanner → AnalyzerRegistry
             → UniversalProjectModel → ProjectKnowledge 兼容层
             → InterviewOutline（3–5 个系统级方向）
             → ReviewPolicy → Direction → Question → Answer
             → Evaluation → Reference Answer（非 100 分）→ Follow-up → Candidate Profile
```

这里的 Java 面试只是第一个可用场景，不是通用模型的边界。Analyzer 负责回答“输入是什么、由什么组成、如何运作”，Domain Review Agent 负责回答“应该如何评审、提问和反馈”。项目事实带有来源路径、定位、摘录和置信度，问题与评价可以回溯到证据。

## 当前支持范围

默认 `AnalyzerRegistry` 已注册四个适配器：

| Analyzer | 当前选择条件 | 当前提取内容 |
| --- | --- | --- |
| `java` | Maven 项目（根级 `pom.xml`）且存在 Java 源文件 | Spring 组件、字段依赖、HTTP endpoint、`@Transactional` 主题、POM 技术事实和证据 |
| `gradle-java` | Gradle 项目（根级 `build.gradle` 或 `build.gradle.kts`）且存在 Java 源文件 | Spring 组件、字段依赖、HTTP endpoint、事务主题、Gradle 依赖/插件事实和证据 |
| `python` | 存在 Python 源文件，且没有根级 `package.json` | 模块、顶层类/函数、`main`/`__main__` 入口、依赖文件和证据 |
| `frontend` | 根级 `package.json` 为 JSON object，且存在 JS/TS 源文件 | 组件、路由、API 调用、依赖、版本、构建工具和证据 |

Maven 与 Gradle 使用独立 Java Analyzer，由根级构建文件确定性选择，不互相猜测或回退。解析器目前是保守的静态规则，不执行构建、不安装依赖，也不承诺完整调用图或完整业务语义。

未来可以增加独立的 Python、Frontend、视频或设计 Analyzer。视频/设计输入可以通过 manifest 表达素材、时间线、脚本、场景、画板和导出文件；本阶段不引入 Premiere、After Effects 或设计工具的专有解析依赖。新增输入类型只应扩展 Analyzer，新增评审方式只应扩展 `ReviewPolicy`。

## 快速开始

后端测试：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q interview_agent
```

启动标准库 HTTP API（默认监听 `127.0.0.1:8000`）：

```powershell
python -m interview_agent.server
```

前端验证：

```powershell
cd frontend
npm test
npm run test:api
npm run test:sites
npm run build
```

完整的上传、分析、面试和持久化示例见 [`docs/demo/project-intelligence-demo.md`](docs/demo/project-intelligence-demo.md)。

前后端工程规范从 [`docs/standards/README.md`](docs/standards/README.md) 进入；机器可读 HTTP 契约为 [`docs/api/openapi.json`](docs/api/openapi.json)。

Stitch 七张产品页面现已全部重构进主应用；当前覆盖状态、真实数据边界和后续完善顺序见 [`docs/product/ui-page-roadmap.md`](docs/product/ui-page-roadmap.md)。

## HTTP API 摘要

- `GET /health`：返回本地服务进程健康状态和 API 版本。
- `POST /projects`：直接注册已有 `ProjectKnowledge`，字段包括 `project_id`、`project_name`、`topics`，以及可选的 `components`、`evidence`、`dependencies`、`weaknesses`。
- `POST /projects/upload`：上传并分析 `folder` 或 `zip` 描述。`folder` 使用 `{ "files": [{ "path": "...", "content": "..." }] }`；`zip` 使用服务进程可访问的 `{ "source_path": "..." }`，并可选传入 `max_total_size`、`max_file_size`、`max_files`。
- `GET /projects/{project_id}/status`：返回 `ProjectAnalysis`，包括 `analysis_status`、`schema_version`、`analyzer_id`、`universal_model`、`knowledge` 和 `error`。
- `GET /projects/{project_id}/knowledge`：返回供面试流程使用的 `ProjectKnowledge` 兼容模型。
- `GET /positions`、`POST /positions`：按面试者列出或创建目标岗位。创建请求包含岗位名称、JD 原文，以及可选的公司、来源链接和关联项目 ID；服务端保存 JD、提取任职要求并生成岗位题库。
- `GET /positions/{position_id}`、`PATCH /positions/{position_id}`、`DELETE /positions/{position_id}`：读取、更新或删除一个目标岗位；岗位状态支持 `preparing`、`applied`、`interviewing` 和 `archived`。
- `POST /positions/{position_id}/questions`：基于最新 JD 和关联项目重新生成岗位题库。只有同时匹配项目内容和具体证据的题目才标记为项目证据题，否则生成经历题。
- `GET /resumes`：按可选的 `candidate_id` 过滤并列出简历库摘要（姓名、岗位、领域、状态、主张数量、关联项目名）；不传 `candidate_id` 时返回简历库全部简历，供“新建复盘”选择面试者使用。
- `POST /resumes`：body 为 `{ "name": "...", "role": "...", "domain": "...", "resume_text": "...", "project_ids": [...] }`，保存简历原文、提取面试者主张并返回详情；`name` 缺省时尝试从正文首行识别。
- `GET /resumes/{resume_id}`：读取简历详情（含提取的主张列表）。
- `PATCH /resumes/{resume_id}`：更新岗位、领域、关联项目、状态，或通过 `claims` 数组切换单条主张的 `skip` 标记。
- `DELETE /resumes/{resume_id}`：从简历库删除简历。
- `POST /sessions`：body 为 `{ "project_id": 1, "candidate_id": "default", "title": "任务 1", "topic": "Transaction" }`，其中 `title` 和首题 `topic` 可选；也可传 `position_id`、`position_question_id`，从岗位题库创建可回溯的练习会话。`topic` 必须匹配当前项目主题，返回 `session_id` 和初始 `state`。
- `GET /sessions`：按可选的 `candidate_id`、`project_id`、`position_id` 和 `limit` 返回包含标题的服务端会话摘要，前端用它恢复最近会话、岗位练习历史和其他任务。
- `GET /sessions/{session_id}`：读取当前会话状态。
- `PATCH /sessions/{session_id}`：body 为 `{ "title": "新的会话标题" }`，修改最近会话标题。
- `DELETE /sessions/{session_id}`：删除指定会话；删除当前会话后，前端自动切换到下一条可用会话或新会话页。
- `POST /sessions/{session_id}/complete`：在至少完成一次回答后幂等结束会话；结束后的会话拒绝继续提交回答。
- `GET /sessions/{session_id}/report`：读取由后端聚合的会话复盘报告。
- `POST /sessions/{session_id}/answers`：body 为 `{ "answer": "..." }`，返回新的问题、评价、追问方向和历史。
- `POST /sessions/{session_id}/answers/stream`：同样提交回答，但使用 SSE 流式返回评价阶段、非满分参考回答片段和最终会话状态；只有评分达到 100 才不生成参考回答。
- `GET /candidates/{candidate_id}/profile`：读取跨会话持久化的面试者能力画像；薄弱项可通过 `weakness_sources` 回溯来源会话、问题序号和证据 ID。

项目分析状态为 `CREATED`、`SOURCE_READY`、`SCANNING`、`ANALYZING`、`READY` 或 `FAILED`。当前默认使用工作区内的 `interview-agent.db`；设置 `INTERVIEW_AGENT_DB` 可以切换 SQLite 文件。未传数据库的嵌入式服务使用内存存储。会话列表、标题和会话详情均从同一 Session Store 读取，前端的 `localStorage` 只作为离线显示缓存，不再作为会话历史事实源。桌面面试工作台支持拖拽调整左右栏宽度，右侧证据面板可收起为窄栏；移动端仍使用抽屉式证据面板。

所有错误响应保留字符串 `error`，并提供稳定的 `code`、`retryable` 和 `request_id`；同一请求 ID 也写入 `X-Request-ID` 响应头。完整字段和 LLM 设置接口以 OpenAPI 为准。

## 岗位准备

侧边栏的“岗位准备”是面试者级的独立页面，不依赖当前是否打开某个项目。用户可以同时保存多个目标岗位，并为每个岗位维护 JD 原文、结构化任职要求、关联项目、独立题库、申请状态和练习历史。一个岗位可关联多个已分析项目；从某道岗位题开始练习后，会话会同时记录岗位和题目 ID，便于回到岗位页查看历史。

当前创建入口支持直接粘贴 JD，或导入不超过 1MB 的 `.txt`、`.md`、`.json` 文本文件。图片和 PDF 的 OCR 尚未实现；这类 JD 需要先复制为文本。题库生成目前是确定性的本地规则，不调用外部模型：能被项目证据支撑的要求生成项目证据题，其余要求生成经历题。

## 简历库

“新建复盘会话”页面从简历库选择面试者：面试者卡片展示姓名与面试者 ID，点击“更换”打开选择简历对话框，按姓名、岗位、领域或关联项目搜索并选中一份简历。简历库是全局资源池，不按当前面试者过滤；选中后以该简历作为面试者开始复盘，跨会话能力画像按 `candidate_id` 继续累积。

侧边栏的“简历库”是独立页面：列出全部简历（姓名、岗位、领域、状态、主张数量、关联项目），支持搜索、删除和上传；点击任意简历进入详情页，逐条确认主张的“暂不用以提问”标记，并查看简历原文、关联项目和更新时间。选择简历对话框的上传入口与简历库页面共用同一个上传/主张确认弹窗。

当前上传入口只接受 PDF 简历（不超过 10MB）：后端提取 PDF 内嵌文本层后按文本简历入库；扫描件（图片型 PDF，无文本层）无法提取。主张提取是确定性的本地规则：跳过章节标题、时间轴和联系方式行，保留以动作词开头或包含结果动词的描述，最多 12 条。每份简历可单独切换主张的 `skip` 标记，表示该主张暂不用于提问。后端不可用时，前端选择简历对话框回退到 Stitch 原稿演示数据并显示离线提示。

选择简历后创建的复盘会话会把该简历中未跳过的主张写入会话状态：面试工作台的上下文栏展示面试者主张，问题生成优先引用与当前主题匹配的简历主张（“简历主张提到……”），主题选择时也会给命中主张的主题加分；跳过了的主张不会进入会话。主张随会话持久化，重启后仍可恢复。

## 领域与记忆边界

当前已实现 `technical_interview`、`portfolio_review` 和 `defense_review` 三种 `ReviewPolicy`。技术面试按基础/深入/架构追问；作品集评审按叙事/权衡/影响追问；项目答辩按澄清/论证/答辩追问。三种模式共享 Analyzer 输出和会话基础设施。

技术面试开始前，领域层会把 Analyzer 提取的组件、接口、流程、数据和工程事实聚合为最多 5 个系统级方向，例如“系统架构与模块协作”“接口设计与前后端联调”“核心业务流程与数据流”。类、函数、文件路径和代码摘录只作为问题与评价的证据，不直接写入面试问题。首问覆盖整体目标、边界和协作方式；后续再进入核心流程、异常处理、方案权衡和架构演进。LLM 若返回包含具体代码标识符或缺少可用 `question` 的响应，会回退到本地系统级问题。

技术面试的追问规则是：分数低于 60 进入基础澄清，60–79 深入核心流程与协作机制，80 及以上进入架构/容量/稳定性权衡。三层记忆分别是：

1. 当前回答上下文：`InterviewState` 中的当前问题、回答、评价和证据引用。
2. 当前会话历史：Session Store 中的 `history`，可随 SQLite 会话恢复。
3. 跨会话面试者画像：Candidate Profile Store 中按 `candidate_id` 保存主题分数、趋势、最近分数、样本数和弱点；每个弱点保留最近一次来源会话、问题和证据引用。

现有工作流保留 `QuestionGenerator`、`Evaluator`、项目仓库、会话存储和 `InterviewGraph` 作为可替换边界；当前使用 LangGraph 编排工作流、LangChain 调用 LLM，但不依赖 LangChain 的自主 Agent 执行器、PostgreSQL、向量数据库或多 Agent 框架。未配置 LLM 时自动回退到本地规则生成器与评价器。
## 前端项目目录上传

面试工作台左侧只展示领域层提炼后的粗粒度“核心方向”：当前方向优先，最多展示 5 个方向。项目组件、代码位置和其余分析事实保留在项目资料与证据视图中，避免把结构导航展开成文件/组件清单。

启动后端和前端后，如果没有设置 `VITE_PROJECT_ID`，首屏仍然是 Agent 聊天工作台。点击聊天输入框左侧的 `+` 附件按钮，在菜单里选择项目目录；浏览器读取其中的文本文件，移除所选目录的顶层名称，并生成如下 Folder JSON descriptor：

```json
{
  "project_id": 1733200000000,
  "project_name": "demo-order-system",
  "source": {
    "type": "folder",
    "files": [{ "path": "src/OrderService.java", "content": "..." }]
  }
}
```

descriptor 通过现有 `POST /projects/upload` 发送；项目分析完成后，前端继续请求 `status`、`knowledge` 并自动创建 `/sessions` 面试会话，分析结果以 Agent 消息的形式回到聊天流。`project_id` 由前端生成数字并保存到 `localStorage`，刷新页面可恢复最近项目。面试者 ID 默认使用 `VITE_CANDIDATE_ID`，未配置时为 `default`。

当前浏览器上传入口只支持目录中的 UTF-8 文本文件和 Folder JSON descriptor；单个文本文件上限为 10MB，单个项目最多 10000 个文件、总文本量 100MB。ZIP、multipart 和二进制文件上传仍不支持。开发模式下显式设置 `VITE_ENABLE_FIXTURE_FALLBACK=true` 时，仍保留无项目 ID 的 fixture fallback 行为。

服务端 ZIP descriptor 的默认解压配额与前端目录上传容量对齐：单文件 `10 MiB`、总解压大小 `100 MiB`、文件数 `10000`。三个配额字段必须是非负 JSON 整数，且只能把限制调小；省略时使用默认值，非法或超限请求返回 `400` 可读错误。Folder JSON 的服务端行为保持原样；ZIP 仍要求 `source_path` 是服务进程可访问的本地路径，当前不支持 multipart。
