import { expect, test } from '@playwright/test';

test.describe('Review Queue', () => {
  test('reviewer inspects the live queue, handles empty state, and can prepare notes for a real item', async ({ page }) => {
    await page.goto('/review-queue');

    await expect(page.locator('.rq-left-label')).toHaveText('Pending Review');
    await expect(page.locator('.sla-banner-text')).toContainText(/Loaded from \/api\/review\/queue|review queue HTTP/, { timeout: 30_000 });

    const liveItems = page.locator('.rq-item');
    const itemCount = await liveItems.count();

    if (itemCount === 0) {
      await expect(page.getByText('No live review queue items returned.')).toBeVisible();
      await expect(page.getByText('Select a live review item to inspect it.')).toBeVisible();
    } else {
      await liveItems.first().click();
      await expect(page.getByText(/^task_id:/)).toBeVisible();
      await expect(page.getByText('Captured task payload')).toBeVisible();

      await page.getByPlaceholder(/Add notes for this review/).fill(
        'Reviewer inspected the live task payload and is preparing a human decision.',
      );
      await expect(page.getByPlaceholder(/Add notes for this review/)).toHaveValue(
        'Reviewer inspected the live task payload and is preparing a human decision.',
      );

      await expect(page.getByRole('button', { name: /Accept & release/ })).toBeVisible();
      await expect(page.getByRole('button', { name: /Re-run/ })).toBeDisabled();
    }

    await page.getByRole('button', { name: '×' }).click();
    await expect(page.locator('.sla-banner')).toBeHidden();
  });
});

test.describe('Review Queue — tab bar', () => {
  test('shows two tabs with escalations active by default', async ({ page }) => {
    await page.goto('/review-queue');
    await expect(page.locator('.rq-tab-bar')).toBeVisible();
    await expect(page.locator('.rq-tab-active-esc')).toContainText('Confidence Escalations');
    await expect(page.locator('.rq-tab').nth(1)).toContainText('Fine-tune Approvals');
    await expect(page.locator('.rq-left-label')).toBeVisible();
  });

  test('switching to fine-tune tab hides escalations content; switching back restores it', async ({ page }) => {
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await expect(page.locator('.rq-tab-active-ft')).toContainText('Fine-tune Approvals');
    await expect(page.locator('.rq-left-label')).not.toBeVisible();
    await page.locator('.rq-tab').first().click();
    await expect(page.locator('.rq-left-label')).toBeVisible();
    await expect(page.locator('.rq-tab-active-esc')).toBeVisible();
  });
});

test.describe('Review Queue — fine-tune approvals tab', () => {
  const candidate = {
    candidate_id: 'cand-001',
    agent_id: 'rigel',
    example_count: 128,
    quality_avg: 0.91,
    emitted_at: '2026-05-10T05:00:00Z',
    status: 'pending',
    reviewed_at: null,
    reviewed_by: null,
    reviewer_note: null,
  };

  test('shows empty state when no candidates are pending', async ({ page }) => {
    await page.route('**/api/review/queue', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    );
    await page.route('**/api/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ candidates: [] }) }),
    );

    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();

    await expect(page.locator('.ft-empty-text')).toHaveText('No fine-tune candidates pending review');
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('0');
  });

  test('renders candidate cards and badge count', async ({ page }) => {
    await page.route('**/api/review/queue', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    );
    await page.route('**/api/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ candidates: [candidate] }) }),
    );

    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();

    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('1');
    await expect(page.locator('.ft-card')).toHaveCount(1);
    await expect(page.locator('.ft-agent-name')).toHaveText('rigel');
    await expect(page.getByText('128')).toBeVisible();
    await expect(page.getByText('0.91')).toBeVisible();
    await expect(page.getByText(/Orion detected enough high-quality rigel examples/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible();
  });

  test('approves a candidate with reviewer note and updates badge', async ({ page }) => {
    let approvedBody: Record<string, unknown> | null = null;

    await page.route('**/api/review/queue', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    );
    await page.route('**/api/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ candidates: [candidate] }) }),
    );
    await page.route('**/api/finetune/candidates/cand-001/approve', async (route, request) => {
      approvedBody = request.postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'approved', candidate_id: 'cand-001' }),
      });
    });

    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.getByRole('button', { name: 'Approve' }).click();
    await page.getByPlaceholder(/Optional note/).fill('Approved for next supervised fine-tune.');
    await page.getByRole('button', { name: 'Confirm Approve' }).click();

    await expect(page.locator('.ft-empty-text')).toHaveText('No fine-tune candidates pending review');
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('0');
    expect(approvedBody).toEqual({
      reviewed_by: 'Admin',
      reviewer_note: 'Approved for next supervised fine-tune.',
    });
  });

  test('rejects a candidate and surfaces API errors inline', async ({ page }) => {
    await page.route('**/api/review/queue', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    );
    await page.route('**/api/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ candidates: [candidate] }) }),
    );
    await page.route('**/api/finetune/candidates/cand-001/reject', route =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'write failed' }) }),
    );

    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.getByRole('button', { name: 'Reject' }).click();
    await page.getByRole('button', { name: 'Confirm Reject' }).click();

    await expect(page.locator('.ft-error-inline')).toContainText('review reject HTTP 500');
    await expect(page.locator('.ft-card')).toContainText('rigel');
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('1');
  });
});
