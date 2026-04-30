import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/reviewqueue.css';

interface QueueItem {
  id: number;
  task_id: string;
  task_type: string;
  confidence: number | null;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
}

function formatConfidence(value: number | null) {
  return typeof value === 'number' ? value.toFixed(2) : '—';
}

function timeAgo(iso: string) {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

function slaClass(confidence: number | null): 'sla-urgent' | 'sla-warn' | 'sla-ok' {
  if (confidence === null) return 'sla-warn';
  if (confidence < 0.4) return 'sla-urgent';
  if (confidence < 0.65) return 'sla-warn';
  return 'sla-ok';
}

function payloadPreview(payload: Record<string, unknown>) {
  const text = JSON.stringify(payload, null, 2);
  return text === '{}' ? 'No payload captured for this review item.' : text;
}

export function ReviewQueue() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [bannerVisible, setBannerVisible] = useState(true);
  const [reviewerNotes, setReviewerNotes] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  async function loadQueue() {
    try {
      const res = await fetch('/api/review/queue');
      if (!res.ok) throw new Error(`review queue HTTP ${res.status}`);
      const data = await res.json();
      setItems(data);
      setSelectedIdx((idx) => Math.min(idx, Math.max(0, data.length - 1)));
      setLoadError(null);
    } catch (err) {
      setLoadError(String(err));
    }
  }

  useEffect(() => {
    loadQueue();
    const timer = window.setInterval(loadQueue, 15000);
    return () => window.clearInterval(timer);
  }, []);

  async function resolveSelected(decision: 'approve' | 'reject') {
    const selected = items[selectedIdx];
    if (!selected) return;

    const res = await fetch(`/api/review/queue/${selected.task_id}/${decision}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer_notes: reviewerNotes }),
    });
    if (!res.ok) {
      setLoadError(`resolve ${decision} HTTP ${res.status}: ${await res.text()}`);
      return;
    }
    setReviewerNotes('');
    await loadQueue();
  }

  const selected = items[selectedIdx] ?? null;

  return (
    <div className="app-shell">
      <Sidebar activeId="review-queue" />

      <div className="app-main">
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Review Queue</span>
            <span className="topbar-sub">— live pending tasks · human review required</span>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost btn-sm" onClick={loadQueue}>Refresh</button>
          </div>
        </div>

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
      </div>
    </div>
  );
}

export default ReviewQueue;
