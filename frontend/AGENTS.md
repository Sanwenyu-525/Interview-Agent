# Prototype Instructions

## 规范入口

本目录除遵守根目录 `AGENTS.md` 外，还必须遵守 `docs/standards/frontend.md`。HTTP 字段、状态码和错误结构以 `docs/api/openapi.json` 为准；持久原型交互决策继续记录在本文件。

## 当前产品交互决策

- 面试工作台以 Agent 聊天流和底部消息输入框为主，不把项目上传做成首屏独立页面。
- 项目目录上传通过聊天输入框左侧的 `+` 附件菜单触发；上传完成后以 Agent/系统消息回到当前聊天流。
- `+` 菜单同时负责选择文件夹作为当前工作区和在工作区内新建任务；任务对应一个可恢复的 Agent 会话，任务索引按项目持久化。
- 工作区选择统一使用浏览器目录上传控件 `webkitdirectory`，保持浏览器预览和 Tauri 桌面版的行为一致。
- 聊天消息列表独立滚动，输入区固定在工作台底部；任务切换不能改变当前工作区的项目证据上下文。
- 桌面面试工作台的项目上下文栏和证据栏可通过聊天区两侧的分隔条拖拽调整宽度；分隔条必须支持键盘方向键和双击恢复默认宽度。
- 右侧证据栏可收起为窄栏并随时展开；窄屏下保持抽屉交互，不显示桌面拖拽条。
- “最近会话”以服务端 Session Store 为事实源，支持创建、读取、重命名和删除；删除前需要确认，删除当前会话后切换到下一条可用会话或新会话页。
- 面试结构中的主题是新会话入口；点击非当前主题时创建以该主题为首题方向的独立会话，不修改当前会话中的题目或回答。
- “岗位准备”是独立主页面：一个候选人可维护多个目标岗位，每个岗位可关联多个项目并拥有独立题库；由岗位题目发起的练习会话必须保留岗位和题目关联。
- “简历库”采用同屏两栏 master-detail：左栏 340px 简历列表（顶部 CANDIDATE CONTEXT + 上传简历按钮 + 搜索框 + 列表），右栏展示选中简历详情；删除操作保留在详情页头部，不做列表跳详情页。
- JD 首版输入支持粘贴或导入 UTF-8 文本文件；图片和 PDF OCR 不属于当前浏览器输入范围，页面必须明确提示限制。
- 项目资料中的结构树需要保持可滚动并提供足够展示高度；浏览器目录上传当前支持最多 10000 个文件、单文件 10MB、总文本量 100MB，仍只接收 UTF-8 文本文件。

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## 上传等待反馈

项目上传不能只依靠按钮禁用态反馈。附件菜单必须展示读取文件、上传项目、分析项目和建立会话等阶段状态，并在失败时保留可读的错误信息。

## 应用级大模型设置

大模型配置属于应用级设置，不绑定单个项目；前端只提交配置表单并展示脱敏状态，API Key 由后端保存、使用和测试，不能回传到前端。
## 当前原型设计决策

- 工作台借鉴 Codex 的空间组织方式：左侧导航与项目/任务上下文，中间面试对话，右侧按需打开证据与评价；不复制 Codex 的聊天语义或视觉品牌。
- 面试 Agent 的主视觉焦点是“项目证据驱动的复盘”，因此上传、项目结构、当前问题、代码证据和能力反馈必须留在同一工作台上下文中。
- 采用浅灰工作台、柔和表面层级和克制的铜色强调，输入区贴近对话底部；空项目状态也必须保留完整的 Agent 对话壳，不单独退化成上传页面。
- 工作台层次优先通过表面明度、留白、当前状态边界和轻量阴影表达；当前任务、可切换主题与最近会话需要有清晰的主次关系，不引入新的强调色。
- 不用密集横线、竖线或重复边框组织普通内容，避免界面呈现表格网格感；优先使用留白、标题层级、缩进、gutter 和表面明度分组。
- 分栏拖拽条、独立滚动区边界、代码/数据基准和焦点状态可以保留语义线；可见线保持弱对比，交互命中区通过透明区域扩大。
- 面试工作台的智能体面板（对话流 + 输入区）是独立圆角卡片：白色表面 + 圆角 16px + 柔和双层阴影，浮在比纸色略深的画布（#f2efe9）上；空项目状态同样套用卡片外壳。卡片内部不做二次边框包裹。
