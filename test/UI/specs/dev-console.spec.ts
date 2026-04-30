import { expect, test } from '@playwright/test';

test.describe('Dev Console', () => {
  test('developer inspects live registered agents, manifest skills, and unavailable live panels', async ({ page }) => {
    await page.goto('/dev-console');

    await expect(page.getByText('Registered Agents')).toBeVisible();
    await expect(page.locator('.agent-item').filter({ hasText: 'rigel' })).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.detail-type')).toHaveText('Rigel Engineering Agent');
    await expect(page.getByText('agent_id: rigel')).toBeVisible();

    await page.getByRole('button', { name: 'Skills' }).click();
    await expect(page.locator('.sk-id').filter({ hasText: 'rigel.skill.code_generation' })).toBeVisible();
    await expect(page.locator('.sk-id').filter({ hasText: 'rigel.skill.debug_triage' })).toBeVisible();
    await expect(page.locator('.skills-table tbody tr')).toHaveCount(6);
    await expect(page.getByText('Manifest Confidence')).toBeVisible();
    await expect(page.getByText('Live Tasks')).toBeVisible();

    await page.getByRole('button', { name: 'LLM Config' }).click();
    await expect(page.getByText('Live LLM config endpoint unavailable')).toBeVisible();
    await expect(page.getByText('No live model configuration returned.')).toBeVisible();

    await page.locator('.agent-item').filter({ hasText: 'vega' }).click();
    await expect(page.locator('.detail-type')).toHaveText('Vega QA Agent');
    await page.getByRole('button', { name: 'Skills' }).click();
    await expect(page.locator('.sk-id').filter({ hasText: 'requirements_to_test_cases' })).toBeVisible();

    await page.locator('.detail-tabs').getByRole('button', { name: 'Logs' }).click();
    await expect(page.getByText('vega · live log output')).toBeVisible();
    await expect(page.getByText('No live log endpoint is available for this agent.')).toBeVisible();
  });
});
