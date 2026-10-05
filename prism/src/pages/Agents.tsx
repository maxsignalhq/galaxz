import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';

interface Skill {
  skill_id: string;
  description: string;
  allowed_origins?: string[] | null;
}

interface Agent {
  agent_id: string;
  agent_name: string;
  version: string;
  skills: Skill[];
}

interface McpServer {
  name: string;
  ok: boolean;
  error: string | null;
  tools: Array<{ skill_id: string; description: string }>;
  allowed_origins: string[] | null;
}

interface QuasarStatus {
  configured: boolean;
  servers: McpServer[];
}

const mono = "'Geist Mono', monospace";

function chip(text: string, color: string): React.ReactElement {
  return (
    <span
      key={text}
      style={{
        fontFamily: mono,
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 10,
        border: `1px solid ${color}`,
        color,
        whiteSpace: 'nowrap',
      }}
    >
      {text}
    </span>
  );
}

/** Who may route to a skill: null = open, [] = nobody, otherwise fnmatch patterns on the task origin. */
function Access({ origins }: { origins?: string[] | null }) {
  if (origins === null || origins === undefined) return chip('open', '#3fb950');
  if (origins.length === 0) return chip('no origin allowed', '#f85149');
  return <>{origins.map((o) => chip(o, '#d29922'))}</>;
}

const sectionTitle: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 10,
  letterSpacing: '0.15em',
  textTransform: 'uppercase',
  color: 'var(--t4)',
  margin: '22px 0 10px',
};

export function Agents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [quasar, setQuasar] = useState<QuasarStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [a, q] = await Promise.all([fetch('/api/agents'), fetch('/api/quasar')]);
      if (!a.ok) throw new Error(`agents HTTP ${a.status}`);
      if (!q.ok) throw new Error(`quasar HTTP ${q.status}`);
      setAgents(await a.json());
      setQuasar(await q.json());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="agents" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)' }}>Agents &amp; Tools</span>
          <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
            — registered skills · who may call them · MCP tool servers
          </span>
        </div>
        <div style={{ fontFamily: mono, fontSize: 10.5, color: 'var(--t4)', marginBottom: 12 }}>
          Access shows a skill's <code>allowed_origins</code>: <b>open</b> means any origin; patterns such as{' '}
          <code>goal:*</code> limit it to matching task origins. Set in an agent's manifest; read-only here.
        </div>

        {error && <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginBottom: 12 }}>{error}</div>}

        <div style={sectionTitle}>MCP tool servers (Quasar)</div>
        {quasar && !quasar.configured && (
          <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
            No MCP servers configured. Add some to <code>config/mcp.yaml</code> and restart.
          </div>
        )}
        {quasar?.servers.map((s) => (
          <div
            key={s.name}
            style={{ border: '1px solid var(--b1)', borderRadius: 8, padding: 12, marginBottom: 10, background: 'var(--bg1)', flexShrink: 0 }}
          >
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--t1)' }}>{s.name}</span>
              {s.ok ? chip(`${s.tools.length} tools`, '#3fb950') : chip('failed to start', '#f85149')}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 4, alignItems: 'center' }}>
                <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>access</span>
                <Access origins={s.allowed_origins} />
              </span>
            </div>
            {s.error && (
              <div style={{ fontFamily: mono, fontSize: 11, color: '#f85149', marginTop: 6 }}>{s.error}</div>
            )}
            {s.tools.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ fontFamily: mono, fontSize: 11, color: 'var(--t3)', cursor: 'pointer' }}>
                  Show tools
                </summary>
                {s.tools.map((t) => (
                  <div key={t.skill_id} style={{ fontSize: 12, color: 'var(--t2)', marginTop: 6 }}>
                    <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t1)' }}>{t.skill_id}</span> — {t.description}
                  </div>
                ))}
              </details>
            )}
          </div>
        ))}

        <div style={sectionTitle}>Registered agents ({agents.length})</div>
        {agents.length === 0 && !error && (
          <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>No agents registered.</div>
        )}
        {agents.map((a) => (
          <div
            key={a.agent_id}
            style={{ border: '1px solid var(--b1)', borderRadius: 8, marginBottom: 12, overflow: 'hidden', flexShrink: 0 }}
          >
            <div
              style={{
                padding: '9px 12px',
                borderBottom: '1px solid var(--b1)',
                display: 'flex',
                alignItems: 'baseline',
                gap: 10,
              }}
            >
              <span style={{ fontSize: 13.5, color: 'var(--t1)' }}>{a.agent_name}</span>
              <span style={{ fontFamily: mono, fontSize: 10.5, color: 'var(--t4)' }}>
                {a.agent_id} · v{a.version} · {a.skills.length} skills
              </span>
            </div>
            {a.skills.map((s) => (
              <div
                key={s.skill_id}
                style={{
                  padding: '7px 12px',
                  borderBottom: '1px solid var(--b1)',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'baseline',
                  flexWrap: 'wrap',
                }}
              >
                <span style={{ fontFamily: mono, fontSize: 11.5, color: 'var(--t1)' }}>{s.skill_id}</span>
                <span style={{ fontSize: 11.5, color: 'var(--t3)', flex: 1, minWidth: 160 }}>{s.description}</span>
                <span style={{ display: 'flex', gap: 4 }}>
                  <Access origins={s.allowed_origins} />
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
