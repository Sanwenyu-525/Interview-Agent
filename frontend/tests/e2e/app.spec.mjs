import { test, expect } from "@playwright/test";

// 01–07 页浏览器回归：无项目状态下的导航、空态与设置页主操作。
// 需要项目数据的完整流程（上传、面试、报告、画像）在 seed 后由 app-flow.spec 覆盖。

test("空工作台展示添加项目入口和引擎状态", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "添加项目目录" })).toBeVisible();
  await expect(page.getByText("面试引擎在线").first()).toBeVisible();
});

test("侧栏可导航到全部七个一级页面", async ({ page }) => {
  await page.goto("/");
  const checks = [
    ["面试工作台", () => page.locator('section[aria-label="面试工作台"]').first()],
    ["岗位准备", () => page.locator('section[aria-label="岗位准备"]').first()],
    ["项目资料", () => page.locator('section[aria-label="项目资料"]').first()],
    ["简历库", () => page.locator('section[aria-label="简历库"]').first()],
    ["会话报告", () => page.locator(".stitch-page").first()],
    ["能力画像", () => page.locator(".stitch-page").first()],
    ["应用设置", () => page.locator('section[aria-label="应用设置"]').first()],
  ];
  for (const [nav, target] of checks) {
    await page.getByRole("button", { name: nav }).click();
    await expect(target()).toBeVisible();
  }
});

test("项目资料页在无项目时展示空态", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "项目资料" }).click();
  await expect(page.getByText("尚未添加项目")).toBeVisible();
  await expect(page.getByRole("button", { name: "添加项目目录" })).toBeVisible();
});

test("应用设置的 Agent 管理展示五个内置角色", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "应用设置" }).click();
  await page.getByRole("tab", { name: "Agent 管理" }).click();
  await expect(page.locator(".agent-card")).toHaveCount(5);
  await expect(page.locator(".agent-card").filter({ hasText: "压力面试官" })).toBeVisible();
});
