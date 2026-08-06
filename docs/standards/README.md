# 前后端规范体系

本目录定义 Interview Agent 的可执行工程规范。它补充根目录 `AGENTS.md` 的产品与架构约束，并把“设计意图”落实为前后端共同遵守的契约、质量门禁和变更流程。

## 1. 规范地图

| 主题 | 唯一事实源 |
| --- | --- |
| 产品定位、领域边界、扩展原则 | 根目录 `AGENTS.md` |
| HTTP 路径、方法、请求、响应、错误结构 | `docs/api/openapi.json` |
| 后端分层、校验、持久化、安全与运行约束 | `docs/standards/backend.md` |
| 前端架构、设计系统、交互状态与无障碍 | `docs/standards/frontend.md` |
| Analyzer 数据模型与扩展规则 | `docs/architecture/project-intelligence.md`、`docs/architecture/analyzer-extension-guide.md` |
| 当前支持能力和启动方式 | `README.md` |
| 持久原型交互决策 | `frontend/AGENTS.md` |

发生冲突时，机器可读契约优先于接口示例；领域边界优先于局部实现便利。代码改变当前能力时，必须在同一变更中更新对应事实源。

## 2. 完成定义

一个前后端功能只有同时满足以下条件才算完成：

1. 业务归属明确：分析、策略、评分和记忆属于后端，前端只负责展示与交互。
2. HTTP 变化先更新 OpenAPI；前端不得依赖契约外字段。
3. 请求具有输入校验，错误使用统一错误结构，异步等待具有可见状态。
4. 新增 UI 覆盖初始、加载、空、成功、失败和禁用等适用状态。
5. 新增交互支持键盘操作、可见焦点和可读辅助文本。
6. 业务状态可序列化；持久化结构变化有 schema version 与兼容策略。
7. 受影响层测试通过；跨层契约变化同时运行前后端测试。
8. 当前能力、限制、演示和规范没有相互矛盾的描述。

## 3. 变更流程

### API 变更

1. 修改 `docs/api/openapi.json`。
2. 修改后端处理和测试。
3. 修改 `frontend/src/api.js` 与前端测试。
4. 运行 `python -m unittest tests.test_api_contract -v`、后端受影响测试和 `npm run test:api`。

已有字段只能保持语义或以可选方式扩展。删除字段、改变类型、改变枚举含义或改变成功状态码属于破坏性变更；在当前无版本路径阶段不得直接进行，必须先设计迁移窗口或新版本路径。

### UI 变更

1. 先确认是否改变持久交互决策；若改变，更新 `frontend/AGENTS.md`。
2. 复用现有 token 和组件形态；新增 token 必须在前端规范中说明语义。
3. 验证桌面、窄屏和移动断点，以及键盘焦点与错误状态。
4. 运行 `npm test` 和 `npm run build`；视觉变化更新 Design QA 证据。

### 领域模型或持久化变更

1. 明确模型所属层，避免把 Analyzer 差异写入 Review Policy 或 UI。
2. 修改 schema version、序列化/反序列化和旧版本读取策略。
3. 增加往返序列化、旧数据读取、未知版本拒绝和并发冲突测试。

## 4. 质量门禁

仓库当前最低门禁：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q interview_agent
cd frontend
npm test
npm run build
```

涉及 Tauri 配置或命令时，再运行：

```powershell
cargo build --manifest-path src-tauri/Cargo.toml
```

测试通过证明实现满足已编码的约束，不替代 API、设计、安全和运行规范本身。

## 5. 文档治理

- `README.md` 只描述当前真实可用能力，不写尚未实现的承诺。
- 架构文档解释原因和边界，不复制容易漂移的完整端点清单。
- OpenAPI 负责字段级事实；示例文档只演示典型链路。
- 计划文档记录历史决策，不作为当前契约。
- 每次新增 Analyzer、Review Policy、HTTP 端点或 UI 主流程，都必须检查规范地图中对应文件。

