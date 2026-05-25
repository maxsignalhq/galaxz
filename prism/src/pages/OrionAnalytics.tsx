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

type VolumeBucket = { bucket: string; count: number };
type DomainRow = { domain: string; count: number };
type AgentRow = { agent_id: string; count: number; avg_confidence: number; success_rate: number };

type OrionAnalyticsData = {
  event_volume: VolumeBucket[];
  by_domain: DomainRow[];
  by_agent: AgentRow[];
  outcome_counts: Record<string, number>;
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

function labelHour(iso: string) {
  const h = parseInt(iso.slice(11, 13), 10);
  if (h === 0) return '12a';
  if (h === 12) return '12p';
  return h < 12 ? `${h}a` : `${h - 12}p`;
}

function FeedbackVolumeCard({ status, analytics }: { status: OrionStatus | null; analytics: OrionAnalyticsData | null }) {
  const buckets = analytics?.event_volume ?? [];
  const maxCount = Math.max(...buckets.map(b => b.count), 1);
  const totalToday = buckets.reduce((s, b) => s + b.count, 0);
  const outcomes = analytics?.outcome_counts ?? {};
  const successCount = outcomes['success'] ?? 0;
  const successRate = (status?.event_count ?? 0) > 0
    ? Math.round((successCount / (status?.event_count ?? 1)) * 100)
    : null;

  const showEvery = buckets.length <= 12 ? 1 : Math.ceil(buckets.length / 8);

  return (
    <div className="oa-card orion-border">
      <div className="oa-card-head">
        <span className="oa-card-title orion">Feedback Event Volume</span>
        <span className="oa-card-meta">events / hour · last 24h</span>
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
            <span className="fv-stat-value" style={{ color: 'var(--t2)' }}>
              {totalToday > 0 ? formatCount(totalToday) : '—'}
            </span>
            <span className="fv-stat-label">last 24h</span>
          </div>
          <div className="fv-stat">
            <span className="fv-stat-value" style={{ color: 'var(--green)' }}>
              {successRate !== null ? `${successRate}%` : '—'}
            </span>
            <span className="fv-stat-label">success rate</span>
          </div>
        </div>

        <div className="fv-chart-wrap">
          {buckets.length === 0 ? (
            <EmptyAnalytics
              title="No events in the last 24 hours"
              text="Events will appear here once Orion receives feedback from completed tasks."
              badge="no recent events"
            />
          ) : (
            <>
              <div className="fv-bars">
                {buckets.map((b) => (
                  <div
                    key={b.bucket}
                    className={`fv-bar${b.count === maxCount ? ' peak' : ''}`}
                    style={{ height: `${Math.max(4, (b.count / maxCount) * 100)}%` }}
                    title={`${labelHour(b.bucket)}: ${b.count} events`}
                  />
                ))}
              </div>
              <div className="fv-xaxis">
                {buckets.map((b, i) => (
                  <span key={b.bucket} style={{ visibility: i % showEvery === 0 ? 'visible' : 'hidden' }}>
                    {labelHour(b.bucket)}
                  </span>
                ))}
              </div>
            </>
          )}
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

function DriftMonitorCard({ analytics }: { analytics: OrionAnalyticsData | null }) {
  const agents = analytics?.by_agent ?? [];
  const BASELINE = 0.80;

  if (agents.length === 0) {
    return (
      <div className="oa-card">
        <div className="oa-card-head">
          <span className="oa-card-title green">Drift Monitor</span>
          <span className="oa-card-meta">confidence δ from 0.80 baseline</span>
        </div>
        <div className="oa-card-body">
          <EmptyAnalytics
            title="No drift data yet"
            text="Drift indicators appear once Orion has received feedback events. Confidence deviation is computed per agent against the 0.80 threshold."
            badge="awaiting events"
          />
        </div>
      </div>
    );
  }

  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title green">Drift Monitor</span>
        <span className="oa-card-meta">confidence δ from 0.80 baseline</span>
      </div>
      <div className="oa-card-body">
        <div className="drift-rows">
          {agents.map(a => {
            const delta     = a.avg_confidence - BASELINE;
            const sigma     = Math.abs(delta) / 0.10;
            const isAlert   = delta < -0.15;
            const isClean   = delta >= 0;
            const fillColor  = isClean ? 'var(--green)' : isAlert ? 'var(--red)' : 'var(--yellow)';
            const sigmaColor = isClean ? 'var(--t2)'    : isAlert ? 'var(--red)' : 'var(--yellow)';
            const badgeClass = isClean ? 'drift-badge-clean' : isAlert ? 'drift-badge-alert' : 'drift-badge-drift';
            const badgeLabel = isClean ? 'nominal' : isAlert ? 'alert' : 'watch';

            return (
              <div key={a.agent_id} className="drift-row">
                <span className="drift-agent">{a.agent_id}</span>
                <div className="drift-track">
                  <div
                    className="drift-fill"
                    style={{ width: `${a.avg_confidence * 100}%`, background: fillColor }}
                  />
                </div>
                <span className="drift-sigma" style={{ color: sigmaColor }}>
                  {sigma.toFixed(1)}σ
                </span>
                <span className={`drift-badge ${badgeClass}`}>{badgeLabel}</span>
              </div>
            );
          })}
        </div>
        <div className="oa-card-footer">
          σ = |conf − 0.80| ÷ 0.10 · bar = avg_confidence · derived from Orion feedback events
        </div>
      </div>
    </div>
  );
}

function DatasetCard({ status, analytics }: { status: OrionStatus | null; analytics: OrionAnalyticsData | null }) {
  const domains = analytics?.by_domain ?? [];
  const maxDomainCount = Math.max(...domains.map(d => d.count), 1);

  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title">Domain Breakdown</span>
        <span className="oa-card-meta">events by domain</span>
      </div>
      <div className="oa-card-body">
        {domains.length === 0 ? (
          <div className="oa-empty compact">
            <span className="oa-empty-icon">📊</span>
            <span className="oa-empty-title">No domain data yet</span>
            <p className="oa-empty-text">
              {status && status.dataset_files.length > 0
                ? status.dataset_files.join(', ')
                : 'Orion has not received domain-tagged events yet.'}
            </p>
            <span className="oa-empty-badge">{formatCount(status?.training_examples)} examples</span>
          </div>
        ) : (
          <div className="domain-rows">
            {domains.map(d => (
              <div key={d.domain} className="domain-row">
                <span className="domain-name">{d.domain}</span>
                <div className="domain-bar-wrap">
                  <div
                    className="domain-bar"
                    style={{ width: `${(d.count / maxDomainCount) * 100}%` }}
                  />
                </div>
                <span className="domain-count">{d.count}</span>
              </div>
            ))}
          </div>
        )}
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

function AgentPerformanceCard({ analytics }: { analytics: OrionAnalyticsData | null }) {
  const agents = analytics?.by_agent ?? [];

  return (
    <div className="oa-card">
      <div className="oa-card-head">
        <span className="oa-card-title">Agent Performance</span>
        <span className="oa-card-meta">from feedback events</span>
      </div>
      {agents.length === 0 ? (
        <EmptyAnalytics
          title="No agent performance data yet"
          text="Agent rows appear here once Orion has received feedback events from completed tasks."
          badge="awaiting events"
        />
      ) : (
        <div className="oa-card-body">
          <div className="ap-header">
            <span className="ap-col-agent">Agent</span>
            <span className="ap-col-tasks">Tasks</span>
            <span className="ap-col-conf">Avg confidence</span>
            <span className="ap-col-rate">Success rate</span>
          </div>
          {agents.map(a => (
            <div key={a.agent_id} className="ap-row">
              <span className="ap-agent">{a.agent_id}</span>
              <span className="ap-tasks">{a.count}</span>
              <div className="ap-bar-wrap">
                <div className="ap-bar ap-bar-conf" style={{ width: `${a.avg_confidence * 100}%` }} />
                <span className="ap-bar-label">{a.avg_confidence.toFixed(2)}</span>
              </div>
              <div className="ap-bar-wrap">
                <div className="ap-bar ap-bar-rate" style={{ width: `${a.success_rate * 100}%` }} />
                <span className="ap-bar-label">{Math.round(a.success_rate * 100)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function OrionAnalytics() {
  const [status, setStatus] = useState<OrionStatus | null>(null);
  const [analytics, setAnalytics] = useState<OrionAnalyticsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [training, setTraining] = useState(false);
  const [trainingResult, setTrainingResult] = useState<{ examples: number; files: number } | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [statusRes, analyticsRes] = await Promise.all([
          fetch('/api/orion/status'),
          fetch('/api/orion/analytics?hours=24'),
        ]);
        if (!statusRes.ok) throw new Error(`orion status HTTP ${statusRes.status}`);
        const data = await statusRes.json();
        const analyticsData = analyticsRes.ok ? await analyticsRes.json() : null;
        if (!cancelled) {
          setStatus(data);
          setAnalytics(analyticsData);
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

  async function handleExport() {
    setExporting(true);
    try {
      const res = await fetch('/api/orion/export');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const cd = res.headers.get('Content-Disposition') ?? '';
      const match = cd.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : 'orion_events.ndjson';
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Export failed:', e);
    } finally {
      setExporting(false);
    }
  }

  async function handleRunTraining() {
    setTraining(true);
    setTrainingResult(null);
    try {
      const res = await fetch('/api/orion/training/run', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setTrainingResult({ examples: data.examples_written ?? 0, files: data.dataset_files_flushed ?? 0 });
    } catch (e) {
      console.error('Training run failed:', e);
    } finally {
      setTraining(false);
    }
  }

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
            <button
              className="btn btn-ghost btn-sm"
              onClick={handleExport}
              disabled={exporting || !status}
            >
              {exporting ? 'Exporting…' : 'Export events'}
            </button>
            <button
              className="btn btn-sm"
              style={{
                background: 'rgba(255,107,157,0.08)',
                border: '1px solid rgba(255,107,157,0.2)',
                color: 'var(--orion)',
                opacity: (training || !status) ? 0.5 : 1,
                cursor: (training || !status) ? 'not-allowed' : 'pointer',
              }}
              onClick={handleRunTraining}
              disabled={training || !status}
              title={trainingResult ? `Last run: ${trainingResult.examples} examples, ${trainingResult.files} file(s) flushed` : undefined}
            >
              {training ? 'Running…' : trainingResult ? `Done (${trainingResult.examples} ex)` : 'Run training'}
            </button>
          </div>
        </div>

        <div className="app-content">
          <div className="orion-banner">
            <span className="orion-icon">🔭</span>
            <div className="orion-text">
              <div className="orion-title">Orion status: {status?.status ?? 'loading'}</div>
              <div className="orion-sub">
                {loadError
                  ? `Unable to load Orion status: ${loadError}`
                  : 'This page only renders values returned by the backend. Missing analytics stay empty until an endpoint provides them.'}
              </div>
            </div>
            <span className="orion-badge">{status?.mode ?? 'live check'}</span>
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
              {(() => {
                const count = (analytics?.by_agent ?? []).filter(a => a.avg_confidence < 0.80).length;
                return (
                  <>
                    <div className="oa-metric-value" style={{ color: !analytics ? 'var(--t4)' : count > 0 ? 'var(--yellow)' : 'var(--green)' }}>
                      {analytics ? count : '—'}
                    </div>
                    <div className="oa-metric-delta" style={{ color: 'var(--t3)' }}>
                      {analytics ? 'agents below 0.80' : 'not exposed'}
                    </div>
                  </>
                );
              })()}
            </div>
          </div>

          <div className="oa-row oa-row-2">
            <FeedbackVolumeCard status={status} analytics={analytics} />
            <TrainingRunsCard status={status} />
          </div>

          <div className="oa-row oa-row-3">
            <DriftMonitorCard analytics={analytics} />
            <DatasetCard status={status} analytics={analytics} />
            <AetherStreamCard status={status} />
          </div>

          <div className="oa-row" style={{ gridTemplateColumns: '1fr' }}>
            <AgentPerformanceCard analytics={analytics} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default OrionAnalytics;
