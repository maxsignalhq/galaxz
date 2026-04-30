import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const prismDir = path.resolve(__dirname, '../../prism');

export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  timeout: 240_000,
  expect: {
    timeout: 30_000,
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: process.env.PRISM_BASE_URL ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: process.env.PRISM_BASE_URL
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1',
        cwd: prismDir,
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  workers: process.env.CI ? 1 : 2,
  outputDir: 'test-results',
});
