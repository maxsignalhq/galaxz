import { expect, test } from '@playwright/test';

test.describe('Dev Console', () => {
  test('developer inspects live registered agents and uses console controls', async ({ page }) => {
    await page.goto('/dev-console');

    await expect(page.getByText('Registered Agents')).toBeVisible();
    await expect(page.locator('.agent-item').filter({ hasText: 'rigel' })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.detail-type')).toHaveText('Rigel Engineering Agent');
    await expect(page.getByText('agent_id: rigel')).toBeVisible();

    await page.getByPlaceholder('Search agents…').fill('debug');
    await expect(page.locator('.agent-item').filter({ hasText: 'rigel' })).toBeVisible();
    await expect(page.locator('.agent-item').filter({ hasText: 'vega' })).toHaveCount(0);
    await page.getByPlaceholder('Search agents…').fill('');

    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(page.getByText('Refreshing live registry data.')).toBeVisible();

    await page.getByRole('button', { name: 'Skills' }).click();
    await expect(page.locator('.sk-id').filter({ hasText: 'rigel.skill.code_generation' })).toBeVisible();
    await expect(page.locator('.sk-id').filter({ hasText: 'rigel.skill.debug_triage' })).toBeVisible();
    await expect(page.locator('.skills-table tbody tr')).toHaveCount(6);
    await expect(page.getByText('Manifest Confidence')).toBeVisible();
    await expect(page.getByText('Live Tasks')).toBeVisible();

    await page.getByRole('button', { name: 'Appearance' }).click();
    await page.getByLabel('Display Name').fill('Rigel Core');
    await page.getByLabel('Use #9d7eff').click();
    await page.getByRole('button', { name: 'Save appearance' }).click();
    await expect(page.getByText('Saved appearance for rigel.')).toBeVisible();
    await expect(page.locator('.detail-name')).toHaveText('Rigel Core');
    await expect(page.locator('.agent-item').filter({ hasText: 'Rigel Core' })).toBeVisible();

    await page.getByRole('button', { name: 'LLM Config' }).click();
    await expect(page.getByText('Workspace-local overrides')).toBeVisible();
    await page.locator('.llm-row').filter({ hasText: 'rigel.skill.code_generation' }).locator('select').selectOption('balanced local');
    await expect(page.getByText('Saved model override for rigel.skill.code_generation.')).toBeVisible();

    await page.getByRole('button', { name: 'Copy manifest' }).click();
    await expect(page.getByText(/Manifest copied to clipboard.|Clipboard permission denied by the browser./)).toBeVisible();

    await page.locator('.agent-item').filter({ hasText: 'vega' }).click();
    await expect(page.locator('.detail-type')).toHaveText('Vega QA Agent');
    await page.getByRole('button', { name: 'Skills' }).click();
    await expect(page.locator('.sk-id').filter({ hasText: 'requirements_to_test_cases' })).toBeVisible();

    await page.locator('.detail-tabs').getByRole('button', { name: 'Logs' }).click();
    await expect(page.getByText('vega · live log output')).toBeVisible();
    await page.getByRole('button', { name: 'Health check' }).click();
    await expect(page.locator('.log-msg').filter({ hasText: '/api/health' })).toBeVisible();
    await page.locator('.log-panel').getByRole('button', { name: 'Clear' }).click();
    await expect(page.getByText('Console activity cleared.')).toBeVisible();
  });
});
