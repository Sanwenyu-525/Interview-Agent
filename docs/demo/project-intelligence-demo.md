# Project Intelligence Engine 演示

本文演示当前代码真实支持的完整链路：将现有 Java fixture 作为 folder source 上传，得到 `UniversalProjectModel`，转换成面试兼容的 `ProjectKnowledge`，创建技术面试会话，提交回答并观察带证据的评价和追问方向。

## 1. 准备

在仓库根目录执行：

```powershell
python -m unittest tests.test_project_analysis_api -v
python -m unittest tests.test_analyzer_registry tests.test_review_policy tests.test_memory -v
```

启动 API。建议在单独的 PowerShell 窗口使用临时数据库，避免污染仓库根目录的默认数据库：

```powershell
$env:INTERVIEW_AGENT_DB = Join-Path $env:TEMP "interview-agent-demo.db"
python -m interview_agent.server
```

服务默认地址为 `http://127.0.0.1:8000`。另开一个 PowerShell 窗口，仍位于仓库根目录。

## 2. 上传并分析 Java 项目

HTTP API 不接收 multipart 文件；folder source 的文件内容必须作为 JSON 字符串发送。下面的命令从已有 `tests/fixtures/java_project` 读取文本并生成请求体，因此请求与实际 API 字段一致，也不会手工伪造源码内容：

```powershell
$fixture = (Resolve-Path "tests/fixtures/java_project").Path
$files = Get-ChildItem -LiteralPath $fixture -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($fixture.Length).TrimStart('\').Replace('\', '/')
    @{
        path = $relative
        content = Get-Content -LiteralPath $_.FullName -Raw -Encoding utf8
    }
}
$upload = @{
    project_id = 9001
    project_name = "demo-order-system"
    source = @{
        type = "folder"
        files = @($files)
    }
} | ConvertTo-Json -Depth 10

$analysis = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/projects/upload" `
    -Method Post `
    -ContentType "application/json" `
    -Body $upload
$analysis | ConvertTo-Json -Depth 10
```

成功响应为 HTTP `201`，关键字段形状如下：

```json
{
  "project_id": 9001,
  "project_name": "demo-order-system",
  "source_type": "folder",
  "workspace_path": ".../workspace/projects/9001/source",
  "analysis_status": "READY",
  "schema_version": 1,
  "analyzer_id": "java",
  "universal_model": {
    "project_id": 9001,
    "identity": {"name": "order-service", "artifact_type": "java_backend"},
    "technologies": [],
    "components": [],
    "relations": [],
    "flows": [],
    "insights": [],
    "evidence": [],
    "topics": [],
    "dependencies": {},
    "metadata": {}
  },
  "knowledge": {
    "project_id": 9001,
    "project_name": "demo-order-system",
    "topics": [],
    "components": {},
    "evidence": {},
    "dependencies": {},
    "weaknesses": []
  },
  "error": ""
}
```

上面的数组和字典在真实响应中会填充。对当前 fixture，已验证的事实包括：`analyzer_id` 为 `java`；技术事实包含 `Spring Boot`、`Spring Web`、`Spring Security`、`MySQL`、`Redis`、`Kafka`；组件包含 `OrderController`、`OrderService`、`OrderRepository`；流程包含 `GET /orders/{id}`、`POST /orders`、`GET /orders/internal`；主题包含 `HTTP API` 和 `Transaction`。具体 evidence ID 是根据文件、行号和符号生成的稳定字符串，不应在客户端硬编码。

查询状态和兼容知识：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/projects/9001/status" |
    ConvertTo-Json -Depth 10

Invoke-RestMethod "http://127.0.0.1:8000/projects/9001/knowledge" |
    ConvertTo-Json -Depth 10
```

`status` 返回完整 `ProjectAnalysis`；`knowledge` 只返回面试流程当前使用的 `ProjectKnowledge`，字段是 `project_id`、`project_name`、`topics`、`components`、`evidence`、`dependencies` 和 `weaknesses`。

前端 Evidence-first 页面读取同一组 API。启动前端开发服务器时，在 `frontend` 目录显式设置真实启动契约中的 `VITE_PROJECT_ID`、`VITE_CANDIDATE_ID` 和 `VITE_API_BASE_URL`：

```powershell
cd frontend
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$env:VITE_PROJECT_ID = "9001"
$env:VITE_CANDIDATE_ID = "candidate-demo"
npm run dev
```

只有开发模式（Vite 的 `import.meta.env.DEV` 为真）且显式设置 `VITE_ENABLE_FIXTURE_FALLBACK=true`（PowerShell 写法为 `$env:VITE_ENABLE_FIXTURE_FALLBACK = "true"`）时，前端才允许在没有 `VITE_PROJECT_ID` 的情况下启用本地 fixture fallback；生产构建不会因为该变量自动启用 fallback。要验证完整的项目理解链路，应先完成本节上传，再设置 `VITE_PROJECT_ID`。

## 3. 创建会话、回答和追问

```powershell
$session = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/sessions" `
    -Method Post `
    -ContentType "application/json" `
    -Body (@{
        project_id = 9001
        candidate_id = "candidate-demo"
    } | ConvertTo-Json)

$session | ConvertTo-Json -Depth 10
$sessionId = $session.session_id

$answer = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/sessions/$sessionId/answers" `
    -Method Post `
    -ContentType "application/json" `
    -Body (@{
        answer = "OrderService 调用 OrderRepository 保存订单；事务失败时回滚。"
    } | ConvertTo-Json)

$answer | ConvertTo-Json -Depth 10
```

初始 state 至少包含 `session_id` 外的 `project_id`、`current_topic`、`level`、`question`、`question_evidence_ids`、`status` 和 `candidate_id`。当前内置规则在这个 fixture 上初始选择 `HTTP API`，问题为 `你的项目为什么使用HTTP API？`。使用上面的回答时，当前默认 evaluator 已验证返回 `score: 60`、`next_direction: "deep"`，并在 `evaluation.evidence_ids` 中保留对应 HTTP flow 的真实 evidence ID。这个结果来自当前本地规则，不代表未来 LLM 评价的固定文案。

回答结果还会带：

```json
{
  "evaluation": {
    "score": 60,
    "strengths": [],
    "weaknesses": ["缺少HTTP API的项目细节或权衡说明"],
    "feedback": "...",
    "reference_answer": "非 100 分回答会返回基于项目证据的参考答案；满分时为空字符串",
    "evidence_ids": ["e-flow-..."],
    "covered_points": [],
    "missing_points": []
  },
  "next_direction": "deep",
  "history": []
}
```

实际 `history` 会包含本次 `AnswerRecord`；示例中的省略号只是文档缩写，真实 JSON 不会返回 `...` 字符串。

读取会话：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/sessions/$sessionId" |
    ConvertTo-Json -Depth 10
```

停止并用同一个 `INTERVIEW_AGENT_DB` 重启服务后，再执行上面的 GET，可以验证项目分析记录和 session JSON 从 SQLite 恢复。Candidate Profile Store 也使用相同 SQLite 数据库保存 `candidate_id`、主题 score/trend、recent score、sample count、weaknesses 和 profile `schema_version`；当前 HTTP API 没有单独的 profile 查询端点。

## 4. ZIP source 变体

如果项目已经打包为服务进程本机可访问的 ZIP，可以使用：

```powershell
$zip = Join-Path $env:TEMP "demo-order-system.zip"
Compress-Archive -Path "tests/fixtures/java_project/*" -DestinationPath $zip -Force

$zipUpload = @{
    project_id = 9002
    project_name = "demo-order-system-zip"
    source = @{
        type = "zip"
        source_path = $zip
        # 可省略；省略时使用服务端默认配额
        max_total_size = 100 * 1024 * 1024
        max_file_size = 10 * 1024 * 1024
        max_files = 10000
    }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/projects/upload" `
    -Method Post `
    -ContentType "application/json" `
    -Body $zipUpload |
    ConvertTo-Json -Depth 10
```

这里的 `source_path` 是服务器本地路径，不是浏览器上传后的临时文件 URL。ZIP descriptor 省略配额字段时，服务端默认限制为单文件解压大小 `10 MiB`、总解压大小 `100 MiB`、文件数 `10000`；字段也可以传入更小的非负 JSON 整数，但不能传负数、浮点数、字符串或超过默认上限的值。ZIP 超限会返回可读错误，并在项目状态中保留 `FAILED` 与 `error`；Folder JSON 上传行为不受这些 ZIP 字段影响。ZIP 和 folder 都会进入相同的 Workspace 与 Analyzer 链路。

## 5. 当前限制与可解释失败

- Java 分析支持 Maven 和 Gradle：分别要求根级 `pom.xml`，或根级 `build.gradle`/`build.gradle.kts`，并存在 Java 源文件；两者由独立 Analyzer 确定性选择。
- Python 和 Frontend 已有最小 Analyzer，但不是完整语言/框架语义分析：Python 使用标准库 AST 和依赖文件扫描，Frontend 使用 JSON/正则静态扫描。
- 没有 Git URL、multipart 上传、远程存储或自动下载依赖；ZIP 必须是服务进程可读的本地路径，folder 内容必须是 JSON 字符串。
- `ProjectScanner` 会忽略 `target`、`build`、`.gradle`、`out`、`node_modules`。Java 规则只覆盖常见 Spring 注解、字段依赖、HTTP mapping、事务标记和有限 POM 技术映射，不保证完整调用图、运行时行为或业务语义。
- 路径安全检查会拒绝 Zip Slip、绝对路径、符号链接、重复/冲突成员和 Workspace 外写入。服务端 ZIP descriptor 默认限制单文件解压大小 `10 MiB`、总解压大小 `100 MiB`、文件数 `10000`；`max_total_size`、`max_file_size`、`max_files` 可选但只能传非负整数且不能超过这些上限。直接调用 `ZipSource` 的显式限制行为保持不变。
- `technical_interview`、`portfolio_review` 和 `defense_review` 均已实现主题选择与分数驱动的追问方向，并共享同一项目证据和会话流程。
- 评分方向是确定性本地规则：低于 60 为 `basic`，60–79 为 `deep`，80 及以上为 `architecture`。真实 LLM、RAG、LangGraph 和向量检索尚未接入。
- SQLite 当前项目分析 schema version 为 `1`，面试者画像 payload version 为 `1`；读取会校验版本和项目 ID，旧的基础 `ProjectKnowledge` 记录保留兼容读取能力。

这些限制是当前 MVP 的实际边界，不应在 UI 或文档中包装成已经完成的能力。未来增加视频/设计 Analyzer 或 Portfolio/Defense Policy 时，仍应保持证据、可序列化和可回溯的接口。
## 6. 前端目录上传入口

启动后端和前端后，未配置 `VITE_PROJECT_ID` 且未启用 fixture fallback 时，首屏仍然是 Agent 聊天工作台。点击聊天输入框左侧的 `+` 附件按钮，在菜单中选择项目目录。目录选择器使用 `input[webkitdirectory]`，浏览器逐个读取目录中的文本文件，生成并发送 Folder JSON descriptor：

```json
{
  "project_id": 1733200000000,
  "project_name": "demo-order-system",
  "source": {
    "type": "folder",
    "files": [{ "path": "pom.xml", "content": "<project />" }]
  }
}
```

上传成功后，前端按 `status → knowledge → startInterviewSession` 的顺序确认分析结果并自动进入面试，项目分析结果回到 Agent 聊天流；面试者 ID 默认是 `VITE_CANDIDATE_ID` 或 `default`。生成的数字 `project_id` 保存在浏览器 `localStorage`，刷新后可以恢复最近上传的项目。浏览器入口支持最多 10000 个文件、单文件 10MB、总文本量 100MB。

本浏览器入口只实现目录 Folder JSON 上传。ZIP、multipart 和二进制文件上传仍不支持；本文第 4 节的 `ZipSource` 仅是后端服务进程可访问本地 ZIP 时的独立 API 示例，不代表前端目录选择器支持 ZIP。
