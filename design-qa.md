# Design QA

## 对照目标

- Source visual truth：`D:\Develop\Interview Agent\output\design-qa\full-redesign\source-01.png` 至 `source-07.png`
- Implementation screenshots：
  - `01-empty-import.png`
  - `impl-02.png` 至 `impl-07.png`
- 截图目录：`D:\Develop\Interview Agent\output\design-qa\full-redesign\`
- Viewport：全部对照图均为 1280 × 720 CSS px。
- Pixel dimensions：全部对照图均为 1280 × 720 px。
- Density normalization：source HTML 与 React 实现均由同一个应用内浏览器、同一个 CSS 视口直接截取；未使用缩放或二次采样。

## 状态

- 01：无项目，导入面板默认打开。
- 02：真实 Java 项目会话，当前问题与项目证据可见，暂无本题评价。
- 03：真实 Universal Project Model，概览与证据追溯可见。
- 04：真实模型配置档案，配置列表与编辑器可见。
- 05：真实项目，新建技术面试会话表单。
- 06：真实当前会话，0 次回答的空报告状态。
- 07：真实候选人画像，1 个能力主题、2 个持久化样本。

Stitch 的 06/07 参考图使用了更丰富的示例数据；实现图使用本地数据库真实状态。该差异只影响内容密度，不改变页面信息架构和组件布局。

## Findings

- 无未解决的 P0 / P1 / P2 视觉或核心可用性问题。
- [P3] 真实 06 报告当前没有回答记录，因此首屏比 Stitch 示例更稀疏。
  - Location：会话复盘报告。
  - Evidence：参考图有 8 道题与评分曲线；实现读取的当前会话为 0 次回答，显示明确空报告。
  - Classification：真实数据状态差异。不得为了视觉密度在前端伪造评分或题目。
- [P3] Stitch HTML 依赖的 Material Symbols 在离线参考页中退化为文字图标；实现使用项目已有 Phosphor 图标。
  - Location：全局导航与页面操作图标。
  - Evidence：source 截图可见 `work`、`description` 等字样；实现图标轮廓正常。
  - Classification：实现资产质量优于离线参考，不需要回退。

## 必查表面

- Fonts and typography：Manrope、Noto Sans SC 与 DM Mono 分工一致；标题、正文、标签、证据元数据层级清楚；长问题和长文件路径可换行且不撑破栏宽。
- Spacing and layout rhythm：全局导航、次级上下文、主工作区和右侧证据栏比例稳定；小圆角、细边框、扁平表面和大留白与 Stitch 一致。
- Colors and visual tokens：纸张白、象牙白、铜色强调、低饱和绿/红状态色已统一为 CSS tokens；没有多余渐变和重阴影。
- Image quality and asset fidelity：目标页面没有照片或插画资产；可见图标全部使用 Phosphor 图标库，无手绘 SVG、emoji 或占位图片。
- Copy and content：静态中文文案独立可读；项目、问题、证据、报告与画像数据来自真实后端，没有前端伪造业务结论。
- Icons and accessibility：图标风格与尺寸一致；主要按钮有语义名称，保留 `focus-visible` 与 `prefers-reduced-motion`；窄窗口证据栏有关闭和重新打开入口。

## Full-view comparison evidence

所有 7 组 source 与 implementation 均在同一个比较输入中逐组检查：

1. 01 的左侧应用导航、居中导入面板、底部输入区关系一致。
2. 02 的全局导航、面试上下文、问答工作区、证据/评价四栏一致。
3. 03 的应用导航、项目结构、项目知识、证据追溯四区一致。
4. 04 的配置档案列表与配置编辑器双栏一致。
5. 05 的 Review Modality 选择与会话范围表单双栏一致。
6. 06 的报告主区与右侧摘要栏一致；当前为空报告状态。
7. 07 的画像主区、能力矩阵与右侧趋势/薄弱点栏一致。

未发现持久控制被裁切、栏位互相覆盖、横向溢出或主要操作丢失。

## Focused region comparison evidence

未额外裁切局部图。1280 × 720 对照中，配置表单、长证据路径、问题卡、报告摘要、能力矩阵和右侧弱项列表均清晰可读，足以判断字体、间距、边框、换行和溢出状态。

## Comparison history

1. 初始 [P1]：用户截图中的面试页仍是旧的“侧栏 + 超大问题卡”结构，没有落实 Stitch 四栏。
   - Fix：增加统一全局导航与独立面试上下文栏；问题字号恢复为工作台正文尺度；证据与评价成为固定第四栏。
   - Post-fix evidence：`impl-02.png` 与 `source-02.png` 同画布对照。
2. 初始 [P1]：05、06、07 只有规划，没有真实页面和数据入口。
   - Fix：实现新建复盘、会话报告、能力画像页面；增加报告与画像只读 API，并同步 OpenAPI 和测试。
   - Post-fix evidence：`impl-05.png`、`impl-06.png`、`impl-07.png` 与对应 source 图同画布对照。
3. 第二轮 [P2]：02 的真实长 Java 路径撑开证据卡并产生横向滚动。
   - Fix：证据面板限制横向溢出，文件路径与 evidence ID 使用 `overflow-wrap:anywhere`。
   - Post-fix evidence：最终 `impl-02.png` 中路径在证据卡内换行，未破坏四栏网格。
4. 第二轮 [P2]：01 的导入入口仍是输入框上方的小型附件菜单，与 Stitch 的主导入状态不一致。
   - Fix：无项目时默认打开导入面板，并改为居中的工作区导入对话框；保留同一套上传逻辑。
   - Post-fix evidence：`01-empty-import.png` 与 `source-01.png` 同画布对照。
5. 最终同画布对照未发现新的 P0 / P1 / P2 问题。

## Primary interactions tested

- 全局导航：面试、项目资料、会话复盘、能力画像、应用设置。
- 新建复盘入口与三种 Review Mode 选择页。
- 项目导入面板默认打开、关闭和文件夹选择入口。
- 报告与画像真实 API 加载、空态和已有样本态。
- 证据栏可见、长路径换行、窄窗口抽屉控制。
- 浏览器控制台 error 日志：0。

## Implementation checklist

- [x] 01–07 全部进入 React 主应用。
- [x] 02 使用 Stitch 四栏信息架构。
- [x] 04 使用配置档案列表 + 编辑器。
- [x] 05 传递真实 `review_mode`。
- [x] 06 使用后端报告聚合结果。
- [x] 07 使用持久化 Candidate Profile。
- [x] OpenAPI、后端、前端 API 与测试同步。
- [x] 同尺寸浏览器 Design QA 与控制台检查。

## Follow-up Polish

- 待会话列表/摘要 API 完成后，可让 06 直接选择历史报告，减少空报告状态出现频率。
- 待画像证据回链 API 完成后，可从 07 的薄弱项跳回具体问题与项目证据。

final result: passed
