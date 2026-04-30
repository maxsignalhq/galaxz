# Fine-tune Approvals Tab — Design Spec

**Date:** 2026-04-29  
**Status:** Approved  
**Screen:** Review Queue (`/review-queue`)

---

## Summary

Add a "Fine-tune Approvals" second tab to the Review Queue screen. The first tab (Confidence Escalations) is unchanged. The new tab lets reviewers approve or reject Orion fine-tune candidates, with an inline confirm flow and live badge count.

---

## Design Tokens

All mandatory — no exceptions, no new tokens:

| Token | Value | Usage |
|-------|-------|-------|
| `--bg` | `#07090e` | Page background |
| `--orion` | `#ff6b9d` | Tab indicator, Approve button fill, badge |
| `--sans` | Geist | Body text |
| `--mono` | Geist Mono | Code-like fields: version, trigger reason, timestamps |

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `prism/src/constants/identity.ts` | New | Exports `REVIEWER` constant |
| `prism/src/utils/time.ts` | New | Exports `timeAgo()` — extracted from ReviewQueue.tsx |
| `prism/src/components/Sidebar.tsx` | Edit | Import `REVIEWER` instead of hardcoded strings |
| `prism/src/pages/ReviewQueue.tsx` | Edit | Tab state + tab bar; conditional rendering; imports `timeAgo` from utils |
| `prism/src/pages/FineTuneTab.tsx` | New | All fine-tune logic and UI; imports `timeAgo` from utils |
| `prism/src/styles/reviewqueue.css` | Edit | Tab bar styles + fine-tune card styles |

---

## Reviewer Identity

`prism/src/constants/identity.ts` exports a single constant:

```ts
export const REVIEWER = { name: 'Max', role: 'Admin' } as const;
```

`Sidebar.tsx` imports and uses it for the footer user row (replacing the current hardcoded strings). `FineTuneTab.tsx` imports `REVIEWER.name` to pass as `reviewed_by` in POST bodies. No React context, no Settings store — matches the existing "everything is local state" codebase pattern.

---

## Layout

```
┌─ topbar (sticky, 48px) ──────────────────────────────────────┐
├─ tab bar (36px) ─────────────────────────────────────────────┤
│  [Confidence Escalations ·3]   [Fine-tune Approvals ·5]      │
├──────────────────────────────────────────────────────────────┤
│  tab content (flex: 1, scrollable)                           │
└──────────────────────────────────────────────────────────────┘
```

**Tab bar rules:**
- Sits between topbar and body, `background: var(--bg1)`, `border-bottom: 1px solid var(--b1)`
- Active tab underline: `--yellow` for Escalations tab, `--orion` for Fine-tune tab
- Badge on each tab: pending count, re-fetched every 30s for the Fine-tune tab
- Fine-tune badge uses `badge-orion` class from existing token system

**When Escalations tab is active:** existing `rq-body` two-panel layout renders unchanged, including the SLA banner (which lives inside the escalations content area, below the tab bar).

**When Fine-tune tab is active:** full-width scrollable card list replaces the body.

---

## Data Model

```ts
interface FineTuneCandidate {
  id: string;
  agent_id: string;          // maps to agent color token
  dataset_version: string;   // Geist Mono
  example_count: number;
  avg_quality_score: number; // displayed to 2dp
  trigger_reason: string;    // Geist Mono, smaller font
  created_at: string;        // ISO → relative time via existing timeAgo()
  status: 'pending' | 'approved' | 'rejected';
}
```

**Agent → color mapping** (existing tokens only):

```ts
const AGENT_COLORS: Record<string, string> = {
  vega:      'var(--green)',
  rigel:     'var(--yellow)',
  andromeda: 'var(--blue)',
  pulsar:    'var(--purple)',
  aether:    'var(--teal)',
  orion:     'var(--orion)',
};
// fallback: var(--t2)
```

---

## API Integration

| Endpoint | When called |
|----------|-------------|
| `GET /finetune/candidates` | On mount + every 30s |
| `POST /finetune/candidates/{id}/approve` | On Confirm (approve flow) |
| `POST /finetune/candidates/{id}/reject` | On Confirm (reject flow) |

POST body: `{ reviewed_by: REVIEWER.name, reviewer_note: string }` (note is empty string if blank).

The 30s poll only updates cards currently in `idle` state — it does not overwrite a card that is mid-confirm or already resolved.

---

## Card Layout

Each pending candidate renders as one card:

```
┌─ header ────────────────────────────────────────────────────┐
│  [Agent name — agent color]   [role]        dataset v1.4.2  │
├─ body ──────────────────────────────────────────────────────┤
│  Examples: 128   Avg quality: 0.87                          │
│  trigger_reason text in Geist Mono, smaller                 │
│  3 hours ago                                                │
├─ footer (idle) ─────────────────────────────────────────────┤
│  [Approve ● orion fill]   [Reject ○ orion outline]          │
└─────────────────────────────────────────────────────────────┘
```

**Confirm state** (either button clicked — inline, replaces footer):
```
├─ confirm area ──────────────────────────────────────────────┤
│  [optional note textarea]                                   │
│  "Confirming: Approve · reviewed by Max"   [Confirm] [Cancel]│
└─────────────────────────────────────────────────────────────┘
```

**Resolved state** (terminal):
- Status badge (Approved → `badge-green`, Rejected → `badge-red`) in the header
- Footer removed
- Card dimmed to 65% opacity

**Empty state** (no pending candidates):
- Centered in the content area
- Orion-colored icon + text: "No fine-tune candidates pending review"
- Uses `var(--orion)` for both icon and text color

---

## Card State Machine

```
idle
  ├─ Approve → confirming-approve
  └─ Reject  → confirming-reject

confirming-approve | confirming-reject
  ├─ Cancel  → idle
  └─ Confirm → submitting

submitting
  ├─ 200         → approved | rejected   (terminal)
  ├─ 409         → error-409             (terminal: inline "Already reviewed")
  ├─ 404         → error-404             (terminal: inline "Candidate not found")
  └─ other/throw → error-network         (retryable)

error-network
  └─ Retry → idle  (note cleared)
```

State is stored in `FineTuneTab.tsx` as `Record<string, CardState>` where `CardState` is a discriminated union. Cards in non-idle states are excluded from poll updates.

---

## Component Structure

**`ReviewQueue.tsx` additions:**
```ts
type Tab = 'escalations' | 'finetune';
const [activeTab, setActiveTab] = useState<Tab>('escalations');
const [ftPendingCount, setFtPendingCount] = useState<number | null>(null);
```

The tab bar renders above the existing body. When `activeTab === 'escalations'`, the existing layout renders unchanged. When `activeTab === 'finetune'`, `<FineTuneTab onCountChange={setFtPendingCount} />` renders instead.

`ftPendingCount` is passed up from `FineTuneTab` via a callback so ReviewQueue can display the badge even when the escalations tab is active.

**`FineTuneTab.tsx`:**
- Props: `{ onCountChange: (n: number) => void }`
- Manages: candidates fetch, 30s poll interval, per-card `CardState` map
- Renders: empty state or card list
- Imports `timeAgo()` from `src/utils/time.ts` (extracted from ReviewQueue.tsx)

---

## CSS Additions (`reviewqueue.css`)

New rule groups to add:
1. `.rq-tab-bar`, `.rq-tab`, `.rq-tab-active-esc`, `.rq-tab-active-ft`, `.rq-tab-badge`
2. `.ft-panel`, `.ft-card`, `.ft-card-hdr`, `.ft-agent-name`, `.ft-version`
3. `.ft-body`, `.ft-row`, `.ft-stat`, `.ft-trigger`, `.ft-time`
4. `.ft-footer`, `.btn-orion-fill`, `.btn-orion-outline`
5. `.ft-confirm`, `.ft-note-input`, `.ft-confirm-row`, `.ft-confirm-hint`
6. `.ft-empty`, `.ft-empty-icon`, `.ft-empty-text`

No modifications to any existing rules.

---

## Acceptance Criteria

- [ ] Tab bar renders with Orion (#ff6b9d) underline on Fine-tune tab
- [ ] Confidence Escalations tab and its layout are visually unchanged
- [ ] SLA banner appears inside the escalations tab content area
- [ ] Fine-tune badge count updates every 30 seconds
- [ ] Empty state renders when no candidates are pending
- [ ] Approve flow: Approve → note field → Confirm → POST → Approved badge
- [ ] Reject flow: Reject → note field → Confirm → POST → Rejected badge
- [ ] 409 response shows inline "Already reviewed" (no retry)
- [ ] 404 response shows inline "Candidate not found" (no retry)
- [ ] Network error shows inline Retry button; Retry resets card to idle
- [ ] `reviewed_by` in POST body equals "Max" (from `REVIEWER.name`)
- [ ] No new color tokens introduced — only existing token system used
- [ ] `timeAgo()` function is not duplicated between files
