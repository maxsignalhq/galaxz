import { expect, test } from '@playwright/test';

test.describe('Settings', () => {
  test('admin updates model provider, fallback behavior, and budget policy from the settings UI', async ({ page }) => {
    await page.goto('/settings');

    await expect(page.locator('.settings-panel-title')).toHaveText('Models & Connections');
    await expect(page.getByText('Anthropic Configuration')).toBeVisible();
    await page.locator('.provider-card').filter({ hasText: /^OpenAI/ }).click();
    await expect(page.locator('.provider-card.provider-active')).toContainText('OpenAI');

    const fallbackToggle = page
      .locator('.toggle-row')
      .filter({ hasText: 'Fallback to secondary provider' })
      .locator('button');
    await expect(fallbackToggle).not.toHaveClass(/toggle-on/);
    await fallbackToggle.click();
    await expect(fallbackToggle).toHaveClass(/toggle-on/);

    await page.getByRole('button', { name: 'Budget & Limits' }).click();
    await expect(page.locator('.budget-cell-label').filter({ hasText: 'Daily token budget' })).toBeVisible();
    await page.locator('.policy-row').filter({ hasText: 'Daily token budget exceeded' }).locator('select').selectOption('fallback');
    await expect(page.locator('.policy-row').filter({ hasText: 'Daily token budget exceeded' }).locator('select')).toHaveValue('fallback');

    await expect(page.getByRole('button', { name: 'Save changes' })).toBeVisible();
    await expect(page.getByText('agents will hot-reload updated config')).toBeVisible();
  });
});
