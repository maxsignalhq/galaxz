import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/dashboard.css';

type RecentTask = {
  task_id: string;
  task_type: string | null;
  assigned_agent: string | null;
  status: string;
  confidence: number | null;
  issued_at: string | null;
};

function confColor(value: number) {
  if (value >= 0.80) return '#00d4a0';
  if (value >= 0.60) return '#f5c040';
  return '#ff4d6a';
}

function formatConfidence(value: number | null) {
  return typeof value === 'number' ? value.toFixed(2) : '-';
}

function timeAgo(iso: string | null) {
  if (!iso) return '-';
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return '-';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h`;
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

function EmptyMessage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: '24px 14px', color: 'var(--t4)', fontFamily: 'var(--mono)', fontSize: 11 }}>
      {children}
    </div>
  );
}

export function TaskQueue() {
  const [tasks, setTasks] = useState<RecentTask[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadTasks() {
      try {
        const response = await fetch('/api/tasks/recent?limit=50');
        if (!response.ok) throw new Error(`tasks HTTP ${response.status}`);
        const nextTasks = (await response.json()) as RecentTask[];
        if (!cancelled) {
          setTasks(nextTasks);
          setLoadError(null);
        }
      } catch (err) {
        if (!cancelled) setLoadError(String(err));
      }
    }

    loadTasks();
    const timer = window.setInterval(loadTasks, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <div className="app-shell">
      <Sidebar activeId="task-queue" />

      <div className="app-main">
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Task Queue</span>
            <span className="topbar-sub">- live task log</span>
          </div>
        </div>

        <div className="app-content">
          <div className="card">
            <div className="card-head">
              <span className="card-title">Recent Tasks</span>
              <span className="card-meta">from /api/tasks/recent</span>
            </div>
            <div className="task-feed-body">
              {loadError && <EmptyMessage>{loadError}</EmptyMessage>}
              {!loadError && tasks.length === 0 && <EmptyMessage>No tasks recorded yet.</EmptyMessage>}
              {!loadError && tasks.map((task) => {
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
                    <span className="system-desc">{task.assigned_agent ?? 'unassigned'}</span>
                    <span className="task-spacer" />
                    {task.confidence === null ? (
                      <span className="task-conf-val" style={{ color: 'var(--t4)' }}>-</span>
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
      </div>
    </div>
  );
}
