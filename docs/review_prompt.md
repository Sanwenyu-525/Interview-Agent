# Project Intelligence Engine 工程审查提示词（已按实际代码对齐）

> 审查目标是 `interview_agent/`，不要假设目录。以下清单是当前真实代码结构，任何分析必须引用真实文件与行号。

```
interview_agent/
├── agent.py        # InterviewAgent（领域评审核心）+ QuestionGenerator/Evaluator Protocol + RuleBased 兜底
├── graph.py        # LangGraph：StateGraph + _InterviewGraphState(TypedDict)，一次性 start/resume 调度
├── llm.py          # LLMConfig、OpenAICompatibleClient、LlmQuestionGenerator/LlmEvaluator、内嵌提示词、LLMError/LLMResponseError
├── models.py       # dataclass：Topic/ProjectKnowledge/Evaluation/ReviewContext/QuestionResult/InterviewState… + AnalysisStatus枚举
├── service.py      # 1505行 InterviewService + InMemorySessionStore + 项目/简历/岗位/设置编排（巨型文件）
├── http_api.py     # 标准库 ThreadingHTTPServer、路由白名单 PUBLIC_API_OPERATIONS、CORS allowlist、X-Request-ID、流式端点
├── server.py       # build_server 组装入口
├── settings.py     # LLM 配置档案存储（InMemory/SQLite），无 pydantic-settings
├── sqlite_store.py # SQLiteProjectRepository / SQLiteSessionStore
├── repository.py   # InMemoryProjectRepository（可替换层）
├── tools.py        # ProjectTools：证据/组件/依赖查询
├── positions.py / resumes.py / profile.py
├── analyzers/      # java / python / frontend / gradle_java + registry + scanner + java_rules（插件式）
├── ingestion/      # 项目摄入（目录/zip）+ sources.py + security.py(normalize_project_id)
├── intelligence/   # models.py：Universal Project Model + project_model_to_knowledge 兼容层
├── memory/         # profile_store.py：跨会话候选画像（SQLite）
└── review/         # 评审策略：policy / technical / portfolio / defense / outline / evidence
tests/              # 全部为 unittest（非 pytest），含 mock
docs/api/openapi.json  # HTTP 契约唯一事实源
```

## 工程事实核对（审查时以此为准，不要凭假设）

1. 依赖：`langchain-core` / `langchain-openai` / `langgraph` / `pypdf`，Python ≥3.10，无 FastAPI/Flask。
2. 无 `ruff`/`black`/`mypy`/`pre-commit`/`tox` 配置；无 Dockerfile/CI；全库无 `logging`；无 `.env` 加载器，环境变量 `LLM_*` 直接读。
3. 测试命令：`python -m unittest discover -s tests`（不是 pytest）。
4. LLM 通过 OpenAI 兼容接口接入（`provider=openai_compatible`）；`rule_based` 仅作为未配置时的内部兜底，不支持 Claude / Azure 专用接口。
5. LangGraph：graph.py 仅做一次 start/resume 调度，checkpointer 未启用；持久化与"暂停/恢复"全部由 service 层 SQLite 承担。
6. PDF 只在简历解析（resumes.py，pypdf 提取），项目分析不吃 PDF，走 analyzers 源码解析。
7. 提示词以中文字符串硬编码在 llm.py 内，没有 prompts/ 目录。
8. Interview 状态机关键点位：`waiting_answer`；Human-in-the-loop 由 service 层驱动。

## 一、架构检查（按真实模块）

检查以下文件职责与边界：`agent.py`、`graph.py`、`service.py`、`http_api.py`、`llm.py`、`models.py`、`analyzers/`、`ingestion/`、`intelligence/`、`memory/`、`review/`、`tools.py`、`sqlite_store.py`、`repository.py`、`settings.py`。

重点分析：
1. `service.py`（1505 行）是否职责过载：面试编排 + Session 存储 + 项目摄入 + 简历/岗位 CRUD 全部聚合，是否应拆分。
2. `agent.py`（面试 Agent）与 `graph.py`（工作流）、`service.py`（业务用例）之间是否职责重叠或相互倒灌：`InterviewAgent` 是否即"完整 Agent"又被 LangGraph 当节点调用；agent 层与 service 层谁说了算。
3. 提示词是否代码分离：现状为 llm.py 内 JSON 中文 prompt 硬编码——评估是否应抽离为可版本控制的模板目录。
4. `OpenAICompatibleClient` 已是 LLM 统一封装，检查是否有绕过它的直接调用。
5. `tools.py` 的 ProjectTools 是否真正接入执行链（当前 LangGraph 未使用它），还是死代码。
6. `repository.py` 内存实现 vs `sqlite_store.py` 的替换语义是否对称（错误类型、幂等性）。
7. `intelligence/`（Universal Project Model）与 `models.py`（旧契约）双模型并存，兼容转换层是否扩散（`project_model_to_knowledge`、`_invoke_compatible`）。

输出：`当前架构 / 优点 / 问题 / 推荐架构（引用真实文件）`。

## 二、Python 工程规范（PEP8/PEP257/3.10+）

按 `models.py`、`agent.py`、`http_api.py`、`service.py` 4 个文件逐一切查：

- 类型系统：Protocol 已用于 `QuestionGenerator`/`Evaluator`（agent.py:22-48）——评估使用是否恰当、是否还有 `Any` 泛滥（如 `graph.py` 的 Any、`service.py` 的 `project_knowledge: Any`）。
- TypedDict：仅 `graph.py` 内部 State 使用；`InterviewState` 用 dataclass——按真实现状评估该决策是否合理。
- `agent.py:505` `_invoke_compatible`、`graph.py:46` `_call_with_resume_claims` 用 `inspect.signature` 做运行时鸭子类型判断——指出该兼容层导致的隐式契约与可读性成本。
- 巨型文件：`service.py` 1505 行、`http_api.py` 538 行、`sqlite_store.py`、`review/technical.py` 等——列出巨型函数/类并给出拆分点。
- 魔法字符串：状态机常量（"waiting_answer"）、review_mode、评分级中文标签散落。
- 硬编码 Prompt、隐式配置（默认值散在 from_payload）。
- 全局/可变状态：`InterviewAgent.profile`/`pending_profile_update` 作为可变态挂在单实例——指出多会话并发风险。

输出：`严重问题（文件:行号） / 优化建议 / 违反哪条规范`。

## 三、LLM 调用架构

已存在：`LLMConfig`（provider 开关）、`OpenAICompatibleClient`（统一调用入口，异常统一为 LLMError/LLMResponseError）、LlmQuestionGenerator/LlmEvaluator（领域适配层）。

检查：
- **模型可替换性**：替换模型必须改业务代码吗？当前只支持 openai_compatible，加 Claude/Azure 需要改什么。
- **ResponseParser 可靠性**：`_json_object` 容错（代码块剥壳）→ 合格 JSON 再由 JsonOutputParser 解析，LLM 回复为非合法 JSON 时 LlmQuestionGenerator 是否可靠降级到 RuleBased（llm.py 已实现空 question 时 fallback，审计其有效性）；无重试与退避。
- **Prompt 规范化**：无独立 prompts/ 目录、无版本、无参数化、无测试入口；ChatPromptTemplate 内硬编码中文 JSON Schema，与领域 prompt 分散。
- **上下文/Token 管控**：`_project_payload`（llm.py:232）注释表示全量 evidence 可达数十万字符，prompt 只保留当前选中证据——评估该取舍是否充分；history 全量拼接是否裁剪；简历/项目文本是否有大小上限（`MAX_PDF_BYTES` 只在简历）；是否有 token 统计/预算。
- **重试/超时**：LLMConfig 有 timeout，但无请求重试、指数退避；检查失败后行为。

输出：`分层建议（LLMClient/Provider/PromptTemplate/ResponseParser 现状对照）`、`可替换模型到业务不动代码吗`、`可靠性缺口（文件+行号）`。

## 四、LangGraph 工作流设计（graph.py）

现状：`_InterviewGraphState` TypedDict、`START` → start/resume 条件路由、10 个节点（每节点=单点一个 agent 方法）、compile 无 checkpointer。

检查：
1. 节点职责是否单一；节点间数据传递（state dict 与参数/返回是否规范）是否有验证。
2. State 把 `project`/`topic`/`history` 等大对象放入节点之间扩散——拷贝成本；未来启用 checkpoint 时该 TypedDict 是否可序列化；现在持久化由 service 层做，评估该分离是否正确。
3. 暂停/恢复：事实是 service 层 `waiting_answer` 状态字段驱动，并不在 graph 内——审计该分工是否合理、Graph 与 SessionStore 谁负责会话推进。
4. `get_state`/`get_state_history` 只对应 checkpointer，当前 build_server 未传 checkpointer——那么曝光这些接口是否空壳，确认。
5. 异常路径：节点抛出时无 error 节点重试/降级，评估是否需要。

输出：`正确设计 / 问题（如 state 规范化、无 checkpoint、错误路径） / 建议`。

## 五、Agent 设计规范

`Agent = Reasoning + Tools + Memory + Workflow` 对照真实现状：

- 推理：InterviewAgent（agent.py）+ ReviewPolicy（review/technical.py）+ RuleBased 兜底。
- Tools：ProjectTools（tools.py）——评估是否只是对象方法而非带输入/输出的 Tool 接口；错误处理（查不到返回 None/空）；是否有独立接口边界。
- Memory：三段实际存在——`InMemorySessionStore`/`SQLiteSessionStore`（会话）、`CandidateProfileStore`（跨会话画像 memory/）、`ReviewContext`（当前证据）。评估三者隔离与序列化；session 与 candidate 关联是否有统一键口径。
- Context 管理：简历主张（resume_claims）如何在问题生成与评价之间流转（agent.py 到 question/evaluate）。

## 六、输入摄入与文档解析（对齐真实管线：ingestion + analyzers，不是 pypdf）

项目输入走 `ingestion/`（Directory/Folder/Zip 源 + security）→ `analyzers/`（java/python/frontend 等）。

检查：
- 空项目/乱结构/不支持的源码类型：扫描器（scanner.py）如何兜底；analyzer registry（registry.py）匹配失败行为。
- 超大项目/超大文件：`ingestion/sources.py` 已有 ZIP 三上限常量（ZIP_DESCRIPTOR_DEFAULT_MAX_FILE_SIZE/MAX_FILES/MAX_TOTAL_SIZE），但目录遍历的文件数量、单个文件大小限制是否齐全。
- ZIP 炸弹、路径穿越（zip 内 `../../`）、上传文件名规范化（`ingestion/security.py` 的 normalize_project_id）——穷尽边界。
- 简历 PDF：`resumes.py extract_pdf_text` 对空/扫描/编码失败的处理；`MAX_PDF_BYTES` 是否真实限流。
- analyzer 产生的中文证据、置信度字段是否保留到 `ProjectKnowledge.evidence`。

## 七、HTTP 层规范（对齐真实实现）

`http_api.py`：ThreadingHTTPServer、路由走 `PUBLIC_API_OPERATIONS` 白名单。

检查：
- 路由解析、query/body/JSON 解析、统一响应与错误（对照 openapi.json 错误 schema）。
- CORS allowlist（仅 127.0.0.1/localhost/tauri/terminal）——是否收敛。
- `POST /sessions/{id}/answers/stream` 流式实现；Content-Length/断连处理。
- 并发：ThreadingHTTPServer 线程模型，`InterviewService` 内 Lock/RLock 覆盖的共享态（如 `pending_profile_update`）线程安全吗？
- 缺陷：无静态后端层。

评估：开发环境是否合适；生产化是否应迁移 FastAPI，还是保持轻量 + 补路径说明。

## 8、异常体系

- LLM：`LLMError`/`LLMResponseError` 归一化（llm.py:27-32）——超时/429/空响应是否分类？重试？降级？
- 服务/领域：`SessionConflictError`/`ProfileConflictError`（models.py）、`PositionNotFoundError`/`ProjectNotFoundError` 等（service 层导出）——错误是否都到 http 层统一映射 4xx/5xx。
- 摄入/分析：`ProjectAnalysisError`、analysis_status=FAILED 记录——失败是否可重试。

输出：异常分类现状、缺失项、统一错误架构建议。

## 9、配置管理

现状：`settings.py`（InMemory/SQLite 配置档案）+ `LLMConfig.from_env/from_payload`；环境变量 `LLM_*`、`INTERVIEW_AGENT_DB`；API Key 明文存 SQLite。

检查：.env 缺失、密钥落库风险、环境隔离（dev/prod）、是否值得引入 pydantic-settings（给出替代而非只提建议）。

## 10、测试

现状：tests/ 全为 unittest + mock；`test_llm.py` 用 fake llm 客户端；`test_graph.py` 覆盖 Graph；契约测试 test_api_contract.py 对照 openapi.json。

检查：LLM mock 是否真实（不触发 API 调用）；prompt 无独立测试；service 大逻辑无行为定义；**覆盖率缺口清单**（并发、线程、上传边界、SQLite 迁移）。

## 11、工程化

无 ruff/black/mypy/pre-commit/CI/Docker/logging。检查是否应补入；日志集中与脱敏。

## 12、安全

- Prompt Injection：简历文本、项目 README/代码内容、回答文本直接进入 system/user prompt，无隔离/白名单。
- 上传：PDF/ZIP 大小限制、ZIP 炸弹、文件类型、路径穿越（security.py）。
- 密钥：API Key 明文存 SQLite、接口只暴露 api_key_set 布尔、无轮换机制。
- SQL 注入：sqlite 参数化是否全覆盖。
- CORS 已收敛，检查其他（SSE 跨域）。

## 输出格式

1. 项目整体评分（架构 / Python规范 / AI Agent设计 / LLM工程 / 安全 / 测试 / 工程化 + 总分）
2. 架构问题表格：`问题 | 严重程度 | 原因(文件+行号) | 建议`
3. AI Agent 专项问题表格：`问题 | 影响 | 优化方案`
4. 推荐目标架构：给出重构后 interview_agent 目录树（以真实代码为准）
5. 改造优先级 P0 / P1 / P2：每项必须可回写真实文件