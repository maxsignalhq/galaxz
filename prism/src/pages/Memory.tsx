import React, { useCallback, useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import { timeAgo } from '../utils/time';
import '../styles/tokens.css';

interface MemoryEntry {
  memory_id: string;
  namespace: string;
  content: string;
  tags: string[];
  source_task_id: string | null;
  created_at: string;
}

interface NamespaceRow {
  namespace: string;
  count: number;
}

const mono = "'Geist Mono', monospace";

const inputStyle: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 12,
  padding: '6px 8px',
  borderRadius: 5,
  border: '1px solid var(--b1)',
  background: 'var(--bg1)',
  color: 'var(--t1)',
};

const buttonStyle: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 11,
  padding: '5px 10px',
  borderRadius: 5,
  border: '1px solid var(--b1)',
  background: 'transparent',
  color: 'var(--t2)',
  cursor: 'pointer',
};

export function Memory() {
  const [namespaces, setNamespaces] = useState<NamespaceRow[]>([]);
  const [namespace, setNamespace] = useState('global');
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [content, setContent] = useState('');
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const loadNamespaces = useCallback(async () => {
    const res = await fetch('/api/memory/namespaces');
    if (!res.ok) throw new Error(`namespaces HTTP ${res.status}`);
    setNamespaces(await res.json());
  }, []);

  const loadEntries = useCallback(async () => {
    const qs = new URLSearchParams({ namespace, limit: '50' });
    if (query.trim()) qs.set('q', query.trim());
    const res = await fetch(`/api/memory?${qs}`);
    if (!res.ok) throw new Error(`memory HTTP ${res.status}`);
    setEntries(await res.json());
  }, [namespace, query]);

  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadNamespaces(), loadEntries()]);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, [loadNamespaces, loadEntries]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function add() {
    if (!content.trim() || !namespace.trim()) return;
    try {
      const res = await fetch('/api/memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          namespace: namespace.trim(),
          content: content.trim(),
          tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        }),
      });
      if (!res.ok) throw new Error(`save HTTP ${res.status}: ${await res.text()}`);
      setContent('');
      setTags('');
      setStatus('Memory saved.');
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  async function forget(entry: MemoryEntry) {
    if (!window.confirm('Delete this memory?')) return;
    try {
      const res = await fetch(`/api/memory/${entry.memory_id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`delete HTTP ${res.status}`);
      setStatus('Memory deleted.');
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="memory" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)' }}>Memory</span>
          <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
            — Nebula · notes recalled into tasks by origin and the global namespace
          </span>
        </div>
        <div style={{ fontFamily: mono, fontSize: 10.5, color: 'var(--t4)', marginBottom: 14 }}>
          A task from origin <code>goal:&lt;id&gt;</code> recalls memories from that namespace plus <code>global</code>.
          Only Rigel code generation uses them so far.
        </div>

        {status && <div style={{ color: '#3fb950', fontFamily: mono, fontSize: 11, marginBottom: 10 }}>{status}</div>}
        {error && <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginBottom: 10 }}>{error}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '230px 1fr', gap: 18 }}>
          <div style={{ border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden', alignSelf: 'start' }}>
            <div
              style={{
                padding: '8px 12px',
                fontFamily: mono,
                fontSize: 10,
                letterSpacing: '0.15em',
                textTransform: 'uppercase',
                color: 'var(--t4)',
                borderBottom: '1px solid var(--b1)',
              }}
            >
              Namespaces
            </div>
            {namespaces.length === 0 && (
              <div style={{ padding: 12, fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>None yet.</div>
            )}
            {namespaces.map((n) => (
              <div
                key={n.namespace}
                onClick={() => setNamespace(n.namespace)}
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--b1)',
                  background: namespace === n.namespace ? 'var(--hover-overlay)' : 'transparent',
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: 12,
                  color: 'var(--t1)',
                }}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.namespace}</span>
                <span style={{ fontFamily: mono, fontSize: 10.5, color: 'var(--t4)' }}>{n.count}</span>
              </div>
            ))}
          </div>

          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
              <input
                aria-label="namespace"
                style={{ ...inputStyle, width: 200 }}
                value={namespace}
                onChange={(e) => setNamespace(e.target.value)}
                placeholder="namespace (or a,b)"
              />
              <input
                aria-label="search"
                style={{ ...inputStyle, flex: 1, minWidth: 160 }}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="search keywords…"
              />
              <button style={buttonStyle} onClick={refresh}>
                Refresh
              </button>
            </div>

            <div style={{ border: '1px solid var(--b1)', borderRadius: 8, padding: 12, marginBottom: 16 }}>
              <textarea
                aria-label="new memory"
                style={{ ...inputStyle, width: '100%', minHeight: 60, boxSizing: 'border-box', resize: 'vertical' }}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder={`New memory in "${namespace}" — e.g. always parse config with yaml.safe_load`}
              />
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <input
                  aria-label="tags"
                  style={{ ...inputStyle, flex: 1 }}
                  value={tags}
                  onChange={(e) => setTags(e.target.value)}
                  placeholder="tags, comma separated (optional)"
                />
                <button style={buttonStyle} onClick={add} disabled={!content.trim() || !namespace.trim()}>
                  Save memory
                </button>
              </div>
            </div>

            {entries.length === 0 && (
              <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
                No memories match in "{namespace}".
              </div>
            )}
            {entries.map((e) => (
              <div
                key={e.memory_id}
                style={{ border: '1px solid var(--b1)', borderRadius: 8, padding: 12, marginBottom: 10, background: 'var(--bg1)' }}
              >
                <div style={{ fontSize: 13, color: 'var(--t1)', whiteSpace: 'pre-wrap' }}>{e.content}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                  <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                    {e.namespace} · {timeAgo(e.created_at)}
                    {e.tags.length > 0 && ` · ${e.tags.map((t) => `#${t}`).join(' ')}`}
                  </span>
                  <button style={buttonStyle} onClick={() => forget(e)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
