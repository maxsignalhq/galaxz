import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/devconsole.css';

/* ── Syntax token helper (module scope, React JSX) ─────────── */

const P = (t: string) => <span style={{ color: '#8a94b0' }}>{t}</span>; // plain

/* ── Types ───────────────────────────────────────────────────── */

type AgentId  = string;
type TabId    = 'manifest' | 'skills' | 'llm-config' | 'logs';
type LogLevel = 'INFO' | 'DEBUG' | 'WARN';

interface AgentManifest {
  agent_id: string;
  agent_name: string;
  version: string;
  skills: SkillDefinition[];
}
interface SkillDefinition {
  skill_id: string;
  description: string;
  avg_confidence?: number;
  avg_latency_ms?: number;
}
interface SkillRow  { id: string; confidence: number | null; latency: string | null; tasks: number | null; }
interface LogEntry  { ts: string; level: LogLevel; content: React.ReactNode; }

/* ── Shared ──────────────────────────────────────────────────── */

const LEVEL_COLORS: Record<LogLevel, string> = {
  INFO:  'var(--green)',
  DEBUG: 'var(--blue)',
  WARN:  'var(--yellow)',
};

/* ── Icons ───────────────────────────────────────────────────── */

function SearchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 8L10.5 10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/* ── Tab sub-components ──────────────────────────────────────── */

function ManifestTab({ lines, filename }: { lines: Array<React.ReactNode | null>; filename: string }) {
  return (
    <div className="code-block">
      <div className="code-block-hdr">
        <span className="code-block-filename">{filename}</span>
        <button className="btn btn-ghost btn-sm">Copy</button>
      </div>
      <div className="code-block-body">
        {lines.map((line, i) =>
          line === null
            ? <span key={i} className="cl-empty" />
            : <span key={i} className="cl">{line}</span>
        )}
      </div>
    </div>
  );
}

function manifestLinesFor(manifest: AgentManifest | null, error: string | null): Array<React.ReactNode | null> {
  if (!manifest) {
    return [
      <>{P(error ?? 'Waiting for /api/agents to return a live manifest.')}</>,
    ];
  }

  return JSON.stringify(manifest, null, 2)
    .split('\n')
    .map((line) => <>{P(line)}</>);
}

function SkillsTab({ skills }: { skills: SkillRow[] }) {
  return (
    <div className="skills-table-wrap">
      <table className="skills-table">
        <thead>
          <tr>
            <th>Skill ID</th>
            <th>Status</th>
            <th>Manifest Confidence</th>
            <th>Avg Latency</th>
            <th>Live Tasks</th>
          </tr>
        </thead>
        <tbody>
          {skills.map(sk => (
            <tr key={sk.id} className="skill-tr">
              <td><span className="sk-id">{sk.id}</span></td>
              <td>
                <div className="sk-status">
                  <span className="sk-dot" />
                  <span className="sk-active-text">active</span>
                </div>
              </td>
              <td>
                <div className="sk-rate-track">
                  <div className="sk-rate-fill" style={{ width: `${(sk.confidence ?? 0) * 100}%` }} />
                </div>
              </td>
              <td><span className="sk-latency">{sk.latency ?? '—'}</span></td>
              <td><span className="sk-tasks">{sk.tasks ?? '—'}</span></td>
            </tr>
          ))}
          {skills.length === 0 && (
            <tr className="skill-tr">
              <td colSpan={5}>
                <span className="sk-latency">No live skills returned from /api/agents.</span>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function LlmConfigTab() {
  return (
    <>
      <div className="llm-banner">
        <span style={{ fontWeight: 600, color: 'var(--blue)' }}>Live LLM config endpoint unavailable</span>
        {' — per-skill model selections are not rendered from synthetic configuration.'}
      </div>

      <span className="llm-section-label">Per-Skill Model Overrides</span>

      <div className="llm-row">
        <div className="llm-row-left">
          <div className="llm-skill-name">No live model configuration returned.</div>
          <div className="llm-skill-desc">Add a backend config endpoint before rendering editable model assignments here.</div>
        </div>
      </div>
    </>
  );
}

function LogsTab({ logs, agentId }: { logs: LogEntry[]; agentId: string }) {
  return (
    <div className="log-panel">
      <div className="log-panel-hdr">
        <span className="log-panel-title">{agentId} · live log output</span>
        <button className="btn btn-ghost btn-sm">Clear</button>
      </div>
      <div className="log-body">
        {logs.length === 0 && (
          <div className="log-line">
            <span className="log-ts">—</span>
            <span className="log-lvl" style={{ color: 'var(--t4)' }}>INFO</span>
            <span className="log-msg">No live log endpoint is available for this agent. Synthetic log lines are not rendered.</span>
          </div>
        )}
        {logs.map((entry, i) => (
          <div key={i} className="log-line">
            <span className="log-ts">{entry.ts}</span>
            <span className="log-lvl" style={{ color: LEVEL_COLORS[entry.level] }}>
              {entry.level}
            </span>
            <span className="log-msg">{entry.content}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── DevConsole ──────────────────────────────────────────────── */

export function DevConsole() {
  const [selected, setSelected] = useState<AgentId>('rigel');
  const [tab, setTab]           = useState<TabId>('manifest');
  const [agents, setAgents]     = useState<AgentManifest[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadAgents() {
      try {
        const res = await fetch('/api/agents');
        if (!res.ok) throw new Error(`agents HTTP ${res.status}`);
        const nextAgents = await res.json();
        if (!cancelled) {
          setAgents(nextAgents);
          setLoadError(null);
          if (nextAgents.length > 0 && !nextAgents.some((agent: AgentManifest) => agent.agent_id === selected)) {
            setSelected(nextAgents[0].agent_id);
          }
        }
      } catch (err) {
        if (!cancelled) setLoadError(String(err));
      }
    }

    loadAgents();
    const timer = window.setInterval(loadAgents, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selected]);

  const isRigel = selected === 'rigel';
  const selectedManifest = agents.find((agent) => agent.agent_id === selected) ?? null;

  const agentColor   = isRigel ? '#f5c040' : selected === 'vega' ? '#00d4a0' : 'var(--blue)';
  const agentType    = selectedManifest?.agent_name ?? 'No live manifest loaded';
  const agentMeta1   = selectedManifest
    ? `agent_id: ${selectedManifest.agent_id} · registered in Pulsar`
    : `agent_id: ${selected} · not returned by /api/agents`;
  const agentMeta2   = selectedManifest
    ? `skills: ${selectedManifest.skills.map(skill => skill.skill_id).join(', ')}`
    : (loadError ?? 'Awaiting /api/agents response');

  const manifestLines  = manifestLinesFor(selectedManifest, loadError);
  const manifestFile   = selectedManifest
    ? `/api/agents — ${selectedManifest.agent_id}`
    : '/api/agents';
  const skills: SkillRow[] = selectedManifest?.skills.map((skill) => ({
    id: skill.skill_id,
    confidence: typeof skill.avg_confidence === 'number' ? skill.avg_confidence : null,
    latency: typeof skill.avg_latency_ms === 'number' ? `${skill.avg_latency_ms}ms` : null,
    tasks: null,
  })) ?? [];
  const logs: LogEntry[]   = [];

  const TABS: { id: TabId; label: string }[] = [
    { id: 'manifest',   label: 'Manifest'   },
    { id: 'skills',     label: 'Skills'     },
    { id: 'llm-config', label: 'LLM Config' },
    { id: 'logs',       label: 'Logs'       },
  ];

  return (
    <div className="app-shell">
      <Sidebar activeId="dev-console" />

      <div className="app-main">

        {/* ── Topbar ── */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Dev Console</span>
            <span className="topbar-sub">— agent registry &amp; manifests</span>
          </div>
          <div className="topbar-right">
            <button className="btn btn-outline btn-sm">+ New agent</button>
            <button className="btn btn-primary btn-sm">Deploy</button>
          </div>
        </div>

        {/* ── Horizontal split ── */}
        <div className="devconsole-body">

          {/* ─── Left panel: Agent list ─── */}
          <aside className="agent-list-panel">

            <div className="agent-list-hdr">
              <span className="agent-list-label">Registered Agents</span>
              <span className="agent-list-count">{agents.length}</span>
            </div>

            <div className="agent-search-wrap">
              <div className="agent-search-inner">
                <span style={{ color: 'var(--t4)', display: 'flex' }}><SearchIcon /></span>
                <input
                  className="agent-search-input"
                  type="text"
                  placeholder="Search agents…"
                />
              </div>
            </div>

            <div className="agent-list-scroll">
              {agents.length === 0 && (
                <div className="agent-item">
                  <div className="agent-item-hdr">
                    <span className="agent-item-name">No live agents returned</span>
                  </div>
                  <div className="agent-item-meta">{loadError ?? 'Waiting for /api/agents'}</div>
                </div>
              )}

              {agents.map((agent) => {
                const color = agent.agent_id === 'rigel'
                  ? '#f5c040'
                  : agent.agent_id === 'vega'
                    ? '#00d4a0'
                    : 'var(--blue)';
                return (
                  <div
                    key={agent.agent_id}
                    className={`agent-item${selected === agent.agent_id ? ' selected' : ''}`}
                    onClick={() => { setSelected(agent.agent_id); setTab('manifest'); }}
                  >
                    <div className="agent-item-hdr">
                      <span
                        className="agent-item-dot"
                        style={{ background: color, boxShadow: `0 0 5px ${color}` }}
                      />
                      <span className="agent-item-name" style={{ color }}>{agent.agent_id}</span>
                      <span className="agent-item-ver">v{agent.version}</span>
                    </div>
                    <div className="agent-item-meta">{agent.agent_name} · {agent.skills.length} skills</div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* ─── Right panel: Detail ─── */}
          <div className="detail-panel">

            {/* Detail header */}
            <div className="detail-header">
              <div className="detail-header-inner">
                <div>
                  <div className="detail-title-row">
                    <span className="detail-name" style={{ color: agentColor }}>{selected}</span>
                    <span className="detail-type">{agentType}</span>
                  </div>
                  <div className="detail-meta">
                    <div>{agentMeta1}</div>
                    <div>{agentMeta2}</div>
                  </div>
                </div>
                <div className="detail-hdr-actions">
                  <button className="btn btn-outline btn-sm">View logs</button>
                  <button className="btn btn-outline btn-sm">Restart</button>
                  <button className="btn btn-primary btn-sm">Edit manifest</button>
                </div>
              </div>
            </div>

            {/* Tab bar */}
            <div className="detail-tabs">
              {TABS.map(t => (
                <button
                  key={t.id}
                  className={`tab-btn${tab === t.id ? ' active' : ''}`}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="tab-content">
              {tab === 'manifest' && (
                <ManifestTab lines={manifestLines} filename={manifestFile} />
              )}

              {tab === 'skills' && (
                <SkillsTab skills={skills} />
              )}

              {tab === 'llm-config' && (
                <LlmConfigTab />
              )}

              {tab === 'logs' && (
                <LogsTab logs={logs} agentId={selected} />
              )}
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

export default DevConsole;
