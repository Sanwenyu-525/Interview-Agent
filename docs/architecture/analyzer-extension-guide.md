# Analyzer 扩展指南

本项目把“输入是什么”与“如何评审”分开。Analyzer 只负责从用户提交的项目或作品中提取可回溯的事实，输出 `UniversalProjectModel`；`ReviewPolicy`、`InterviewAgent` 和前端面试流程消费这个模型，不感知 Java、Python 或前端语法。

## 1. 插件契约

每个 Analyzer 实现以下最小契约：

```python
class ArtifactAnalyzer(Protocol):
    analyzer_id: str

    def supports(self, structure: object) -> bool: ...
    def analyze(self, artifact_root: Path, project_id: int) -> UniversalProjectModel: ...
```

`structure` 必须是 `ProjectScanner.scan(root)` 的结果。`supports()` 只根据 Scanner 已发现的文件、语言计数和根目录结构选择插件；它不应解析完整源码，也不应依赖领域 Review Policy。

Scanner 通过公开的 `is_ignored_path()` 和 `iter_project_files()` 统一过滤 `target`、`build`、`.gradle`、`out`、`node_modules` 等生成或依赖目录；Analyzer 应复用这两个边界，保证语言统计、文件列表和实际分析集合一致。

注册和选择由 `AnalyzerRegistry` 负责：

```python
registry = AnalyzerRegistry.with_defaults()
analyzer = registry.select(ProjectScanner.scan(project_root))
model = analyzer.analyze(project_root, project_id=7)
```

默认 Registry 现在包含 `JavaAnalyzer`、`GradleJavaAnalyzer`、`PythonAnalyzer` 和 `FrontendAnalyzer`；`InterviewService` 使用同一个默认组合，因此 Service/API 的项目分析也支持这些输入。也可以显式传入 Analyzer 列表覆盖默认组合。注册契约要求：

- `analyzer_id` 非空且唯一；必须提供可调用的 `supports()` 和 `analyze()`。
- 恰好一个 Analyzer 支持 Scanner structure 时才选择它。
- 没有支持者时抛出 `LookupError`，消息包含 Scanner structure。
- 多个支持者时抛出 `ValueError`，消息列出所有冲突的 `analyzer_id`；Registry 不猜测优先级，也不静默覆盖。
- 增加 Analyzer 只需注册新插件，不修改 `ReviewPolicy`、`InterviewAgent` 或前端领域流程。

如果两个插件的识别边界确实重叠，应收窄 `supports()`，或把它们作为互斥的显式注册组合。不要在 Registry 中添加按名称、语言或注册顺序的隐式优先级。

## 2. UniversalProjectModel 输出要求

Analyzer 应优先填充以下通用字段：

- `identity`：名称、`artifact_type`、目标或描述；不得把领域问题写入 identity。
- `structure`：模块、目录、清单或源文件等结构节点。
- `technologies`：工具、依赖和版本事实。
- `components`、`relations`、`flows`：可引用的组件、依赖关系和流程事实。
- `evidence`：每个事实的来源路径、定位、摘录、类型和置信度。
- `metadata`：仅放 JSON-safe 的输入摘要；不要放不可序列化的 Path、AST 或运行时对象。

组件、关系、流程和主题通过 `evidence_ids` 回指 `Evidence.id`。`source_path` 必须是相对于 artifact root 的 POSIX 路径，并且应存在于 Scanner 的文件列表中。Analyzer 不生成问题、不调用 `QuestionGenerator`，也不写入领域评价、候选人能力画像或带领域含义的排序分数；没有明确评审策略时不生成 `topics`。

组件 ID 必须包含规范化 source path、符号名称和源码行/位置；同名符号也必须得到不同 ID。用于 ID 的可读清洗结果必须结合稳定摘要，避免 `a/b.ts` 与 `a-b.ts` 碰撞。关系去重至少使用 source path 与 target 的组合，不能因为不同源文件调用同一个 URL 而丢失关系。解析失败必须保留来源上下文并抛出带路径/行号的错误，不能静默生成不完整模型。

## 3. PythonAnalyzer

`PythonAnalyzer` 的选择条件是项目内存在非忽略目录的 Python 源文件，且没有根级 `package.json`。因此 source-only 项目（例如 `src/app.py`）可以被识别，嵌套前端目录中的 `package.json` 不会排除 Python 项目。它是轻量 Adapter，不执行代码、不安装依赖、不引入 Python AST 第三方库：

- 用标准库 `ast` 提取模块、顶层类、函数和 `main`/`__main__` 入口。
- 入口记录使用 source path 与源码位置作为稳定 key；多入口 Flow 的 `evidence_ids` 覆盖每个入口，不能只引用第一个入口。
- 识别 `requirements.txt`、`requirements-dev.txt`、`pyproject.toml`、`setup.py`、`setup.cfg` 和 `Pipfile` 等依赖文件。
- 将依赖文件和解析出的包名作为通用技术/依赖事实，并为源码符号和依赖清单保留 Evidence。
- 输出 `artifact_type="python_project"`，不输出 Java/Spring 专属字段，也不产生面试问题。

当前解析是保守的文本/AST 提取：复杂动态导入、代码执行后才出现的依赖和完整 TOML/INI 语义不在 MVP 范围内。

## 4. FrontendAnalyzer

`FrontendAnalyzer` 的选择条件是根级 `package.json` 加上 JavaScript/TypeScript 源文件；嵌套 `package.json` 和 `node_modules` 不作为项目入口或源码来源。它只使用标准库 JSON 和正则扫描，不依赖 React、Vue、Angular 或任何框架专用库：

根 `package.json` 的 JSON 顶层必须是 object；Scanner 以 `manifest_status=invalid_json` 区分语法错误，以 `manifest_status=invalid_shape` 区分数组、null 或其他顶层值。两者都会被 Registry 排除，直接分析时抛出包含 manifest 路径的准确 `ValueError`。

- 从 JS/TS 源文件提取函数、类和常见导出组件名称。
- 提取 `path`/`route` 字面量作为路由 Flow。
- 同一路由在不同源码 occurrence 出现时分别生成 Flow 和 Evidence；显示名称可以重复，但来源不能合并丢失。
- 提取 `fetch`、`axios.*` 和常见 HTTP 方法调用的 URL 作为 API call Relation。
- 从 `package.json` 的依赖和 scripts 识别依赖、版本和常见构建工具（例如 Vite、Webpack、Rollup）。
- 输出 `artifact_type="frontend_project"`，所有事实都关联清单或源文件 Evidence，不复制 Java 解析逻辑，也不生成面试问题。

该 Adapter 不试图构建完整 JavaScript AST、解析动态路由、执行 bundler 或推断框架运行时行为；无法从静态文件确认的内容应保持缺失，而不是猜测。

## 5. 未来 MediaArtifact 契约

视频、设计和其他媒体输入暂不实现复杂解析。未来可增加独立的 `MediaArtifact` Analyzer，仍遵循 `supports()`/`analyze()` 和 `UniversalProjectModel` 边界。建议输入 manifest 至少定义：

```json
{
  "artifact_type": "video|design|mixed_media",
  "assets": [{"path": "", "mime_type": "", "duration_ms": 0}],
  "timeline": [{"start_ms": 0, "end_ms": 0, "asset": "", "label": ""}],
  "scripts": [{"path": "", "language": "", "version": ""}],
  "metadata": {}
}
```

未来 Media Analyzer 应把素材、时间线、脚本、场景或画板作为结构事实，把 manifest、时间码、页码或文件路径作为 Evidence 来源。它不应迫使 `ReviewPolicy` 了解视频编码、设计工具或媒体格式；新增领域评审模式时，同样只扩展 Review Policy 和问题/评价策略。
