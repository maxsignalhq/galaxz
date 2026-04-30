import React, { useEffect, useRef, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/taskui.css';

/* ── API types ──────────────────────────────────────────────── */

interface ApiResult {
  code?:                 string;
  language?:             string;
  notes?:                string;
  confidence?:           number;
  confidence_breakdown?: Record<string, number>;
  gaps?:                 string[];
}

interface ApiResponse {
  task_id:               string;
  task_type:             string;
  assigned_agent:        string;
  assignment_reason:     string;
  result:                ApiResult | null;
  confidence:            number;
  confidence_breakdown:  Record<string, number> | null;
  gaps:                  string[];
  status:                string;
  failure_reason:        string | null;
  escalated_to_human:    boolean;
  issued_at:             string;
  completed_at:          string | null;
}

interface SubmittedTask {
  localId:     number;
  text:        string;
  skillId:     string;
  submittedAt: Date;
  status:      'loading' | 'complete' | 'failed' | 'escalated';
  response?:   ApiResponse;
  error?:      string;
}

/* ── Skills ─────────────────────────────────────────────────── */

const SKILLS = [
  { id: 'code_generation', label: 'code_generation' },
  { id: 'test_writing',    label: 'test_writing'    },
  { id: 'refactor',        label: 'refactor'        },
  { id: 'pr_review',       label: 'pr_review'       },
  { id: 'debug_triage',    label: 'debug_triage'    },
  { id: 'scaffold',        label: 'scaffold'        },
];

/* ── Helpers ─────────────────────────────────────────────────── */

function elapsedMs(issued: string, completed: string | null): number {
  if (!completed) return 0;
  return Math.round(new Date(completed).getTime() - new Date(issued).getTime());
}

function confColor(v: number): string {
  return v >= 0.80 ? 'var(--green)' : v >= 0.60 ? 'var(--yellow)' : 'var(--red)';
}

function extractCode(raw: string): string {
  const match = raw.match(/```(?:\w+)?\n([\s\S]*?)```/);
  return match ? match[1].trim() : raw.trim();
}

function timeAgo(d: Date): string {
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 60)   return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

/* ── Icons ───────────────────────────────────────────────────── */

function PaperclipIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none">
      <path d="M9.5 5.5L5 10C3.62 11.38 1.38 11.38 0 10C-1.38 8.62-1.38 6.38 0 5L5.5 0.5C6.5-0.5 8-0.5 9 0.5C10 1.5 10 3 9 4L3.5 9.5C2.95 10.05 2.05 10.05 1.5 9.5C0.95 8.95 0.95 8.05 1.5 7.5L6.5 2.5"
        stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

function SendArrow() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M2.5 6H9.5M7 3.5L9.5 6L7 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── Recent tasks sidebar ────────────────────────────────────── */

function RecentTasksSection({ tasks }: { tasks: SubmittedTask[] }) {
  const statusColor = (s: SubmittedTask['status']) =>
    s === 'complete' ? 'var(--green)' : s === 'loading' ? 'var(--yellow)' : 'var(--red)';

  return (
    <div className="recent-tasks-section">
      <span className="recent-tasks-label">Recent Tasks</span>
      {tasks.length === 0 && (
        <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--t4)', fontFamily: 'var(--mono)' }}>
          no tasks yet
        </div>
      )}
      {[...tasks].reverse().slice(0, 6).map((t) => (
        <div key={t.localId} className="rt-item">
          <span className="rt-skill">rigel.skill.{t.skillId}</span>
          <div className="rt-meta">
            <span className="rt-dot" style={{ background: statusColor(t.status) }} />
            <span>{t.status}</span>
            {t.response && <><span>·</span><span>{t.response.confidence.toFixed(2)}</span></>}
            <span>·</span>
            <span>{timeAgo(t.submittedAt)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Routing trace ───────────────────────────────────────────── */

function RoutingTraceCard({ response }: { response: ApiResponse }) {
  const total = elapsedMs(response.issued_at, response.completed_at);
  const agent = response.assigned_agent || 'rigel';

  const nodes = [
    { label: 'client',    time: '+0ms',                            icon: '✓' },
    { label: 'andromeda', time: '+12ms',                           icon: '✓' },
    { label: 'pulsar',    time: '+15ms',                           icon: '✓' },
    { label: 'aether',    time: '+16ms',                           icon: '✓' },
    { label: agent,       time: `+${Math.max(17, total - 10)}ms`,  icon: agent[0].toUpperCase() },
    { label: 'result',    time: `+${total}ms`,                     icon: '✓' },
  ];

  return (
    <div className="routing-trace-card">
      <div className="trace-header">routing trace · task {response.task_id.slice(0, 8)}</div>
      <div className="trace-nodes">
        {nodes.map((node, i) => (
          <React.Fragment key={`${node.label}-${i}`}>
            <div className="trace-node">
              <div className="trace-circle">{node.icon}</div>
              <span className="trace-node-label">{node.label}</span>
              <span className="trace-node-time">{node.time}</span>
            </div>
            {i < nodes.length - 1 && <div className="trace-line" />}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

/* ── User bubble ─────────────────────────────────────────────── */

function UserBubble({ task }: { task: SubmittedTask }) {
  const ts = task.submittedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return (
    <div className="user-msg">
      <div className="user-bubble">
        <p className="user-bubble-text">{task.text}</p>
        <div className="user-bubble-meta">
          <span>skill: rigel.skill.{task.skillId}</span>
          <span>·</span>
          <span>auto-routed to rigel</span>
          <span>·</span>
          <span>{ts}</span>
        </div>
      </div>
    </div>
  );
}

/* ── Loading bubble ──────────────────────────────────────────── */

function LoadingBubble({ skillId }: { skillId: string }) {
  return (
    <div className="agent-result">
      <div className="agent-avatar-circle">R</div>
      <div className="agent-result-body">
        <span className="agent-result-name">rigel · {skillId} · routing…</span>
        <div className="result-card" style={{ padding: '14px 16px' }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--t3)' }}>
            andromeda → pulsar → aether → rigel
          </span>
          <span style={{ marginLeft: 8, color: 'var(--yellow)', fontSize: 14 }}>⋯</span>
        </div>
      </div>
    </div>
  );
}

/* ── Error bubble ────────────────────────────────────────────── */

function ErrorBubble({ task }: { task: SubmittedTask }) {
  const msg = task.response?.failure_reason || task.error || 'unknown error';
  return (
    <div className="agent-result">
      <div className="agent-avatar-circle" style={{ borderColor: 'rgba(255,77,106,0.3)', color: 'var(--red)' }}>!</div>
      <div className="agent-result-body">
        <span className="agent-result-name" style={{ color: 'var(--red)' }}>
          rigel · {task.skillId} · {task.status}
        </span>
        <div className="result-card" style={{ padding: '14px 16px' }}>
          <p style={{ fontSize: 12, color: 'var(--red)', fontFamily: 'var(--mono)' }}>{msg}</p>
        </div>
      </div>
    </div>
  );
}

/* ── Agent result bubble ─────────────────────────────────────── */

function AgentResultBubble({ task }: { task: SubmittedTask }) {
  const resp  = task.response!;
  const conf  = resp.confidence;
  const cc    = confColor(conf);
  const raw   = resp.result?.code ?? '';
  const code  = extractCode(raw);
  const lang  = resp.result?.language ?? 'text';
  const notes = resp.result?.notes ?? '';

  return (
    <div className="agent-result">
      <div className="agent-avatar-circle">R</div>

      <div className="agent-result-body">
        <span className="agent-result-name">rigel · {task.skillId}</span>

        <div className="result-card">
          {/* Confidence bar */}
          <div className="conf-section">
            <span className="conf-label">confidence</span>
            <div className="conf-track">
              <div className="conf-fill" style={{ width: `${conf * 100}%`, background: cc }} />
              <div className="conf-marker" />
            </div>
            <span className="conf-value" style={{ color: cc }}>{conf.toFixed(2)}</span>
            <div className="conf-actions">
              <button className="btn btn-accept btn-sm">✓ Accept</button>
              <button className="btn btn-reject btn-sm">✗ Reject</button>
            </div>
          </div>

          {/* Code block */}
          {code && (
            <div className="code-output">
              <span className="co-line" style={{ color: 'var(--t4)', fontSize: 9 }}>{lang}</span>
              <span className="co-empty" />
              {code.split('\n').map((line, i) => (
                <span key={i} className="co-line">{line}</span>
              ))}
            </div>
          )}

          {/* Notes */}
          {notes && <p className="result-explanation">{notes}</p>}

          {/* Confidence breakdown */}
          {resp.confidence_breakdown && Object.keys(resp.confidence_breakdown).length > 0 && (
            <p className="result-explanation" style={{ fontSize: 10.5, color: 'var(--t4)' }}>
              {Object.entries(resp.confidence_breakdown)
                .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`)
                .join(' · ')}
            </p>
          )}

          {/* Orion notice */}
          <div className="orion-notice">
            <span className="orion-notice-dot" />
            <span className="orion-notice-text">
              FeedbackEvent emitted → aether · Orion will ingest in Phase 3 · task_id: {resp.task_id}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Agent selector bar ──────────────────────────────────────── */

function AgentSelectorBar({
  routeMode,
  setRouteMode,
  skillId,
  setSkillId,
}: {
  routeMode:    'auto' | 'rigel' | 'vega';
  setRouteMode: (m: 'auto' | 'rigel' | 'vega') => void;
  skillId:      string;
  setSkillId:   (s: string) => void;
}) {
  const labels:  Record<string, string> = { auto: 'Auto-route', rigel: 'Rigel (Engineering)', vega: 'Vega (QA)' };
  const classes: Record<string, string> = { auto: 'chip-auto',  rigel: 'chip-rigel',          vega: 'chip-vega' };

  return (
    <div className="agent-selector-bar">
      <span className="agent-selector-label">Route via:</span>
      <div className="agent-chips">
        {(['auto', 'rigel', 'vega'] as const).map((m) => (
          <button
            key={m}
            className={`agent-chip ${classes[m]}`}
            style={{
              opacity: routeMode === m ? 1 : 0.5,
              cursor: m === 'vega' ? 'not-allowed' : 'pointer',
            }}
            onClick={() => m !== 'vega' && setRouteMode(m)}
            title={m === 'vega' ? 'Vega not yet wired to HTTP API' : undefined}
          >
            {labels[m]}
          </button>
        ))}
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--t4)' }}>skill:</span>
        <select
          value={skillId}
          onChange={(e) => setSkillId(e.target.value)}
          style={{
            background: 'var(--bg2)',
            border: '1px solid var(--b1)',
            borderRadius: 5,
            color: 'var(--t2)',
            fontFamily: 'var(--mono)',
            fontSize: 11,
            padding: '3px 8px',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          {SKILLS.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}

/* ── Empty chat state ────────────────────────────────────────── */

function EmptyChatState() {
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
      color: 'var(--t4)',
      userSelect: 'none',
      paddingBottom: 60,
    }}>
      <div style={{ fontSize: 28, opacity: 0.35 }}>⚡</div>
      <div style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
        submit a task to route through andromeda → rigel
      </div>
      <div style={{ fontSize: 10, color: 'var(--t4)', fontFamily: 'var(--mono)', marginTop: 2 }}>
        api: localhost:8001 · rigel skills: {SKILLS.length} registered · ⌘Enter to send
      </div>
    </div>
  );
}

/* ── Input bar ───────────────────────────────────────────────── */

function InputBar({
  value,
  onChange,
  onSend,
  disabled,
  routeMode,
}: {
  value:     string;
  onChange:  (v: string) => void;
  onSend:    () => void;
  disabled:  boolean;
  routeMode: 'auto' | 'rigel' | 'vega';
}) {
  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSend();
    }
  }

  return (
    <div className="input-bar">
      <div className="input-wrap">
        <textarea
          className="input-textarea"
          rows={2}
          placeholder="Describe what you need — ⌘Enter to send"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          disabled={disabled}
        />
        <div className="input-footer-row">
          <button className="micro-btn" disabled>
            <PaperclipIcon /> Attach
          </button>
          <div className="input-footer-right">
            <span className="auto-route-label">
              {disabled ? 'routing…' : routeMode === 'auto' ? 'Auto-route active' : `${routeMode} selected`}
            </span>
            <button
              className="send-btn"
              onClick={onSend}
              disabled={disabled || !value.trim()}
              style={{ opacity: disabled || !value.trim() ? 0.5 : 1, cursor: disabled || !value.trim() ? 'not-allowed' : 'pointer' }}
            >
              {disabled ? 'Routing…' : 'Send'} <SendArrow />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── TaskUI ─────────────────────────────────────────────────── */

export function TaskUI() {
  const [tasks,      setTasks]      = useState<SubmittedTask[]>([]);
  const [draftText,  setDraftText]  = useState('');
  const [routeMode,  setRouteMode]  = useState<'auto' | 'rigel' | 'vega'>('auto');
  const [skillId,    setSkillId]    = useState('code_generation');
  const [submitting, setSubmitting] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [tasks]);

  async function handleSend() {
    if (!draftText.trim() || submitting) return;

    const localId = Date.now();
    const newTask: SubmittedTask = {
      localId,
      text:        draftText.trim(),
      skillId,
      submittedAt: new Date(),
      status:      'loading',
    };

    setTasks((prev) => [...prev, newTask]);
    setDraftText('');
    setSubmitting(true);

    try {
      const res = await fetch('/api/task', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ task: newTask.text, skill_id: newTask.skillId }),
      });

      if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
      const data: ApiResponse = await res.json();

      const finalStatus: SubmittedTask['status'] =
        data.status === 'complete'        ? 'complete'  :
        data.escalated_to_human           ? 'escalated' : 'failed';

      setTasks((prev) => prev.map((t) =>
        t.localId === localId ? { ...t, status: finalStatus, response: data } : t
      ));
    } catch (err) {
      setTasks((prev) => prev.map((t) =>
        t.localId === localId ? { ...t, status: 'failed', error: String(err) } : t
      ));
    } finally {
      setSubmitting(false);
    }
  }

  const lastTask     = tasks[tasks.length - 1];
  const topbarTaskId = lastTask?.response?.task_id?.slice(0, 8) ?? '—';

  return (
    <div className="app-shell">
      <Sidebar
        activeId="task-ui"
        extraNav={<RecentTasksSection tasks={tasks} />}
      />

      <div className="app-main">
        {/* Topbar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Task UI</span>
            <span className="topbar-sub">— submit tasks · view routing trace · review results</span>
          </div>
          <div className="topbar-right">
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--t4)' }}>
              task_id: {topbarTaskId}
            </span>
          </div>
        </div>

        {/* Agent + skill selector */}
        <AgentSelectorBar
          routeMode={routeMode}
          setRouteMode={setRouteMode}
          skillId={skillId}
          setSkillId={setSkillId}
        />

        {/* Chat area */}
        <div className="chat-area">
          {tasks.length === 0 && <EmptyChatState />}

          {tasks.map((task) => (
            <React.Fragment key={task.localId}>
              {task.status === 'complete' && task.response && (
                <RoutingTraceCard response={task.response} />
              )}
              <UserBubble task={task} />
              {task.status === 'loading'   && <LoadingBubble skillId={task.skillId} />}
              {task.status === 'failed'    && <ErrorBubble   task={task} />}
              {task.status === 'escalated' && <ErrorBubble   task={task} />}
              {task.status === 'complete'  && <AgentResultBubble task={task} />}
            </React.Fragment>
          ))}

          <div ref={chatEndRef} />
        </div>

        {/* Input */}
        <InputBar
          value={draftText}
          onChange={setDraftText}
          onSend={handleSend}
          disabled={submitting}
          routeMode={routeMode}
        />
      </div>
    </div>
  );
}

export default TaskUI;
