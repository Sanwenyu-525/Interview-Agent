import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const tokens = await readFile(new URL("../src/styles/tokens.css", import.meta.url), "utf8");
const primitives = await readFile(new URL("../src/styles/primitives.css", import.meta.url), "utf8");
const main = await readFile(new URL("../src/main.jsx", import.meta.url), "utf8");
const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const pages = await readFile(new URL("../src/StitchPages.jsx", import.meta.url), "utf8");
const interviewComposer = await readFile(new URL("../src/components/interview/InterviewComposer.jsx", import.meta.url), "utf8");
const interviewThread = await readFile(new URL("../src/components/interview/InterviewThread.jsx", import.meta.url), "utf8");
const evidencePanel = await readFile(new URL("../src/components/interview/EvidencePanel.jsx", import.meta.url), "utf8");
const evaluationSummary = await readFile(new URL("../src/components/interview/EvaluationSummary.jsx", import.meta.url), "utf8");
const tauriConfig = JSON.parse(await readFile(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));

test("desktop interview keeps a readable evidence-first desktop layout", () => {
  assert.match(app, /className=\{`app-shell stitch-shell view-\$\{activeView\}/);
  assert.match(app, /<PrimarySidebar/);
  assert.match(app, /<InterviewContextRail/);
  assert.match(app, /<EvidencePanel/);
  assert.match(evidencePanel, /className=\{`evidence-panel \$\{isEvidenceOpen \? "is-open" : ""\} \$\{isEvidenceCollapsed \? "is-collapsed" : ""\}`\}/);
  assert.match(css, /grid-template-columns:\s*176px var\(--context-rail-width, 216px\) minmax\(600px, 1fr\) minmax\(320px, var\(--evidence-panel-width, 372px\)\);/);
  assert.match(css, /\.view-interview \.evidence-panel\s*\{[^}]*grid-column:\s*4;/s);
});

test("responsive interview turns navigation and evidence into accessible drawers", () => {
  assert.match(app, /const \[isNavOpen, setIsNavOpen\] = useState\(false\)/);
  assert.match(app, /className="mobile-nav-trigger"/);
  assert.match(pages, /id="app-navigation"/);
  assert.match(pages, /className="mobile-nav-backdrop"/);
  assert.match(css, /@media \(min-width: 921px\) and \(max-width: 1279px\)/);
  assert.match(css, /@media \(max-width: 920px\)/);
  assert.match(css, /@media \(max-width: 620px\)/);
  assert.match(css, /\.mobile-nav-trigger\s*\{/);
  assert.match(css, /\.view-interview \.evidence-panel\.is-open\s*\{[^}]*transform: translateX\(0\)/s);
});

test("interview focus hierarchy keeps current question open and history collapsed", () => {
  assert.match(app, /<InterviewThread/);
  assert.match(interviewThread, /className="agent-message agent-message-agent current-question-message"/);
  assert.match(interviewThread, /className="message-bubble current-question-bubble"/);
  assert.match(interviewThread, /className="history-pair history-collapsed"/);
  assert.match(app, /const questionProgressLabel/);
  assert.match(css, /\.view-interview \.current-question-bubble\s*\{/);
  assert.match(css, /\.view-interview \.history-collapsed\s*\{/);
});

test("chat workspace exposes keyboard-accessible left and right resize handles", () => {
  assert.match(app, /className="workspace-resizer is-left"/);
  assert.match(app, /className="workspace-resizer is-right"/);
  assert.match(app, /role="separator"/);
  assert.match(app, /\{\.\.\.leftResize\.handlers\}/);
  assert.match(app, /\{\.\.\.rightResize\.handlers\}/);
  assert.match(css, /--context-rail-width/);
  assert.match(css, /--evidence-panel-width/);
  assert.match(css, /cursor:\s*col-resize/);
});

test("Stitch rebuild exposes setup, report, profile, project, and settings screens", () => {
  assert.match(app, /<SessionSetupView/);
  assert.match(app, /<SessionReportView/);
  assert.match(app, /<CandidateProfileView/);
  assert.match(app, /stitch-project-workspace/);
  assert.match(app, /stitch-settings-workspace/);
  assert.match(css, /\.session-setup-grid\s*\{/);
  assert.match(css, /\.report-layout\s*\{/);
  assert.match(css, /\.profile-layout\s*\{/);
});

test("position preparation has a dedicated multi-position page and question practice flow", () => {
  assert.match(app, /<PositionPreparationView/);
  assert.match(app, /activeView === "positions"/);
  assert.match(app, /handlePositionPractice/);
  assert.match(css, /\.position-layout\s*\{/);
  assert.match(css, /\.position-question-card\s*\{/);
});

test("interactive controls expose keyboard focus and reduced-motion fallbacks", () => {
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
});

test("shared design tokens and primitives remain the single visual baseline", () => {
  assert.match(tokens, /--background:\s*#f4f1eb/);
  assert.match(tokens, /--text-primary:\s*#26241f/);
  assert.match(tokens, /--space-1:\s*4px/);
  assert.match(tokens, /--control-height:\s*40px/);
  assert.match(primitives, /\.ui-button/);
  assert.match(primitives, /\.ui-field/);
  assert.match(primitives, /\.ui-status/);
  assert.match(main, /styles\/tokens\.css/);
  assert.match(main, /styles\/primitives\.css/);
});

test("management pages keep destructive actions behind accessible more menus", () => {
  assert.match(pages, /className="ui-more-menu position-more-menu"/);
  assert.match(pages, /className="ui-more-menu resume-row-menu"/);
  assert.match(pages, /className="ui-more-menu resume-detail-more-menu"/);
  assert.match(pages, /默认用于提问/);
  assert.match(app, /className="ui-more-menu settings-more-menu"/);
  assert.match(primitives, /\.ui-more-menu/);
});

test("reports and profile translate low-sample data into cautious user-facing labels", () => {
  assert.match(pages, /const isPreliminary = sampleCount < 3/);
  assert.match(pages, /样本可信度：\{confidenceLabel\}/);
  assert.match(pages, /样本不足，暂不下结论/);
  assert.match(pages, /function candidateLabel/);
  assert.match(pages, /function trendLabel/);
  assert.match(pages, /profile-bar-empty/);
  assert.match(pages, /weaknesses\.slice\(0, 3\)/);
  assert.match(css, /\.report-confidence-label/);
  assert.match(css, /\.profile-bar-empty/);
});

test("P2 motion uses bounded tokens and a reduced-motion fallback", () => {
  assert.match(tokens, /--motion-fast:\s*160ms/);
  assert.match(tokens, /--motion-standard:\s*180ms/);
  assert.match(tokens, /--motion-ease-out:\s*cubic-bezier/);
  assert.match(css, /transition:\s*[\s\S]*transform var\(--motion-standard\) var\(--motion-ease-out\)/);
  assert.match(css, /@keyframes p2-fade-in/);
  assert.match(css, /\/\* P2-1 motion:[\s\S]*@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important;/);
});

test("P2 theme uses semantic dark tokens and a persisted system preference", () => {
  assert.match(tokens, /:root\[data-theme="dark"\]/);
  assert.match(tokens, /--background:\s*#171815/);
  assert.match(tokens, /--surface:\s*#22231f/);
  assert.match(tokens, /--text-primary:\s*#f4f1e9/);
  assert.match(tokens, /--primary:\s*#d89258/);
  assert.match(app, /THEME_STORAGE_KEY/);
  assert.match(app, /readThemePreference/);
  assert.match(app, /prefers-color-scheme: dark/);
  assert.match(app, /document\.documentElement\.dataset\.theme/);
  assert.match(app, /role="radiogroup" aria-label="选择界面主题"/);
  assert.match(app, /跟随系统/);
  assert.match(app, /label: "深色"/);
  assert.match(css, /\.theme-control-options/);
  assert.match(css, /--code-surface/);
});

test("P2 profile visualization only enables a radar summary with reliable dimensions", () => {
  assert.match(pages, /function CapabilityRadar/);
  assert.match(pages, /item\.sample_count >= 3 && item\.trend !== "new"/);
  assert.match(pages, /const canShowRadar = stableSkills\.length >= 5/);
  assert.match(pages, /稳定能力分布/);
  assert.match(pages, /详细分数、样本数与证据仍以能力矩阵为准/);
  assert.match(css, /\.profile-radar\s*\{/);
  assert.match(css, /\.profile-radar-summary\s+li/);
});

test("desktop layout uses the center workspace as the primary scroll container", () => {
  assert.match(app, /<PrimarySidebar/);
  assert.match(css, /\.stitch-primary-sidebar\s*\{[^}]*grid-column:\s*1;/s);
  assert.match(css, /\.stitch-sidebar-footer\s*\{[^}]*border-top:/s);
  assert.match(css, /\.workspace\s*\{[^}]*overflow-y:\s*auto;/s);
  assert.match(css, /\.secondary-workspace\s*\{[^}]*grid-column:\s*2;/s);
});

test("interview composer stays outside the message scroll area", () => {
  assert.match(css, /\.agent-message-list\s*\{[^}]*overflow-y:\s*auto;/s);
  assert.match(css, /\.chat-composer-wrap\s*\{[^}]*flex:\s*0 0 auto;/s);
  assert.match(css, /\.interview-workspace\s*\{[^}]*display:\s*flex;[^}]*overflow:\s*hidden;/s);
});

test("interview composer uses a compact borderless submit footer", () => {
  assert.match(css, /\.chat-composer-footer\s*\{[^}]*border-top:\s*0;/s);
  assert.match(css, /\.view-interview \.composer-submit\s*\{[^}]*min-width:\s*112px;[^}]*min-height:\s*32px;/s);
  assert.match(css, /\.chat-composer textarea\s*\{[^}]*resize:\s*none;/s);
  assert.doesNotMatch(css, /\.composer-tool-button/);
  assert.match(interviewComposer, /<ArrowUp size=\{18\} weight="bold" \/>/);
});

test("interview feedback keeps process and evaluation hierarchy compact", () => {
  assert.match(css, /\.process-details\s*\{/);
  assert.match(css, /\.history-evaluation\s*\{/);
  assert.match(css, /\.streaming-message\s+\.process-details/);
  assert.match(evaluationSummary, /className="evaluation-section"/);
});

test("project intelligence view traces universal model facts to evidence", () => {
  assert.match(app, /session\.status\?\.universal_model/);
  assert.match(app, /className="project-intelligence"/);
  assert.match(app, /className="project-structure-pane"/);
  assert.match(app, /className="project-evidence-pane"/);
  assert.match(app, /项目智能资料/);
  assert.match(app, /核心调用链/);
  assert.match(app, /证据追溯/);
  assert.match(css, /\.project-intelligence\s*\{/);
  assert.match(css, /\.project-structure-pane\s*\{/);
  assert.match(css, /\.project-evidence-pane\s*\{/);
});

test("interview evidence exposes source confidence", () => {
  assert.match(evidencePanel, /className="confidence-badge"/);
  assert.match(css, /\.confidence-badge\s*\{/);
});

test("interview workbench keeps stateful orchestration in App and view boundaries separate", () => {
  assert.match(app, /submitAnswerStream/);
  assert.match(app, /<InterviewComposer/);
  assert.match(app, /<InterviewThread/);
  assert.match(app, /<EvidencePanel/);
  assert.doesNotMatch(interviewComposer, /submitAnswerStream|fetch\(/);
  assert.doesNotMatch(interviewThread, /submitAnswerStream|fetch\(/);
  assert.doesNotMatch(evidencePanel, /submitAnswerStream|fetch\(/);
});

test("desktop app uses a custom draggable titlebar with window controls", () => {
  assert.match(app, /function CustomTitleBar\(\)/);
  assert.match(app, /data-tauri-drag-region/);
  assert.match(app, /getCurrentWindow/);
  assert.match(app, /handleWindowMinimize/);
  assert.match(app, /handleWindowMaximize/);
  assert.match(app, /handleWindowClose/);
  assert.match(app, /className="window-control window-control-close"/);
  assert.match(app, /className="titlebar-drag-region" data-tauri-drag-region/);
  assert.doesNotMatch(app, /className="app-titlebar" data-tauri-drag-region/);
  assert.match(css, /\.app-titlebar\s*\{/);
  assert.match(css, /\.window-control-close:hover\s*\{/);
  assert.match(css, /\.interview-workspace\s*\{[^}]*overflow:\s*hidden;/s);
  assert.match(css, /\.agent-workspace-content\s*\{[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s);
  assert.equal(tauriConfig.app.windows[0].decorations, false);
});

test("settings view exposes editable LLM configuration and connection feedback", () => {
  assert.match(app, /getLLMSettings/);
  assert.match(app, /saveLLMSettings/);
  assert.match(app, /testLLMConnection/);
  assert.match(app, /className="llm-settings-form"/);
  assert.match(app, /name="base_url"/);
  assert.match(app, /name="api_key"/);
  assert.match(app, /name="model"/);
  assert.match(app, /<input name="model"/);
  assert.match(app, /<datalist id="preset-models"/);
  assert.doesNotMatch(app, /<select name="model"/);
  assert.match(app, /测试连接/);
  assert.match(app, /保存配置/);
});

test("settings view shows configured model and vendor presets", () => {
  assert.match(app, /configured-model-card/);
  assert.match(app, /已配置的大模型/);
  assert.match(app, /provider-preset-grid/);
  assert.match(app, /data-provider=\{providerKey\}/);
  assert.match(app, /\n  agnes: \{/);
  assert.match(app, /\n  deepseek: \{/);
  assert.match(app, /applyProviderPreset/);
});

test("settings view exposes local preset model suggestions", () => {
  assert.match(app, /models: \["Agnes-2\.0-Flash", "Agnes-2\.5-Flash", "Agnes-2\.5-Pro-Alpha"\]/);
  assert.match(app, /models: \["deepseek-v4-flash", "deepseek-v4-pro"\]/);
  assert.match(app, /本地预设模型/);
  assert.match(app, /候选项来自本地预设/);
  assert.doesNotMatch(app, /getLLMModels/);
});

test("settings view exposes LLM profile management actions", () => {
  assert.match(app, /getLLMProfiles/);
  assert.match(app, /新增配置/);
  assert.match(app, /设为当前/);
  assert.match(app, /编辑/);
  assert.match(app, /测试/);
  assert.match(app, /删除/);
  assert.match(app, /onCreateProfile/);
  assert.match(app, /onUpdateProfile/);
  assert.match(app, /onDeleteProfile/);
  assert.match(app, /onActivateProfile/);
  assert.match(app, /onTestProfile/);
  assert.match(app, /profile-test-feedback/);
  assert.match(app, /configured-model-actions/);
  assert.match(app, /name="profile_name"/);
});
