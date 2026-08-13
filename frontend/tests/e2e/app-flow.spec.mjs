import { test, expect } from "@playwright/test";

// 需要项目数据的完整复盘链路：上传 → 面试工作台 → 提交回答 → 会话报告 → 能力画像。
// 后端以 InMemory 存储运行（见 playwright.config.mjs），project_id 使用固定整数避免与前端随机 ID 冲突。

const PROJECT_ID = 900001;

async function seedProject(request) {
  const response = await request.post("http://127.0.0.1:8000/projects/upload", {
    data: {
      project_id: PROJECT_ID,
      project_name: "e2e 示例项目",
      source: {
        type: "folder",
        files: [
          {
            path: "app.py",
            content:
              "def main():\n    return True\n\n\nclass OrderService:\n    def place(self):\n        return 'ok'\n",
          },
          { path: "requirements.txt", content: "requests==2.32.0\nfastapi>=0.100\n" },
        ],
      },
    },
  });
  if (!response.ok()) {
    throw new Error(`seed 失败: ${response.status()} ${await response.text()}`);
  }
}

test("上传项目后完成一轮问答并生成报告与画像", async ({ page, request }) => {
  await seedProject(request);
  await page.addInitScript((id) => {
    globalThis.localStorage.setItem("interview-agent.project-id", String(id));
  }, PROJECT_ID);
  await page.goto("/");

  // 02 面试工作台完整态：回答输入框启用（项目分析 + 建会话完成）
  await expect(page.getByRole("textbox", { name: "你的回答" })).toBeEnabled({ timeout: 20000 });

  // 提交一轮回答
  await page
    .getByRole("textbox", { name: "你的回答" })
    .fill("我实现了 main 函数作为入口，并通过缓存与事务保证数据一致性。");
  await page.getByRole("button", { name: "提交回答" }).click();

  // 评价完成后，结束会话按钮解除禁用
  await expect(page.getByRole("button", { name: "结束会话" })).toBeEnabled({ timeout: 20000 });

  // 06 会话报告：结束会话后自动跳转并渲染报告
  await page.getByRole("button", { name: "结束会话" }).click();
  await expect(page.locator('section[aria-label="会话报告"]')).toBeVisible({ timeout: 15000 });

  // 07 能力画像：有样本后渲染画像页
  await page.getByRole("button", { name: "能力画像" }).click();
  await expect(page.locator('section[aria-label="面试者能力画像"]')).toBeVisible({ timeout: 15000 });
});
