import { expect, test } from '@playwright/test';
import { realisticTasks } from '../fixtures/task-inputs';

const LIVE_TASK_TIMEOUT_MS = 180_000;
const RIGEL_CODE = 'rigel.skill.code_generation';
const RIGEL_DEBUG = 'rigel.skill.debug_triage';
const RIGEL_PR_REVIEW = 'rigel.skill.pr_review';
const VEGA_REQUIREMENTS = 'vega.skill.requirements_to_test_cases';
const VEGA_EXECUTION = 'vega.skill.test_case_execution';

test.describe.configure({ mode: 'serial' });

test.describe('Task UI functional flows against the live backend', () => {
  test.beforeEach(async ({ page, request, baseURL }) => {
    const health = await request.get(`${baseURL}/api/health`);
    if (!health.ok()) {
      throw new Error(
        `Backend health check failed before UI test: HTTP ${health.status()} ${await health.text()}`,
      );
    }

    await page.goto('/');
    await page.evaluate(() => {
      window.localStorage.removeItem('galaxz.taskUi.session');
    });
    await page.goto('/task-ui');
  });

  test('engineer submits a code-generation task through Andromeda and sees the live Rigel result', async ({ page }) => {
    test.setTimeout(240_000);

    const apiRequest = page.waitForRequest((request) => request.url().includes('/api/task'));
    const apiResponse = page.waitForResponse(
      (response) => response.url().includes('/api/task'),
      { timeout: LIVE_TASK_TIMEOUT_MS },
    );

    await page.locator('.agent-selector-bar select').selectOption(RIGEL_CODE);
    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(realisticTasks.codeGenerationRequest);
    await page.getByRole('button', { name: /Send/ }).click();

    const request = await apiRequest;
    expect(request.postDataJSON()).toEqual({
      task: realisticTasks.codeGenerationRequest,
      skill_id: RIGEL_CODE,
      route_mode: 'auto',
      session_context: [],
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
    await expect(page.locator('.agent-result-name').filter({ hasText: `rigel · ${RIGEL_CODE}` })).toBeVisible();
    await expect(page.locator('.conf-value')).toContainText(payload.confidence.toFixed(2));
    await expect(page.locator('.code-output')).toBeVisible();
    await expect(page.locator('.code-output')).toContainText('rotate_refresh_token');
    await expect(page.getByText('FeedbackEvent emitted → Aether · Orion ingestion is active')).toBeVisible();
    await expect(page.getByText(`task_id: ${payload.task_id}`)).toBeVisible();
    await expect(page.locator('.recent-tasks-section')).toContainText('complete');

    await page.goto('/dashboard');
    await page.goto('/task-ui');
    await expect(page.getByText(`task_id: ${payload.task_id}`)).toBeVisible();
    await expect(page.locator('.recent-tasks-section')).toContainText('complete');
  });

  test('keeps draft and route controls after navigating away and back', async ({ page }) => {
    await page.locator('.agent-selector-bar select').selectOption(RIGEL_DEBUG);
    await page.getByRole('button', { name: 'Rigel Engineering Agent' }).click();
    await page
      .getByPlaceholder('Describe what you need — ⌘Enter to send')
      .fill(realisticTasks.debugTriageRequest);

    await page.goto('/dashboard');
    await page.goto('/task-ui');

    await expect(page.locator('.agent-selector-bar select')).toHaveValue(RIGEL_DEBUG);
    await expect(page.getByPlaceholder('Describe what you need — ⌘Enter to send')).toHaveValue(realisticTasks.debugTriageRequest);
    await expect(page.getByText('rigel selected')).toBeVisible();
  });

  test('attaches selected text files to the task draft and submits them', async ({ page }) => {
    const startingPrompt = 'Create test cases from these attached requirements.';
    const firstAttachment = 'REQ-001: Users can reset their password with a verified email.';
    const secondAttachment = 'REQ-002: Reset links expire after 15 minutes.';
    let capturedTask = '';

    await page.route('**/api/task', async (route, request) => {
      const body = request.postDataJSON();
      capturedTask = body.task;
      expect(body.skill_id).toBe(RIGEL_CODE);
      expect(body.route_mode).toBe('auto');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'mock-attach-task',
          task_type: 'code_generation',
          required_skills: ['rigel.skill.code_generation'],
          assigned_agent: 'rigel',
          status: 'complete',
          confidence: 0.88,
          confidence_breakdown: null,
          gaps: [],
          failure_reason: null,
          escalated_to_human: false,
          issued_at: '2026-05-10T00:00:00Z',
          completed_at: '2026-05-10T00:00:01Z',
          result: {
            code: 'def reset_password_requirements():\n    return True',
            language: 'python',
            notes: 'mock complete',
          },
        }),
      });
    });

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(startingPrompt);
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.locator('.micro-btn').filter({ hasText: 'Attach' }).click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles([
      {
        name: 'password-reset.md',
        mimeType: 'text/markdown',
        buffer: Buffer.from(firstAttachment),
      },
      {
        name: 'expiry.txt',
        mimeType: 'text/plain',
        buffer: Buffer.from(secondAttachment),
      },
    ]);

    const textarea = page.getByPlaceholder('Describe what you need — ⌘Enter to send');
    await expect(textarea).toHaveValue(new RegExp(`${startingPrompt}[\\s\\S]*--- password-reset\\.md ---[\\s\\S]*${firstAttachment}[\\s\\S]*--- expiry\\.txt ---[\\s\\S]*${secondAttachment}`));

    await page.getByRole('button', { name: /Send/ }).click();
    await expect(page.locator('.agent-result-name').filter({ hasText: `rigel · ${RIGEL_CODE}` })).toBeVisible();
    expect(capturedTask).toContain(startingPrompt);
    expect(capturedTask).toContain('--- password-reset.md ---');
    expect(capturedTask).toContain(firstAttachment);
    expect(capturedTask).toContain('--- expiry.txt ---');
    expect(capturedTask).toContain(secondAttachment);
  });

  test('starts a new submission while keeping the prior thread in history', async ({ page }) => {
    const firstPrompt = 'Write a Python script that has Word Frequency Counter.';
    const secondPrompt = 'Write a Python script that converts Celsius to Fahrenheit.';
    let callCount = 0;

    await page.route('**/api/task', async (route) => {
      callCount += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: `mock-task-${callCount}`,
          task_type: 'code_generation',
          required_skills: ['rigel.skill.code_generation'],
          assigned_agent: 'rigel',
          status: 'complete',
          confidence: 0.82,
          confidence_breakdown: null,
          gaps: [],
          failure_reason: null,
          escalated_to_human: false,
          issued_at: '2026-05-10T00:00:00Z',
          completed_at: '2026-05-10T00:00:01Z',
          result: {
            code: callCount === 1 ? 'def word_frequency(text):\n    return {}' : 'def c_to_f(c):\n    return c * 9 / 5 + 32',
            language: 'python',
            notes: 'mock complete',
          },
        }),
      });
    });

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(firstPrompt);
    await page.getByRole('button', { name: /Send/ }).click();
    await expect(page.locator('.chat-area').getByText(firstPrompt)).toBeVisible();
    await expect(page.locator('.chat-area').getByText('def word_frequency')).toBeVisible();

    await page.getByRole('button', { name: 'New', exact: true }).click();
    await expect(page.locator('.chat-area').getByText(firstPrompt)).not.toBeVisible();
    await expect(page.getByText('no tasks yet')).toBeVisible();
    await expect(page.locator('.thread-item').filter({ hasText: firstPrompt })).toBeVisible();

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(secondPrompt);
    await page.getByRole('button', { name: /Send/ }).click();
    await expect(page.locator('.chat-area').getByText(secondPrompt)).toBeVisible();
    await expect(page.locator('.chat-area').getByText('def c_to_f')).toBeVisible();

    await page.locator('.thread-item').filter({ hasText: firstPrompt }).click();
    await expect(page.locator('.chat-area').getByText(firstPrompt)).toBeVisible();
    await expect(page.locator('.chat-area').getByText('def word_frequency')).toBeVisible();
    await expect(page.locator('.thread-item').filter({ hasText: secondPrompt })).toBeVisible();
  });

  test('auto-routes QA execution skills to Vega', async ({ page }) => {
    const apiRequest = page.waitForRequest((request) => request.url().includes('/api/task'));
    const apiResponse = page.waitForResponse(
      (response) => response.url().includes('/api/task'),
      { timeout: LIVE_TASK_TIMEOUT_MS },
    );

    await page.locator('.agent-selector-bar select').selectOption(VEGA_EXECUTION);
    await expect(page.getByText('routes to vega')).toBeVisible();
    await page
      .getByPlaceholder('Describe what you need — ⌘Enter to send')
      .fill('Executed checkout regression: payment validation failed for expired cards.');
    await page.getByRole('button', { name: /Send/ }).click();

    const request = await apiRequest;
    expect(request.postDataJSON()).toEqual({
      task: 'Executed checkout regression: payment validation failed for expired cards.',
      skill_id: VEGA_EXECUTION,
      route_mode: 'auto',
      session_context: [],
    });

    const response = await apiResponse;
    if (!response.ok()) {
      throw new Error(`Task API failed: HTTP ${response.status()} ${await response.text()}`);
    }
    const payload = await response.json();
    expect(payload.assigned_agent).toBe('vega');
    expect(payload.status).toBe('complete');

    await expect(page.locator('.agent-result-name').filter({ hasText: `vega · ${VEGA_EXECUTION}` })).toBeVisible({ timeout: LIVE_TASK_TIMEOUT_MS });
    await expect(page.getByText(`skill: ${VEGA_EXECUTION}`)).toBeVisible();
  });

  test('auto-route chains implementation work through Rigel and QA work through Vega', async ({ page }) => {
    const prompt = [
      'Write a Python script that converts measurements like Celsius to Fahrenheit or pounds to kilograms.',
      'Then using same requirements create test cases of this in ISTQB style.',
    ].join(' ');
    await page.route('**/api/task', async (route, request) => {
      expect(request.postDataJSON()).toEqual({
        task: prompt,
        skill_id: RIGEL_CODE,
        route_mode: 'auto',
        session_context: [],
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'auto-route-task',
          task_type: 'code_then_qa',
          required_skills: [RIGEL_CODE, VEGA_REQUIREMENTS],
          assigned_agent: 'rigel+vega',
          status: 'complete',
          confidence: 0.66,
          escalated_to_human: false,
          result: {
            code: 'def celsius_to_fahrenheit(value):\n    return value * 9 / 5 + 32',
            language: 'python',
            notes: 'Auto-route completed: Rigel generated the Python program, then Vega generated ISTQB-style test cases.',
            qa_result: {
              test_cases: [{
                tc_id: 'TC-001',
                req_id: 'REQ-001',
                title: 'Convert Celsius to Fahrenheit',
                preconditions: ['Measurement converter is available'],
                steps: ['Enter 0 Celsius', 'Convert to Fahrenheit'],
                expected_result: 'The result is 32 Fahrenheit.',
                test_type: 'positive',
                priority: 'high',
                automated: true,
              }],
              total_count: 1,
            },
          },
        }),
      });
    });

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(prompt);
    await page.getByRole('button', { name: /Send/ }).click();

    await expect(page.locator('.agent-result-name').filter({ hasText: `rigel+vega · ${RIGEL_CODE}` })).toBeVisible({ timeout: LIVE_TASK_TIMEOUT_MS });
    await expect(page.getByText(/Rigel generated the Python program, then Vega generated ISTQB-style test cases/)).toBeVisible();
    await expect(page.getByText('Vega test cases')).toBeVisible();
    await expect(page.getByText('TC-001')).toBeVisible();
    await expect(page.getByText('Convert Celsius to Fahrenheit')).toBeVisible();
    await expect(page.getByText('The result is 32 Fahrenheit.')).toBeVisible();
  });

  test('sends prior Task UI thread context with follow-up requests', async ({ page }) => {
    const firstPrompt = 'Write a Python script that converts Celsius to Fahrenheit.';
    const followUpPrompt = 'Redo it and come back with the same program at 90% confidence.';
    let callCount = 0;

    await page.route('**/api/task', async (route, request) => {
      callCount += 1;
      const body = request.postDataJSON();

      if (callCount === 1) {
        expect(body).toEqual({
          task: firstPrompt,
          skill_id: RIGEL_CODE,
          route_mode: 'auto',
          session_context: [],
        });
      } else {
        expect(body.task).toBe(followUpPrompt);
        expect(body.skill_id).toBe(RIGEL_CODE);
        expect(body.route_mode).toBe('auto');
        expect(body.session_context).toEqual(expect.arrayContaining([
          expect.objectContaining({
            role: 'user',
            skill_id: 'rigel.skill.code_generation',
            content: firstPrompt,
          }),
          expect.objectContaining({
            role: 'agent',
            assigned_agent: 'rigel',
            content: expect.stringContaining('def c_to_f'),
            confidence: 0.6,
          }),
        ]));
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: `mock-context-task-${callCount}`,
          task_type: 'code_generation',
          required_skills: ['rigel.skill.code_generation'],
          assigned_agent: 'rigel',
          status: 'complete',
          confidence: callCount === 1 ? 0.6 : 0.9,
          confidence_breakdown: null,
          gaps: [],
          failure_reason: null,
          escalated_to_human: false,
          issued_at: '2026-05-10T00:00:00Z',
          completed_at: '2026-05-10T00:00:01Z',
          result: {
            code: callCount === 1 ? 'def c_to_f(c):\n    return c * 9 / 5 + 32' : 'def c_to_f(celsius):\n    return celsius * 9 / 5 + 32',
            language: 'python',
            notes: 'mock complete',
          },
        }),
      });
    });

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(firstPrompt);
    await page.getByRole('button', { name: /Send/ }).click();
    await expect(page.locator('.chat-area').getByText('def c_to_f')).toBeVisible();

    await page.getByPlaceholder('Describe what you need — ⌘Enter to send').fill(followUpPrompt);
    await page.getByRole('button', { name: /Send/ }).click();
    await expect(page.locator('.chat-area').getByText('def c_to_f(celsius)')).toBeVisible();
  });

  test('operator gets a visible failure if the live task API returns an error', async ({ page }) => {
    test.setTimeout(240_000);

    await page.locator('.agent-selector-bar select').selectOption(RIGEL_PR_REVIEW);
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

    await expect(outcome).toContainText(`rigel · ${RIGEL_PR_REVIEW}`);
  });
});
