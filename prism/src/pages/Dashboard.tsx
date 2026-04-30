import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/dashboard.css';

type TaskStats = {
  total: number;
  complete: number;
  failed: number;
  escalated: number;
};

type StatusResponse = {
  status: string;
  service: string;
  version: string;
  pulsar: {
    status: string;
    skill_count: number;
    agents: string[];
  };
  tasks: TaskStats;
  review_queue: {
    pending: number;
  };
  aether?: {
    status: string;
    error?: string;
  };
  orion?: {
    status: string;
    event_count: number;
    training_examples: number;
    dataset_files: string[];
  };
};

type AgentManifest = {
  agent_id: string;
  agent_name: string;
  skills: Array<{ skill_id: string }>;
};

type RecentTask = {
  task_id: string;
  task_type: string | null;
  assigned_agent: string | null;
  status: string;
  confidence: number | null;
  issued_at: string | null;
};

const SYSTEM_COLORS: Record<string, string> = {
  andromeda: '#4f8eff',
  rigel: '#f5c040',
  vega: '#00d4a0',
  aether: '#38a8ff',
  pulsar: '#9d7eff',
  orion: '#ff6b9d',
};

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
      <circle cx="5.5" cy="5.5" r="3.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8.5 8.5L11 11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M7 1.5C4.79 1.5 3 3.29 3 5.5V8.5L1.5 10H12.5L11 8.5V5.5C11 3.29 9.21 1.5 7 1.5Z"
        stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M5.5 10C5.5 10.83 6.17 11.5 7 11.5C7.83 11.5 8.5 10.83 8.5 10"
        stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
      <path d="M7.5 2L13.5 13H1.5L7.5 2Z"
        fill="rgba(245,192,64,0.15)" stroke="rgba(245,192,64,0.6)"
        strokeWidth="1.2" strokeLinejoin="round" />
      <rect x="6.9" y="5.5" width="1.2" height="4" rx="0.6" fill="#f5c040" />
      <circle cx="7.5" cy="11" r="0.7" fill="#f5c040" />
    </svg>
  );
}

function confColor(v: number) {
  if (v >= 0.80) return '#00d4a0';
  if (v >= 0.60) return '#f5c040';
  return '#ff4d6a';
}

function MiniConfBar({ value }: { value: number }) {
  return (
    <div className="task-conf-track">
      <div
        className="task-conf-fill"
        style={{ width: `${value * 100}%`, background: confColor(value) }}
      />
    </div>
  );
}

function EmptyCardMessage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '24px 14px', color: 'var(--t4)', fontFamily: 'var(--mono)', fontSize: 11 }}>
      {children}
    </div>
  );
}

function formatCount(value: number | undefined) {
  return typeof value === 'number' ? value.toLocaleString() : '—';
}

function formatConfidence(value: number | null) {
  return typeof value === 'number' ? value.toFixed(2) : '—';
}

function timeAgo(iso: string | null) {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h`;
}

export function Dashboard() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [agents, setAgents] = useState<AgentManifest[]>([]);
  const [recentTasks, setRecentTasks] = useState<RecentTask[]>([]);
  const [apiPingMs, setApiPingMs] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const started = performance.now();
        const [statusRes, agentsRes, tasksRes] = await Promise.all([
          fetch('/api/status'),
          fetch('/api/agents'),
          fetch('/api/tasks/recent?limit=8'),
        ]);
        const finished = performance.now();

        if (!statusRes.ok) throw new Error(`status HTTP ${statusRes.status}`);
        if (!agentsRes.ok) throw new Error(`agents HTTP ${agentsRes.status}`);
        if (!tasksRes.ok) throw new Error(`tasks HTTP ${tasksRes.status}`);

        const nextStatus = await statusRes.json();
        const nextAgents = await agentsRes.json();
        const nextTasks = await tasksRes.json();

        if (!cancelled) {
          setStatus(nextStatus);
          setAgents(nextAgents);
          setRecentTasks(nextTasks);
          setApiPingMs(Math.round(finished - started));
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

  const taskStats = status?.tasks;
  const pendingReviews = status?.review_queue.pending ?? 0;
  const completed = taskStats?.complete ?? 0;
  const total = taskStats?.total ?? 0;
  const failed = taskStats?.failed ?? 0;

  const systemRows = [
    {
      id: 'andromeda',
      desc: `api · ${status?.version ?? 'unknown'}`,
      ping: apiPingMs === null ? '—' : `${apiPingMs}ms`,
      ok: status?.status === 'ok',
    },
    {
      id: 'pulsar',
      desc: `registry · ${formatCount(status?.pulsar.skill_count)} skills`,
      ping: status?.pulsar.status ?? '—',
      ok: status?.pulsar.status === 'ok',
    },
    {
      id: 'aether',
      desc: 'redis streams',
      ping: status?.aether?.status ?? '—',
      ok: status?.aether?.status === 'ok',
    },
    {
      id: 'orion',
      desc: 'embedded refinery',
      ping: status?.orion?.status ?? '—',
      ok: status?.orion?.status === 'running',
    },
  ];

  const agentRows = agents.map((agent) => ({
    id: agent.agent_id,
    color: SYSTEM_COLORS[agent.agent_id] ?? 'var(--t3)',
    status: 'registered',
    statusColor: 'var(--green)',
    s1v: String(agent.skills.length),
    s1l: 'skills',
    s2v: '—',
    s2l: 'live tasks',
  }));

  return (
    <div className="app-shell">
      <Sidebar activeId="dashboard" />

      <div className="app-main">
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Dashboard</span>
            <span className="topbar-sub">— live system view</span>
          </div>
          <div className="topbar-right">
            <button className="dash-search">
              <SearchIcon />
              <span className="dash-search-label">Search...</span>
              <span className="dash-search-kbd">⌘K</span>
            </button>
            <div className="notif-wrap">
              <button
                className="btn btn-ghost btn-sm"
                style={{ width: 30, height: 30, padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                <BellIcon />
              </button>
              {pendingReviews > 0 && <span className="notif-dot" />}
            </div>
          </div>
        </div>

        <div className="app-content">
          {loadError && (
            <div className="review-banner">
              <WarningIcon />
              <div className="review-banner-text">
                <div className="review-banner-title">Live dashboard data unavailable</div>
                <div className="review-banner-sub">{loadError}</div>
              </div>
            </div>
          )}

          <div className="review-banner">
            <WarningIcon />
            <div className="review-banner-text">
              <div className="review-banner-title">
                {pendingReviews > 0 ? `${pendingReviews} tasks pending human review` : 'No tasks pending human review'}
              </div>
              <div className="review-banner-sub">
                {pendingReviews > 0 ? 'Loaded from review queue' : 'Review queue returned zero pending items'}
              </div>
            </div>
            <button className="btn-open-review" onClick={() => { window.location.href = '/review-queue'; }}>
              Open Review Queue →
            </button>
          </div>

          <div className="metrics-strip">
            <div className="metric-card">
              <span className="metric-value" style={{ color: 'var(--t1)' }}>{formatCount(total)}</span>
              <span className="metric-label">Task log rows</span>
              <span className="metric-delta" style={{ color: 'var(--t3)' }}>from Andromeda task log</span>
            </div>
            <div className="metric-card">
              <span className="metric-value" style={{ color: 'var(--green)' }}>{formatCount(completed)}</span>
              <span className="metric-label">Completed rows</span>
              <span className="metric-delta" style={{ color: 'var(--t3)' }}>from task status history</span>
            </div>
            <div className="metric-card">
              <span className="metric-value" style={{ color: 'var(--yellow)' }}>{formatCount(pendingReviews)}</span>
              <span className="metric-label">Pending reviews</span>
              <span className="metric-delta" style={{ color: 'var(--t3)' }}>from review queue</span>
            </div>
            <div className="metric-card">
              <span className="metric-value" style={{ color: failed > 0 ? 'var(--red)' : 'var(--teal)' }}>{formatCount(failed)}</span>
              <span className="metric-label">Failed rows</span>
              <span className="metric-delta" style={{ color: 'var(--t3)' }}>from task status history</span>
            </div>
          </div>

          <div className="dash-main-grid">
            <div className="dash-left-col">
              <div className="card">
                <div className="card-head">
                  <span className="card-title">Task Throughput</span>
                  <span className="card-meta">not available</span>
                </div>
                <div className="card-body">
                  <EmptyCardMessage>
                    No hourly throughput endpoint is available yet. This chart is intentionally empty instead of rendering fake traffic.
                  </EmptyCardMessage>
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <span className="card-title">Agent Health</span>
                  <span className="card-meta">registry data</span>
                </div>
                <div className="agent-health-body">
                  {agentRows.length === 0 && <EmptyCardMessage>No registered agents returned by Pulsar.</EmptyCardMessage>}
                  {agentRows.map(agent => (
                    <div key={agent.id} className="agent-row">
                      <span
                        className="agent-glow"
                        style={{
                          background: agent.color,
                          boxShadow: `0 0 5px ${agent.color}`,
                        }}
                      />
                      <span className="agent-row-name" style={{ color: agent.color }}>
                        {agent.id}
                      </span>
                      <span className="agent-row-status" style={{ color: agent.statusColor }}>
                        {agent.status}
                      </span>
                      <span className="agent-row-spacer" />
                      <div className="agent-stat">
                        <span className="agent-stat-val">{agent.s1v}</span>
                        <span className="agent-stat-lbl">{agent.s1l}</span>
                      </div>
                      <div className="agent-stat" style={{ marginLeft: 6 }}>
                        <span className="agent-stat-val">{agent.s2v}</span>
                        <span className="agent-stat-lbl">{agent.s2l}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <span className="card-title">Live Task Feed</span>
                  <span className="card-meta">recent task log rows</span>
                </div>
                <div className="task-feed-body">
                  {recentTasks.length === 0 && <EmptyCardMessage>No tasks recorded yet.</EmptyCardMessage>}
                  {recentTasks.map((task) => {
                    const isComplete = task.status === 'complete';
                    const isFailed = task.status === 'failed' || task.status === 'escalated';
                    const dotColor = isComplete ? '#00d4a0' : isFailed ? '#ff4d6a' : '#f5c040';
                    const badgeClass = isComplete ? 'badge badge-green' : isFailed ? 'badge badge-red' : 'badge badge-yellow';
                    const confidence = task.confidence ?? 0;
                    return (
                      <div key={`${task.task_id}-${task.status}`} className="task-row">
                        <span
                          className="task-dot"
                          style={{ background: dotColor, boxShadow: `0 0 4px ${dotColor}` }}
                        />
                        <span className="task-skill">{task.task_type || task.task_id.slice(0, 8)}</span>
                        <span className="task-spacer" />
                        {task.confidence === null ? (
                          <span className="task-conf-val" style={{ color: 'var(--t4)' }}>—</span>
                        ) : (
                          <>
                            <MiniConfBar value={confidence} />
                            <span className="task-conf-val" style={{ color: confColor(confidence) }}>
                              {formatConfidence(task.confidence)}
                            </span>
                          </>
                        )}
                        <span className={badgeClass}>{task.status}</span>
                        <span className="task-time">{timeAgo(task.issued_at)}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="dash-right-col">
              <div className="card">
                <div className="card-head">
                  <span className="card-title">System Health</span>
                  <span className="card-meta">live API response</span>
                </div>
                <div className="card-body">
                  {systemRows.map(sys => {
                    const color = SYSTEM_COLORS[sys.id] ?? 'var(--t3)';
                    return (
                      <div key={sys.id} className="system-row">
                        <span
                          className="system-glow"
                          style={{
                            background: color,
                            boxShadow: sys.ok ? `0 0 5px ${color}` : 'none',
                          }}
                        />
                        <span className="system-name" style={{ color }}>{sys.id}</span>
                        <span className="system-desc">{sys.desc}</span>
                        <span
                          className="system-ping"
                          style={{ color: sys.ok ? 'var(--green)' : 'var(--t4)' }}
                        >
                          {sys.ping}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <span className="card-title">Event Timeline</span>
                  <span className="card-meta">not available</span>
                </div>
                <div className="card-body" style={{ paddingTop: 8, paddingBottom: 8 }}>
                  <EmptyCardMessage>
                    No event timeline endpoint is available yet. Recent task rows are shown in Live Task Feed.
                  </EmptyCardMessage>
                </div>
              </div>

              <div className="card">
                <div className="card-head">
                  <span className="card-title" style={{ color: 'rgba(255,107,157,0.6)' }}>
                    Orion Refinery
                  </span>
                  <span className="card-meta" style={{ color: 'rgba(255,107,157,0.4)' }}>
                    live status
                  </span>
                </div>
                <div className="card-body">
                  <div className="orion-empty">
                    <div className="orion-empty-icon">🔭</div>
                    <div className="orion-empty-title">Orion {status?.orion?.status ?? 'unknown'}</div>
                    <p className="orion-empty-desc">
                      Feedback events: {formatCount(status?.orion?.event_count)} ·
                      training examples: {formatCount(status?.orion?.training_examples)}
                    </p>
                    <span className="orion-phase-badge">embedded service</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
