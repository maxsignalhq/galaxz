import React, { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/taskui.css';

/* ── API types ──────────────────────────────────────────────── */

interface Artifact {
  filename:      string;
  path?:         string;
  written:       boolean;
  artifact_type: string;
  language:      string;
  content?:      string;
  error?:        string | null;
}

interface ApiResult {
  code?:                 string;
  language?:             string;
  notes?:                string;
  qa_result?:            QaResult;
  test_cases?:           QaTestCase[];
  total_count?:          number;
  coverage_summary?:     Record<string, number>;
  uncovered_reqs?:       string[];
  confidence?:           number;
  confidence_breakdown?: Record<string, number>;
  gaps?:                 string[];
}

type QaTestCase = {
  tc_id?:           string;
  id?:              string;
  req_id?:          string;
  title?:           string;
  preconditions?:   string[];
  steps?:           string[];
  expected_result?: string;
  test_type?:       string;
  priority?:        string;
  automated?:       boolean;
};

type QaResult = {
  test_cases?:       QaTestCase[];
  total_count?:      number;
  coverage_summary?: Record<string, number>;
  uncovered_reqs?:   string[];
};

interface ApiResponse {
  task_id:               string;
  task_type:             string;
  required_skills?:      string[];
  assigned_agent:        string;
  assignment_reason:     string;
  result:                ApiResult | null;
  confidence:            number;
  confidence_breakdown:  Record<string, number | null> | null;
  gaps:                  string[];
  status:                string;
  failure_reason:        string | null;
  escalated_to_human:    boolean;
  issued_at:             string;
  completed_at:          string | null;
  artifacts?:            Artifact[];
  workspace_path?:       string | null;
  summary?:              string;
}

interface SubmittedTask {
  localId:     number;
  text:        string;
  skillId:     string;
  submittedAt: Date;
  status:      'loading' | 'complete' | 'failed' | 'escalated';
  response?:   ApiResponse;
  error?:      string;
  feedback?:   'accepted' | 'rejected';
}

type PersistedTask = Omit<SubmittedTask, 'submittedAt'> & {
  submittedAt: string;
};

type ArchivedTaskThread = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  tasks: PersistedTask[];
};

type TaskUiSession = {
  tasks: PersistedTask[];
  archivedThreads: ArchivedTaskThread[];
  draftText: string;
  routeMode: string;
  skillId: string;
};

type AgentManifest = {
  agent_id: string;
  agent_name: string;
  skills: { skill_id: string; description: string; avg_confidence: number }[];
  metadata: { color?: string };
};

type TaskSessionContextItem = {
  role: 'user' | 'agent';
  content: string;
  skill_id?: string;
  assigned_agent?: string;
  status?: string;
  confidence?: number;
};

/* ── Skills ─────────────────────────────────────────────────── */

type SkillOption = {
  skillId: string;   // full qualified: "rigel.skill.code_generation"
  label: string;
  agentId: string;
  color: string;
};

function deriveSkills(agents: AgentManifest[]): SkillOption[] {
  return agents.flatMap((a) =>
    a.skills.map((s) => ({
      skillId: s.skill_id,
      label: `${a.agent_name} · ${s.skill_id.split('.').pop()}`,
      agentId: a.agent_id,
      color: a.metadata?.color ?? '#94a3b8',
    }))
  );
}

function fullSkillId(skillId: string, skills?: SkillOption[]): string {
  if (skillId === 'auto') return 'auto';
  if (skillId.includes('.')) return skillId;
  // Exact match (e.g. vega's "requirements_to_test_cases" has no prefix)
  if (skills?.find((s) => s.skillId === skillId)) return skillId;
  // Legacy short ID: try suffix match, fall back to rigel prefix
  const match = skills?.find((s) => s.skillId.endsWith(`.${skillId}`));
  return match?.skillId ?? `rigel.skill.${skillId}`;
}

function agentAvatar(agentId: string): string {
  if (agentId === 'rigel+vega') return 'A';
  return agentId.charAt(0).toUpperCase();
}

function agentColorFor(agentId: string, agents: AgentManifest[]): string {
  return agents.find((a) => a.agent_id === agentId)?.metadata?.color ?? '#94a3b8';
}

const TASK_UI_SESSION_KEY = 'galaxz.taskUi.session';

function persistTaskUiSession(session: TaskUiSession) {
  window.localStorage.setItem(TASK_UI_SESSION_KEY, JSON.stringify(session));
}

function titleForTasks(tasks: SubmittedTask[] | PersistedTask[]): string {
  const first = tasks[0]?.text?.trim();
  if (!first) return 'Untitled submission';
  return first.length > 64 ? `${first.slice(0, 61)}...` : first;
}

function archiveFromTasks(tasks: SubmittedTask[]): ArchivedTaskThread {
  const serialized = serializeTasks(tasks);
  return {
    id: `thread-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    title: titleForTasks(tasks),
    createdAt: serialized[0]?.submittedAt ?? new Date().toISOString(),
    updatedAt: serialized[serialized.length - 1]?.submittedAt ?? new Date().toISOString(),
    tasks: serialized,
  };
}

function serializeTasks(tasks: SubmittedTask[]): PersistedTask[] {
  return tasks.map((task) => ({
    ...task,
    submittedAt: task.submittedAt.toISOString(),
  }));
}

function parseTasks(tasks: PersistedTask[] | undefined): SubmittedTask[] {
  if (!Array.isArray(tasks)) return [];
  return tasks.map((task) => ({
    ...task,
    submittedAt: new Date(task.submittedAt),
  }));
}

function parseArchivedThreads(value: unknown): ArchivedTaskThread[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((thread): thread is ArchivedTaskThread =>
      typeof thread === 'object'
      && thread !== null
      && Array.isArray((thread as ArchivedTaskThread).tasks)
      && typeof (thread as ArchivedTaskThread).id === 'string'
    )
    .map((thread) => ({
      id: thread.id,
      title: typeof thread.title === 'string' ? thread.title : titleForTasks(thread.tasks),
      createdAt: typeof thread.createdAt === 'string' ? thread.createdAt : new Date().toISOString(),
      updatedAt: typeof thread.updatedAt === 'string' ? thread.updatedAt : new Date().toISOString(),
      tasks: thread.tasks,
    }));
}

function loadTaskUiSession(): TaskUiSession {
  try {
    const raw = window.localStorage.getItem(TASK_UI_SESSION_KEY);
    if (!raw) throw new Error('empty');
    const parsed = JSON.parse(raw) as Partial<TaskUiSession>;
    const routeMode = typeof parsed.routeMode === 'string' && parsed.routeMode ? parsed.routeMode : 'auto';
    const skillId = typeof parsed.skillId === 'string' && parsed.skillId ? parsed.skillId : 'rigel.skill.code_generation';
    return {
      tasks: Array.isArray(parsed.tasks) ? parsed.tasks : [],
      archivedThreads: parseArchivedThreads((parsed as Partial<TaskUiSession>).archivedThreads),
      draftText: typeof parsed.draftText === 'string' ? parsed.draftText : '',
      routeMode,
      skillId,
    };
  } catch {
    return {
      tasks: [],
      archivedThreads: [],
      draftText: '',
      routeMode: 'auto',
      skillId: 'rigel.skill.code_generation',
    };
  }
}

function updatePersistedTask(
  localId: number,
  update: (task: PersistedTask) => PersistedTask,
  fallback: Pick<TaskUiSession, 'draftText' | 'routeMode' | 'skillId'>,
) {
  const session = loadTaskUiSession();
  const tasks = session.tasks.map((task) => task.localId === localId ? update(task) : task);
  persistTaskUiSession({
    tasks,
    archivedThreads: session.archivedThreads ?? [],
    draftText: session.draftText ?? fallback.draftText,
    routeMode: session.routeMode ?? fallback.routeMode,
    skillId: session.skillId ?? fallback.skillId,
  });
}

function truncateSessionText(value: string, limit: number): string {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit)}\n\n[truncated]`;
}

function summarizeAgentResponse(response: ApiResponse): string {
  const result = response.result;
  const chunks: string[] = [];

  if (result?.code) {
    chunks.push(`Code:\n${truncateSessionText(result.code, 5000)}`);
  }
  if (result?.notes) {
    chunks.push(`Notes:\n${truncateSessionText(result.notes, 1200)}`);
  }

  const qaResult = qaResultFor(result);
  const testCases = qaResult?.test_cases ?? [];
  if (testCases.length > 0) {
    chunks.push(`QA test cases:\n${testCases
      .slice(0, 6)
      .map((tc, index) => `${tc.tc_id ?? tc.id ?? `TC-${index + 1}`}: ${tc.title ?? tc.expected_result ?? 'Untitled test case'}`)
      .join('\n')}`);
  }

  if (chunks.length === 0) {
    chunks.push(JSON.stringify(result ?? {}, null, 2));
  }

  return truncateSessionText(chunks.join('\n\n'), 7000);
}

function buildSessionContext(tasks: SubmittedTask[]): TaskSessionContextItem[] {
  const context: TaskSessionContextItem[] = [];

  for (const task of tasks) {
    context.push({
      role: 'user',
      skill_id: fullSkillId(task.skillId),
      status: task.status,
      content: truncateSessionText(task.text, 4000),
    });

    if (task.response) {
      context.push({
        role: 'agent',
        skill_id: task.response.required_skills?.[0] ?? fullSkillId(task.skillId),
        assigned_agent: task.response.assigned_agent,
        status: task.response.status,
        confidence: task.response.confidence,
        content: summarizeAgentResponse(task.response),
      });
    } else if (task.error) {
      context.push({
        role: 'agent',
        skill_id: fullSkillId(task.skillId),
        status: 'failed',
        content: truncateSessionText(task.error, 1200),
      });
    }
  }

  return context.slice(-12);
}

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

function RecentTasksSection({
  tasks,
  archivedThreads,
  onNewSubmission,
  onOpenThread,
  disabled,
}: {
  tasks: SubmittedTask[];
  archivedThreads: ArchivedTaskThread[];
  onNewSubmission: () => void;
  onOpenThread: (thread: ArchivedTaskThread) => void;
  disabled: boolean;
}) {
  const statusColor = (s: SubmittedTask['status']) =>
    s === 'complete' ? 'var(--green)' : s === 'loading' ? 'var(--yellow)' : 'var(--red)';

  return (
    <div className="recent-tasks-section">
      <button className="rt-new-btn" onClick={onNewSubmission} disabled={disabled}>
        + New submission
      </button>
      <span className="recent-tasks-label">Recent Tasks</span>
      {tasks.length === 0 && (
        <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--t4)', fontFamily: 'var(--mono)' }}>
          no tasks yet
        </div>
      )}
      {[...tasks].reverse().slice(0, 6).map((t) => (
        <div key={t.localId} className="rt-item">
          <span className="rt-skill">{fullSkillId(t.skillId)}</span>
          <div className="rt-meta">
            <span className="rt-dot" style={{ background: statusColor(t.status) }} />
            <span>{t.status}</span>
            {t.response && t.response.confidence != null && <><span>·</span><span>{t.response.confidence.toFixed(2)}</span></>}
            <span>·</span>
            <span>{timeAgo(t.submittedAt)}</span>
          </div>
        </div>
      ))}
      <span className="recent-tasks-label">Submission History</span>
      {archivedThreads.length === 0 && (
        <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--t4)', fontFamily: 'var(--mono)' }}>
          no archived submissions
        </div>
      )}
      {archivedThreads.slice(0, 10).map((thread) => (
        <button
          key={thread.id}
          className="thread-item"
          onClick={() => onOpenThread(thread)}
          disabled={disabled}
        >
          <span className="thread-title">{thread.title}</span>
          <span className="thread-meta">
            {thread.tasks.length} task{thread.tasks.length === 1 ? '' : 's'} · {timeAgo(new Date(thread.updatedAt))}
          </span>
        </button>
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
          <span>skill: {fullSkillId(task.skillId)}</span>
          <span>·</span>
          <span>auto-routed by andromeda</span>
          <span>·</span>
          <span>{ts}</span>
        </div>
      </div>
    </div>
  );
}

/* ── Loading bubble ──────────────────────────────────────────── */

function agentFromSkillId(skillId: string): string {
  if (skillId.includes('.')) return skillId.split('.')[0];
  return 'vega';
}

function LoadingBubble({ skillId }: { skillId: string }) {
  const agent = agentFromSkillId(skillId);
  return (
    <div className="agent-result">
      <div className="agent-avatar-circle">{agentAvatar(agent)}</div>
      <div className="agent-result-body">
        <span className="agent-result-name">{agent} · {skillId} · routing…</span>
        <div className="result-card" style={{ padding: '14px 16px' }}>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--t3)' }}>
            andromeda → pulsar → aether → {agent}
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
  const agent = task.response?.assigned_agent || agentFromSkillId(task.skillId);
  return (
    <div className="agent-result">
      <div className="agent-avatar-circle" style={{ borderColor: 'rgba(255,77,106,0.3)', color: 'var(--red)' }}>!</div>
      <div className="agent-result-body">
        <span className="agent-result-name" style={{ color: 'var(--red)' }}>
          {agent} · {task.skillId} · {task.status}
        </span>
        <div className="result-card" style={{ padding: '14px 16px' }}>
          <p style={{ fontSize: 12, color: 'var(--red)', fontFamily: 'var(--mono)' }}>{msg}</p>
        </div>
      </div>
    </div>
  );
}

function qaResultFor(result: ApiResult | null): QaResult | null {
  if (!result) return null;
  if (result.qa_result?.test_cases) return result.qa_result;
  if (result.test_cases) {
    return {
      test_cases: result.test_cases,
      total_count: result.total_count,
      coverage_summary: result.coverage_summary,
      uncovered_reqs: result.uncovered_reqs,
    };
  }
  return null;
}

function TestCasesPanel({ qaResult }: { qaResult: QaResult }) {
  const cases = qaResult.test_cases ?? [];
  if (!cases.length) return null;

  return (
    <section className="qa-output">
      <div className="qa-output-header">
        <span>Vega test cases</span>
        <span>{qaResult.total_count ?? cases.length} total</span>
      </div>
      <div className="qa-case-list">
        {cases.map((tc, index) => (
          <article key={`${tc.tc_id ?? tc.id ?? index}`} className="qa-case">
            <div className="qa-case-head">
              <span className="qa-case-id">{tc.tc_id ?? tc.id ?? `TC-${index + 1}`}</span>
              <span className="qa-case-title">{tc.title ?? 'Untitled test case'}</span>
              {tc.priority && <span className="qa-pill">{tc.priority}</span>}
              {tc.test_type && <span className="qa-pill">{tc.test_type}</span>}
            </div>
            {tc.req_id && <div className="qa-case-meta">req: {tc.req_id}</div>}
            {Array.isArray(tc.preconditions) && tc.preconditions.length > 0 && (
              <div className="qa-case-block">
                <span className="qa-case-label">preconditions</span>
                <ul>{tc.preconditions.map((item, i) => <li key={i}>{item}</li>)}</ul>
              </div>
            )}
            {Array.isArray(tc.steps) && tc.steps.length > 0 && (
              <div className="qa-case-block">
                <span className="qa-case-label">steps</span>
                <ol>{tc.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
              </div>
            )}
            {tc.expected_result && (
              <div className="qa-case-block">
                <span className="qa-case-label">expected</span>
                <p>{tc.expected_result}</p>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

/* ── Workspace banner ────────────────────────────────────────── */

function WorkspaceBanner() {
  const navigate = useNavigate();
  return (
    <div style={{
      background: '#1a2035',
      borderLeft: '3px solid #f5c040',
      borderRadius: '0 5px 5px 0',
      fontSize: 13,
      padding: '12px 16px',
      marginBottom: 12,
      display: 'flex',
      alignItems: 'center',
      gap: 12,
    }}>
      <span style={{ color: 'var(--t2)', flex: 1, lineHeight: 1.55 }}>
        No workspace configured — files are not being saved to disk.
        Set a workspace root in Settings to write artifacts directly to your project.
      </span>
      <button
        onClick={() => navigate('/settings')}
        style={{
          flexShrink: 0,
          background: 'transparent',
          border: '1px solid rgba(245,192,64,0.35)',
          borderRadius: 5,
          color: 'var(--yellow)',
          fontFamily: 'var(--sans)',
          fontSize: 11,
          padding: '5px 10px',
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        Open Settings
      </button>
    </div>
  );
}

/* ── Artifact card ───────────────────────────────────────────── */

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const savedPath = artifact.written && artifact.path ? artifact.path : null;
  return (
    <div style={{
      border: '1px solid var(--b1)',
      borderRadius: 6,
      marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: 'var(--bg2)',
        borderBottom: artifact.content ? '1px solid var(--b1)' : undefined,
        flexWrap: 'wrap',
      }}>
        <span style={{
          fontFamily: 'var(--mono)',
          fontSize: 11,
          color: savedPath ? 'var(--t2)' : 'var(--t3)',
          fontStyle: savedPath ? undefined : 'italic',
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>
          {savedPath ?? artifact.filename}
        </span>
        <span className="qa-pill">{artifact.language}</span>
        {artifact.written ? (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: '#00d4a0', flexShrink: 0 }}>
            ✓ Saved to disk
          </span>
        ) : (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--t4)', flexShrink: 0 }}>
            Not saved
          </span>
        )}
      </div>
      {artifact.content && (
        <div className="code-output" style={{ marginBottom: 0, borderRadius: 0 }}>
          <span className="co-line" style={{ color: 'var(--t4)', fontSize: 9 }}>{artifact.language}</span>
          <span className="co-empty" />
          {String(artifact.content).split('\n').map((line, i) => (
            <span key={i} className="co-line">{line}</span>
          ))}
        </div>
      )}
      {artifact.error && (
        <p style={{
          fontFamily: 'var(--mono)',
          fontSize: 11,
          color: 'rgba(255,77,106,0.8)',
          padding: '6px 12px',
          margin: 0,
          background: 'rgba(255,77,106,0.05)',
        }}>
          ⚠ {artifact.error}
        </p>
      )}
    </div>
  );
}

/* ── Confidence + gaps disclosure ────────────────────────────── */

function ConfidenceDisclosure({
  confidence,
  breakdown,
  gaps,
}: {
  confidence: number;
  breakdown: Record<string, number | null> | null;
  gaps: string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 10 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          background: 'transparent',
          border: 'none',
          color: 'var(--t3)',
          fontFamily: 'var(--mono)',
          fontSize: 10,
          cursor: 'pointer',
          padding: '4px 0',
        }}
      >
        <span>Confidence details</span>
        <span style={{ fontSize: 8 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={{
          background: 'var(--bg)',
          border: '1px solid var(--b1)',
          borderRadius: 5,
          padding: '10px 14px',
          fontFamily: 'var(--mono)',
          fontSize: 11,
          marginTop: 4,
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            marginBottom: 8,
            paddingBottom: 8,
            borderBottom: '1px solid var(--b1)',
          }}>
            <span style={{ color: 'var(--t3)' }}>Composite score</span>
            <span style={{ color: 'var(--t1)', fontWeight: 600 }}>{Math.round(confidence * 100)}%</span>
          </div>
          {breakdown && Object.entries(breakdown).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
              <span style={{ color: 'var(--t3)' }}>
                {k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')}
              </span>
              <span style={{ color: 'var(--t2)' }}>
                {v === null || v === undefined ? '—' : typeof v === 'number' ? `${Math.round(v * 100)}%` : String(v)}
              </span>
            </div>
          ))}
          <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--b1)' }}>
            <span style={{ color: 'var(--t3)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
              Gaps
            </span>
            {gaps.length > 0 ? (
              <ul style={{ margin: '5px 0 0 16px', padding: 0, color: 'var(--t2)', fontSize: 11, lineHeight: 1.6 }}>
                {gaps.map((gap, i) => <li key={i}>{gap}</li>)}
              </ul>
            ) : (
              <p style={{ margin: '4px 0 0', color: 'var(--t4)', fontSize: 11 }}>No gaps identified</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Agent result bubble ─────────────────────────────────────── */

function AgentResultBubble({
  task,
  onFeedback,
}: {
  task: SubmittedTask;
  onFeedback: (outcome: 'accepted' | 'rejected') => void;
}) {
  const [submitting, setSubmitting] = useState<'accepted' | 'rejected' | null>(null);

  const resp       = task.response!;
  const conf       = resp.confidence ?? 0;
  const cc         = confColor(conf);
  const raw        = resp.result?.code ?? '';
  const code       = extractCode(raw);
  const lang       = resp.result?.language ?? 'text';
  const notes      = resp.result?.notes ?? '';
  const agent      = resp.assigned_agent || agentFromSkillId(task.skillId);
  const qaResult   = qaResultFor(resp.result);
  const artifacts  = resp.artifacts ?? [];
  const hasArtifacts = artifacts.length > 0;

  async function handleFeedback(outcome: 'accepted' | 'rejected') {
    if (task.feedback || submitting) return;
    setSubmitting(outcome);
    try {
      const res = await fetch(`/api/tasks/${resp.task_id}/feedback`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ outcome }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onFeedback(outcome);
    } catch {
      // feedback failed — reset so user can retry
    } finally {
      setSubmitting(null);
    }
  }

  const feedbackDone = !!task.feedback;

  return (
    <div className="agent-result">
      <div className="agent-avatar-circle">{agentAvatar(agent)}</div>

      <div className="agent-result-body">
        <span className="agent-result-name">{agent} · {task.skillId}</span>

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
              {feedbackDone ? (
                <span className="feedback-confirmed" style={{ color: task.feedback === 'accepted' ? 'var(--green)' : 'var(--red)' }}>
                  {task.feedback === 'accepted' ? '✓ Accepted' : '✗ Rejected'}
                </span>
              ) : (
                <>
                  <button
                    className="btn btn-accept btn-sm"
                    disabled={submitting !== null}
                    onClick={() => handleFeedback('accepted')}
                  >
                    {submitting === 'accepted' ? '…' : '✓ Accept'}
                  </button>
                  <button
                    className="btn btn-reject btn-sm"
                    disabled={submitting !== null}
                    onClick={() => handleFeedback('rejected')}
                  >
                    {submitting === 'rejected' ? '…' : '✗ Reject'}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Workspace banner — only when artifacts present and no workspace configured */}
          {hasArtifacts && !resp.workspace_path && <WorkspaceBanner />}

          {/* Artifact cards */}
          {hasArtifacts && artifacts.map((artifact, i) => (
            <ArtifactCard key={i} artifact={artifact} />
          ))}

          {/* Fallback code block — backward compat when no artifacts returned */}
          {!hasArtifacts && code && (
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

          {/* Vega QA output */}
          {qaResult && <TestCasesPanel qaResult={qaResult} />}

          {/* Confidence + gaps disclosure */}
          <ConfidenceDisclosure
            confidence={conf}
            breakdown={resp.confidence_breakdown}
            gaps={resp.gaps ?? []}
          />

          {/* Orion notice */}
          <div className="orion-notice">
            <span className="orion-notice-dot" />
            <span className="orion-notice-text">
              FeedbackEvent emitted → Aether · Orion ingestion is active · task_id: {resp.task_id}
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
  agents,
  skills,
}: {
  routeMode:    string;
  setRouteMode: (m: string) => void;
  skillId:      string;
  setSkillId:   (s: string) => void;
  agents:       AgentManifest[];
  skills:       SkillOption[];
}) {
  const selectedSkill = skills.find((s) => s.skillId === skillId);

  function selectRouteMode(mode: string) {
    setRouteMode(mode);
    if (mode !== 'auto') {
      const first = skills.find((s) => s.agentId === mode);
      if (first && selectedSkill?.agentId !== mode) setSkillId(first.skillId);
    }
  }

  const chipModes = ['auto', ...agents.map((a) => a.agent_id)];

  return (
    <div className="agent-selector-bar">
      <span className="agent-selector-label">Route via:</span>
      <div className="agent-chips">
        {chipModes.map((m) => {
          const color = m === 'auto' ? '#64748b' : agentColorFor(m, agents);
          const label = m === 'auto' ? 'Auto-route' : (agents.find((a) => a.agent_id === m)?.agent_name ?? m);
          return (
            <button
              key={m}
              className="agent-chip"
              style={{
                opacity: routeMode === m ? 1 : 0.5,
                cursor: 'pointer',
                borderColor: color,
                color: routeMode === m ? color : 'var(--t3)',
                background: routeMode === m ? `${color}18` : 'transparent',
              }}
              onClick={() => selectRouteMode(m)}
              title={m === 'auto' ? 'Andromeda routes by selected skill manifest' : undefined}
            >
              {label}
            </button>
          );
        })}
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
          {skills.map((s) => (
            <option key={s.skillId} value={s.skillId}>{s.label}</option>
          ))}
        </select>
        <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--t4)' }}>
          routes to {selectedSkill?.agentId ?? '—'}
        </span>
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
        api: localhost:8001 · andromeda routes by skill manifest · ⌘Enter to send
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
  onChange:  React.Dispatch<React.SetStateAction<string>>;
  onSend:    () => void;
  disabled:  boolean;
  routeMode: string;
}) {
  const fileInputId = useId();

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSend();
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    void Promise.all(
      files.map(async (file) => ({
        name: file.name,
        content: await file.text(),
      })),
    ).then((attachments) => {
      onChange((current) => {
        const attachmentText = attachments
          .map((attachment) => `--- ${attachment.name} ---\n${attachment.content}`)
          .join('\n\n');
        return current.trim() ? `${current}\n\n${attachmentText}` : attachmentText;
      });
    });
    e.target.value = '';
  }

  return (
    <div className="input-bar">
      <input
        id={fileInputId}
        className="file-input-hidden"
        type="file"
        multiple
        onChange={handleFileChange}
        disabled={disabled}
      />
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
          <label
            className={`micro-btn ${disabled ? 'is-disabled' : ''}`}
            htmlFor={fileInputId}
            aria-disabled={disabled}
            onClick={(event) => {
              if (disabled) event.preventDefault();
            }}
          >
            <PaperclipIcon /> Attach
          </label>
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
  const [initialSession] = useState(loadTaskUiSession);
  const [tasks,      setTasks]      = useState<SubmittedTask[]>(() => parseTasks(initialSession.tasks));
  const [archivedThreads, setArchivedThreads] = useState<ArchivedTaskThread[]>(initialSession.archivedThreads);
  const [draftText,  setDraftText]  = useState(initialSession.draftText);
  const [routeMode,  setRouteMode]  = useState<string>(initialSession.routeMode);
  const [skillId,    setSkillId]    = useState(initialSession.skillId);
  const [submitting, setSubmitting] = useState(false);
  const [agents,     setAgents]     = useState<AgentManifest[]>([]);

  useEffect(() => {
    fetch('/api/agents')
      .then((r) => r.json())
      .then(setAgents)
      .catch(() => {});
  }, []);

  const skills = deriveSkills(agents);

  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [tasks]);

  useEffect(() => {
    persistTaskUiSession({
      tasks: serializeTasks(tasks),
      archivedThreads,
      draftText,
      routeMode,
      skillId,
    });
  }, [tasks, archivedThreads, draftText, routeMode, skillId]);

  function archiveCurrentTasks(nextArchive = archivedThreads): ArchivedTaskThread[] {
    if (tasks.length === 0) return nextArchive;
    return [archiveFromTasks(tasks), ...nextArchive].slice(0, 24);
  }

  function handleNewSubmission() {
    if (submitting) return;
    const nextArchive = archiveCurrentTasks();
    setArchivedThreads(nextArchive);
    setTasks([]);
    setDraftText('');
    persistTaskUiSession({
      tasks: [],
      archivedThreads: nextArchive,
      draftText: '',
      routeMode,
      skillId,
    });
  }

  function handleOpenThread(thread: ArchivedTaskThread) {
    if (submitting) return;
    const remaining = archivedThreads.filter((item) => item.id !== thread.id);
    const nextArchive = archiveCurrentTasks(remaining);
    const restoredTasks = parseTasks(thread.tasks);
    setArchivedThreads(nextArchive);
    setTasks(restoredTasks);
    setDraftText('');
    persistTaskUiSession({
      tasks: serializeTasks(restoredTasks),
      archivedThreads: nextArchive,
      draftText: '',
      routeMode,
      skillId,
    });
  }

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

    const nextTasks = [...tasks, newTask];
    const sessionContext = buildSessionContext(tasks);
    setTasks(nextTasks);
    persistTaskUiSession({
      tasks: serializeTasks(nextTasks),
      archivedThreads,
      draftText: '',
      routeMode,
      skillId,
    });
    setDraftText('');
    setSubmitting(true);

    try {
      const res = await fetch('/api/task', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          task: newTask.text,
          skill_id: fullSkillId(newTask.skillId, skills),
          route_mode: routeMode,
          session_context: sessionContext,
        }),
      });

      if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
      const data: ApiResponse = await res.json();

      const finalStatus: SubmittedTask['status'] =
        data.status === 'complete'        ? 'complete'  :
        data.escalated_to_human           ? 'escalated' : 'failed';

      updatePersistedTask(
        localId,
        (task) => ({ ...task, status: finalStatus, response: data }),
        { draftText: '', routeMode, skillId },
      );
      setTasks((prev) => {
        const updated = prev.map((t) =>
          t.localId === localId ? { ...t, status: finalStatus, response: data } : t
        );
        persistTaskUiSession({
          tasks: serializeTasks(updated),
          archivedThreads,
          draftText: '',
          routeMode,
          skillId,
        });
        return updated;
      });
    } catch (err) {
      updatePersistedTask(
        localId,
        (task) => ({ ...task, status: 'failed', error: String(err) }),
        { draftText: '', routeMode, skillId },
      );
      setTasks((prev) => {
        const updated = prev.map((t) =>
          t.localId === localId ? { ...t, status: 'failed' as const, error: String(err) } : t
        );
        persistTaskUiSession({
          tasks: serializeTasks(updated),
          archivedThreads,
          draftText: '',
          routeMode,
          skillId,
        });
        return updated;
      });
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
        extraNav={
          <RecentTasksSection
            tasks={tasks}
            archivedThreads={archivedThreads}
            onNewSubmission={handleNewSubmission}
            onOpenThread={handleOpenThread}
            disabled={submitting}
          />
        }
      />

      <div className="app-main">
        {/* Topbar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Task UI</span>
            <span className="topbar-sub">— submit tasks · view routing trace · review results</span>
          </div>
          <div className="topbar-right">
            <button className="topbar-action" onClick={handleNewSubmission} disabled={submitting}>
              New
            </button>
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
          agents={agents}
          skills={skills}
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
              {task.status === 'complete'  && (
                <AgentResultBubble
                  task={task}
                  onFeedback={(outcome) =>
                    setTasks((prev) => prev.map((t) =>
                      t.localId === task.localId ? { ...t, feedback: outcome } : t
                    ))
                  }
                />
              )}
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
