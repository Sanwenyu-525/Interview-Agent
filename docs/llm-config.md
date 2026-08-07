# LLM 配置

后端默认使用本地规则引擎，不需要网络或 API Key。需要接入 OpenAI、Agnes、DeepSeek 或其他 OpenAI 兼容服务时，设置以下环境变量：

```powershell
$env:LLM_PROVIDER="openai_compatible"
$env:LLM_BASE_URL="https://apihub.agnes-ai.com/v1"
$env:LLM_API_KEY="your-api-key"
$env:LLM_MODEL="your-model-name"
$env:LLM_API_MODE="chat_completions"
python -m interview_agent.server
```

可选配置：

```powershell
$env:LLM_TIMEOUT_SECONDS="60"
$env:LLM_TEMPERATURE="0.2"
```

`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL` 需要同时配置。API Key 只由后端读取，不能写入前端环境变量或提交到项目文件。

当前 LLM 负责生成项目面试问题、评价回答和非满分回答的参考答案；项目知识仍来自已有的 Universal Project Model、ProjectKnowledge 和证据引用。LLM 上游仍使用 Chat Completions，应用通过 `/sessions/{session_id}/answers/stream` 将评价阶段、参考答案片段和最终会话状态以 SSE 返回。

如果不配置 `LLM_PROVIDER=openai_compatible`，服务会继续使用规则引擎，便于离线开发和测试。

## 通过应用设置配置

启动前端和后端后，进入左侧的“应用设置”，可以直接填写服务类型、Base URL、模型名称、API Key、温度和超时时间。保存请求由后端处理，并写入当前应用使用的 SQLite 数据库；页面只会收到 `api_key_set`，不会读取或显示原始 API Key。

“测试连接”只验证当前表单配置，不会保存配置；“保存配置”会立即替换当前后端 Agent，重启后继续使用已保存的配置。

## 已配置模型档案

应用设置中的“已配置的大模型”支持多个配置档案：

- 可以新增、编辑、删除档案，也可以把任意档案设为当前使用的模型。
- “测试”只测试已保存档案，不会改变当前激活档案；连接失败时不会切换运行时 Agent。
- 删除当前档案后，系统会回退到本地规则引擎；其他档案仍会保留。
- API Key 只保存在后端 SQLite 中，列表和详情接口只返回 `api_key_set`，不会返回原始密钥。
- 旧版本的单一 `llm_config` 配置会在读取时兼容为一个档案，现有配置无需手动重填。

对应接口为 `GET/POST /settings/llm/profiles`、`PUT/DELETE /settings/llm/profiles/{id}`、`POST /settings/llm/profiles/{id}/activate` 和 `POST /settings/llm/profiles/{id}/test`。

## 模型下拉框与在线检测

模型下拉框采用“在线优先、预设兜底”策略。选择 Agnes 或 DeepSeek 后，页面会自动请求兼容接口的 `/models`；接口返回的模型排在前面，并与内置预设模型合并去重。网络不可用、鉴权失败或接口没有返回模型时，仍然可以从预设模型中选择并保存。

当前内置预设包括 Agnes 的 `Agnes-2.0-Flash`、`Agnes-2.5-Flash`、`Agnes-2.5-Pro-Alpha`，以及 DeepSeek 的 `deepseek-v4-flash`、`deepseek-v4-pro`。预设只是兜底，实际可用模型以服务商接口返回结果为准。DeepSeek 的模型列表和更新以[官方模型列表](https://api-docs.deepseek.com/api/list-models)及[官方更新日志](https://api-docs.deepseek.com/updates/)为准。

## 自动启停本地开发服务

项目根目录的 `dev.bat` 可在启动/停止前后端、查看状态和日志之间切换，并在启动前清理 8000 和 4173 端口上的本项目旧进程：

```bat
dev.bat              rem 打开交互菜单（双击默认）：1 桌面版 2 浏览器版 3 停止 4 状态 5 日志 0 退出
dev.bat desktop      rem 启动 Tauri 桌面端
dev.bat start        rem 仅启动后端和浏览器前端
dev.bat stop
dev.bat restart
dev.bat status
dev.bat logs
```

后端地址为 `http://127.0.0.1:8000`，前端地址为 `http://127.0.0.1:4173`。运行日志保存在项目根目录的 `.runtime` 文件夹中。
