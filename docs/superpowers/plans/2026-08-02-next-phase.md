# Project Review Expansion and Upload Hardening Implementation Plan

> **For agentic workers:** Execute these tasks serially. Each task must pass its focused tests before the next task starts.

**Goal:** 在现有 MVP 基础上依次实现 Portfolio Review、Defense Review、Gradle Java Analyzer，并为服务端 ZIP descriptor 增加明确的上传配额。

**Architecture:** 继续复用 `ReviewPolicy`、`AnalyzerRegistry`、`ProjectScanner`、`ProjectSource` 和现有 SQLite/HTTP 边界，不引入新框架或依赖。每个 Review Policy 只改变主题选择和追问方向；Gradle 作为独立 Analyzer 加入 Registry；上传配额在 descriptor 到 `ZipSource` 的转换边界完成。

**Execution order:** Portfolio Review → Defense Review → Gradle Analyzer → ZIP upload quota hardening.

---

## Task 1: Portfolio Review

实现可通过 `policy_for_mode(ReviewMode.PORTFOLIO_REVIEW)` 获取的策略，并让会话可以显式选择 review mode。策略应优先选择有证据的组件/流程/技术主题，追问方向使用作品目标、决策取舍和结果影响；保持 Technical Interview 的默认行为不变。

**验证：** 新增策略选择、方向规则和 HTTP/Service mode 传递测试；运行 `python -m unittest tests.test_review_policy tests.test_service_api -v`。

## Task 2: Defense Review

实现 `policy_for_mode(ReviewMode.DEFENSE_REVIEW)`，优先围绕项目目标、关键决策、风险与证据链提问；追问方向使用事实澄清、设计论证和风险防御。与 Portfolio Review 共享通用 helper，不复制 Analyzer 或 InterviewAgent。

**验证：** 新增 Defense 策略和会话 mode 持久化测试；运行相关 Review/Service/SQLite 测试及全量后端测试。

## Task 3: Gradle Java Analyzer

新增独立 Gradle Java Analyzer，支持根级 `build.gradle` 或 `build.gradle.kts` 与 Java 源文件，复用 Java/Spring 事实提取规则，至少提取构建工具、Java/Spring 组件、依赖、HTTP flow、事务主题和证据。Registry 必须在 Maven 与 Gradle 之间确定性选择，不能让 Java Analyzer 猜测或覆盖 Gradle。

**验证：** 新增 Gradle fixture、Scanner/Registry/Analyzer 测试；运行 `python -m unittest tests.test_project_scanner tests.test_java_analyzer tests.test_analyzer_registry -v`。

## Task 4: ZIP Upload Quota Hardening

在 `POST /projects/upload` 的 ZIP descriptor 中支持可选且有上限的 `max_total_size`、`max_file_size`、`max_files`，使用服务端默认上限防止请求绕过配额；拒绝非法、负数和超过服务端上限的值，并在失败记录中保留可读错误。Folder JSON 上传行为保持不变。

**验证：** 新增 HTTP descriptor 配额和越界测试；运行完整后端测试、前端测试和 `npm run build`，并同步 README/架构/Demo 的实际边界。

## 执行状态（2026-08-02）

四项任务已按顺序完成并通过规格/代码质量审查：Portfolio Review、Defense Review、Gradle Java Analyzer、ZIP descriptor 上传配额加固。

最终验证结果：后端 200 项测试通过；前端 `npm test` 的 25 项测试通过；`npm run build` 成功并生成 Sites 所需产物。当前仍不包含 multipart、Git URL、LLM、RAG 或远程存储。

## 最终验收

```powershell
python -m unittest discover -s tests -v
cd frontend
npm test
npm run build
```
