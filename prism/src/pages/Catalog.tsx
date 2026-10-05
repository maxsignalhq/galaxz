import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';

interface CatalogEntry {
  agent_id: string;
  agent_name: string;
  version: string;
  versions: string[];
  description: string;
  author: string;
  tags: string[];
  skills: string[];
  installed_version: string | null;
}

const mono = "'Geist Mono', monospace";

export function Catalog() {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      const res = await fetch('/api/catalog');
      if (!res.ok) throw new Error(`catalog HTTP ${res.status}`);
      setEntries(await res.json());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function install(entry: CatalogEntry, force: boolean) {
    if (force && !window.confirm(`Overwrite the installed ${entry.agent_id} config with catalog v${entry.version}?`)) {
      return;
    }
    setBusy(entry.agent_id);
    setStatus(null);
    try {
      const res = await fetch(`/api/catalog/${entry.agent_id}/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force }),
      });
      if (!res.ok) throw new Error(`install HTTP ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setStatus(
        data.restart_required
          ? `${entry.agent_id} ${data.version} installed — restart Galaxz to load it.`
          : `${entry.agent_id} ${data.version} is already installed.`,
      );
      setError(null);
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="catalog" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)' }}>Catalog</span>
          <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
            — installable agents · restart required after install
          </span>
        </div>

        {status && (
          <div style={{ color: '#3fb950', fontFamily: mono, fontSize: 11, marginBottom: 12 }}>{status}</div>
        )}
        {error && (
          <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginBottom: 12 }}>{error}</div>
        )}

        {entries.length === 0 && !error && (
          <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>No agents in the catalog.</div>
        )}

        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {entries.map((e) => {
            const upToDate = e.installed_version === e.version;
            const differs = e.installed_version !== null && !upToDate;
            return (
              <div
                key={e.agent_id}
                style={{ border: '1px solid var(--b1)', borderRadius: 8, padding: 14, background: 'var(--bg1)' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 13.5, color: 'var(--t1)' }}>{e.agent_name}</span>
                  <span style={{ fontFamily: mono, fontSize: 10.5, color: 'var(--t4)' }}>v{e.version}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--t2)', margin: '6px 0 8px' }}>{e.description}</div>
                <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)', marginBottom: 10 }}>
                  {e.skills.join(' · ')}
                  {e.tags.length > 0 && <div style={{ marginTop: 4 }}>{e.tags.map((t) => `#${t}`).join(' ')}</div>}
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button
                    disabled={busy === e.agent_id || upToDate}
                    onClick={() => install(e, differs)}
                    style={{
                      fontFamily: mono,
                      fontSize: 11,
                      padding: '4px 10px',
                      borderRadius: 5,
                      border: '1px solid var(--b1)',
                      background: 'transparent',
                      color: 'var(--t2)',
                      cursor: upToDate ? 'default' : 'pointer',
                    }}
                  >
                    {upToDate ? 'Installed' : differs ? 'Replace installed' : 'Install'}
                  </button>
                  {differs && (
                    <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                      installed: {e.installed_version}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
