import React, { useEffect, useMemo, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import { timeAgo } from '../utils/time';
import '../styles/tokens.css';

interface FileRow {
  identity_key: string;
  filename: string;
  latest_version: number;
  updated_at: string;
  task_id: string;
}

interface VersionRow {
  version: number;
  task_id: string;
  skill: string;
  created_at: string;
  content_hash: string;
}

function splitKey(identityKey: string): { workspaceRoot: string; path: string } {
  const idx = identityKey.indexOf('::');
  if (idx === -1) return { workspaceRoot: '', path: identityKey };
  return { workspaceRoot: identityKey.slice(0, idx), path: identityKey.slice(idx + 2) };
}

const mono = "'Geist Mono', monospace";

function DiffView({ text }: { text: string }) {
  const lines = text.length ? text.split('\n') : [];
  return (
    <pre
      style={{
        margin: 0,
        padding: 12,
        fontFamily: mono,
        fontSize: 11.5,
        lineHeight: 1.5,
        overflowX: 'auto',
        background: 'var(--bg1)',
        border: '1px solid var(--b1)',
        borderRadius: 6,
      }}
    >
      {lines.map((line, i) => {
        let color = 'var(--t2)';
        if (line.startsWith('+') && !line.startsWith('+++')) color = '#3fb950';
        else if (line.startsWith('-') && !line.startsWith('---')) color = '#f85149';
        else if (line.startsWith('@@')) color = '#a371f7';
        return (
          <div key={i} style={{ color, whiteSpace: 'pre' }}>
            {line || ' '}
          </div>
        );
      })}
    </pre>
  );
}

export function Artifacts() {
  const [files, setFiles] = useState<FileRow[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [history, setHistory] = useState<VersionRow[]>([]);
  const [fromVersion, setFromVersion] = useState<number | null>(null);
  const [toVersion, setToVersion] = useState<number | null>(null);
  const [diffText, setDiffText] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [confirmRollback, setConfirmRollback] = useState<number | null>(null);

  const selectedFile = useMemo(
    () => files.find((f) => f.identity_key === selectedKey) ?? null,
    [files, selectedKey],
  );

  async function loadFiles() {
    try {
      const res = await fetch('/api/artifacts');
      if (!res.ok) throw new Error(`artifacts HTTP ${res.status}`);
      setFiles(await res.json());
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => {
    loadFiles();
  }, []);

  async function selectFile(key: string) {
    setSelectedKey(key);
    setDiffText('');
    setStatus(null);
    setConfirmRollback(null);
    const { workspaceRoot, path } = splitKey(key);
    const qs = new URLSearchParams({ path, workspace_root: workspaceRoot });
    try {
      const res = await fetch(`/api/artifacts/history?${qs}`);
      if (!res.ok) throw new Error(`history HTTP ${res.status}`);
      const rows: VersionRow[] = await res.json();
      setHistory(rows);
      if (rows.length >= 2) {
        setFromVersion(rows[1].version);
        setToVersion(rows[0].version);
      } else if (rows.length === 1) {
        setFromVersion(rows[0].version);
        setToVersion(rows[0].version);
      }
      setError(null);
    } catch (err) {
      setError(String(err));
      setHistory([]);
    }
  }

  async function loadDiff() {
    if (!selectedKey || fromVersion === null || toVersion === null) return;
    const { workspaceRoot, path } = splitKey(selectedKey);
    const qs = new URLSearchParams({
      path,
      workspace_root: workspaceRoot,
      from_: String(fromVersion),
      to: String(toVersion),
    });
    try {
      const res = await fetch(`/api/artifacts/diff?${qs}`);
      if (!res.ok) throw new Error(`diff HTTP ${res.status}`);
      const data = await res.json();
      setDiffText(data.diff || '(no differences)');
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }

  async function rollback(version: number) {
    if (!selectedKey) return;
    const { workspaceRoot, path } = splitKey(selectedKey);
    try {
      const res = await fetch('/api/artifacts/rollback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, workspace_root: workspaceRoot, version }),
      });
      if (!res.ok) throw new Error(`rollback HTTP ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setStatus(
        data.written
          ? `Rolled back to v${version} — file rewritten in workspace.`
          : `Rolled back to v${version} — content returned (no workspace path configured, file not written).`,
      );
      setConfirmRollback(null);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="artifacts" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)' }}>Artifacts</span>
          <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
            — versioned artifact history · diff · rollback
          </span>
        </div>
        <button
          onClick={loadFiles}
          style={{
            fontFamily: mono,
            fontSize: 11,
            padding: '4px 10px',
            borderRadius: 5,
            border: '1px solid var(--b1)',
            background: 'transparent',
            color: 'var(--t2)',
            cursor: 'pointer',
            marginBottom: 14,
          }}
        >
          Refresh
        </button>

        {error && (
          <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginBottom: 12 }}>
            {error}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 18 }}>
          <div style={{ border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
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
              Files ({files.length})
            </div>
            {files.length === 0 && (
              <div style={{ padding: 14, fontFamily: mono, fontSize: 11, color: 'var(--t4)' }}>
                No artifacts recorded yet.
              </div>
            )}
            {files.map((f) => (
              <div
                key={f.identity_key}
                onClick={() => selectFile(f.identity_key)}
                style={{
                  padding: '9px 12px',
                  cursor: 'pointer',
                  borderBottom: '1px solid var(--b1)',
                  background: selectedKey === f.identity_key ? 'var(--hover-overlay)' : 'transparent',
                }}
              >
                <div style={{ fontSize: 12.5, color: 'var(--t1)' }}>{f.filename}</div>
                <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                  v{f.latest_version} · {timeAgo(f.updated_at)}
                </div>
              </div>
            ))}
          </div>

          <div>
            {!selectedFile ? (
              <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)', paddingTop: 8 }}>
                Select a file to view its version history.
              </div>
            ) : (
              <>
                <div style={{ fontSize: 13, color: 'var(--t1)', marginBottom: 2 }}>
                  {selectedFile.filename}
                </div>
                <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)', marginBottom: 14 }}>
                  {selectedFile.identity_key}
                </div>

                {status && (
                  <div
                    style={{
                      color: '#3fb950',
                      fontFamily: mono,
                      fontSize: 11,
                      marginBottom: 12,
                    }}
                  >
                    {status}
                  </div>
                )}

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12 }}>
                  <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t3)' }}>diff</span>
                  <select
                    value={fromVersion ?? ''}
                    onChange={(e) => setFromVersion(Number(e.target.value))}
                    style={{ fontFamily: mono, fontSize: 11, padding: '3px 6px' }}
                  >
                    {history.map((h) => (
                      <option key={h.version} value={h.version}>
                        v{h.version}
                      </option>
                    ))}
                  </select>
                  <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t3)' }}>→</span>
                  <select
                    value={toVersion ?? ''}
                    onChange={(e) => setToVersion(Number(e.target.value))}
                    style={{ fontFamily: mono, fontSize: 11, padding: '3px 6px' }}
                  >
                    {history.map((h) => (
                      <option key={h.version} value={h.version}>
                        v{h.version}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={loadDiff}
                    style={{
                      fontFamily: mono,
                      fontSize: 11,
                      padding: '4px 10px',
                      borderRadius: 5,
                      border: '1px solid var(--b1)',
                      background: 'transparent',
                      color: 'var(--t2)',
                      cursor: 'pointer',
                    }}
                  >
                    Show diff
                  </button>
                </div>

                {diffText && <DiffView text={diffText} />}

                <div
                  style={{
                    marginTop: 18,
                    fontFamily: mono,
                    fontSize: 10,
                    letterSpacing: '0.15em',
                    textTransform: 'uppercase',
                    color: 'var(--t4)',
                    marginBottom: 6,
                  }}
                >
                  Versions
                </div>
                <div style={{ border: '1px solid var(--b1)', borderRadius: 8, overflow: 'hidden' }}>
                  {history.map((h) => (
                    <div
                      key={h.version}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        padding: '9px 12px',
                        borderBottom: '1px solid var(--b1)',
                      }}
                    >
                      <span style={{ fontFamily: mono, fontSize: 12, color: 'var(--t1)' }}>v{h.version}</span>
                      <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t3)' }}>{h.skill}</span>
                      <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                        {timeAgo(h.created_at)}
                      </span>
                      <span style={{ flex: 1 }} />
                      {confirmRollback === h.version ? (
                        <>
                          <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t3)' }}>
                            rollback to v{h.version}?
                          </span>
                          <button
                            onClick={() => rollback(h.version)}
                            style={{
                              fontFamily: mono,
                              fontSize: 10,
                              padding: '3px 8px',
                              borderRadius: 4,
                              border: '1px solid #f85149',
                              background: 'transparent',
                              color: '#f85149',
                              cursor: 'pointer',
                            }}
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmRollback(null)}
                            style={{
                              fontFamily: mono,
                              fontSize: 10,
                              padding: '3px 8px',
                              borderRadius: 4,
                              border: '1px solid var(--b1)',
                              background: 'transparent',
                              color: 'var(--t3)',
                              cursor: 'pointer',
                            }}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmRollback(h.version)}
                          style={{
                            fontFamily: mono,
                            fontSize: 10,
                            padding: '3px 8px',
                            borderRadius: 4,
                            border: '1px solid var(--b1)',
                            background: 'transparent',
                            color: 'var(--t2)',
                            cursor: 'pointer',
                          }}
                        >
                          Rollback
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Artifacts;
