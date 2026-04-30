# Fine-tune Approvals Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Fine-tune Approvals" tab to the Review Queue screen that lets reviewers approve or reject Orion fine-tune candidates, with an inline confirm flow, live badge count, and per-card error handling.

**Architecture:** ReviewQueue.tsx gains a tab bar and conditionally renders either the existing escalations two-panel layout or a new FineTuneTab component. FineTuneTab owns all candidate state including a per-card discriminated-union state machine. A shared `timeAgo` utility and `REVIEWER` constant prevent duplication across files.

**Tech Stack:** React 18, TypeScript, CSS custom properties (existing token system), Playwright + Chromium for e2e tests, Vite dev server on port 5173.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `prism/src/utils/time.ts` | Create | `timeAgo(iso)` — extracted from ReviewQueue.tsx |
| `prism/src/constants/identity.ts` | Create | `REVIEWER` constant `{ name: 'Max', role: 'Admin' }` |
| `prism/src/components/Sidebar.tsx` | Edit | Import REVIEWER instead of hardcoded strings |
| `prism/src/pages/ReviewQueue.tsx` | Edit | Import timeAgo; add tab state + tab bar + conditional rendering |
| `prism/src/pages/FineTuneTab.tsx` | Create | All fine-tune logic: fetch, poll, per-card state machine, UI |
| `prism/src/styles/reviewqueue.css` | Edit | Append tab bar + fine-tune card CSS rules |
| `test/UI/specs/review-queue.spec.ts` | Edit | Add tab bar tests + fine-tune tab tests in new describe blocks |

---

## Task 1: Extract `timeAgo` to a shared utility

**Files:**
- Create: `prism/src/utils/time.ts`
- Modify: `prism/src/pages/ReviewQueue.tsx`

- [ ] **Step 1: Create `prism/src/utils/time.ts`**

```ts
export function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}
```

- [ ] **Step 2: Update `ReviewQueue.tsx` — replace inline definition with import**

At the top of `prism/src/pages/ReviewQueue.tsx`, add this import after the existing imports:

```ts
import { timeAgo } from '../utils/time';
```

Then delete the inline function definition (currently lines 20–27):

```ts
// DELETE this entire block:
function timeAgo(iso: string) {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}
```

- [ ] **Step 3: Verify the existing test still passes (no regression)**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 1 passed (the existing test).

- [ ] **Step 4: Commit**

```bash
git add prism/src/utils/time.ts prism/src/pages/ReviewQueue.tsx
git commit -m "refactor: extract timeAgo to src/utils/time.ts"
```

---

## Task 2: Create `REVIEWER` constant and update Sidebar

**Files:**
- Create: `prism/src/constants/identity.ts`
- Modify: `prism/src/components/Sidebar.tsx`

- [ ] **Step 1: Create `prism/src/constants/identity.ts`**

```ts
export const REVIEWER = { name: 'Max', role: 'Admin' } as const;
```

- [ ] **Step 2: Update Sidebar.tsx — import REVIEWER and use it in the footer**

Add this import near the top of `prism/src/components/Sidebar.tsx` (after the existing imports):

```ts
import { REVIEWER } from '../constants/identity';
```

Find the footer section (currently around lines 226–233) and replace the hardcoded strings:

```tsx
// BEFORE:
<div style={styles.userRow}>
  <div style={styles.avatar}>M</div>
  <div style={styles.userInfo}>
    <span style={styles.userName}>Max</span>
    <span style={styles.userMeta}>Admin · v0.1.0</span>
  </div>
</div>

// AFTER:
<div style={styles.userRow}>
  <div style={styles.avatar}>{REVIEWER.name[0]}</div>
  <div style={styles.userInfo}>
    <span style={styles.userName}>{REVIEWER.name}</span>
    <span style={styles.userMeta}>{REVIEWER.role} · v0.1.0</span>
  </div>
</div>
```

- [ ] **Step 3: Typecheck to confirm no errors**

```bash
cd prism && npm run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add prism/src/constants/identity.ts prism/src/components/Sidebar.tsx
git commit -m "feat: add REVIEWER constant, wire Sidebar to it"
```

---

## Task 3: Add CSS for tab bar and fine-tune cards

**Files:**
- Modify: `prism/src/styles/reviewqueue.css`

- [ ] **Step 1: Append all new CSS rules to `prism/src/styles/reviewqueue.css`**

Add this entire block at the end of the file (after the last existing rule):

```css
/* ── Tab bar ──────────────────────────────────────────────────── */

.rq-tab-bar {
  display: flex;
  align-items: stretch;
  background: var(--bg1);
  border-bottom: 1px solid var(--b1);
  padding: 0 20px;
  flex-shrink: 0;
  height: 36px;
}

.rq-tab {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 500;
  color: var(--t3);
  border-bottom: 2px solid transparent;
  border-top: none;
  border-left: none;
  border-right: none;
  background: none;
  font-family: var(--sans);
  cursor: pointer;
  position: relative;
  top: 1px;
  transition: color 0.12s ease;
  white-space: nowrap;
}

.rq-tab:hover { color: var(--t2); }

.rq-tab-active-esc {
  color: var(--yellow);
  border-bottom-color: var(--yellow);
}

.rq-tab-active-ft {
  color: var(--orion);
  border-bottom-color: var(--orion);
}

.rq-tab-badge {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 10px;
  letter-spacing: 0.02em;
}

.rq-tab-badge-esc { background: rgba(245, 192, 64, 0.12);  color: var(--yellow); }
.rq-tab-badge-ft  { background: rgba(255, 107, 157, 0.15); color: var(--orion);  }

/* ── Fine-tune panel ──────────────────────────────────────────── */

.ft-panel {
  flex: 1;
  overflow-y: auto;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--bg);
}

/* ── Fine-tune card ───────────────────────────────────────────── */

.ft-card {
  background: var(--bg1);
  border: 1px solid var(--b1);
  border-radius: 8px;
  overflow: hidden;
  transition: border-color 0.12s ease;
}

.ft-card-resolved {
  opacity: 0.65;
  pointer-events: none;
}

.ft-card-hdr {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--b1);
  background: var(--bg2);
}

.ft-agent-name {
  font-size: 12.5px;
  font-weight: 600;
}

.ft-version {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--t3);
  margin-left: auto;
}

.ft-body {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ft-row {
  display: flex;
  gap: 24px;
}

.ft-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ft-stat-label {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--t4);
}

.ft-stat-value {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--t1);
}

.ft-trigger {
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--t2);
  line-height: 1.5;
}

.ft-time {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--t4);
}

/* ── Card footer — idle buttons ───────────────────────────────── */

.ft-footer {
  padding: 9px 16px;
  border-top: 1px solid var(--b1);
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-orion-fill {
  background: var(--orion);
  color: #fff;
  border: 1px solid var(--orion);
  font-family: var(--sans);
  font-size: 11px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: opacity 0.12s ease;
}

.btn-orion-fill:hover    { opacity: 0.88; }
.btn-orion-fill:disabled { opacity: 0.45; cursor: not-allowed; }

.btn-orion-outline {
  background: transparent;
  color: var(--orion);
  border: 1px solid rgba(255, 107, 157, 0.3);
  font-family: var(--sans);
  font-size: 11px;
  font-weight: 500;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: border-color 0.12s ease;
}

.btn-orion-outline:hover    { border-color: rgba(255, 107, 157, 0.55); }
.btn-orion-outline:disabled { opacity: 0.45; cursor: not-allowed; }

/* ── Confirm area ─────────────────────────────────────────────── */

.ft-confirm {
  padding: 10px 16px;
  border-top: 1px solid var(--b1);
  background: rgba(255, 107, 157, 0.03);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ft-note-input {
  width: 100%;
  background: var(--bg3);
  border: 1px solid var(--b2);
  border-radius: 4px;
  padding: 7px 10px;
  font-family: var(--sans);
  font-size: 11.5px;
  color: var(--t1);
  outline: none;
  resize: none;
  caret-color: var(--orion);
  transition: border-color 0.12s ease;
}

.ft-note-input:focus       { border-color: rgba(255, 107, 157, 0.4); }
.ft-note-input::placeholder { color: var(--t4); }

.ft-confirm-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.ft-confirm-hint {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--t4);
  flex: 1;
}

/* ── Error states ─────────────────────────────────────────────── */

.ft-error-inline {
  padding: 8px 16px;
  border-top: 1px solid var(--b1);
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--red);
  background: rgba(255, 77, 106, 0.04);
  display: flex;
  align-items: center;
  gap: 10px;
}

.ft-error-retry {
  background: transparent;
  border: 1px solid rgba(255, 77, 106, 0.3);
  color: var(--red);
  font-family: var(--sans);
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 3px;
  cursor: pointer;
  margin-left: auto;
  flex-shrink: 0;
  transition: border-color 0.12s ease;
}

.ft-error-retry:hover { border-color: rgba(255, 77, 106, 0.55); }

/* ── Empty state ──────────────────────────────────────────────── */

.ft-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 24px;
}

.ft-empty-icon {
  font-size: 28px;
  color: var(--orion);
  opacity: 0.4;
}

.ft-empty-text {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--orion);
  opacity: 0.6;
}
```

- [ ] **Step 2: Commit**

```bash
git add prism/src/styles/reviewqueue.css
git commit -m "feat: add tab bar and fine-tune card CSS to reviewqueue.css"
```

---

## Task 4: Add tab bar to ReviewQueue.tsx

**Files:**
- Modify: `prism/src/pages/ReviewQueue.tsx`
- Modify: `test/UI/specs/review-queue.spec.ts`

- [ ] **Step 1: Write the failing tab bar tests**

Append this new describe block to `test/UI/specs/review-queue.spec.ts` (after the closing `});` of the existing describe):

```ts
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 2 new tests fail with "locator.toBeVisible: Error … .rq-tab-bar not found". The original test still passes.

- [ ] **Step 3: Update ReviewQueue.tsx — add tab state, import FineTuneTab, add tab bar JSX**

At the top of `prism/src/pages/ReviewQueue.tsx`, add these imports (after the existing imports):

```ts
import { FineTuneTab } from './FineTuneTab';
```

Inside the `ReviewQueue` function, after the existing `useState` declarations, add:

```ts
const [activeTab, setActiveTab] = useState<'escalations' | 'finetune'>('escalations');
const [ftPendingCount, setFtPendingCount] = useState<number | null>(null);
```

In the JSX, after the closing `</div>` of the topbar and before the `{bannerVisible && ...}` line, insert the tab bar:

```tsx
<div className="rq-tab-bar">
  <button
    className={`rq-tab${activeTab === 'escalations' ? ' rq-tab-active-esc' : ''}`}
    onClick={() => setActiveTab('escalations')}
  >
    Confidence Escalations
    <span className="rq-tab-badge rq-tab-badge-esc">{items.length}</span>
  </button>
  <button
    className={`rq-tab${activeTab === 'finetune' ? ' rq-tab-active-ft' : ''}`}
    onClick={() => setActiveTab('finetune')}
  >
    Fine-tune Approvals
    {ftPendingCount !== null && (
      <span className="rq-tab-badge rq-tab-badge-ft">{ftPendingCount}</span>
    )}
  </button>
</div>
```

Then wrap the existing SLA banner + rq-body section in a conditional, and add the FineTuneTab branch. Replace the current block that starts with `{bannerVisible && (` through the end of `<div className="rq-body"...>...</div>` with:

```tsx
{activeTab === 'escalations' ? (
  <>
    {bannerVisible && (
      <div className="sla-banner">
        <span className="sla-banner-icon">⚠</span>
        <span className="sla-banner-text">
          <span className="sla-banner-bold">
            {items.length > 0 ? `${items.length} task${items.length === 1 ? '' : 's'} pending review.` : 'No pending review tasks.'}
          </span>
          {' '}
          {loadError ?? 'Loaded from /api/review/queue.'}
        </span>
        <button className="sla-dismiss" onClick={() => setBannerVisible(false)}>×</button>
      </div>
    )}

    <div className="rq-body" style={{ marginTop: 14 }}>
      {/* — existing left panel — */}
      <div className="rq-left">
        <div className="rq-left-hdr">
          <span className="rq-left-label">Pending Review</span>
          <span className="rq-count-badge">{items.length} tasks</span>
        </div>

        <div className="rq-list-scroll">
          {items.length === 0 && (
            <div style={{ padding: 16, color: 'var(--t4)', fontFamily: 'var(--mono)', fontSize: 11 }}>
              No live review queue items returned.
            </div>
          )}
          {items.map((item, i) => {
            const cls = slaClass(item.confidence);
            return (
              <div
                key={item.task_id}
                className={`rq-item${selectedIdx === i ? ' rq-item-sel' : ''}`}
                onClick={() => setSelectedIdx(i)}
              >
                <div className="rq-item-top">
                  <span className="rq-skill-id">{item.task_type || item.task_id.slice(0, 8)}</span>
                  <span className={`sla-chip ${cls}`}>{item.status}</span>
                </div>
                <div className="rq-conf-row">
                  <div className="rq-conf-track">
                    <div className="rq-conf-fill" style={{ width: `${(item.confidence ?? 0) * 100}%` }} />
                  </div>
                  <span className="rq-conf-value">{formatConfidence(item.confidence)}</span>
                </div>
                <div className="rq-item-meta">
                  {item.task_id.slice(0, 8)} · {timeAgo(item.created_at)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* — existing right panel — */}
      <div className="rq-right">
        {selected ? (
          <>
            <div className="rq-detail-hdr">
              <div className="rq-detail-hdr-inner">
                <div className="rq-detail-left">
                  <div className="rq-detail-title-row">
                    <span className="rq-detail-title">{selected.task_type || selected.task_id}</span>
                    <span className={`sla-chip ${slaClass(selected.confidence)}`}>{selected.status}</span>
                  </div>
                  <div className="rq-detail-meta">task_id: {selected.task_id}</div>
                  <div className="rq-detail-meta">confidence: {formatConfidence(selected.confidence)} · created: {selected.created_at}</div>
                </div>
                <div className="rq-detail-actions">
                  <button className="btn btn-accept btn-sm" onClick={() => resolveSelected('approve')}>✓ Accept &amp; release</button>
                  <button className="btn btn-rerun btn-sm" disabled>↺ Re-run</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => resolveSelected('reject')}>Reject</button>
                </div>
              </div>
            </div>

            <div className="rq-detail-content">
              <div className="rq-card">
                <div className="rq-card-hdr">
                  <span className="rq-card-label">Confidence Breakdown</span>
                </div>
                <div className="rq-card-body">
                  <div className="cf-overall">
                    <span className="cf-overall-label">Overall confidence</span>
                    <div className="cf-overall-right">
                      <span className="cf-overall-value">{formatConfidence(selected.confidence)}</span>
                      <span className="cf-overall-sub">from review queue item</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="uncertainty-card">
                <div className="uncertainty-title">Captured task payload</div>
                <pre className="uncertainty-text" style={{ whiteSpace: 'pre-wrap' }}>
                  {payloadPreview(selected.payload)}
                </pre>
              </div>

              <div className="rq-card">
                <div className="rq-card-hdr">
                  <span className="rq-card-label">Flagged Test Cases</span>
                  <span className="rq-card-sub">not provided</span>
                </div>
                <div style={{ padding: 14, color: 'var(--t4)', fontFamily: 'var(--mono)', fontSize: 11 }}>
                  No flagged-test endpoint exists for this task. Nothing synthetic is shown.
                </div>
              </div>

              <div className="rq-card">
                <div className="rq-card-hdr">
                  <span className="rq-card-label">Reviewer Notes</span>
                </div>
                <textarea
                  className="notes-textarea"
                  rows={3}
                  placeholder="Add notes for this review. Your decision and notes will be sent to Orion as training signal…"
                  value={reviewerNotes}
                  onChange={(e) => setReviewerNotes(e.target.value)}
                />
                <div className="notes-footer">
                  <div className="notes-footer-dot" />
                  <span className="notes-footer-text">
                    Your decision and notes will be included in the FeedbackEvent emitted to Orion.
                  </span>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="rq-detail-content">
            <div className="rq-card">
              <div style={{ padding: 18, color: 'var(--t4)', fontFamily: 'var(--mono)', fontSize: 11 }}>
                Select a live review item to inspect it. The queue is currently empty.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  </>
) : (
  <FineTuneTab onCountChange={setFtPendingCount} />
)}
```

**Note:** `FineTuneTab` does not exist yet — the app will fail to compile until Task 5. Create a temporary stub to unblock the typecheck:

```tsx
// prism/src/pages/FineTuneTab.tsx (temporary stub — replaced in Task 5)
import React from 'react';
interface Props { onCountChange: (n: number) => void; }
export function FineTuneTab({ onCountChange }: Props) {
  React.useEffect(() => { onCountChange(0); }, []);
  return <div className="ft-panel"><div className="ft-empty"><span className="ft-empty-icon">✦</span><span className="ft-empty-text">Loading…</span></div></div>;
}
export default FineTuneTab;
```

- [ ] **Step 4: Typecheck**

```bash
cd prism && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Run tab bar tests**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 3 passed (original + 2 new tab bar tests).

- [ ] **Step 6: Commit**

```bash
git add prism/src/pages/ReviewQueue.tsx prism/src/pages/FineTuneTab.tsx test/UI/specs/review-queue.spec.ts
git commit -m "feat: add tab bar to Review Queue, stub FineTuneTab"
```

---

## Task 5: FineTuneTab — fetch, empty state, badge callback

**Files:**
- Modify: `prism/src/pages/FineTuneTab.tsx` (replace stub)
- Modify: `test/UI/specs/review-queue.spec.ts`

- [ ] **Step 1: Write the failing empty-state and badge tests**

Append to `test/UI/specs/review-queue.spec.ts`:

```ts
test.describe('Review Queue — fine-tune approvals tab', () => {
  test('shows empty state when no candidates are pending', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await expect(page.locator('.ft-empty-text')).toBeVisible();
    await expect(page.locator('.ft-empty-text')).toHaveText('No fine-tune candidates pending review');
  });

  test('badge shows pending candidate count', async ({ page }) => {
    const candidates = [
      {
        id: 'cand-001', agent_id: 'vega', dataset_version: 'v1.4.2',
        example_count: 128, avg_quality_score: 0.87,
        trigger_reason: 'confidence_drop — 3 consecutive tasks below threshold',
        created_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
        status: 'pending',
      },
      {
        id: 'cand-002', agent_id: 'rigel', dataset_version: 'v0.9.1',
        example_count: 64, avg_quality_score: 0.91,
        trigger_reason: 'manual_flag — reviewer marked 5 outputs for training',
        created_at: new Date(Date.now() - 7 * 3600 * 1000).toISOString(),
        status: 'pending',
      },
    ];
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(candidates) })
    );
    await page.goto('/review-queue');
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('2');
  });
});
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 2 new tests fail ("Loading…" is visible, not the empty state text; badge shows nothing or 0 instead of 2).

- [ ] **Step 3: Replace `prism/src/pages/FineTuneTab.tsx` with the real implementation**

```tsx
import React, { useEffect, useState } from 'react';
import { REVIEWER } from '../constants/identity';
import { timeAgo } from '../utils/time';

export interface FineTuneCandidate {
  id: string;
  agent_id: string;
  dataset_version: string;
  example_count: number;
  avg_quality_score: number;
  trigger_reason: string;
  created_at: string;
  status: 'pending' | 'approved' | 'rejected';
}

const AGENT_COLORS: Record<string, string> = {
  vega:      'var(--green)',
  rigel:     'var(--yellow)',
  andromeda: 'var(--blue)',
  pulsar:    'var(--purple)',
  aether:    'var(--teal)',
  orion:     'var(--orion)',
};

export type CardState =
  | { kind: 'idle' }
  | { kind: 'confirming'; action: 'approve' | 'reject'; note: string }
  | { kind: 'submitting'; action: 'approve' | 'reject'; note: string }
  | { kind: 'approved' }
  | { kind: 'rejected' }
  | { kind: 'error-409' }
  | { kind: 'error-404' }
  | { kind: 'error-network'; action: 'approve' | 'reject'; note: string };

interface Props {
  onCountChange: (n: number) => void;
}

export function FineTuneTab({ onCountChange }: Props) {
  const [candidates, setCandidates] = useState<FineTuneCandidate[]>([]);
  const [cardStates, setCardStates] = useState<Record<string, CardState>>({});

  async function fetchCandidates() {
    try {
      const res = await fetch('/finetune/candidates');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FineTuneCandidate[] = await res.json();
      setCandidates(data);
      setCardStates(prev => {
        const next: Record<string, CardState> = {};
        data.forEach(c => {
          const existing = prev[c.id];
          next[c.id] = existing && existing.kind !== 'idle' ? existing : { kind: 'idle' };
        });
        return next;
      });
      onCountChange(data.filter(c => c.status === 'pending').length);
    } catch {
      // keep existing state on poll failure
    }
  }

  useEffect(() => {
    fetchCandidates();
    const timer = window.setInterval(fetchCandidates, 30_000);
    return () => window.clearInterval(timer);
  }, []);

  function setCardState(id: string, state: CardState) {
    setCardStates(prev => ({ ...prev, [id]: state }));
  }

  async function submit(id: string, action: 'approve' | 'reject', note: string) {
    setCardState(id, { kind: 'submitting', action, note });
    try {
      const res = await fetch(`/finetune/candidates/${id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewed_by: REVIEWER.name, reviewer_note: note }),
      });
      if (res.status === 409) { setCardState(id, { kind: 'error-409' }); return; }
      if (res.status === 404) { setCardState(id, { kind: 'error-404' }); return; }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setCardState(id, action === 'approve' ? { kind: 'approved' } : { kind: 'rejected' });
      onCountChange(candidates.filter(c => c.status === 'pending' && c.id !== id).length);
    } catch {
      setCardState(id, { kind: 'error-network', action, note });
    }
  }

  const pending = candidates.filter(c => c.status === 'pending');

  if (pending.length === 0) {
    return (
      <div className="ft-panel">
        <div className="ft-empty">
          <span className="ft-empty-icon">✦</span>
          <span className="ft-empty-text">No fine-tune candidates pending review</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ft-panel">
      {pending.map(c => {
        const cs: CardState = cardStates[c.id] ?? { kind: 'idle' };
        const isResolved = cs.kind === 'approved' || cs.kind === 'rejected';
        const agentColor = AGENT_COLORS[c.agent_id.toLowerCase()] ?? 'var(--t2)';
        const agentLabel = c.agent_id.charAt(0).toUpperCase() + c.agent_id.slice(1);

        return (
          <div key={c.id} className={`ft-card${isResolved ? ' ft-card-resolved' : ''}`}>
            <div className="ft-card-hdr">
              <span className="ft-agent-name" style={{ color: agentColor }}>{agentLabel}</span>
              <span className="ft-version">{c.dataset_version}</span>
              {cs.kind === 'approved' && <span className="badge badge-green" style={{ marginLeft: 8 }}>Approved</span>}
              {cs.kind === 'rejected' && <span className="badge badge-red"   style={{ marginLeft: 8 }}>Rejected</span>}
            </div>
            <div className="ft-body">
              <div className="ft-row">
                <div className="ft-stat">
                  <span className="ft-stat-label">Examples</span>
                  <span className="ft-stat-value">{c.example_count}</span>
                </div>
                <div className="ft-stat">
                  <span className="ft-stat-label">Avg Quality</span>
                  <span className="ft-stat-value">{c.avg_quality_score.toFixed(2)}</span>
                </div>
              </div>
              <div className="ft-trigger">{c.trigger_reason}</div>
              <div className="ft-time">{timeAgo(c.created_at)}</div>
            </div>

            {cs.kind === 'idle' && (
              <div className="ft-footer">
                <button className="btn-orion-fill"
                  onClick={() => setCardState(c.id, { kind: 'confirming', action: 'approve', note: '' })}>
                  Approve
                </button>
                <button className="btn-orion-outline"
                  onClick={() => setCardState(c.id, { kind: 'confirming', action: 'reject', note: '' })}>
                  Reject
                </button>
              </div>
            )}

            {(cs.kind === 'confirming' || cs.kind === 'submitting') && (
              <div className="ft-confirm">
                <textarea
                  className="ft-note-input"
                  rows={2}
                  placeholder="Optional note (sent to Orion as training signal)…"
                  value={cs.note}
                  onChange={e => setCardState(c.id, { ...cs, note: e.target.value })}
                  disabled={cs.kind === 'submitting'}
                />
                <div className="ft-confirm-row">
                  <span className="ft-confirm-hint">
                    Confirming: {cs.action === 'approve' ? 'Approve' : 'Reject'} · reviewed by {REVIEWER.name}
                  </span>
                  <button className="btn-orion-fill"
                    onClick={() => submit(c.id, cs.action, cs.note)}
                    disabled={cs.kind === 'submitting'}>
                    {cs.kind === 'submitting' ? '…' : 'Confirm'}
                  </button>
                  <button className="btn btn-ghost btn-sm"
                    onClick={() => setCardState(c.id, { kind: 'idle' })}
                    disabled={cs.kind === 'submitting'}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {cs.kind === 'error-409' && (
              <div className="ft-error-inline">
                <span>Already reviewed</span>
              </div>
            )}

            {cs.kind === 'error-404' && (
              <div className="ft-error-inline">
                <span>Candidate not found</span>
              </div>
            )}

            {cs.kind === 'error-network' && (
              <div className="ft-error-inline">
                <span>Network error — changes not saved</span>
                <button className="ft-error-retry"
                  onClick={() => setCardState(c.id, { kind: 'idle' })}>
                  Retry
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default FineTuneTab;
```

- [ ] **Step 4: Typecheck**

```bash
cd prism && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Run tests**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 5 passed (original + 2 tab bar + 2 new fine-tune tests).

- [ ] **Step 6: Commit**

```bash
git add prism/src/pages/FineTuneTab.tsx test/UI/specs/review-queue.spec.ts
git commit -m "feat: implement FineTuneTab with fetch, empty state, and badge callback"
```

---

## Task 6: Add candidate card rendering tests

**Files:**
- Modify: `test/UI/specs/review-queue.spec.ts`

The card rendering and idle-state buttons are already implemented in Task 5. This task adds tests to verify that rendering is correct before building the confirm flow.

- [ ] **Step 1: Write and run card-rendering tests**

Append inside the existing `'Review Queue — fine-tune approvals tab'` describe block in `test/UI/specs/review-queue.spec.ts`:

```ts
  test('renders candidate card with agent name, version, stats, trigger, and buttons', async ({ page }) => {
    const candidates = [{
      id: 'cand-001', agent_id: 'vega', dataset_version: 'v1.4.2',
      example_count: 128, avg_quality_score: 0.87,
      trigger_reason: 'confidence_drop — 3 consecutive tasks below threshold',
      created_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
      status: 'pending',
    }];
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(candidates) })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();

    await expect(page.locator('.ft-agent-name')).toHaveText('Vega');
    await expect(page.locator('.ft-version')).toHaveText('v1.4.2');
    await expect(page.locator('.ft-stat-value').first()).toHaveText('128');
    await expect(page.locator('.ft-stat-value').nth(1)).toHaveText('0.87');
    await expect(page.locator('.ft-trigger')).toContainText('confidence_drop');
    await expect(page.locator('.ft-time')).toContainText('ago');
    await expect(page.locator('.btn-orion-fill')).toBeVisible();
    await expect(page.locator('.btn-orion-outline')).toBeVisible();
  });
```

- [ ] **Step 2: Run**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 6 passed.

- [ ] **Step 3: Commit**

```bash
git add test/UI/specs/review-queue.spec.ts
git commit -m "test: add candidate card rendering assertions for fine-tune tab"
```

---

## Task 7: Add confirm flow tests

**Files:**
- Modify: `test/UI/specs/review-queue.spec.ts`

The confirm flow is already implemented in Task 5. This task adds tests to verify it.

- [ ] **Step 1: Write and run confirm flow tests**

Append inside the `'Review Queue — fine-tune approvals tab'` describe block. The `ONE_CANDIDATE` constant must be inserted **before** the first test that uses it (i.e., at describe scope, right after the opening of the describe block — or placed just before these tests):

```ts
  // Define once at describe scope — used by Tasks 7, 8, 9 tests
  const ONE_CANDIDATE = [{
    id: 'cand-001', agent_id: 'vega', dataset_version: 'v1.4.2',
    example_count: 128, avg_quality_score: 0.87,
    trigger_reason: 'confidence_drop — 3 consecutive tasks below threshold',
    created_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
    status: 'pending',
  }];

  test('Approve button shows confirm area with correct hint text', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await expect(page.locator('.ft-confirm')).toBeVisible();
    await expect(page.locator('.ft-confirm-hint')).toContainText('Confirming: Approve · reviewed by Max');
    await expect(page.locator('.ft-note-input')).toBeVisible();
  });

  test('Reject button shows confirm area with correct hint text', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-outline').click();
    await expect(page.locator('.ft-confirm')).toBeVisible();
    await expect(page.locator('.ft-confirm-hint')).toContainText('Confirming: Reject · reviewed by Max');
  });

  test('Cancel returns card to idle state', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await page.locator('.ft-note-input').fill('test note');
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.locator('.ft-confirm')).not.toBeVisible();
    await expect(page.locator('.btn-orion-fill')).toBeVisible();
  });
```

- [ ] **Step 2: Run**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 9 passed.

- [ ] **Step 3: Commit**

```bash
git add test/UI/specs/review-queue.spec.ts
git commit -m "test: add confirm flow assertions for fine-tune tab"
```

---

## Task 8: Add submission, resolved states, and error handling tests

**Files:**
- Modify: `test/UI/specs/review-queue.spec.ts`

All submission and error handling logic is already implemented in Task 5. This task adds tests to verify each path.

- [ ] **Step 1: Write and run submission and error tests**

Append inside the `'Review Queue — fine-tune approvals tab'` describe block:

```ts
  test('Confirm Approve: POST sent, card shows Approved badge, buttons removed', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    let postedBody = '';
    await page.route('/finetune/candidates/cand-001/approve', async route => {
      postedBody = route.request().postData() ?? '';
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
    });
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await page.locator('.ft-note-input').fill('LGTM');
    await page.locator('.ft-confirm').getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.badge-green')).toBeVisible();
    await expect(page.locator('.badge-green')).toHaveText('Approved');
    await expect(page.locator('.btn-orion-fill')).not.toBeVisible();
    // Verify reviewed_by and reviewer_note in POST body
    const body = JSON.parse(postedBody);
    expect(body.reviewed_by).toBe('Max');
    expect(body.reviewer_note).toBe('LGTM');
  });

  test('Confirm Reject: card shows Rejected badge', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.route('/finetune/candidates/cand-001/reject', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-outline').click();
    await page.locator('.ft-confirm').getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.badge-red')).toBeVisible();
    await expect(page.locator('.badge-red')).toHaveText('Rejected');
    await expect(page.locator('.btn-orion-outline')).not.toBeVisible();
  });

  test('409 response shows inline Already reviewed message', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.route('/finetune/candidates/cand-001/approve', route =>
      route.fulfill({ status: 409, body: '' })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await page.locator('.ft-confirm').getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.ft-error-inline')).toContainText('Already reviewed');
    await expect(page.locator('.ft-error-retry')).not.toBeVisible();
  });

  test('404 response shows inline Candidate not found message', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.route('/finetune/candidates/cand-001/approve', route =>
      route.fulfill({ status: 404, body: '' })
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await page.locator('.ft-confirm').getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.ft-error-inline')).toContainText('Candidate not found');
    await expect(page.locator('.ft-error-retry')).not.toBeVisible();
  });

  test('network error shows retry button; clicking retry resets card to idle', async ({ page }) => {
    await page.route('/finetune/candidates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ONE_CANDIDATE) })
    );
    await page.route('/finetune/candidates/cand-001/approve', route =>
      route.abort('failed')
    );
    await page.goto('/review-queue');
    await page.locator('.rq-tab').nth(1).click();
    await page.locator('.btn-orion-fill').click();
    await page.locator('.ft-confirm').getByRole('button', { name: 'Confirm' }).click();
    await expect(page.locator('.ft-error-retry')).toBeVisible();
    await expect(page.locator('.ft-error-inline')).toContainText('Network error');
    await page.locator('.ft-error-retry').click();
    await expect(page.locator('.ft-error-inline')).not.toBeVisible();
    await expect(page.locator('.btn-orion-fill')).toBeVisible();
  });
```

- [ ] **Step 2: Run all tests**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 14 passed.

- [ ] **Step 3: Commit**

```bash
git add test/UI/specs/review-queue.spec.ts
git commit -m "test: add submission, resolved state, and error handling assertions"
```

---

## Task 9: Verify 30s polling updates the badge

**Files:**
- Modify: `test/UI/specs/review-queue.spec.ts`

The 30s `setInterval` is already wired in Task 5. This task verifies it fires and updates the badge by using Playwright's fake-clock API.

- [ ] **Step 1: Write and run the polling test**

Append inside the `'Review Queue — fine-tune approvals tab'` describe block:

```ts
  test('badge count updates after 30s poll returns new data', async ({ page }) => {
    let callCount = 0;
    await page.route('/finetune/candidates', route => {
      callCount += 1;
      const body = callCount === 1
        ? JSON.stringify([{
            id: 'cand-001', agent_id: 'vega', dataset_version: 'v1.4.2',
            example_count: 128, avg_quality_score: 0.87,
            trigger_reason: 'initial', status: 'pending',
            created_at: new Date().toISOString(),
          }])
        : JSON.stringify([
            {
              id: 'cand-001', agent_id: 'vega', dataset_version: 'v1.4.2',
              example_count: 128, avg_quality_score: 0.87,
              trigger_reason: 'initial', status: 'pending',
              created_at: new Date().toISOString(),
            },
            {
              id: 'cand-002', agent_id: 'rigel', dataset_version: 'v0.9.1',
              example_count: 64, avg_quality_score: 0.91,
              trigger_reason: 'new candidate', status: 'pending',
              created_at: new Date().toISOString(),
            },
          ]);
      route.fulfill({ status: 200, contentType: 'application/json', body });
    });

    await page.clock.install({ time: 0 });
    await page.goto('/review-queue');
    // Initial badge = 1
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('1');
    // Advance clock 30s to trigger the poll
    await page.clock.tick(30_000);
    // Badge should update to 2
    await expect(page.locator('.rq-tab-badge-ft')).toHaveText('2');
  });
```

- [ ] **Step 2: Run all tests**

```bash
cd test/UI && npx playwright test specs/review-queue.spec.ts --project=chromium
```

Expected: 15 passed.

- [ ] **Step 3: Commit**

```bash
git add test/UI/specs/review-queue.spec.ts
git commit -m "test: verify 30s polling updates fine-tune tab badge count"
```

---

## Final verification

- [ ] **Run full test suite**

```bash
cd test/UI && npx playwright test --project=chromium
```

Expected: all tests pass including the navigation-and-dashboard, settings, and task-submission specs.

- [ ] **Typecheck**

```bash
cd prism && npm run typecheck
```

Expected: no errors.

- [ ] **Smoke-check in browser** — start the dev server, open http://127.0.0.1:5173/review-queue, verify:
  1. Tab bar visible, "Confidence Escalations" active with yellow underline
  2. Escalations layout unchanged; SLA banner visible
  3. Click "Fine-tune Approvals" tab — Orion (#ff6b9d) underline, existing escalations layout gone
  4. Empty state or candidate cards depending on what the API returns
  5. Badge count visible on Fine-tune tab
