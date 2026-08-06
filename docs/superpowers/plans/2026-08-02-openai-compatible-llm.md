# 通用 OpenAI 兼容 LLM 接入计划

## 目标

将当前规则引擎替换为可配置的真实 LLM，同时保留规则引擎作为未配置时的本地兜底。Agnes、OpenAI、DeepSeek 和本地 OpenAI 兼容服务统一走同一客户端，不新增供应商专用适配器。

## 边界

- 第一版使用 Chat Completions 接口。
- API Key 只在后端读取。
- LLM 负责问题生成和回答评价；项目知识仍来自现有 Universal Project Model 和证据数据。
- 暂不接入向量数据库、embedding、Responses API、工具调用和流式传输。

## 执行步骤

1. 为配置读取、请求体、响应解析、问题生成和评价 JSON 编写测试。
2. 实现 `LLMConfig`、`OpenAICompatibleClient`、`LlmQuestionGenerator` 和 `LlmEvaluator`。
3. 在服务启动时按环境变量选择 LLM Agent，否则使用现有规则 Agent。
4. 运行 LLM 专项测试和后端全量测试，并补充 README 配置说明。

## 验收标准

- 配置 `LLM_PROVIDER=openai_compatible` 后，问题生成和回答评价请求发往配置的 `base_url`。
- Agnes 只需要修改配置中的 URL、Key 和模型名，不需要改业务代码。
- 返回合法 JSON 时正确映射为 `QuestionResult` / `Evaluation`。
- 返回非法 JSON 或未配置 LLM 时，系统仍能使用规则引擎或给出明确错误。
- 现有后端测试全部通过。

## 执行结果

- 已新增 `interview_agent/llm.py`，统一处理配置、Chat Completions 请求、JSON 响应和领域适配。
- 已在 `server.py` 接入环境变量选择：默认规则引擎，显式启用后使用 LLM。
- LLM 网络或响应错误通过 HTTP 502 返回，避免前端连接无响应。
- 后端全量测试：209 个通过。
