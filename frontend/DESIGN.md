# Design System: Interview Agent — Evidence-first Studio

## 1. Visual Theme & Atmosphere

Interview Agent is a desktop-first project review cockpit: calm, exact, evidence-led, and suitable for long technical sessions. The interface should feel like a well-organized engineering notebook combined with a focused interview room.

- Density: 7/10, information-rich without becoming cramped.
- Variance: 5/10, asymmetric three-pane workspaces with predictable navigation.
- Motion: 3/10, restrained and purposeful. Status changes may pulse softly; content should never feel theatrical.
- Product hierarchy: project evidence first, current question second, evaluation and progress always traceable.
- Current production capabilities and future concept capabilities must be visibly distinguishable through labels such as “当前能力” and “概念预览”.

## 2. Color Palette & Roles

Use one warm neutral family across the product and one restrained accent. Never mix cool blue-gray surfaces into this palette.

- **Paper Canvas** (#F7F5EF) — application background and main workspace canvas.
- **Porcelain Surface** (#FFFDF8) — panels, input surfaces, primary reading areas.
- **Linen Surface** (#F1EEE7) — secondary regions, hover states, grouped controls.
- **Whisper Line** (#E6E1D8) — 1px structural borders and dividers.
- **Charcoal Ink** (#25241F) — primary text; never use pure black.
- **Graphite Copy** (#5E5A52) — body copy and secondary labels.
- **Muted Stone** (#8A877F) — metadata, timestamps, placeholders.
- **Mineral Copper** (#B36A2E) — the only accent; primary actions, active navigation, evidence references, focus rings.
- **Copper Wash** (#F7EBDD) — selected rows, evidence highlights, quiet active states.
- **Verdigris Success** (#4C8A70) — semantic success and online status only, never a competing brand accent.
- **Terracotta Risk** (#B65F49) — errors, destructive actions, and risk findings only.

No gradients in core application chrome. No neon, purple, blue glow, or outer-glow effects.

## 3. Typography Rules

- **Display and UI headings:** Manrope, 600–700 weight, tight tracking from -0.02em to -0.04em. Page titles 24–32px; question headings may reach 34px.
- **Body and controls:** Manrope, 400–600 weight, 13–16px with relaxed 1.55–1.75 line height. Long explanatory text should not exceed 65 characters per line.
- **Code and metadata:** DM Mono, 400–500 weight, 10–14px. Use for paths, evidence IDs, timestamps, scores, model names, versions, and line numbers.
- **Chinese fallback:** PingFang SC, Microsoft YaHei, sans-serif.
- **Banned:** Inter, generic serif fonts, pure system-only typography, oversized marketing-style headings.

## 4. Component Stylings

- **Application shell:** 38px desktop title bar; 272px left navigation; fluid central workspace; optional 372px evidence drawer. Use tonal separation and 1px Whisper Line borders.
- **Buttons:** 7–8px radius, minimum 32px desktop hit area and 44px touch target on narrow layouts. Primary buttons use Mineral Copper fill with warm-white text. Active state translates down 1px. No glow.
- **Navigation:** Compact rows with icon, title, and optional metadata. Active item uses Copper Wash, Mineral Copper text, and a subtle 1px copper-tinted border.
- **Cards:** Use only when grouping or elevation carries meaning. Main panels use 8–12px radius; message bubbles may use one asymmetric corner. Dense data uses dividers and whitespace instead of repeated floating cards.
- **Inputs:** Visible label above, helper or constraint text below, inline error below the field. Focus uses a 2px Mineral Copper ring with low-opacity Copper Wash.
- **Composer:** Stays fixed at the bottom of the interview thread. Includes attachment menu, mode context, shortcut hint, and one primary submit action.
- **Evidence:** File path and language in the header; code excerpt with DM Mono line numbers; evidence ID, confidence, and source explanation remain visible. Clicking a reference should highlight the matching structure node.
- **Evaluation:** Score, direction, strengths, weaknesses, and next action must be separate semantic groups. Never communicate score quality by color alone.
- **Tables and lists:** Compact 40–48px rows, sticky headings where useful, no zebra striping. Selection uses Copper Wash.
- **Charts:** Sparse axes, direct labels, real uneven values, and accessible text summaries. Avoid decorative donut charts.
- **Loading:** Exact-dimension skeletons and named progress stages: 读取文件、上传项目、分析项目、建立会话. Do not use generic circular spinners as the only feedback.
- **Empty states:** Preserve the full workspace shell and explain the next action. Never replace the product with a standalone upload landing page.
- **Errors:** Keep user input and project context visible. State what failed and provide a specific recovery action.

## 5. Layout Principles

- Desktop reference canvas: 1440×960. Maximum content width 1440px; application chrome may fill the viewport.
- Use CSS Grid logic: fixed navigation, fluid primary content, contextual right rail.
- The interview page prioritizes the conversation thread; the evidence rail is contextual, not a permanent competing dashboard.
- Project Intelligence uses an asymmetric explorer layout: structure tree on the left, facts and flows in the center, selected evidence on the right.
- Settings uses a narrow profile list and a wider configuration form, not a grid of equal cards.
- Reports use an editorial two-column structure with a readable narrative main column and a narrow evidence/metric rail.
- Never overlap content. Every panel occupies a clear spatial zone.
- Below 1180px, narrow the navigation and evidence rail. Below 920px, navigation becomes a drawer and evidence moves after the main content. Below 620px, use a strict single column with no horizontal scroll.
- Preserve long project names, long paths, long errors, empty evidence, and many feedback items without clipping.

## 6. Motion & Interaction

- Use 160–200ms ease-out transitions for hover, drawer, selection, and menu states.
- Animate transform and opacity only; do not use spring or bounce effects.
- Animate transform and opacity only. Respect prefers-reduced-motion.
- The online dot may use a very soft 2.5-second opacity pulse. Upload progress may move through named steps once; no infinite spinner after failure.
- New evaluation sections reveal in a short stagger: score, strengths, weaknesses, next direction.
- Core navigation, tabs, menus, filters, attachment selection, review-mode selection, and form controls must show clear hover, focus, active, disabled, loading, success, and error states.

## 7. Product Screen Family

Use one persistent application shell and realistic Chinese content across all screens.

1. **Workspace / Empty Project** — existing capability. Agent shell remains visible; attachment menu is open with directory selection, “针对文件提问 / 存入知识库”, candidate ID, capacity limits, and four upload stages.
2. **Evidence-first Interview** — existing capability. Active technical interview with history, current question, composer, open evidence panel, current evaluation, progress, and marked-question state.
3. **Project Intelligence Explorer** — existing capability. Identity, analyzer status, structure tree, technologies, components, relations, flows, risks, topics, evidence confidence, and source excerpt.
4. **LLM Profile Settings** — existing capability. Provider profile list, active status, masked API key, base URL, model discovery, save/test/activate/delete actions, and clear error handling.
5. **New Review Session** — concept UI over existing backend modes. Technical Interview, Portfolio Review, and Defense Review are selected without changing Analyzer output; include candidate, difficulty, focus topics, evidence coverage, and session estimate.
6. **Session Review Report** — concept preview. Question timeline, score progression, evidence coverage, strengths, weaknesses, marked questions, follow-up plan, and export action.
7. **Candidate Capability Profile** — concept preview. Cross-session trend, domain competencies, recurring weak points, evidence-backed examples, recent sessions, and recommended next practice.

## 8. Anti-Patterns (Banned)

- No emojis, fake avatars, generic names such as John Doe or Acme, or fake round metrics.
- No Inter, generic serif fonts, pure black, neon colors, outer glows, gradient text, glass-heavy panels, or custom cursors.
- No generic three-equal-card feature rows, oversized KPI tiles, or decorative analytics with no product decision attached.
- No detached generic chat page. Questions, answers, evidence, evaluation, project structure, and progress must remain linked.
- No hardcoded promises about Analyzer capability. Show analyzer ID, detected facts, confidence, and evidence returned by the backend.
- No hidden API keys, secrets, or full credentials in visible UI. Only masked status is shown.
- No filler copy such as “Elevate”, “Seamless”, “Next-Gen”, “Scroll to explore”, or vague AI marketing slogans.
- No content overlap, cropped paths, broken overflow, horizontal mobile scroll, or color-only status communication.
