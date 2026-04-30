import { expect, test } from '@playwright/test';

test.describe('Galaxz navigation and dashboard', () => {
  test('operator moves from public landing page into the system dashboard and review queue', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('navigation')).toContainText('galaxz');
    await expect(page.getByText('The open AI agent operating system')).toBeVisible();
    await expect(page.getByText('Andromeda Router', { exact: true })).toBeVisible();
    await expect(page.getByText('Rigel Engineering', { exact: true })).toBeVisible();

    await page.goto('/dashboard');
    await expect(page.locator('.topbar-title')).toHaveText('Dashboard');
    await expect(page.locator('.metric-label').filter({ hasText: 'Task log rows' })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.metric-label').filter({ hasText: 'Completed rows' })).toBeVisible();
    await expect(page.locator('.metric-label').filter({ hasText: 'Pending reviews' })).toBeVisible();
    await expect(page.locator('.metric-label').filter({ hasText: 'Failed rows' })).toBeVisible();
    await expect(page.getByText('No hourly throughput endpoint is available yet.')).toBeVisible();

    await page.locator('aside').getByRole('button', { name: /^Review Queue/ }).click();
    await expect(page).toHaveURL(/\/review-queue$/);
    await expect(page.locator('.rq-left-label')).toHaveText('Pending Review');
    await expect(page.locator('.sla-banner-text')).toContainText(/Loaded from \/api\/review\/queue|review queue HTTP/);
  });

  test('sidebar lets an operator reach every major workspace area', async ({ page }) => {
    await page.goto('/dashboard');

    await page.getByRole('button', { name: 'Dev Console' }).click();
    await expect(page).toHaveURL(/\/dev-console$/);
    await expect(page.getByText('Registered Agents')).toBeVisible();

    await page.getByRole('button', { name: 'Task UI' }).click();
    await expect(page).toHaveURL(/\/task-ui$/);
    await expect(page.getByPlaceholder('Describe what you need — ⌘Enter to send')).toBeVisible();

    await page.getByRole('button', { name: 'Orion Analytics' }).click();
    await expect(page).toHaveURL(/\/orion$/);
    await expect(page.locator('.topbar-title')).toHaveText('Orion Analytics');

    await page.getByRole('button', { name: 'Settings' }).click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.locator('.settings-panel-title')).toHaveText('Models & Connections');
  });
});
