import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
const app = await readFile(new URL("../src/App.jsx", import.meta.url), "utf8");
const tauriConfig = JSON.parse(await readFile(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));

test("desktop interview uses the Stitch four-column evidence layout", () => {
  assert.match(app, /className=\{`app-shell stitch-shell view-\$\{activeView\}/);
  assert.match(app, /<PrimarySidebar/);
  assert.match(app, /<InterviewContextRail/);
  assert.match(app, /className=\{`evidence-panel \$\{isEvidenceOpen \? "is-open" : ""\} \$\{isEvidenceCollapsed \? "is-collapsed" : ""\}`\}/);
  assert.match(css, /\.stitch-shell\.view-interview:not\(\.is-empty-project\)\s*\{[^}]*grid-template-columns:\s*176px var\(--context-rail-width, 216px\) minmax\(320px, 1fr\) var\(--evidence-panel-width, 372px\);/s);
  assert.match(css, /\.view-interview \.evidence-panel\s*\{[^}]*grid-column:\s*4;/s);
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
  assert.match(app, /<ArrowUp size=\{18\} weight="bold" \/>/);
});

test("interview feedback keeps process and evaluation hierarchy compact", () => {
  assert.match(css, /\.process-details\s*\{/);
  assert.match(css, /\.history-evaluation\s*\{/);
  assert.match(css, /\.streaming-message\s+\.process-details/);
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
  assert.match(app, /className="confidence-badge"/);
  assert.match(css, /\.confidence-badge\s*\{/);
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
