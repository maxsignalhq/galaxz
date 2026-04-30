import { expect, test } from '@playwright/test';
import { realisticTasks } from '../fixtures/task-inputs';

const LIVE_TASK_TIMEOUT_MS = 180_000;

test.describe.configure({ mode: 'serial' });

test.describe('Task UI functional flows against the live backend', () => {
  test.beforeEach(async ({ page, request, baseURL }) => {
    const health = await request.get(`${baseURL}/api/health`);
    if (!health.ok()) {
      throw new Error(
        `Backend health check failed before UI test: HTTP ${health.status()} ${await health.text()}`,
      );
    }

    await page.goto('/task-ui');
  });

  test('engineer submits a code-generation task through Andromeda and sees the live Rigel result', async ({ page }) => {
    test.setTimeout(240_000);

    const apiRequest = page.waitForRequest((request) => request.url().includes('/api/task'));
    const apiResponse = page.waitForResponse(
      (response) => response.url().includes('/api/task'),
      { timeout: LIVE_TASK_TIMEOUT_MS },
    );

    await page.locator('.agent-selector-bar select').selectOption('code_generation');
    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(realisticTasks.codeGenerationRequest);
    await page.getByRole('button', { name: /Send/ }).click();

    const request = await apiRequest;
    expect(request.postDataJSON()).toEqual({
      task: realisticTasks.codeGenerationRequest,
      skill_id: 'code_generation',
    });

    const response = await apiResponse;
    if (!response.ok()) {
      throw new Error(`Task API failed: HTTP ${response.status()} ${await response.text()}`);
    }

    const payload = await response.json();
    if (payload.status !== 'complete') {
      throw new Error(
        `Task API did not complete. status=${payload.status} failure_reason=${payload.failure_reason ?? 'none'}`,
      );
    }
    if (payload.assigned_agent !== 'rigel') {
      throw new Error(`Expected live task to route to rigel, routed to ${payload.assigned_agent}`);
    }
    if (typeof payload.confidence !== 'number' || payload.confidence < 0.65) {
      throw new Error(`Expected confidence >= 0.65, received ${payload.confidence}`);
    }

    await expect(page.getByText(/routing trace · task [0-9a-f-]{8}/i)).toBeVisible({ timeout: LIVE_TASK_TIMEOUT_MS });
    await expect(page.getByText('skill: rigel.skill.code_generation')).toBeVisible();
    await expect(page.getByText('rigel · code_generation')).toBeVisible();
    await expect(page.locator('.conf-value')).toContainText(payload.confidence.toFixed(2));
    await expect(page.locator('.code-output')).toBeVisible();
    await expect(page.locator('.code-output')).toContainText('rotate_refresh_token');
    await expect(page.getByText(`task_id: ${payload.task_id}`)).toBeVisible();
    await expect(page.locator('.recent-tasks-section')).toContainText('complete');
  });

  test('operator gets a visible failure if the live task API returns an error', async ({ page }) => {
    test.setTimeout(240_000);

    await page.locator('.agent-selector-bar select').selectOption('pr_review');
    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(realisticTasks.prReviewRequest);
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Enter' : 'Control+Enter');

    const outcome = page.locator('.agent-result').last();
    await expect(outcome).toBeVisible({ timeout: LIVE_TASK_TIMEOUT_MS });

    const text = await outcome.innerText();
    if (text.includes('failed') || text.includes('escalated')) {
      throw new Error(
        `Live API surfaced an endpoint or payload-contract issue for pr_review: ${text}`,
      );
    }

    await expect(outcome).toContainText('rigel · pr_review');
  });
});
