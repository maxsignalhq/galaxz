import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/devconsole.css';

/* ── API base ────────────────────────────────────────────── */

const API_BASE =
  (import.meta as unknown as { env: Record<string, string | undefined> }).env.VITE_API_URL
  ?? '/api';

/* ── Syntax token helper ─────────────────────────────────── */

const P = (t: string) => <span style={{ color: '#8a94b0' }}>{t}</span>;

/* ── Types ───────────────────────────────────────────────── */

type MainTabId = 'agents' | 'logs' | 'forge';
type AgentId   = string;
type TabId     = 'manifest' | 'skills' | 'appearance' | 'llm-config' | 'logs';
type LogLevel  = 'INFO' | 'DEBUG' | 'WARN' | 'ERROR';

interface AgentManifest {
  agent_id: string;
  agent_name: string;
  version: string;
  skills: SkillDefinition[];
  metadata?: {
    color?: string;
    [key: string]: unknown;
  };
}
interface SkillDefinition {
  skill_id: string;
  description: string;
  avg_confidence?: number;
  avg_latency_ms?: number;
}
interface SkillRow  { id: string; confidence: number | null; latency: string | null; tasks: number | null; }
interface LogEntry  { ts: string; level: LogLevel; content: React.ReactNode; }
interface AgentAppearance { displayName?: string; color?: string; }

/* ── Forge types ─────────────────────────────────────────── */

interface ForgeAgent { agent_id: string; agent_name: string; }
interface SchemaRow  { id: number; key: string; type: string; }

type ForgeResultState =
  | { kind: 'success'; files_created: string[]; warning?: string | null }
  | { kind: 'conflict'; message: string }
  | { kind: 'error';    message: string }
  | null;

let _rowId = 0;
const newRowId = () => ++_rowId;

const SCHEMA_TYPES = ['string', 'integer', 'float', 'boolean', 'list', 'dict'];
const ID_PATTERN   = /^[a-z][a-z0-9_]*$/;

/* ── Shared ──────────────────────────────────────────────── */

const LEVEL_COLORS: Record<LogLevel, string> = {
  INFO:  'var(--green)',
  DEBUG: 'var(--blue)',
  WARN:  'var(--yellow)',
  ERROR: 'var(--red)',
};

const AGENT_APPEARANCE_KEY = 'galaxz.devConsole.agentAppearance';

const DEFAULT_AGENT_COLORS: Record<string, string> = {
  rigel: '#f5c040',
  vega: '#00d4a0',
};

const AGENT_PALETTE = [
  '#4f8eff',
  '#00d4a0',
  '#f5c040',
  '#9d7eff',
  '#38a8ff',
  '#ff6b9d',
  '#ff4d6a',
  '#94a3b8',
];

function defaultAgentColor(agent: AgentManifest | null, agentId: string) {
  return agent?.metadata?.color ?? DEFAULT_AGENT_COLORS[agentId] ?? '#4f8eff';
}

function agentDisplayName(agent: AgentManifest | null, appearance: AgentAppearance | undefined, fallbackId: string) {
  const preferred = appearance?.displayName?.trim();
  return preferred || agent?.agent_id || fallbackId;
}

function agentColorFor(agent: AgentManifest | null, appearance: AgentAppearance | undefined, agentId: string) {
  return appearance?.color ?? defaultAgentColor(agent, agentId);
}

/* ── Icons ───────────────────────────────────────────────── */

function SearchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 8L10.5 10.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg width="10" height="6" viewBox="0 0 10 6" fill="none">
      <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── Agent tab sub-components ────────────────────────────── */

function ManifestTab({
  lines,
  filename,
  onCopy,
  copyLabel,
}: {
  lines: Array<React.ReactNode | null>;
  filename: string;
  onCopy: () => void;
  copyLabel: string;
}) {
  return (
    <div className="code-block">
      <div className="code-block-hdr">
        <span className="code-block-filename">{filename}</span>
        <button className="btn btn-ghost btn-sm" onClick={onCopy}>{copyLabel}</button>
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
    return [<>{P(error ?? 'Waiting for /api/agents to return a live manifest.')}</>];
  }
  return JSON.stringify(manifest, null, 2).split('\n').map((line) => <>{P(line)}</>);
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

function LlmConfigTab({
  skills,
  overrides,
  onChange,
}: {
  skills: SkillRow[];
  overrides: Record<string, string>;
  onChange: (skillId: string, model: string) => void;
}) {
  const models = ['workspace default', 'fast local', 'balanced local', 'quality local'];
  return (
    <>
      <div className="llm-banner">
        <span style={{ fontWeight: 600, color: 'var(--blue)' }}>Workspace-local overrides</span>
        {' — selections are saved in this browser until a backend model-config endpoint is available.'}
      </div>
      <span className="llm-section-label">Per-Skill Model Overrides</span>
      {skills.length === 0 && (
        <div className="llm-row">
          <div className="llm-row-left">
            <div className="llm-skill-name">No live skills returned.</div>
            <div className="llm-skill-desc">Model overrides appear after /api/agents returns manifest skills.</div>
          </div>
        </div>
      )}
      {skills.map((skill) => (
        <div className="llm-row" key={skill.id}>
          <div className="llm-row-left">
            <div className="llm-skill-name">{skill.id}</div>
            <div className="llm-skill-desc">Override saved locally for Dev Console workflows.</div>
          </div>
          <select
            className="llm-select"
            value={overrides[skill.id] ?? models[0]}
            onChange={(event) => onChange(skill.id, event.target.value)}
          >
            {models.map((model) => <option key={model} value={model}>{model}</option>)}
          </select>
        </div>
      ))}
    </>
  );
}

function AppearanceTab({
  manifest,
  displayName,
  color,
  onSave,
  onReset,
}: {
  manifest: AgentManifest | null;
  displayName: string;
  color: string;
  onSave: (appearance: AgentAppearance) => void;
  onReset: () => void;
}) {
  const [draftName, setDraftName] = useState(displayName);
  const [draftColor, setDraftColor] = useState(color);

  useEffect(() => {
    setDraftName(displayName);
    setDraftColor(color);
  }, [displayName, color, manifest?.agent_id]);

  const stableName = manifest?.agent_id ?? 'agent';
  const nameValue = draftName.trim();
  const canSave = Boolean(nameValue);

  return (
    <div className="appearance-panel">
      <div className="appearance-preview">
        <span
          className="appearance-preview-dot"
          style={{ background: draftColor, boxShadow: `0 0 8px ${draftColor}` }}
        />
        <div className="appearance-preview-text">
          <span className="appearance-preview-name" style={{ color: draftColor }}>{nameValue || stableName}</span>
          <span className="appearance-preview-id">{stableName}</span>
        </div>
      </div>

      <div className="appearance-form-grid">
        <div className="appearance-field">
          <label className="appearance-label" htmlFor="agent-display-name">Display Name</label>
          <input
            id="agent-display-name"
            className="appearance-input"
            type="text"
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            placeholder={stableName}
          />
        </div>

        <div className="appearance-field">
          <label className="appearance-label" htmlFor="agent-custom-color">Custom Color</label>
          <input
            id="agent-custom-color"
            className="appearance-color-input"
            type="color"
            value={draftColor}
            onChange={(event) => setDraftColor(event.target.value)}
          />
        </div>
      </div>

      <div className="appearance-field">
        <span className="appearance-label">Color Palette</span>
        <div className="appearance-swatches">
          {AGENT_PALETTE.map((paletteColor) => (
            <button
              key={paletteColor}
              type="button"
              className={`appearance-swatch${draftColor.toLowerCase() === paletteColor.toLowerCase() ? ' selected' : ''}`}
              style={{ background: paletteColor }}
              aria-label={`Use ${paletteColor}`}
              title={paletteColor}
              onClick={() => setDraftColor(paletteColor)}
            />
          ))}
        </div>
      </div>

      <div className="appearance-actions">
        <button
          className="btn btn-primary btn-sm"
          type="button"
          disabled={!canSave}
          onClick={() => onSave({ displayName: nameValue, color: draftColor })}
        >
          Save appearance
        </button>
        <button className="btn btn-outline btn-sm" type="button" onClick={onReset}>
          Reset
        </button>
      </div>
    </div>
  );
}

function LogsTab({ logs, agentId, onClear }: { logs: LogEntry[]; agentId: string; onClear: () => void }) {
  return (
    <div className="log-panel">
      <div className="log-panel-hdr">
        <span className="log-panel-title">{agentId} · live log output</span>
        <button className="btn btn-ghost btn-sm" onClick={onClear}>Clear</button>
      </div>
      <div className="log-body">
        {logs.length === 0 && (
          <div className="log-line">
            <span className="log-ts">—</span>
            <span className="log-lvl" style={{ color: 'var(--t4)' }}>INFO</span>
            <span className="log-msg">No console activity yet. Use refresh, health check, copy, or model override controls to add entries.</span>
          </div>
        )}
        {logs.map((entry, i) => (
          <div key={i} className="log-line">
            <span className="log-ts">{entry.ts}</span>
            <span className="log-lvl" style={{ color: LEVEL_COLORS[entry.level] }}>{entry.level}</span>
            <span className="log-msg">{entry.content}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Forge sub-components ────────────────────────────────── */

function ForgeResult({ result, entityLabel }: { result: NonNullable<ForgeResultState>; entityLabel: string }) {
  if (result.kind === 'success') {
    return (
      <div className="forge-result forge-result-success">
        <div className="forge-result-hdr forge-result-hdr-success">
          <span>✓</span>
          <span>{entityLabel} scaffolded</span>
        </div>
        <div className="forge-result-files">
          {result.files_created.map(f => (
            <div key={f} className="forge-result-file-line">
              <span className="forge-result-file-plus">+</span>{f}
            </div>
          ))}
        </div>
        {result.warning && (
          <div className="forge-result-warning">⚠ {result.warning}</div>
        )}
      </div>
    );
  }

  return (
    <div className="forge-result forge-result-error">
      <div className="forge-result-hdr forge-result-hdr-error">
        <span>✕</span>
        <span>{result.kind === 'conflict' ? 'Already exists' : 'Scaffold failed'}</span>
      </div>
      <div className="forge-result-body">{result.message}</div>
    </div>
  );
}

function SchemaBuilder({
  rows,
  onChange,
  onRemove,
  onAdd,
  addLabel,
  keyPlaceholder,
  disabled,
}: {
  rows: SchemaRow[];
  onChange: (id: number, field: 'key' | 'type', value: string) => void;
  onRemove: (id: number) => void;
  onAdd: () => void;
  addLabel: string;
  keyPlaceholder: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <div className="forge-schema-rows">
        {rows.map(row => (
          <div key={row.id} className="forge-schema-row">
            <input
              className="forge-input forge-schema-key"
              type="text"
              placeholder={keyPlaceholder}
              value={row.key}
              onChange={e => onChange(row.id, 'key', e.target.value)}
              disabled={disabled}
            />
            <span style={{ color: 'var(--t3)', fontSize: '11px', flexShrink: 0 }}>:</span>
            <div className="forge-select-wrap forge-schema-type-wrap">
              <select
                className="forge-select"
                value={row.type}
                onChange={e => onChange(row.id, 'type', e.target.value)}
                disabled={disabled}
              >
                {SCHEMA_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <span className="forge-select-chevron"><ChevronIcon /></span>
            </div>
            <button
              type="button"
              className="forge-schema-remove"
              onClick={() => onRemove(row.id)}
              disabled={disabled}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="forge-add-field-btn"
        onClick={onAdd}
        disabled={disabled}
      >
        + {addLabel}
      </button>
    </div>
  );
}

function ForgeTab({ apiBase }: { apiBase: string }) {
  /* ── Agent form state ── */
  const [aId,       setAId]       = useState('');
  const [aName,     setAName]     = useState('');
  const [aDesc,     setADesc]     = useState('');
  const [taskTags,  setTaskTags]  = useState<string[]>([]);
  const [tagInput,  setTagInput]  = useState('');
  const [llm,       setLlm]       = useState('');
  const [conf,      setConf]      = useState(0.80);
  const [aErrs,     setAErrs]     = useState<Record<string, string>>({});
  const [aResult,   setAResult]   = useState<ForgeResultState>(null);
  const [aLoading,  setALoading]  = useState(false);

  /* ── Skill form state ── */
  const [sParent,    setSParent]    = useState('');
  const [sId,        setSId]        = useState('');
  const [sName,      setSName]      = useState('');
  const [sDesc,      setSDesc]      = useState('');
  const [inSchema,   setInSchema]   = useState<SchemaRow[]>([{ id: newRowId(), key: '', type: 'string' }]);
  const [outSchema,  setOutSchema]  = useState<SchemaRow[]>([{ id: newRowId(), key: '', type: 'string' }]);
  const [sErrs,      setSErrs]      = useState<Record<string, string>>({});
  const [sResult,    setSResult]    = useState<ForgeResultState>(null);
  const [sLoading,   setSLoading]   = useState(false);

  /* ── Shared: agent dropdown ── */
  const [forgeAgents,    setForgeAgents]    = useState<ForgeAgent[]>([]);
  const [agentsLoading,  setAgentsLoading]  = useState(true);
  const [agentsError,    setAgentsError]    = useState<string | null>(null);

  /* ── Refs for focus-on-error ── */
  const aIdRef      = useRef<HTMLInputElement>(null);
  const aNameRef    = useRef<HTMLInputElement>(null);
  const aDescRef    = useRef<HTMLTextAreaElement>(null);
  const tagInputRef = useRef<HTMLInputElement>(null);
  const confRef     = useRef<HTMLInputElement>(null);
  const sParentRef  = useRef<HTMLSelectElement>(null);
  const sIdRef      = useRef<HTMLInputElement>(null);
  const sNameRef    = useRef<HTMLInputElement>(null);
  const sDescRef    = useRef<HTMLTextAreaElement>(null);

  async function loadForgeAgents() {
    setAgentsLoading(true);
    setAgentsError(null);
    try {
      const res = await fetch('/api/agents');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as ForgeAgent[];
      setForgeAgents(data);
    } catch (e) {
      setAgentsError('Could not load agents');
    } finally {
      setAgentsLoading(false);
    }
  }

  useEffect(() => { loadForgeAgents(); }, []);

  /* ── Tag input helpers ── */
  function commitTag(raw: string) {
    const trimmed = raw.trim().replace(/,$/, '').trim();
    if (trimmed && !taskTags.includes(trimmed)) {
      setTaskTags(prev => [...prev, trimmed]);
    }
    setTagInput('');
  }

  function handleTagKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      commitTag(tagInput);
    } else if (e.key === 'Backspace' && tagInput === '' && taskTags.length > 0) {
      setTaskTags(prev => prev.slice(0, -1));
    }
  }

  /* ── Schema row helpers ── */
  function updateRow(
    setter: React.Dispatch<React.SetStateAction<SchemaRow[]>>,
    id: number, field: 'key' | 'type', value: string
  ) {
    setter(prev => prev.map(r => r.id === id ? { ...r, [field]: value } : r));
  }

  function removeRow(setter: React.Dispatch<React.SetStateAction<SchemaRow[]>>, id: number) {
    setter(prev => prev.filter(r => r.id !== id));
  }

  function addRow(setter: React.Dispatch<React.SetStateAction<SchemaRow[]>>) {
    setter(prev => [...prev, { id: newRowId(), key: '', type: 'string' }]);
  }

  /* ── Agent form submit ── */
  async function submitAgent(e: React.FormEvent) {
    e.preventDefault();
    const errors: Record<string, string> = {};

    if (!ID_PATTERN.test(aId))      errors.aId       = 'Lowercase letters, numbers, underscores. Must start with a letter.';
    if (!aName.trim())               errors.aName     = 'Agent name is required.';
    if (!aDesc.trim())               errors.aDesc     = 'Description is required.';
    if (taskTags.length === 0)       errors.taskTypes = 'Add at least one task type.';
    if (conf < 0 || conf > 1 || isNaN(conf)) errors.conf = 'Must be between 0.0 and 1.0.';

    if (Object.keys(errors).length > 0) {
      setAErrs(errors);
      if (errors.aId)       aIdRef.current?.focus();
      else if (errors.aName) aNameRef.current?.focus();
      else if (errors.aDesc) aDescRef.current?.focus();
      else if (errors.taskTypes) tagInputRef.current?.focus();
      else if (errors.conf)  confRef.current?.focus();
      return;
    }

    setAErrs({});
    setALoading(true);
    setAResult(null);

    try {
      const res = await fetch(`${apiBase}/forge/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id:             aId,
          agent_name:           aName,
          description:          aDesc,
          task_types:           taskTags,
          llm_override:         llm.trim() || null,
          confidence_threshold: conf,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        setAResult({ kind: 'success', files_created: data.files_created ?? [], warning: data.warning ?? null });
        setAId(''); setAName(''); setADesc(''); setTaskTags([]); setTagInput(''); setLlm(''); setConf(0.80);
        await loadForgeAgents();
      } else if (res.status === 409) {
        setAResult({ kind: 'conflict', message: data.detail ?? data.error ?? 'Agent already exists.' });
      } else {
        setAResult({ kind: 'error', message: data.detail ?? data.error ?? `HTTP ${res.status}` });
      }
    } catch (err) {
      setAResult({ kind: 'error', message: String(err) });
    } finally {
      setALoading(false);
    }
  }

  /* ── Skill form submit ── */
  async function submitSkill(e: React.FormEvent) {
    e.preventDefault();
    const errors: Record<string, string> = {};

    if (!sParent)                errors.sParent  = 'Select a parent agent.';
    if (!ID_PATTERN.test(sId))   errors.sId      = 'Lowercase letters, numbers, underscores. Must start with a letter.';
    if (!sName.trim())            errors.sName    = 'Skill name is required.';
    if (!sDesc.trim())            errors.sDesc    = 'Description is required.';

    const validIn  = inSchema.filter(r => r.key.trim());
    const validOut = outSchema.filter(r => r.key.trim());
    if (validIn.length  === 0) errors.inSchema  = 'Add at least one input field.';
    if (validOut.length === 0) errors.outSchema = 'Add at least one output field.';

    if (Object.keys(errors).length > 0) {
      setSErrs(errors);
      if (errors.sParent)    sParentRef.current?.focus();
      else if (errors.sId)   sIdRef.current?.focus();
      else if (errors.sName) sNameRef.current?.focus();
      else if (errors.sDesc) sDescRef.current?.focus();
      return;
    }

    setSErrs({});
    setSLoading(true);
    setSResult(null);

    const inputSchemaObj: Record<string, string>  = {};
    const outputSchemaObj: Record<string, string> = {};
    validIn.forEach(r  => { inputSchemaObj[r.key.trim()]  = r.type; });
    validOut.forEach(r => { outputSchemaObj[r.key.trim()] = r.type; });

    try {
      const res = await fetch(`${apiBase}/forge/skill`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id:        sId,
          skill_name:      sName,
          parent_agent_id: sParent,
          description:     sDesc,
          input_schema:    inputSchemaObj,
          output_schema:   outputSchemaObj,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        setSResult({ kind: 'success', files_created: data.files_created ?? [], warning: data.warning ?? null });
        setSId(''); setSName(''); setSDesc(''); setSParent('');
        setInSchema([{ id: newRowId(), key: '', type: 'string' }]);
        setOutSchema([{ id: newRowId(), key: '', type: 'string' }]);
      } else if (res.status === 409) {
        setSResult({ kind: 'conflict', message: data.detail ?? data.error ?? 'Skill already exists.' });
      } else {
        setSResult({ kind: 'error', message: data.detail ?? data.error ?? `HTTP ${res.status}` });
      }
    } catch (err) {
      setSResult({ kind: 'error', message: String(err) });
    } finally {
      setSLoading(false);
    }
  }

  const skillFormDisabled = agentsLoading || forgeAgents.length === 0;

  return (
    <div className="dev-forge-body">

      {/* ─── Left panel: New Agent ─── */}
      <div className="forge-panel forge-panel-left">
        <div className="forge-panel-hdr">New Agent</div>

        <form onSubmit={submitAgent} noValidate>

          {/* Agent ID */}
          <div className="forge-field">
            <label className="forge-label">Agent ID</label>
            <input
              ref={aIdRef}
              className={`forge-input${aErrs.aId ? ' error' : ''}`}
              type="text"
              placeholder="nova_search"
              value={aId}
              onChange={e => setAId(e.target.value)}
              onBlur={() => {
                if (aId && !ID_PATTERN.test(aId)) {
                  setAErrs(prev => ({ ...prev, aId: 'Lowercase letters, numbers, underscores. Must start with a letter.' }));
                } else if (aId) {
                  setAErrs(prev => { const n = { ...prev }; delete n.aId; return n; });
                }
              }}
            />
            <div className="forge-helper">Lowercase letters, numbers, underscores. Must start with a letter.</div>
            {aErrs.aId && <div className="forge-field-error">{aErrs.aId}</div>}
          </div>

          {/* Agent Name */}
          <div className="forge-field">
            <label className="forge-label">Agent Name</label>
            <input
              ref={aNameRef}
              className={`forge-input${aErrs.aName ? ' error' : ''}`}
              type="text"
              placeholder="Nova Search Agent"
              value={aName}
              onChange={e => setAName(e.target.value)}
            />
            {aErrs.aName && <div className="forge-field-error">{aErrs.aName}</div>}
          </div>

          {/* Description */}
          <div className="forge-field">
            <label className="forge-label">Description</label>
            <textarea
              ref={aDescRef}
              className={`forge-textarea${aErrs.aDesc ? ' error' : ''}`}
              rows={3}
              placeholder="Handles web search and retrieval tasks"
              value={aDesc}
              onChange={e => setADesc(e.target.value)}
            />
            {aErrs.aDesc && <div className="forge-field-error">{aErrs.aDesc}</div>}
          </div>

          {/* Task Types */}
          <div className="forge-field">
            <label className="forge-label">Task Types</label>
            <div
              className={`forge-tag-wrap${aErrs.taskTypes ? ' error' : ''}`}
              onClick={() => tagInputRef.current?.focus()}
            >
              {taskTags.map(tag => (
                <span key={tag} className="forge-tag">
                  {tag}
                  <button
                    type="button"
                    className="forge-tag-remove"
                    onClick={ev => { ev.stopPropagation(); setTaskTags(prev => prev.filter(t => t !== tag)); }}
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                ref={tagInputRef}
                className="forge-tag-input"
                placeholder={taskTags.length === 0 ? 'Type and press Enter' : ''}
                value={tagInput}
                onChange={e => setTagInput(e.target.value)}
                onKeyDown={handleTagKeyDown}
                onBlur={() => { if (tagInput.trim()) commitTag(tagInput); }}
              />
            </div>
            {aErrs.taskTypes && <div className="forge-field-error">{aErrs.taskTypes}</div>}
          </div>

          {/* LLM Override */}
          <div className="forge-field">
            <label className="forge-label">LLM Override</label>
            <input
              className="forge-input"
              type="text"
              placeholder="openai/gpt-4o  (optional)"
              value={llm}
              onChange={e => setLlm(e.target.value)}
            />
          </div>

          {/* Confidence Threshold */}
          <div className="forge-field">
            <label className="forge-label">Confidence Threshold</label>
            <input
              ref={confRef}
              className={`forge-input${aErrs.conf ? ' error' : ''}`}
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={conf}
              onChange={e => setConf(parseFloat(e.target.value))}
            />
            {aErrs.conf && <div className="forge-field-error">{aErrs.conf}</div>}
          </div>

          <button
            className="forge-submit-btn forge-submit-agent"
            type="submit"
            disabled={aLoading}
          >
            {aLoading ? 'Scaffolding…' : 'Scaffold Agent'}
          </button>

          {aResult && <ForgeResult result={aResult} entityLabel="Agent" />}
        </form>
      </div>

      {/* ─── Right panel: New Skill ─── */}
      <div className="forge-panel forge-panel-right">
        <div className="forge-panel-hdr">New Skill</div>

        <form onSubmit={submitSkill} noValidate>

          {/* Parent Agent */}
          <div className="forge-field">
            <label className="forge-label">Parent Agent</label>
            <div className="forge-select-wrap">
              <select
                ref={sParentRef}
                className={`forge-select${sErrs.sParent ? ' error' : ''}`}
                value={sParent}
                onChange={e => setSParent(e.target.value)}
                disabled={agentsLoading}
              >
                {agentsLoading && <option value="" disabled>Loading agents…</option>}
                {!agentsLoading && forgeAgents.length === 0 && (
                  <option value="" disabled>No agents registered</option>
                )}
                {!agentsLoading && forgeAgents.length > 0 && (
                  <option value="">Select agent…</option>
                )}
                {forgeAgents.map(a => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.agent_name} ({a.agent_id})
                  </option>
                ))}
              </select>
              <span className="forge-select-chevron"><ChevronIcon /></span>
            </div>
            {agentsError && <div className="forge-field-error" style={{ color: 'var(--red)' }}>{agentsError}</div>}
            {sErrs.sParent && <div className="forge-field-error">{sErrs.sParent}</div>}
          </div>

          {/* Skill ID */}
          <div className="forge-field">
            <label className="forge-label">Skill ID</label>
            <input
              ref={sIdRef}
              className={`forge-input${sErrs.sId ? ' error' : ''}`}
              type="text"
              placeholder="web_search"
              value={sId}
              onChange={e => setSId(e.target.value)}
              onBlur={() => {
                if (sId && !ID_PATTERN.test(sId)) {
                  setSErrs(prev => ({ ...prev, sId: 'Lowercase letters, numbers, underscores. Must start with a letter.' }));
                } else if (sId) {
                  setSErrs(prev => { const n = { ...prev }; delete n.sId; return n; });
                }
              }}
              disabled={skillFormDisabled}
            />
            {sErrs.sId && <div className="forge-field-error">{sErrs.sId}</div>}
          </div>

          {/* Skill Name */}
          <div className="forge-field">
            <label className="forge-label">Skill Name</label>
            <input
              ref={sNameRef}
              className={`forge-input${sErrs.sName ? ' error' : ''}`}
              type="text"
              placeholder="Web Search"
              value={sName}
              onChange={e => setSName(e.target.value)}
              disabled={skillFormDisabled}
            />
            {sErrs.sName && <div className="forge-field-error">{sErrs.sName}</div>}
          </div>

          {/* Description */}
          <div className="forge-field">
            <label className="forge-label">Description</label>
            <textarea
              ref={sDescRef}
              className={`forge-textarea${sErrs.sDesc ? ' error' : ''}`}
              rows={3}
              placeholder="Searches the web and returns structured results"
              value={sDesc}
              onChange={e => setSDesc(e.target.value)}
              disabled={skillFormDisabled}
            />
            {sErrs.sDesc && <div className="forge-field-error">{sErrs.sDesc}</div>}
          </div>

          {/* Input Schema */}
          <div className="forge-field">
            <label className="forge-label">Input Schema</label>
            <SchemaBuilder
              rows={inSchema}
              onChange={(id, field, value) => updateRow(setInSchema, id, field, value)}
              onRemove={id => removeRow(setInSchema, id)}
              onAdd={() => addRow(setInSchema)}
              addLabel="Add Input Field"
              keyPlaceholder="query"
              disabled={skillFormDisabled}
            />
            {sErrs.inSchema && <div className="forge-field-error">{sErrs.inSchema}</div>}
          </div>

          {/* Output Schema */}
          <div className="forge-field">
            <label className="forge-label">Output Schema</label>
            <SchemaBuilder
              rows={outSchema}
              onChange={(id, field, value) => updateRow(setOutSchema, id, field, value)}
              onRemove={id => removeRow(setOutSchema, id)}
              onAdd={() => addRow(setOutSchema)}
              addLabel="Add Output Field"
              keyPlaceholder="results"
              disabled={skillFormDisabled}
            />
            {sErrs.outSchema && <div className="forge-field-error">{sErrs.outSchema}</div>}
          </div>

          <button
            className="forge-submit-btn forge-submit-skill"
            type="submit"
            disabled={sLoading || skillFormDisabled}
          >
            {sLoading ? 'Scaffolding…' : 'Scaffold Skill'}
          </button>

          {sResult && <ForgeResult result={sResult} entityLabel="Skill" />}
        </form>
      </div>

    </div>
  );
}

/* ── DevConsole ──────────────────────────────────────────── */

export function DevConsole() {
  const navigate = useNavigate();
  const [mainTab,  setMainTab]  = useState<MainTabId>('agents');
  const [selected, setSelected] = useState<AgentId>('rigel');
  const [tab,      setTab]      = useState<TabId>('manifest');
  const [agents,   setAgents]   = useState<AgentManifest[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery]   = useState('');
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [copyLabel, setCopyLabel]       = useState('Copy');
  const [logs,       setLogs]           = useState<LogEntry[]>([]);
  const [refreshKey, setRefreshKey]     = useState(0);
  const [llmOverrides, setLlmOverrides] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(window.localStorage.getItem('galaxz.devConsole.llmOverrides') ?? '{}');
    } catch {
      return {};
    }
  });
  const [agentAppearance, setAgentAppearance] = useState<Record<string, AgentAppearance>>(() => {
    try {
      return JSON.parse(window.localStorage.getItem(AGENT_APPEARANCE_KEY) ?? '{}');
    } catch {
      return {};
    }
  });

  function appendLog(level: LogLevel, content: React.ReactNode) {
    const ts = new Date().toLocaleTimeString([], { hour12: false });
    setLogs((current) => [...current.slice(-99), { ts, level, content }]);
  }

  function showNotice(message: string) {
    setActionNotice(message);
    window.setTimeout(() => {
      setActionNotice((current) => current === message ? null : current);
    }, 3000);
  }

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
          appendLog('INFO', `Loaded ${nextAgents.length} agent manifest${nextAgents.length === 1 ? '' : 's'} from /api/agents.`);
          if (nextAgents.length > 0 && !nextAgents.some((a: AgentManifest) => a.agent_id === selected)) {
            setSelected(nextAgents[0].agent_id);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(String(err));
          appendLog('ERROR', `Failed to load /api/agents: ${String(err)}`);
        }
      }
    }

    loadAgents();
    const timer = window.setInterval(loadAgents, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selected, refreshKey]);

  useEffect(() => {
    window.localStorage.setItem('galaxz.devConsole.llmOverrides', JSON.stringify(llmOverrides));
  }, [llmOverrides]);

  useEffect(() => {
    window.localStorage.setItem(AGENT_APPEARANCE_KEY, JSON.stringify(agentAppearance));
  }, [agentAppearance]);

  const selectedManifest = agents.find((a) => a.agent_id === selected) ?? null;
  const selectedAppearance = agentAppearance[selected];
  const filteredAgents   = agents.filter((a) => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    const displayName = agentDisplayName(a, agentAppearance[a.agent_id], a.agent_id);
    return (
      a.agent_id.toLowerCase().includes(q) ||
      a.agent_name.toLowerCase().includes(q) ||
      displayName.toLowerCase().includes(q) ||
      a.skills.some((sk) => sk.skill_id.toLowerCase().includes(q))
    );
  });

  const agentColor  = agentColorFor(selectedManifest, selectedAppearance, selected);
  const displayName = agentDisplayName(selectedManifest, selectedAppearance, selected);
  const agentType   = selectedManifest?.agent_name ?? 'No live manifest loaded';
  const agentMeta1  = selectedManifest
    ? `agent_id: ${selectedManifest.agent_id} · registered in Pulsar`
    : `agent_id: ${selected} · not returned by /api/agents`;
  const agentMeta2  = selectedManifest
    ? `skills: ${selectedManifest.skills.map(sk => sk.skill_id).join(', ')}`
    : (loadError ?? 'Awaiting /api/agents response');

  const manifestLines = manifestLinesFor(selectedManifest, loadError);
  const manifestFile  = selectedManifest
    ? `/api/agents — ${selectedManifest.agent_id}`
    : '/api/agents';
  const skills: SkillRow[] = selectedManifest?.skills.map((sk) => ({
    id:         sk.skill_id,
    confidence: typeof sk.avg_confidence === 'number' ? sk.avg_confidence : null,
    latency:    typeof sk.avg_latency_ms === 'number' ? `${sk.avg_latency_ms}ms` : null,
    tasks:      null,
  })) ?? [];
  const manifestText = selectedManifest
    ? JSON.stringify(selectedManifest, null, 2)
    : (loadError ?? 'Waiting for /api/agents to return a live manifest.');

  async function copyManifest() {
    try {
      await navigator.clipboard.writeText(manifestText);
      setCopyLabel('Copied');
      showNotice('Manifest copied to clipboard.');
      appendLog('INFO', `Copied ${selected} manifest to clipboard.`);
      window.setTimeout(() => setCopyLabel('Copy'), 1500);
    } catch {
      setCopyLabel('Copy failed');
      showNotice('Clipboard permission denied by the browser.');
      appendLog('WARN', 'Clipboard write failed.');
      window.setTimeout(() => setCopyLabel('Copy'), 1500);
    }
  }

  async function checkHealth() {
    setTab('logs');
    setMainTab('logs');
    try {
      const res  = await fetch('/api/health');
      const body = await res.json();
      appendLog(res.ok ? 'INFO' : 'WARN', `/api/health ${res.status}: ${body.status ?? 'unknown'}`);
      showNotice(`Health check returned ${body.status ?? res.status}.`);
    } catch (err) {
      appendLog('ERROR', `Health check failed: ${String(err)}`);
      showNotice('Health check failed.');
    }
  }

  function updateOverride(skillId: string, model: string) {
    setLlmOverrides((current) => ({ ...current, [skillId]: model }));
    showNotice(`Saved model override for ${skillId}.`);
    appendLog('INFO', `Model override saved: ${skillId} -> ${model}`);
  }

  function saveAppearance(appearance: AgentAppearance) {
    setAgentAppearance((current) => ({ ...current, [selected]: appearance }));
    showNotice(`Saved appearance for ${selected}.`);
    appendLog('INFO', `Appearance saved: ${selected} -> ${appearance.displayName ?? selected}, ${appearance.color ?? 'default color'}`);
  }

  function resetAppearance() {
    setAgentAppearance((current) => {
      const next = { ...current };
      delete next[selected];
      return next;
    });
    showNotice(`Reset appearance for ${selected}.`);
    appendLog('INFO', `Appearance reset for ${selected}.`);
  }

  const INNER_TABS: { id: TabId; label: string }[] = [
    { id: 'manifest',   label: 'Manifest'   },
    { id: 'skills',     label: 'Skills'     },
    { id: 'appearance', label: 'Appearance' },
    { id: 'llm-config', label: 'LLM Config' },
    { id: 'logs',       label: 'Logs'       },
  ];

  const MAIN_TABS: { id: MainTabId; label: string }[] = [
    { id: 'agents', label: 'Agents' },
    { id: 'logs',   label: 'Logs'   },
    { id: 'forge',  label: 'Forge'  },
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
            {actionNotice && <span className="dev-action-notice">{actionNotice}</span>}
            <button
              className="btn btn-outline btn-sm"
              onClick={() => {
                setRefreshKey((v) => v + 1);
                showNotice('Refreshing live registry data.');
              }}
            >
              Refresh
            </button>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/task-ui')}>Open Task UI</button>
          </div>
        </div>

        {/* ── Main tabs: Agents | Logs | Forge ── */}
        <div className="dev-main-tabs">
          {MAIN_TABS.map(t => (
            <button
              key={t.id}
              className={`main-tab-btn${mainTab === t.id ? ' active' : ''}`}
              onClick={() => setMainTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Agents view ── */}
        {mainTab === 'agents' && (
          <div className="devconsole-body">

            {/* Left panel: Agent list */}
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
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
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
                {agents.length > 0 && filteredAgents.length === 0 && (
                  <div className="agent-item">
                    <div className="agent-item-hdr">
                      <span className="agent-item-name">No matching agents</span>
                    </div>
                    <div className="agent-item-meta">Search checks agent names and skill ids.</div>
                  </div>
                )}
                {filteredAgents.map((agent) => {
                  const appearance = agentAppearance[agent.agent_id];
                  const color = agentColorFor(agent, appearance, agent.agent_id);
                  const itemName = agentDisplayName(agent, appearance, agent.agent_id);
                  return (
                    <div
                      key={agent.agent_id}
                      className={`agent-item${selected === agent.agent_id ? ' selected' : ''}`}
                      onClick={() => {
                        setSelected(agent.agent_id);
                        setTab('manifest');
                        appendLog('DEBUG', `Selected agent ${agent.agent_id}.`);
                      }}
                    >
                      <div className="agent-item-hdr">
                        <span className="agent-item-dot" style={{ background: color, boxShadow: `0 0 5px ${color}` }} />
                        <span className="agent-item-name" style={{ color }}>{itemName}</span>
                        <span className="agent-item-ver">v{agent.version}</span>
                      </div>
                      <div className="agent-item-meta">{agent.agent_id} · {agent.agent_name} · {agent.skills.length} skills</div>
                    </div>
                  );
                })}
              </div>
            </aside>

            {/* Right panel: Detail */}
            <div className="detail-panel">
              <div className="detail-header">
                <div className="detail-header-inner">
                  <div>
                    <div className="detail-title-row">
                      <span className="detail-name" style={{ color: agentColor }}>{displayName}</span>
                      <span className="detail-type">{agentType}</span>
                    </div>
                    <div className="detail-meta">
                      <div>{agentMeta1}</div>
                      <div>{agentMeta2}</div>
                    </div>
                  </div>
                  <div className="detail-hdr-actions">
                    <button className="btn btn-outline btn-sm" onClick={() => setTab('logs')}>View logs</button>
                    <button className="btn btn-outline btn-sm" onClick={checkHealth}>Health check</button>
                    <button className="btn btn-primary btn-sm" onClick={copyManifest}>Copy manifest</button>
                  </div>
                </div>
              </div>

              <div className="detail-tabs">
                {INNER_TABS.map(t => (
                  <button
                    key={t.id}
                    className={`tab-btn${tab === t.id ? ' active' : ''}`}
                    onClick={() => setTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div className="tab-content">
                {tab === 'manifest'   && <ManifestTab lines={manifestLines} filename={manifestFile} onCopy={copyManifest} copyLabel={copyLabel} />}
                {tab === 'skills'     && <SkillsTab skills={skills} />}
                {tab === 'appearance' && (
                  <AppearanceTab
                    manifest={selectedManifest}
                    displayName={displayName}
                    color={agentColor}
                    onSave={saveAppearance}
                    onReset={resetAppearance}
                  />
                )}
                {tab === 'llm-config' && <LlmConfigTab skills={skills} overrides={llmOverrides} onChange={updateOverride} />}
                {tab === 'logs'       && <LogsTab logs={logs} agentId={selected} onClear={() => { setLogs([]); showNotice('Console activity cleared.'); }} />}
              </div>
            </div>

          </div>
        )}

        {/* ── Logs view ── */}
        {mainTab === 'logs' && (
          <div className="dev-logs-view">
            <LogsTab
              logs={logs}
              agentId="system"
              onClear={() => { setLogs([]); showNotice('Console activity cleared.'); }}
            />
          </div>
        )}

        {/* ── Forge view ── */}
        {mainTab === 'forge' && (
          <ForgeTab apiBase={API_BASE} />
        )}

      </div>
    </div>
  );
}

export default DevConsole;
