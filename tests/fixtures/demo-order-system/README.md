# Demo Order System

这是 Task9 文档使用的项目语义锚点：一个带 Maven、Spring 分层、HTTP endpoint、事务和组件依赖的订单系统示例。

本目录目前只放这份说明文件，**不是可直接被 `JavaAnalyzer` 分析的完整输入**。Java Analyzer 要求根级 `pom.xml` 和至少一个 Java 源文件；可运行的现有 Java fixture 是 [`tests/fixtures/java_project`](../java_project/)。演示文档会把它作为 `demo-order-system` 项目名上传，因此不会把不存在的源码或输出写成项目事实。

## 可验证的示例事实

现有可运行 fixture 包含：

下表中 JavaAnalyzer 的事实均指最终输出到 `UniversalProjectModel` 的内容；`application.yml` 单独标明为 ProjectScanner 的内部识别结果，不属于该模型输出。

| 文件/结构 | Scanner / JavaAnalyzer 结果 |
| --- | --- |
| `pom.xml` | `Spring Boot`、`Spring Web`、`Spring Security`、`MySQL`、`Redis`、`Kafka` |
| `OrderController` | `RestController`、`GET /orders/{id}`、`POST /orders`、`GET /orders/internal` |
| `OrderService` | `Service`、`OrderRepository` 依赖、`@Transactional` → `Transaction` 主题 |
| `OrderRepository` | `Repository` 及其被 `OrderService` 使用的关系 |
| `OrderMetrics` / `OrderConfiguration` / `Order` | `Component`、`Configuration`、`Entity` 组件 |
| `application.yml` | `ProjectScanner` 仅在内部扫描结果的 `config_files` 中识别该配置文件；当前 `JavaAnalyzer` 不会把它输出到最终的 `UniversalProjectModel`，也不会据此推断运行时数据库连接成功等事实 |

## 预期链路

```text
FolderSource
  → workspace/projects/{project_id}/source
  → ProjectScanner
  → AnalyzerRegistry.select() == JavaAnalyzer
  → UniversalProjectModel
  → project_model_to_knowledge()
  → TechnicalInterviewPolicy
```

模型中的组件、关系、流程和主题都通过 `evidence_ids` 指向 `source_path`、`locator`、`excerpt` 和 `confidence`。这是静态事实提取，不代表系统实际运行过 Maven、Spring、MySQL、Redis 或 Kafka。

完整命令、HTTP 字段、SQLite 恢复和已知限制见 [`docs/demo/project-intelligence-demo.md`](../../../docs/demo/project-intelligence-demo.md)。
