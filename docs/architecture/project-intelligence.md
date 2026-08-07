# Project Intelligence Engine + Domain Review Agent 架构

当前 `InterviewGraph` 已使用 LangGraph `StateGraph` 编排开始面试和提交回答两个入口。它只负责一次请求内的工作流路由，`InterviewService` 仍负责 Session Store、Candidate Profile Store、CAS 和失败回滚。暂不启用 LangGraph Checkpointer，避免会话状态同时由两套持久化系统管理。

开始面试路径依次经过 `load_project`、`select_initial_topic`、`generate_initial_question` 和 `assemble_initial_state`；提交回答路径依次经过 `validate_answer`、`evaluate_answer`、`update_profile`、`decide_follow_up`、`generate_follow_up_question` 和 `assemble_follow_up` 节点。画像更新使用工作副本，只有完整生成下一题后才交给 Service 提交，保持现有失败回滚语义。

`InterviewGraph` 支持可选 Checkpointer 和 `thread_id`，用于验证检查点、状态历史和恢复。该能力通过 `InterviewService.workflow_checkpointer` 注入，但默认关闭；在确认 Checkpointer 与 SessionStore 的事务一致性前，不将其作为默认会话持久化方案。

## 1. 定位与边界

本项目的核心不是只面向 Java 的聊天面试助手，而是两层组合：

- **Project Intelligence Engine**：把项目、代码、配置或未来的作品素材转换为带证据的 `UniversalProjectModel`。
- **Domain Review Agent**：基于统一模型和面试者记忆，按技术面试、作品集评审或项目答辩等领域策略生成问题、评价和追问。

两层通过模型契约解耦：Analyzer 只回答“输入是什么、由什么组成、如何运作”；Review Policy 只回答“如何评审、问什么、如何根据回答决定下一步”。Java、Python、前端、视频和设计的差异不得渗入通用面试流程。

当前实际链路是：

```text
ProjectSource
    ↓ prepare()
Workspace: workspace/projects/{project_id}/source + analysis
    ↓
ProjectScanner
    ↓
AnalyzerRegistry.select()
    ↓
ArtifactAnalyzer.analyze()
    ↓
UniversalProjectModel
    ↓ project_model_to_knowledge()
ProjectKnowledge 兼容层
    ↓
ReviewPolicy / InterviewAgent
    ↓
Topic → Question → Answer → Evaluation → Follow-up
    ↓
InterviewState + Session Store + Candidate Profile Store
```

当前 `InterviewService` 会先把分析器输出转换为旧的 `ProjectKnowledge`，以保持 `QuestionGenerator`、`Evaluator`、项目仓库和 `InterviewGraph` 的兼容边界。概念上 Review Policy 消费统一项目事实；实现上第一版通过这个显式兼容转换进入现有面试流程。

当前已引入 LangGraph 作为轻量工作流编排层，但仍保持 SQLite 和现有 Session Store 的可测试边界；PostgreSQL、向量数据库、多 Agent Runtime 以及 LangGraph Checkpointer 暂不接入，等现有工作流出现明确需求后再单独评估。

## 2. 输入、Workspace 与生命周期

### ProjectSource

输入统一遵循：

```python
class ProjectSource(Protocol):
    source_type: str

    def prepare(self, workspace_path: Path) -> Path:
        """将输入准备到 workspace_path，并返回项目根目录。"""
```

当前实现：

- `FolderSource`：接收带相对路径的文件集合或映射，保留目录结构；内容在 HTTP 适配层中是 UTF-8 字符串。
- `ZipSource`：从本地 ZIP 归档准备目录。

两者都拒绝空路径、绝对路径、目标目录外路径、重复/冲突路径和符号链接；ZIP 额外拒绝 Zip Slip。服务端通过 `source_from_descriptor()` 为 ZIP descriptor 设置固定默认配额：单文件解压大小 `10 MiB`、总解压大小 `100 MiB`、文件数 `10000`。descriptor 可以传入 `max_total_size`、`max_file_size` 和 `max_files` 覆盖为更小的非负整数，但每个值都不能超过对应服务端上限；省略字段使用默认值。超限或非法类型会以可读错误返回，实际解压失败会在 `ProjectAnalysis` 的 `FAILED` 记录中保留错误。直接调用 `ZipSource` 仍使用调用方显式传入的限制，不额外注入这些 descriptor 默认值。

当前没有 Git URL、multipart 上传或远程对象存储 Source；文档中的可运行示例只使用 folder descriptor 或服务进程本地可访问的 ZIP 路径。

### Workspace

`WorkspaceManager` 对项目 ID 做整数规范化，并固定创建：

```text
workspace/projects/{project_id}/source/
workspace/projects/{project_id}/analysis/
```

Analyzer 只读取 `source` 下的准备结果；`analysis` 用于分析输出所在的隔离区域。重复 ingest 会原子替换 `source`，并保留已有 `analysis` 目录。

项目分析记录的生命周期是：

```text
CREATED → SOURCE_READY → SCANNING → ANALYZING → READY
                                                ↘ FAILED
```

失败记录保留可读 `error`，不会把错误输入转换成缺少来源的假知识。

## 3. Scanner、AnalyzerRegistry 与支持矩阵

`ProjectScanner.scan(root)` 只收集文件结构事实：文件列表、语言计数、根级构建工具和构建文件、Java 源码根、常见配置文件、根级 `package.json` 类型和 manifest 状态。它不会解析 Java/Spring 语义，也不会生成面试问题。

Scanner 统一忽略 `target`、`build`、`.gradle`、`out` 和 `node_modules` 等目录。

```python
class ArtifactAnalyzer(Protocol):
    analyzer_id: str

    def supports(self, structure: object) -> bool: ...
    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel: ...
```

`AnalyzerRegistry` 要求 `analyzer_id` 非空且唯一，并且实现 `supports()`、`analyze()`。选择必须是确定性的：恰好一个支持者才返回；没有支持者抛出 `LookupError`；多个支持者抛出列出冲突 ID 的 `ValueError`，不会按注册顺序猜测。

默认注册器是 `JavaAnalyzer`、`GradleJavaAnalyzer`、`PythonAnalyzer`、`FrontendAnalyzer`：

| Analyzer | `supports()` 条件 | 已实现的事实提取 |
| --- | --- | --- |
| `java` | `build_tool == "maven"`，Java 文件数大于 0 | 根级 `pom.xml`、Spring 组件注解、字段依赖、`GetMapping`/`PostMapping`/`RequestMapping` endpoint、`@Transactional`、有限 POM 技术映射 |
| `gradle-java` | `build_tool == "gradle"`，Java 文件数大于 0 | 根级 Gradle 构建文件、Spring 组件与字段依赖、HTTP endpoint、事务主题、有限插件与依赖映射 |
| `python` | 存在非忽略 Python 文件，且没有根级 `package.json` | 模块、顶层类/函数、`main`/`__main__` 入口、依赖文件和包名 |
| `frontend` | 根级 `package.json` 是 object，且存在 JS/TS 文件 | 函数/类/大写变量组件、字面量路由、`fetch`/`axios`/HTTP 方法调用、依赖版本和常见构建工具 |

Maven 与 Gradle 由独立 Analyzer 处理，Registry 根据根级构建文件确定性选择。Python 和 Frontend 适配器也都是保守的静态分析，不执行源码或 bundler。

## 4. UniversalProjectModel

`UniversalProjectModel` 使用标准库 `dataclass`，所有字段可以经过 `dataclasses.asdict()` 进入 JSON。当前字段契约如下：

```python
@dataclass(frozen=True)
class UniversalProjectModel:
    project_id: int
    identity: ProjectIdentity
    structure: list[StructureNode]
    technologies: list[Technology]
    components: list[Component]
    relations: list[Relation]
    flows: list[Flow]
    insights: list[Insight]
    evidence: list[Evidence]
    topics: list[ProjectTopic]
    dependencies: dict[str, list[str]]
    metadata: dict[str, JsonValue]
```

各层含义：

- `identity`：`name`、`artifact_type`、`goal`、`description`。
- `structure`：目录、模块、manifest、源文件或依赖文件等结构节点。
- `technologies`：技术/工具名称、类别、版本和证据引用。
- `components`：可引用的服务、类、函数、组件等，含 `id`、显示名、类型、路径和证据引用。
- `relations`：组件依赖、API 调用等关系，含 source/target、关系类型和证据引用。
- `flows`：HTTP endpoint、Python 入口、前端 route 等流程节点，含组件和证据引用。
- `insights`：Analyzer 能从事实中确定的能力、风险、弱点或主题摘要；不是自然语言评价器的结果。
- `topics`：当前分析器可明确绑定证据的项目主题，含名称、分数和 `evidence_ids`。
- `dependencies`：可序列化的源组件到目标组件/依赖文件映射。
- `metadata`：JSON-safe 的分析摘要，例如 analyzer ID、源文件列表、入口列表或 manifest 名称。

### Evidence

每条 `Evidence` 至少包含：

```python
Evidence(
    id="e-...",
    source_path="src/main/java/demo/OrderService.java",
    locator="line 15 (Transaction)",
    excerpt="@Transactional",
    kind="topic",
    confidence=0.9,
    metadata={},
)
```

`source_path` 是相对于分析根目录的 POSIX 路径；`locator` 是行号、符号或静态扫描位置；`excerpt` 是来源摘录；`kind` 区分 component、relation、flow、topic 等事实；`confidence` 保留提取置信度。组件、关系、流程、主题通过 `evidence_ids` 回指这些记录。

模型构造会拒绝重复 `Evidence.id` 和重复组件名，并要求 `evidence` 真正是 `list[Evidence]`。`metadata` 中的 `Path`、mapping、tuple、set 等值会先归一化为 JSON-safe 值，避免持久化时静默丢失。

### 兼容转换

`project_model_to_knowledge()` 是明确的向后兼容边界：

- `topics` 转为旧 `Topic(name, score, evidence)`；没有显式 topics 时，可从带 topic 的 insights 推导。
- `components` 转为旧模型的名称到路径/描述映射。
- `evidence` 按 ID 转为旧模型字典，并保留来源、摘录、类型和置信度。
- dependency relations 与显式 `dependencies` 合并到旧依赖字典。
- `weakness`、`risk`、`gap` 类型 insight 转为旧 weaknesses。
- 主题若只能绑定一个真实 evidence ID，转换器会创建可查询别名；没有唯一证据或引用 Ghost ID 时会抛出 `ValueError`。

面试流程暂时消费 `ProjectKnowledge`：

```python
@dataclass(frozen=True)
class ProjectKnowledge:
    project_id: int
    project_name: str
    topics: list[Topic]
    components: dict[str, str]
    evidence: dict[str, dict[str, Any]]
    dependencies: dict[str, list[str]]
    weaknesses: list[str]
```

这使 Universal Project Model 可以先稳定演进，而不要求一次性重写旧的 QuestionGenerator、Evaluator 和 InterviewAgent。

## 5. ReviewPolicy 与证据驱动面试

领域模式由 `ReviewMode` 表达：`technical_interview`、`portfolio_review`、`defense_review`。统一契约是：

```python
class ReviewPolicy(Protocol):
    mode: ReviewMode

    def select_topic(project, profile, history) -> Topic: ...
    def next_direction(score: int, current_level: int) -> tuple[str, int]: ...
```

当前三个策略均已实现。`TechnicalInterviewPolicy` 优先结合真实证据、弱点和依赖关系；`PortfolioReviewPolicy` 优先组件、流程和作品证据；`DefenseReviewPolicy` 优先目标、决策、风险和关系证据。它们共享 Analyzer 输出和面试工作流，不复制语言解析逻辑。

技术主题选择的确定性优先级包含：主题是否有真实证据、项目/画像/历史弱点是否命中、依赖关系是否相关、证据数量、主题分数和原始顺序。`resolve_topic_evidence()` 只返回存在于 `project.evidence` 的记录，`real_evidence_ids()` 会过滤 Ghost ID 并去重。

内置评分方向规则：

| 分数 | `next_direction` | 下一层级 |
| --- | --- | --- |
| `< 60` | `basic` | 1 |
| `60–79` | `deep` | 当前层级加 1，最多 3 |
| `>= 80` | `architecture` | 4 |

问题生成器和评价器通过 `ReviewContext` 接收证据、证据 ID、已覆盖点和缺失点。`Evaluation` 会保留 `evidence_ids`、`covered_points`、`missing_points`，因此 UI 只展示后端结果，不自行计算评分或拼装证据。

## 6. 三层 Memory 与版本持久化

### 当前回答上下文

`InterviewState` 保存当前 `project_id`、`project`、`current_topic`、`level`、`question`、`answer`、`evaluation`、`next_direction`、当前会话 `history`、问题证据引用和 `candidate_id`。这是一次提交回答时的工作上下文，不是跨会话画像。

### 当前面试会话

Session Store 持久化完整 `InterviewState` 和面试者归属。内存实现使用 `InMemorySessionStore`；SQLite 实现使用 `sessions` 表的 JSON `payload`、`candidate_id` 和整数 `version`。写入时可使用 expected version 做 CAS，冲突返回 `SessionConflictError`，避免两个请求覆盖同一回答。

### 跨会话面试者画像

`CandidateProfileStore` 按非空 `candidate_id` 保存 `CandidateProfile`。每个 skill snapshot 当前包含：

```json
{
  "score": 40,
  "trend": "declining|improving|stable|new",
  "recent_score": 40,
  "sample_count": 1,
  "weaknesses": ["..."],
  "weakness_sources": [
    {
      "weakness": "...",
      "session_id": "...",
      "project_id": 26,
      "record_index": 0,
      "question": "...",
      "evidence_ids": ["..."]
    }
  ]
}
```

每个薄弱项只保留最近一次可追溯来源，避免与完整 Session History 重复增长。SQLite profile payload 的 `schema_version` 当前为 `2`；读取时兼容缺省版本 `0`、旧版本 `1` 和当前版本 `2`，拒绝未知版本。`save`、`update`、`merge`、`commit` 和条件恢复都会增加 profile version；Profile Store 还会在并发更新时使用事务/锁保护不同面试者的样本。

## 7. HTTP API 与字段契约

HTTP 层是无额外依赖的标准库 JSON API，响应统一为 `application/json; charset=utf-8`。`docs/api/openapi.json` 是路径、请求、响应、状态码和错误字段的唯一事实源；本节只解释核心链路。

### 上传、状态与知识

```http
POST /projects/upload
Content-Type: application/json
```

Folder 请求：

```json
{
  "project_id": 26,
  "project_name": "订单系统",
  "source": {
    "type": "folder",
    "files": [
      {"path": "pom.xml", "content": "<project>...</project>"},
      {"path": "src/main/java/demo/OrderService.java", "content": "..."}
    ]
  }
}
```

ZIP 请求：

```json
{
  "project_id": 27,
  "source": {
    "type": "zip",
    "source_path": "C:/tmp/order-system.zip",
    "max_total_size": 52428800,
    "max_file_size": 5242880,
    "max_files": 5000
  }
}
```

ZIP descriptor 中的三个配额字段都是字节数或文件数的 JSON 整数；它们可以省略以使用服务端默认值，但不能传负数、浮点数、字符串或超过服务端上限的值。Folder JSON descriptor 的字段和行为不受这些 ZIP 配额字段影响。

上传成功返回 `201` 和 `ProjectAnalysis`；分析失败通常返回 `422`，并保留 `analysis_status: "FAILED"` 与 `error`。输入格式、ID 或 JSON 错误返回 `400`。

```http
GET /projects/{project_id}/status
GET /projects/{project_id}/knowledge
```

`status` 返回：`project_id`、`project_name`、`source_type`、`workspace_path`、`analysis_status`、`schema_version`、`analyzer_id`、`universal_model`、`knowledge`、`error`。`knowledge` 返回 `ProjectKnowledge` 的 `project_id`、`project_name`、`topics`、`components`、`evidence`、`dependencies`、`weaknesses`。

### 会话、回答与错误

```http
POST /sessions
{"project_id": 26, "candidate_id": "candidate-1"}

GET /sessions/{session_id}

POST /sessions/{session_id}/answers
{"answer": "OrderService 调用 OrderRepository 保存订单。"}
```

创建会话返回 `201`，回答返回 `200`，结构均为 `{ "session_id": "...", "state": { ... } }`。状态中包含 `question`、`current_topic`、`question_evidence_ids`、`evaluation`、`next_direction` 和 `history`。找不到项目/会话返回 `404`；会话或画像版本冲突返回 `409`。

### SQLite 项目记录

`SQLiteProjectRepository` 使用 `projects` 表保存兼容旧字段 `payload`，并保存：

```text
source_type
workspace_path
analysis_status
schema_version = 1
analyzer_id
project_name
universal_model_payload
knowledge_payload
error_message
```

`universal_model_payload` 与 `knowledge_payload` 都是 JSON。读取时校验 schema version 和 project ID；只包含旧 `ProjectKnowledge` 的记录仍可读取，并按兼容默认值恢复为 `READY/manual`。未知项目分析版本、模型项目 ID 不匹配或非法 JSON 会失败而不是静默接受。

## 8. 未来扩展

未来视频、设计或混合媒体可以增加独立 Analyzer，仍只实现 `supports()`/`analyze()` 并输出 Universal Project Model。建议用 manifest 表达素材、时间线、脚本和元数据，例如：

```json
{
  "artifact_type": "video|design|mixed_media",
  "assets": [{"path": "", "mime_type": "", "duration_ms": 0}],
  "timeline": [{"start_ms": 0, "end_ms": 0, "asset": "", "label": ""}],
  "scripts": [{"path": "", "language": "", "version": ""}],
  "metadata": {}
}
```

素材路径、时间码、页码、画板和导出元数据都应成为可回溯 Evidence。Analyzer 不应了解评审话术；作品集评审或答辩只通过新的 Review Policy 改变问题、评价维度和追问策略。
