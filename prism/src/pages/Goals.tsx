import React, { useEffect, useRef, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';

const mono = "'Geist Mono', monospace";

interface TaskNode {
  task_id: string;
  skill: string;
  status: string;
  confidence: number | null;
  depends_on: string[];
  error: string | null;
  job_id: string | null;
  resolved_payload: Record<string, unknown> | null;
  attempts?: Array<{ attempt_id: string; worker_id: string; attempt_number: number; outcome: string | null; lease_expires_at: string }>;
  transitions?: Array<{ from_status: string | null; to_status: string; reason: string; created_at: string }>;
}
interface ProjectNode {
  project_id: string;
  title: string;
  description: string;
  tasks: TaskNode[];
}
interface GoalTree {
  goal: { goal_id: string; objective: string; status: string; plan_confidence: number | null };
  projects: ProjectNode[];
  plan_pending_review?: boolean;
  rollup?: { completed: number; total: number; min_confidence: number | null };
  events?: Array<{ actor: string; action: string; reason: string | null; created_at: string }>;
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'var(--t4)',
  running: '#4f8eff',
  complete: '#3fb950',
  failed: '#f85149',
  escalated: '#d29922',
  blocked: '#f85149',
  cancelled: '#8b949e',
  ready: '#4f8eff',
  paused: '#d29922',
  planning: 'var(--t4)',
};

export function Goals() {
  const [objective, setObjective] = useState('');
  const [tree, setTree] = useState<GoalTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  function stopPoll() {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }
  useEffect(() => stopPoll, []);

  async function refresh(goalId: string) {
    try {
      const res = await fetch(`/api/goals/${goalId}`);
      if (!res.ok) throw new Error(`goal HTTP ${res.status}`);
      const data: GoalTree = await res.json();
      setTree(data);
      if (!['running', 'ready'].includes(data.goal.status)) stopPoll();
    } catch (err) {
      setError(String(err));
      stopPoll();
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    stopPoll();
    try {
      const res = await fetch('/api/goals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objective }),
      });
      if (!res.ok) throw new Error(`plan HTTP ${res.status}: ${await res.text()}`);
      const data: GoalTree = await res.json();
      setTree(data);
      if (data.goal.status === 'running' || data.goal.status === 'ready') {
        pollRef.current = window.setInterval(() => refresh(data.goal.goal_id), 3000);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!tree) return;
    const res = await fetch(`/api/goals/${tree.goal.goal_id}/resume`, { method: 'POST' });
    if (!res.ok) {
      setError(`resume HTTP ${res.status}: ${await res.text()}`);
      return;
    }
    pollRef.current = window.setInterval(() => refresh(tree.goal.goal_id), 3000);
  }

  async function control(action: 'pause' | 'cancel') {
    if (!tree) return;
    const res = await fetch(`/api/goals/${tree.goal.goal_id}/${action}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res.ok) { setError(`${action} HTTP ${res.status}: ${await res.text()}`); return; }
    await refresh(tree.goal.goal_id);
  }

  async function rerun(taskId: string) {
    if (!tree) return;
    const res = await fetch(`/api/goals/${tree.goal.goal_id}/tasks/${taskId}/rerun`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    if (!res.ok) { setError(`rerun HTTP ${res.status}: ${await res.text()}`); return; }
    await refresh(tree.goal.goal_id);
    pollRef.current = window.setInterval(() => refresh(tree.goal.goal_id), 3000);
  }

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="goals" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)', marginBottom: 4 }}>Goals</div>
        <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)', marginBottom: 16 }}>
          — submit an objective · Andromeda plans and runs a Goal → Project → Task DAG
        </div>

        <textarea
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          rows={3}
          placeholder="e.g. Build a Python REST API for a todo list, with pytest tests and a README"
          style={{
            width: '100%', maxWidth: 720, fontFamily: mono, fontSize: 12, padding: 10,
            background: 'var(--bg1)', color: 'var(--t1)', border: '1px solid var(--b1)', borderRadius: 6,
          }}
        />
        <div style={{ marginTop: 8 }}>
          <button
            onClick={submit}
            disabled={busy || objective.trim().length === 0}
            style={{
              fontFamily: mono, fontSize: 11, padding: '6px 14px', borderRadius: 5,
              border: '1px solid var(--b1)', background: '#4f8eff', color: '#fff',
              cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? 'Planning…' : 'Plan & run'}
          </button>
        </div>

        {error && (
          <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginTop: 12 }}>{error}</div>
        )}

        {tree && (
          <div style={{ marginTop: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--t1)' }}>{tree.goal.objective}</span>
              <span style={{ fontFamily: mono, fontSize: 10, color: STATUS_COLOR[tree.goal.status] ?? 'var(--t3)' }}>
                {tree.goal.status.toUpperCase()}
              </span>
              {tree.goal.plan_confidence !== null && (
                <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                  plan {tree.goal.plan_confidence.toFixed(2)}
                </span>
              )}
              {tree.rollup && (
                <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                  {tree.rollup.completed}/{tree.rollup.total} tasks
                </span>
              )}
            </div>

            {tree.plan_pending_review && (
              <div style={{ fontFamily: mono, fontSize: 11, color: '#d29922', marginBottom: 12 }}>
                Plan confidence below threshold — sent to the review queue. Approve it there, then Resume.
              </div>
            )}

            {(tree.goal.status === 'paused' || tree.goal.status === 'ready') && (
              <button
                onClick={resume}
                style={{
                  fontFamily: mono, fontSize: 11, padding: '4px 10px', borderRadius: 5,
                  border: '1px solid var(--b1)', background: 'transparent', color: 'var(--t2)',
                  cursor: 'pointer', marginBottom: 12,
                }}
              >
                Resume
              </button>
            )}
            {tree.goal.status === 'running' && (
              <button onClick={() => control('pause')} className="notif-item-link" style={{ margin: '0 12px 12px 0' }}>Pause</button>
            )}
            {!['complete', 'failed', 'cancelled'].includes(tree.goal.status) && (
              <button onClick={() => control('cancel')} className="notif-item-link" style={{ marginBottom: 12 }}>Cancel goal</button>
            )}

            {tree.projects.map((p) => (
              <div key={p.project_id} style={{ border: '1px solid var(--b1)', borderRadius: 8, marginBottom: 12 }}>
                <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--b1)' }}>
                  <div style={{ fontSize: 12.5, color: 'var(--t1)' }}>{p.title}</div>
                  {p.description && (
                    <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>{p.description}</div>
                  )}
                </div>
                {p.tasks.map((t) => (
                  <div
                    key={t.task_id}
                    style={{
                      padding: '9px 12px',
                      borderBottom: '1px solid var(--b1)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t2)' }}>{t.skill}</span>
                      <span style={{ flex: 1 }} />
                      {t.confidence !== null && <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>{t.confidence.toFixed(2)}</span>}
                      <span style={{ fontFamily: mono, fontSize: 10, color: STATUS_COLOR[t.status] ?? 'var(--t3)' }}>{t.status}</span>
                      {['complete', 'failed', 'escalated'].includes(t.status) && (
                        <button className="notif-item-link" onClick={() => rerun(t.task_id)}>Rerun</button>
                      )}
                    </div>
                    {t.error && <div style={{ fontFamily: mono, fontSize: 10, color: '#f85149', marginTop: 5 }}>{t.error}</div>}
                    {t.job_id && (
                      <div style={{ fontFamily: mono, fontSize: 9, color: 'var(--t4)', marginTop: 5 }}>
                        job {t.job_id.slice(0, 8)} · {t.attempts?.map(a => `attempt ${a.attempt_number} ${a.worker_id} ${a.outcome ?? `lease ${new Date(a.lease_expires_at).toLocaleTimeString()}`}`).join(' · ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}
            {tree.events && tree.events.length > 0 && (
              <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)', marginTop: 12 }}>
                {tree.events.map((event, index) => <div key={`${event.created_at}-${index}`}>{event.created_at} · {event.actor} · {event.action}{event.reason ? ` · ${event.reason}` : ''}</div>)}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default Goals;
