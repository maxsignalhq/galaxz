import React, { useCallback, useEffect, useState } from 'react';
import { REVIEWER } from '../constants/identity';
import { timeAgo } from '../utils/time';

interface Props {
  onCountChange: (n: number) => void;
}

export interface FineTuneCandidate {
  candidate_id: string;
  agent_id: string;
  example_count: number;
  quality_avg: number;
  emitted_at: string;
  status: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  reviewer_note?: string | null;
}

type ReviewAction = 'approve' | 'reject';

type CardState =
  | { mode: 'idle' }
  | { mode: 'confirm'; action: ReviewAction; note: string }
  | { mode: 'submitting'; action: ReviewAction; note: string }
  | { mode: 'error'; message: string };

const IDLE: CardState = { mode: 'idle' };

function shortId(id: string): string {
  return id.slice(0, 8);
}

function formatQuality(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : '--';
}

function loadCandidatesFromResponse(value: unknown): FineTuneCandidate[] {
  if (Array.isArray(value)) return value as FineTuneCandidate[];
  if (
    typeof value === 'object'
    && value !== null
    && Array.isArray((value as { candidates?: unknown }).candidates)
  ) {
    return (value as { candidates: FineTuneCandidate[] }).candidates;
  }
  return [];
}

function actionLabel(action: ReviewAction): string {
  return action === 'approve' ? 'Approve' : 'Reject';
}

export function FineTuneTab({ onCountChange }: Props) {
  const [candidates, setCandidates] = useState<FineTuneCandidate[]>([]);
  const [cardStates, setCardStates] = useState<Record<string, CardState>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadCandidates = useCallback(async () => {
    try {
      const res = await fetch('/api/finetune/candidates');
      if (!res.ok) throw new Error(`finetune candidates HTTP ${res.status}`);
      const data = loadCandidatesFromResponse(await res.json());
      const pending = data.filter((candidate) => candidate.status === 'pending');

      setCandidates(pending);
      onCountChange(pending.length);
      setCardStates((prev) => {
        const next: Record<string, CardState> = {};
        const pendingIds = new Set(pending.map((candidate) => candidate.candidate_id));
        for (const candidate of pending) {
          const current = prev[candidate.candidate_id];
          next[candidate.candidate_id] = current && current.mode !== 'idle' ? current : IDLE;
        }
        for (const [candidateId, state] of Object.entries(prev)) {
          if (!pendingIds.has(candidateId) && state.mode === 'submitting') {
            next[candidateId] = state;
          }
        }
        return next;
      });
      setLoadError(null);
    } catch (err) {
      setLoadError(String(err));
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    void loadCandidates();
    const timer = window.setInterval(() => void loadCandidates(), 30000);
    return () => window.clearInterval(timer);
  }, [loadCandidates]);

  function setCardState(candidateId: string, state: CardState) {
    setCardStates((prev) => ({ ...prev, [candidateId]: state }));
  }

  async function submitDecision(candidate: FineTuneCandidate, action: ReviewAction, note: string) {
    setCardState(candidate.candidate_id, { mode: 'submitting', action, note });
    try {
      const res = await fetch(`/api/finetune/candidates/${candidate.candidate_id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reviewed_by: REVIEWER.name,
          reviewer_note: note.trim() || undefined,
        }),
      });
      if (!res.ok) throw new Error(`review ${action} HTTP ${res.status}: ${await res.text()}`);

      setCandidates((prev) => {
        const updated = prev.filter((item) => item.candidate_id !== candidate.candidate_id);
        onCountChange(updated.length);
        return updated;
      });
      setCardStates((prev) => {
        const next = { ...prev };
        delete next[candidate.candidate_id];
        return next;
      });
    } catch (err) {
      setCardState(candidate.candidate_id, { mode: 'error', message: String(err) });
    }
  }

  if (loading) {
    return (
      <div className="ft-panel">
        <div className="ft-empty">
          <span className="ft-empty-icon">✦</span>
          <span className="ft-empty-text">Loading fine-tune candidates…</span>
        </div>
      </div>
    );
  }

  if (candidates.length === 0) {
    return (
      <div className="ft-panel">
        {loadError && (
          <div className="ft-error-inline">
            <span>{loadError}</span>
            <button className="ft-error-retry" onClick={() => void loadCandidates()}>Retry</button>
          </div>
        )}
        <div className="ft-empty">
          <span className="ft-empty-icon">✦</span>
          <span className="ft-empty-text">No fine-tune candidates pending review</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ft-panel">
      {loadError && (
        <div className="ft-error-inline">
          <span>{loadError}</span>
          <button className="ft-error-retry" onClick={() => void loadCandidates()}>Retry</button>
        </div>
      )}

      {candidates.map((candidate) => {
        const state = cardStates[candidate.candidate_id] ?? IDLE;
        const isConfirm = state.mode === 'confirm';
        const isSubmitting = state.mode === 'submitting';

        return (
          <article key={candidate.candidate_id} className="ft-card">
            <div className="ft-card-hdr">
              <span className="ft-agent-name">{candidate.agent_id}</span>
              <span className="sla-chip sla-ok">{candidate.status}</span>
              <span className="ft-version">candidate {shortId(candidate.candidate_id)}</span>
            </div>

            <div className="ft-body">
              <div className="ft-row">
                <div className="ft-stat">
                  <span className="ft-stat-label">examples</span>
                  <span className="ft-stat-value">{candidate.example_count.toLocaleString()}</span>
                </div>
                <div className="ft-stat">
                  <span className="ft-stat-label">quality avg</span>
                  <span className="ft-stat-value">{formatQuality(candidate.quality_avg)}</span>
                </div>
                <div className="ft-stat">
                  <span className="ft-stat-label">reviewer</span>
                  <span className="ft-stat-value">{REVIEWER.name}</span>
                </div>
              </div>
              <div className="ft-trigger">
                Orion detected enough high-quality {candidate.agent_id} examples to prepare a fine-tune candidate.
              </div>
              <div className="ft-time">emitted {timeAgo(candidate.emitted_at)}</div>
            </div>

            {state.mode === 'idle' && (
              <div className="ft-footer">
                <button
                  className="btn-orion-fill"
                  onClick={() => setCardState(candidate.candidate_id, { mode: 'confirm', action: 'approve', note: '' })}
                >
                  Approve
                </button>
                <button
                  className="btn-orion-outline"
                  onClick={() => setCardState(candidate.candidate_id, { mode: 'confirm', action: 'reject', note: '' })}
                >
                  Reject
                </button>
              </div>
            )}

            {isConfirm && (
              <div className="ft-confirm">
                <textarea
                  className="ft-note-input"
                  rows={3}
                  placeholder="Optional note (sent to Orion as training signal)…"
                  value={state.note}
                  onChange={(event) => setCardState(candidate.candidate_id, {
                    mode: 'confirm',
                    action: state.action,
                    note: event.target.value,
                  })}
                />
                <div className="ft-confirm-row">
                  <span className="ft-confirm-hint">
                    Confirm {state.action} for {candidate.agent_id} candidate {shortId(candidate.candidate_id)}
                  </span>
                  <button
                    className={state.action === 'approve' ? 'btn-orion-fill' : 'btn-orion-outline'}
                    onClick={() => void submitDecision(candidate, state.action, state.note)}
                  >
                    Confirm {actionLabel(state.action)}
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => setCardState(candidate.candidate_id, IDLE)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {isSubmitting && (
              <div className="ft-confirm">
                <div className="ft-confirm-row">
                  <span className="ft-confirm-hint">{actionLabel(state.action)} submitting…</span>
                </div>
              </div>
            )}

            {state.mode === 'error' && (
              <div className="ft-error-inline">
                <span>{state.message}</span>
                <button className="ft-error-retry" onClick={() => setCardState(candidate.candidate_id, IDLE)}>
                  Dismiss
                </button>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

export default FineTuneTab;
