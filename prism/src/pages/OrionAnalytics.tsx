import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/orion.css';

type OrionStatus = {
  status: string;
  mode: string;
  db_path: string;
  event_count: number;
  dataset_path: string;
  dataset_files: string[];
  training_examples: number;
};

function formatCount(value: number | undefined) {
  return typeof value === 'number' ? value.toLocaleString() : '—';
}

function EmptyAnalytics({ title, text, badge }: { title: string; text: string; badge: string }) {
  return (
    <div className="oa-empty">
      <span className="oa-empty-icon">∅</span>
      <span className="oa-empty-title">{title}</span>
      <p className="oa-empty-text">{text}</p>
      <span className="oa-empty-badge">{badge}</span>
    </div>
  );
}

function FeedbackVolumeCard({ status }: { status: OrionStatus | null }) {
  return (
    <div className="oa-card orion-border">
      <div className="oa-card-head">
        <span className="oa-card-title orion">Feedback Event Volume</span>
        <span className="oa-card-meta">from Orion event log</span>
      </div>
      <div className="oa-card-body">
        <div className="fv-trend-row">
          <div className="fv-stat">
            <span className="fv-stat-value" style={{ color: 'var(--orion)' }}>
              {formatCount(status?.event_count)}
            </span>
            <span className="fv-stat-label">stored events</span>
          </div>
          <div className="fv-stat">
            <span className="fv-stat-value" style={{ color: 'var(--t2)' }}>—</span>
            <span className="fv-stat-label">per day avg</span>
          </div>
          <div className="fv-stat">
            <span className="fv-stat-value" style={{ color: 'var(--green)' }}>—</span>
            <span className="fv-stat-label">human-verified</span>
          </div>
        </div>

        <div className="fv-chart-wrap">
          <EmptyAnalytics
            title="No time-series endpoint yet"
            text="Orion exposes the current event count, but not a daily bucketed event series. The chart stays empty until that data exists."
            badge="no derived chart data"
          />
        </div>
      </div>
    </div>
  );
}

function TrainingRunsCard({ status }: { status: OrionStatus | null }) {
  return (
    <div className="oa-card orion-border">
      <div className="oa-card-head">
        <span className="oa-card-title orion">Training Runs</span>
        <span className="oa-card-meta">not reported by API</span>
      </div>
      <EmptyAnalytics
        title="No training-run data available"
        text={`Orion reports ${formatCount(status?.training_examples)} curated training examples, but no training-run history endpoint exists yet.`}
        badge="training runs unavailable"
      />
    </div>
  );
}

function DriftMonitorCard() {
  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title green">Drift Monitor</span>
        <span className="oa-card-meta">not reported by API</span>
      </div>
      <div className="oa-card-body">
        <EmptyAnalytics
          title="No drift metrics available"
          text="The backend currently runs Orion heuristic cycles, but Prism has no drift-metric endpoint to render. No synthetic sigma values are shown."
          badge="awaiting real drift data"
        />
      </div>
    </div>
  );
}

function DatasetCard({ status }: { status: OrionStatus | null }) {
  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title">Dataset Breakdown</span>
        <span className="oa-card-meta">from dataset directory</span>
      </div>
      <div className="oa-empty compact">
        <span className="oa-empty-icon">📊</span>
        <span className="oa-empty-title">
          {status && status.dataset_files.length > 0 ? `${status.dataset_files.length} dataset files` : 'No dataset files yet'}
        </span>
        <p className="oa-empty-text">
          {status && status.dataset_files.length > 0
            ? status.dataset_files.join(', ')
            : 'Orion has not created any JSONL dataset files yet.'}
        </p>
        <span className="oa-empty-badge">{formatCount(status?.training_examples)} examples</span>
      </div>
    </div>
  );
}

function AetherStreamCard({ status }: { status: OrionStatus | null }) {
  const rows = [
    { dotClass: 'stream-dot-green', key: 'Orion service', val: status?.status ?? 'unknown', valStyle: { color: 'var(--green)' } },
    { dotClass: 'stream-dot-teal', key: 'Mode', val: status?.mode ?? '—', valStyle: {} },
    { dotClass: 'stream-dot-yellow', key: 'Stored events', val: formatCount(status?.event_count), valStyle: { color: 'var(--yellow)' } },
    { dotClass: 'stream-dot-muted', key: 'Event DB', val: status?.db_path ?? '—', valStyle: { color: 'var(--t4)' } },
    { dotClass: 'stream-dot-muted', key: 'Dataset path', val: status?.dataset_path ?? '—', valStyle: { color: 'var(--t4)' } },
  ];

  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title teal">Aether / Orion Status</span>
        <span className="oa-card-meta">live</span>
      </div>
      <div className="oa-card-body">
        <div className="stream-rows">
          {rows.map((r) => (
            <div key={r.key} className="stream-row">
              <div className={`stream-dot ${r.dotClass}`} />
              <span className="stream-key">{r.key}</span>
              <span className="stream-val" style={r.valStyle}>{r.val}</span>
            </div>
          ))}
        </div>
        <div className="oa-card-footer">
          Values are returned by /api/orion/status. Stream lag and pending-event counts are not exposed yet.
        </div>
      </div>
    </div>
  );
}

function AgentPerformanceCard() {
  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title">Agent Performance — from Feedback Events</span>
        <span className="oa-card-meta">not reported by API</span>
      </div>
      <EmptyAnalytics
        title="No agent performance aggregates yet"
        text="The backend does not currently expose agent-level confidence, task-count, or routing-improvement aggregates. This panel intentionally avoids synthetic values."
        badge="awaiting aggregate endpoint"
      />
    </div>
  );
}

export function OrionAnalytics() {
  const [status, setStatus] = useState<OrionStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch('/api/orion/status');
        if (!res.ok) throw new Error(`orion status HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) {
          setStatus(data);
          setLoadError(null);
        }
      } catch (err) {
        if (!cancelled) setLoadError(String(err));
      }
    }

    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <div className="app-shell">
      <Sidebar activeId="orion" />

      <div className="app-main">
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Orion Analytics</span>
            <span className="topbar-sub">— learning layer · feedback refinery</span>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost btn-sm" disabled>Export events</button>
            <button
              className="btn btn-sm"
              style={{
                background: 'rgba(255,107,157,0.08)',
                border: '1px solid rgba(255,107,157,0.2)',
                color: 'var(--orion)',
                opacity: 0.5,
                cursor: 'not-allowed',
              }}
              disabled
            >
              Run training
            </button>
          </div>
        </div>

        <div className="app-content">
          <div className="phase3-banner">
            <span className="phase3-icon">🔭</span>
            <div className="phase3-text">
              <div className="phase3-title">Orion status: {status?.status ?? 'loading'}</div>
              <div className="phase3-sub">
                {loadError
                  ? `Unable to load Orion status: ${loadError}`
                  : 'This page only renders values returned by the backend. Missing analytics stay empty until an endpoint provides them.'}
              </div>
            </div>
            <span className="phase3-badge">{status?.mode ?? 'live check'}</span>
          </div>

          <div className="oa-metrics">
            <div className="oa-metric-card">
              <div className="oa-metric-label">FeedbackEvents stored</div>
              <div className="oa-metric-value" style={{ color: 'var(--orion)' }}>{formatCount(status?.event_count)}</div>
              <div className="oa-metric-delta" style={{ color: 'var(--t3)' }}>from event log</div>
            </div>
            <div className="oa-metric-card">
              <div className="oa-metric-label">Training examples</div>
              <div className="oa-metric-value" style={{ color: 'var(--t4)' }}>{formatCount(status?.training_examples)}</div>
              <div className="oa-metric-delta" style={{ color: 'var(--t3)' }}>from dataset files</div>
            </div>
            <div className="oa-metric-card">
              <div className="oa-metric-label">Routing improvement</div>
              <div className="oa-metric-value" style={{ color: 'var(--t4)' }}>—</div>
              <div className="oa-metric-delta" style={{ color: 'var(--t3)' }}>not exposed</div>
            </div>
            <div className="oa-metric-card">
              <div className="oa-metric-label">Drift alerts</div>
              <div className="oa-metric-value" style={{ color: 'var(--t4)' }}>—</div>
              <div className="oa-metric-delta" style={{ color: 'var(--t3)' }}>not exposed</div>
            </div>
          </div>

          <div className="oa-row oa-row-2">
            <FeedbackVolumeCard status={status} />
            <TrainingRunsCard status={status} />
          </div>

          <div className="oa-row oa-row-3">
            <DriftMonitorCard />
            <DatasetCard status={status} />
            <AetherStreamCard status={status} />
          </div>

          <div className="oa-row" style={{ gridTemplateColumns: '1fr' }}>
            <AgentPerformanceCard />
          </div>
        </div>
      </div>
    </div>
  );
}

export default OrionAnalytics;
