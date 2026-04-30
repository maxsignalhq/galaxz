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
