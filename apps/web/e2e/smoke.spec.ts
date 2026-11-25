import { expect, test } from "@playwright/test";

test("built app serves the BookScope shell", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto("/");
  await expect(page).toHaveTitle("BookScope");
  await expect(page.getByRole("heading", { level: 1, name: "BookScope" })).toBeVisible();
  expect(errors).toEqual([]);
});
