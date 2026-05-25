import React, { useEffect, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/settings.css';

/* ── Types ──────────────────────────────────────────────────── */

type Panel = 'models' | 'budget' | 'general' | 'members' | 'api-keys' | 'plan';

type NavEntry =
  | { kind: 'section'; label: string }
  | { kind: 'item';    id: Panel; label: string };

type LLMConfig = {
  provider:    string;
  model:       string;
  api_key_set: boolean;
  base_url:    string;
};

type StatusData = {
  status: string;
  version: string;
  pulsar: { skill_count: number; agents: string[] };
  tasks: { total: number; complete: number; failed: number };
  orion?: { event_count: number; training_examples: number };
};

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/* ── Nav structure ──────────────────────────────────────────── */

const NAV: NavEntry[] = [
  { kind: 'item',    id: 'models',   label: 'Models & Connections' },
  { kind: 'item',    id: 'budget',   label: 'Budget & Limits'      },
  { kind: 'item',    id: 'general',  label: 'General'              },
  { kind: 'section', label: 'Team' },
  { kind: 'item',    id: 'members',  label: 'Members'              },
  { kind: 'item',    id: 'api-keys', label: 'API Keys'             },
  { kind: 'section', label: 'Billing' },
  { kind: 'item',    id: 'plan',     label: 'Plan & Usage'         },
];

/* ── Provider data ──────────────────────────────────────────── */

const PROVIDERS = [
  { id: 'anthropic', name: 'Anthropic',        models: 'claude-sonnet-4-6, opus-4-6, haiku-4-5'    },
  { id: 'openai',    name: 'OpenAI',            models: 'gpt-4o, gpt-4o-mini, o3-mini'              },
  { id: 'google',    name: 'Google Vertex',     models: 'gemini-2.0-flash, pro, ultra'              },
  { id: 'mistral',   name: 'Mistral',           models: 'mistral-large, medium, 8x7b'               },
  { id: 'lmstudio',  name: 'LM Studio',         models: 'OpenAI-compatible · any loaded model'      },
  { id: 'ollama',    name: 'Ollama',             models: 'llama3, mistral, phi3, custom'             },
  { id: 'custom',    name: 'Custom Endpoint',   models: 'OpenAI-compatible API'                     },
];

type ProviderCfg = {
  label:        string;
  needsKey:     boolean;
  keyHint:      string;
  baseDefault:  string;
  modelOptions: string[];
  modelHint:    string;
  litellmFmt:   string;
};

const PROVIDER_CFG: Record<string, ProviderCfg> = {
  anthropic: {
    label:        'Anthropic',
    needsKey:     true,
    keyHint:      'Set ANTHROPIC_AUTH_TOKEN in .env — resolved at boot',
    baseDefault:  'https://api.anthropic.com',
    modelOptions: ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5'],
    modelHint:    'Per-agent overrides in Dev Console → LLM Config',
    litellmFmt:   'anthropic/{model}',
  },
  openai: {
    label:        'OpenAI',
    needsKey:     true,
    keyHint:      'Set OPENAI_API_KEY in .env',
    baseDefault:  'https://api.openai.com/v1',
    modelOptions: ['gpt-4o', 'gpt-4o-mini', 'o3-mini'],
    modelHint:    '',
    litellmFmt:   'openai/{model}',
  },
  lmstudio: {
    label:        'LM Studio',
    needsKey:     false,
    keyHint:      '',
    baseDefault:  'http://localhost:1234/v1',
    modelOptions: [],
    modelHint:    'Exact name shown in LM Studio\'s model list (e.g. llama-3.2-3b-instruct)',
    litellmFmt:   'openai/{model}',
  },
  ollama: {
    label:        'Ollama',
    needsKey:     false,
    keyHint:      '',
    baseDefault:  'http://localhost:11434',
    modelOptions: [],
    modelHint:    'Run `ollama list` to see available model names',
    litellmFmt:   'ollama/{model}',
  },
  google: {
    label:        'Google Vertex',
    needsKey:     true,
    keyHint:      'Set GOOGLE_API_KEY in .env',
    baseDefault:  '',
    modelOptions: ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
    modelHint:    '',
    litellmFmt:   'gemini/{model}',
  },
  mistral: {
    label:        'Mistral',
    needsKey:     true,
    keyHint:      'Set MISTRAL_API_KEY in .env',
    baseDefault:  'https://api.mistral.ai/v1',
    modelOptions: ['mistral-large-latest', 'mistral-medium', 'open-mixtral-8x7b'],
    modelHint:    '',
    litellmFmt:   'mistral/{model}',
  },
  custom: {
    label:        'Custom Endpoint',
    needsKey:     false,
    keyHint:      'Leave empty if the endpoint requires no auth',
    baseDefault:  '',
    modelOptions: [],
    modelHint:    'Model identifier as expected by the endpoint',
    litellmFmt:   'openai/{model}',
  },
};

/* ── Toggle ─────────────────────────────────────────────────── */

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button className={`toggle-btn${on ? ' toggle-on' : ''}`} onClick={onToggle}>
      <span className="toggle-thumb" />
    </button>
  );
}

/* ── Status pill ─────────────────────────────────────────────── */

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="cfg-status-pill" style={{ color: ok ? 'var(--green)' : 'var(--red)', borderColor: ok ? 'rgba(0,212,160,0.25)' : 'rgba(255,77,106,0.25)' }}>
      <span style={{ display: 'inline-block', width: 5, height: 5, borderRadius: '50%', background: ok ? 'var(--green)' : 'var(--red)', marginRight: 5 }} />
      {label}
    </span>
  );
}

/* ── Info row ────────────────────────────────────────────────── */

function InfoRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="cfg-info-row">
      <span className="cfg-info-label">{label}</span>
      <span className="cfg-info-value" style={mono ? { fontFamily: 'var(--mono)', fontSize: 11 } : {}}>{value}</span>
    </div>
  );
}

/* ── Models & Connections panel ─────────────────────────────── */

function ModelsPanel({
  config,
  setConfig,
  apiKey,
  setApiKey,
  toggles,
  flipToggle,
}: {
  config:     LLMConfig;
  setConfig:  (c: LLMConfig) => void;
  apiKey:     string;
  setApiKey:  (v: string) => void;
  toggles:    Record<string, boolean>;
  flipToggle: (key: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Models & Connections</div>
      <div className="settings-panel-sub">
        Global LLM defaults used by all agents. Agents can override per-skill in Dev Console → LLM Config.
      </div>

      <div className="form-section">
        <div className="form-section-hdr">Default LLM Provider</div>
        <div className="provider-grid">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              className={`provider-card${config.provider === p.id ? ' provider-active' : ''}`}
              onClick={() => {
                const cfg = PROVIDER_CFG[p.id] ?? PROVIDER_CFG.custom;
                setConfig({ ...config, provider: p.id, base_url: cfg.baseDefault, model: '' });
              }}
            >
              {config.provider === p.id && <span className="provider-check">✓</span>}
              <div className="provider-name">{p.name}</div>
              <div className="provider-models">{p.models}</div>
            </button>
          ))}
        </div>
      </div>

      {(() => {
        const provCfg = PROVIDER_CFG[config.provider] ?? PROVIDER_CFG.custom;
        const isLocal = config.provider === 'lmstudio' || config.provider === 'ollama';
        const litellm = provCfg.litellmFmt.replace('{model}', config.model || '<model>');
        return (
          <div className="form-section">
            <div className="form-section-hdr">
              {provCfg.label} Configuration
              {provCfg.needsKey && (
                <StatusPill ok={config.api_key_set} label={config.api_key_set ? 'API key set' : 'No API key'} />
              )}
              {isLocal && (
                <StatusPill ok label="No API key required" />
              )}
            </div>

            {provCfg.needsKey && (
              <div className="form-field" style={{ marginBottom: 14 }}>
                <label className="form-label">
                  API Key <span className="form-label-req">*</span>
                </label>
                <input
                  type="password"
                  className="form-input"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={config.api_key_set ? '••••••••  (key is set — enter to replace)' : 'Enter API key'}
                />
                <span className="form-hint">{provCfg.keyHint}</span>
              </div>
            )}

            <div className="form-2col">
              <div className="form-field">
                <label className="form-label">Model</label>
                {provCfg.modelOptions.length > 0 ? (
                  <select
                    className="form-select"
                    value={config.model}
                    onChange={(e) => setConfig({ ...config, model: e.target.value })}
                  >
                    {!config.model && <option value="">— not configured —</option>}
                    {provCfg.modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                ) : (
                  <input
                    type="text"
                    className="form-input"
                    value={config.model}
                    onChange={(e) => setConfig({ ...config, model: e.target.value })}
                    placeholder={
                      config.provider === 'lmstudio' ? 'e.g. llama-3.2-3b-instruct' :
                      config.provider === 'ollama'   ? 'e.g. llama3, mistral, phi3' :
                      'e.g. local-model'
                    }
                  />
                )}
                {provCfg.modelHint && <span className="form-hint">{provCfg.modelHint}</span>}
              </div>

              <div className="form-field">
                <label className="form-label">Base URL</label>
                <input
                  type="text"
                  className="form-input"
                  value={config.base_url}
                  onChange={(e) => setConfig({ ...config, base_url: e.target.value })}
                  placeholder={provCfg.baseDefault || 'https://…'}
                />
                {config.provider === 'lmstudio' && (
                  <span className="form-hint">Enable in LM Studio → Local Server tab, then Start Server</span>
                )}
                {config.provider === 'ollama' && (
                  <span className="form-hint">Run <code className="cfg-code">ollama serve</code> to start the local server</span>
                )}
              </div>
            </div>

            <div className="cfg-notice" style={{ marginTop: 10 }}>
              liteLLM routing: <code className="cfg-code">{litellm}</code>
              {isLocal && <span> — routed via <code className="cfg-code">{config.base_url || provCfg.baseDefault}</code></span>}
              {' '}· written to <code className="cfg-code">config/providers.yaml</code> on save
            </div>
          </div>
        );
      })()}

      <div className="form-section">
        <div className="form-section-hdr">Connection Health</div>
        <div className="toggle-list">
          {[
            {
              key:   'testBoot',
              label: 'Test connection on boot',
              desc:  'Andromeda pings the configured LLM provider during python boot.py startup',
            },
            {
              key:   'fallback',
              label: 'Fallback to secondary provider',
              desc:  'If primary provider is unavailable, fall back to configured secondary',
            },
            {
              key:   'logAether',
              label: 'Log all LLM calls to Aether',
              desc:  'Emit LLMCallEvent to aether stream for every model invocation. Required for Orion.',
            },
          ].map((t) => (
            <div key={t.key} className="toggle-row">
              <div className="toggle-row-left">
                <div className="toggle-label">{t.label}</div>
                <div className="toggle-desc">{t.desc}</div>
              </div>
              <Toggle on={toggles[t.key]} onToggle={() => flipToggle(t.key)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Budget & Limits panel ──────────────────────────────────── */

function BudgetPanel({
  toggles,
  flipToggle,
  policies,
  setPolicy,
  budget,
  setBudget,
}: {
  toggles:    Record<string, boolean>;
  flipToggle: (key: string) => void;
  policies:   Record<string, string>;
  setPolicy:  (key: string, value: string) => void;
  budget:     Record<string, string>;
  setBudget:  (key: string, value: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Budget & Limits</div>
      <div className="settings-panel-sub">
        Set daily token budgets and cost caps. When limits are hit, choose what Galaxz does — queue,
        reject, or fall back to a cheaper model.
      </div>

      <div className="form-section">
        <div className="form-section-hdr">Daily Limits</div>
        <div className="budget-grid">
          <div className="budget-cell">
            <span className="budget-cell-label">Daily token budget</span>
            <input
              type="text"
              className="budget-input"
              value={budget.tokens}
              onChange={(e) => setBudget('tokens', e.target.value)}
              placeholder="Unlimited"
            />
            <span className="budget-unit">tokens / day across all agents</span>
          </div>
          <div className="budget-cell">
            <span className="budget-cell-label">Daily cost cap</span>
            <input
              type="text"
              className="budget-input"
              value={budget.costCap}
              onChange={(e) => setBudget('costCap', e.target.value)}
              placeholder="No cap"
            />
            <span className="budget-unit">USD / day — estimated</span>
          </div>
          <div className="budget-cell">
            <span className="budget-cell-label">Concurrent limit</span>
            <input
              type="text"
              className="budget-input"
              value={budget.concurrent}
              onChange={(e) => setBudget('concurrent', e.target.value)}
              placeholder="Unlimited"
            />
            <span className="budget-unit">max parallel tasks</span>
          </div>
        </div>
      </div>

      <div className="form-section">
        <div className="form-section-hdr">Action Policy — When Limits Are Hit</div>
        <div className="policy-list">
          {[
            {
              key:     'tokenBudget',
              event:   'Daily token budget exceeded',
              options: ['Queue tasks', 'Reject with error', 'Fall back to Haiku'],
              values:  ['queue', 'reject', 'fallback'],
            },
            {
              key:     'costCap',
              event:   'Daily cost cap reached',
              options: ['Reject with error', 'Queue tasks', 'Fall back to Haiku'],
              values:  ['reject', 'queue', 'fallback'],
            },
            {
              key:     'concurrentLimit',
              event:   'Concurrent limit hit',
              options: ['Queue tasks', 'Reject with 429'],
              values:  ['queue', 'reject429'],
            },
          ].map((p) => (
            <div key={p.key} className="policy-row">
              <span className="policy-event">{p.event}</span>
              <select
                className="policy-select"
                value={policies[p.key]}
                onChange={(e) => setPolicy(p.key, e.target.value)}
              >
                {p.options.map((opt, i) => (
                  <option key={i} value={p.values[i]}>{opt}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      <div className="form-section">
        <div className="form-section-hdr">Alerts</div>
        <div className="toggle-list">
          {[
            {
              key:   'alertBudget',
              label: 'Alert at 80% of daily budget',
              desc:  'Notify via dashboard notification when daily token use reaches 80%',
            },
            {
              key:   'emitBudget',
              label: 'Emit budget events to Aether',
              desc:  'BudgetEvent emitted when thresholds are crossed. Orion can learn from budget constraints.',
            },
          ].map((t) => (
            <div key={t.key} className="toggle-row">
              <div className="toggle-row-left">
                <div className="toggle-label">{t.label}</div>
                <div className="toggle-desc">{t.desc}</div>
              </div>
              <Toggle on={toggles[t.key]} onToggle={() => flipToggle(t.key)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── General panel ──────────────────────────────────────────── */

function GeneralPanel({
  general,
  setGeneral,
}: {
  general:    Record<string, string>;
  setGeneral: (key: string, value: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">General</div>
      <div className="settings-panel-sub">
        Workspace-wide defaults applied to all agents and task routing.
      </div>
      <div className="form-section">
        <div className="form-2col">
          <div className="form-field">
            <label className="form-label">Workspace name</label>
            <input
              type="text"
              className="form-input"
              value={general.workspaceName}
              onChange={(e) => setGeneral('workspaceName', e.target.value)}
              placeholder="My Galaxz workspace"
            />
          </div>
          <div className="form-field">
            <label className="form-label">Default confidence threshold</label>
            <input
              type="text"
              className="form-input"
              value={general.confidenceThreshold}
              onChange={(e) => setGeneral('confidenceThreshold', e.target.value)}
            />
            <span className="form-hint">
              Tasks below this value are escalated for human review.
            </span>
          </div>
        </div>
        <div className="form-2col">
          <div className="form-field">
            <label className="form-label">Log level</label>
            <select
              className="form-select"
              value={general.logLevel}
              onChange={(e) => setGeneral('logLevel', e.target.value)}
            >
              <option value="INFO">INFO</option>
              <option value="DEBUG">DEBUG</option>
              <option value="WARN">WARN</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>
          <div className="form-field">
            <label className="form-label">Timezone</label>
            <select
              className="form-select"
              value={general.timezone}
              onChange={(e) => setGeneral('timezone', e.target.value)}
            >
              <option value="UTC">UTC</option>
              <option value="America/New_York">America/New_York</option>
              <option value="America/Los_Angeles">America/Los_Angeles</option>
              <option value="Europe/London">Europe/London</option>
              <option value="Asia/Tokyo">Asia/Tokyo</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Members panel ───────────────────────────────────────────── */

function MembersPanel({ status }: { status: StatusData | null }) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Members</div>
      <div className="settings-panel-sub">
        Workspace access and team management. Galaxz currently runs in single-user mode — multi-tenant support is on the roadmap.
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Current Workspace</div>
        <div className="cfg-info-list">
          <InfoRow label="Mode" value={<StatusPill ok label="Single-user" />} />
          <InfoRow label="Andromeda version" value={status?.version ?? '—'} mono />
          <InfoRow label="Registered agents" value={status?.pulsar.agents.join(', ') || '—'} mono />
          <InfoRow label="Skills available" value={status?.pulsar.skill_count ?? '—'} />
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Multi-tenant Support</div>
        <div className="cfg-notice">
          Role-based access control, team invitations, and per-member API key scoping are on the roadmap. Currently, all access is via the single{' '}
          <code className="cfg-code">GALAXZ_API_KEY</code> environment variable.
        </div>
      </div>
    </div>
  );
}

/* ── API Keys panel ──────────────────────────────────────────── */

function ApiKeysPanel({ status }: { status: StatusData | null }) {
  const serviceUrl = window.location.origin.replace(':5173', ':8000');

  return (
    <div className="settings-panel">
      <div className="settings-panel-title">API Keys</div>
      <div className="settings-panel-sub">
        Authentication credentials for the Galaxz platform and LLM providers. Keys are read from environment variables — never stored in the database.
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Platform Auth</div>
        <div className="cfg-info-list">
          <InfoRow
            label="GALAXZ_API_KEY"
            value={
              <StatusPill
                ok={status?.status === 'ok'}
                label={status?.status === 'ok' ? 'Service reachable' : 'Service unreachable'}
              />
            }
          />
          <InfoRow label="Auth mode" value="Bearer token (Authorization header)" />
          <InfoRow label="Service endpoint" value={serviceUrl} mono />
        </div>
        <div className="cfg-notice" style={{ marginTop: 12 }}>
          Set <code className="cfg-code">GALAXZ_API_KEY</code> in your <code className="cfg-code">.env</code> file to require auth. If unset, the service runs in local dev mode with auth disabled.
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-hdr">LLM Provider Keys</div>
        <div className="cfg-notice">
          LLM API keys are configured via environment variables and resolved at boot time from{' '}
          <code className="cfg-code">config/providers.yaml</code>. Use the{' '}
          <strong>Models &amp; Connections</strong> panel to view the current provider configuration. Keys are never sent to the frontend.
        </div>
        <div className="cfg-info-list" style={{ marginTop: 12 }}>
          <InfoRow label="ANTHROPIC_AUTH_TOKEN" value="Resolved at boot — see Models panel" />
          <InfoRow label="Key rotation" value="Restart the Andromeda service after updating .env" />
        </div>
      </div>
    </div>
  );
}

/* ── Plan & Usage panel ──────────────────────────────────────── */

function PlanPanel({ status }: { status: StatusData | null }) {
  function fmt(n: number | undefined) {
    return typeof n === 'number' ? n.toLocaleString() : '—';
  }

  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Plan & Usage</div>
      <div className="settings-panel-sub">
        Current usage metrics from the live system. Galaxz is open-source — there is no billing tier in self-hosted mode.
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Task Activity</div>
        <div className="cfg-stat-grid">
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: 'var(--t1)' }}>{fmt(status?.tasks.total)}</span>
            <span className="cfg-stat-label">Total tasks logged</span>
          </div>
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: 'var(--green)' }}>{fmt(status?.tasks.complete)}</span>
            <span className="cfg-stat-label">Completed</span>
          </div>
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: status?.tasks.failed ? 'var(--red)' : 'var(--t3)' }}>{fmt(status?.tasks.failed)}</span>
            <span className="cfg-stat-label">Failed</span>
          </div>
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: 'var(--purple, #9d7eff)' }}>{fmt(status?.pulsar.skill_count)}</span>
            <span className="cfg-stat-label">Skills registered</span>
          </div>
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Orion Learning Layer</div>
        <div className="cfg-stat-grid">
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: 'var(--orion, #ff6b9d)' }}>{fmt(status?.orion?.event_count)}</span>
            <span className="cfg-stat-label">Feedback events stored</span>
          </div>
          <div className="cfg-stat-card">
            <span className="cfg-stat-value" style={{ color: 'var(--t2)' }}>{fmt(status?.orion?.training_examples)}</span>
            <span className="cfg-stat-label">Training examples curated</span>
          </div>
        </div>
      </div>
      <div className="form-section">
        <div className="form-section-hdr">Hosted Platform</div>
        <div className="cfg-notice">
          Usage-based billing, team seats, and SLA tiers are planned for the hosted platform. The self-hosted open-source version is and will remain free.
        </div>
      </div>
    </div>
  );
}

/* ── Settings ───────────────────────────────────────────────── */

const LS_KEY = 'galaxz_settings_v1';

function loadLocal() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch { return {}; }
}

export function Settings() {
  const [panel, setPanel]     = useState<Panel>('models');
  const [saveState, setSaveState] = useState<SaveState>('idle');

  // LLM config — loaded from backend
  const [config, setConfig]   = useState<LLMConfig>({ provider: 'anthropic', model: '', api_key_set: false, base_url: '' });
  const [configOrig, setConfigOrig] = useState<LLMConfig>(config);
  const [apiKey, setApiKey]   = useState('');

  // Status — loaded from /api/status for Members / Plan panels
  const [statusData, setStatusData] = useState<StatusData | null>(null);

  // Toggles
  const [toggles, setToggles] = useState<Record<string, boolean>>(() => ({
    testBoot:    true,
    fallback:    false,
    logAether:   true,
    alertBudget: true,
    emitBudget:  true,
    ...loadLocal().toggles,
  }));

  // Policies
  const [policies, setPolicies] = useState<Record<string, string>>(() => ({
    tokenBudget:     'queue',
    costCap:         'reject',
    concurrentLimit: 'queue',
    ...loadLocal().policies,
  }));

  // Budget inputs
  const [budget, setBudgetState] = useState<Record<string, string>>(() => ({
    tokens: '', costCap: '', concurrent: '',
    ...loadLocal().budget,
  }));

  // General
  const [general, setGeneralState] = useState<Record<string, string>>(() => ({
    workspaceName: '',
    confidenceThreshold: '0.80',
    logLevel: 'DEBUG',
    timezone: 'UTC',
    ...loadLocal().general,
  }));

  useEffect(() => {
    Promise.all([
      fetch('/api/config').then(r => r.ok ? r.json() : null),
      fetch('/api/status').then(r => r.ok ? r.json() : null),
    ]).then(([cfg, status]) => {
      if (cfg) {
        setConfig(cfg);
        setConfigOrig(cfg);
      }
      if (status) setStatusData(status);
    });
  }, []);

  function flipToggle(key: string) {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function setPolicy(key: string, value: string) {
    setPolicies((prev) => ({ ...prev, [key]: value }));
  }

  function setBudget(key: string, value: string) {
    setBudgetState((prev) => ({ ...prev, [key]: value }));
  }

  function setGeneral(key: string, value: string) {
    setGeneralState((prev) => ({ ...prev, [key]: value }));
  }

  function saveToLocal() {
    localStorage.setItem(LS_KEY, JSON.stringify({ toggles, policies, budget, general }));
  }

  async function handleSave() {
    setSaveState('saving');
    try {
      if (panel === 'models') {
        const body: Record<string, string> = {};
        if (config.model)    body.model    = config.model;
        if (config.base_url) body.base_url = config.base_url;
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setConfigOrig(config);
        setApiKey('');
      } else {
        saveToLocal();
      }
      setSaveState('saved');
    } catch {
      setSaveState('error');
    }
    setTimeout(() => setSaveState('idle'), 2000);
  }

  function handleCancel() {
    if (panel === 'models') {
      setConfig(configOrig);
      setApiKey('');
    }
    const saved = loadLocal();
    if (panel === 'budget')  { setBudgetState({ tokens: '', costCap: '', concurrent: '', ...saved.budget }); }
    if (panel === 'general') { setGeneralState({ workspaceName: '', confidenceThreshold: '0.80', logLevel: 'DEBUG', timezone: 'UTC', ...saved.general }); }
  }

  const readOnlyPanel = panel === 'members' || panel === 'api-keys' || panel === 'plan';

  function renderPanel() {
    switch (panel) {
      case 'models':
        return (
          <ModelsPanel
            config={config}
            setConfig={setConfig}
            apiKey={apiKey}
            setApiKey={setApiKey}
            toggles={toggles}
            flipToggle={flipToggle}
          />
        );
      case 'budget':
        return (
          <BudgetPanel
            toggles={toggles}
            flipToggle={flipToggle}
            policies={policies}
            setPolicy={setPolicy}
            budget={budget}
            setBudget={setBudget}
          />
        );
      case 'general':
        return <GeneralPanel general={general} setGeneral={setGeneral} />;
      case 'members':
        return <MembersPanel status={statusData} />;
      case 'api-keys':
        return <ApiKeysPanel status={statusData} />;
      case 'plan':
        return <PlanPanel status={statusData} />;
    }
  }

  const saveLabel = saveState === 'saving' ? 'Saving…' : saveState === 'saved' ? 'Saved ✓' : saveState === 'error' ? 'Error — retry' : 'Save changes';

  return (
    <div className="app-shell">
      <Sidebar activeId="settings" />

      <div className="app-main">
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Settings</span>
          </div>
        </div>

        <div className="settings-body">
          <nav className="settings-nav">
            {NAV.map((entry, i) =>
              entry.kind === 'section' ? (
                <span key={i} className="settings-nav-section">{entry.label}</span>
              ) : (
                <button
                  key={entry.id}
                  className={`settings-nav-item${panel === entry.id ? ' settings-nav-active' : ''}`}
                  onClick={() => setPanel(entry.id)}
                >
                  {entry.label}
                </button>
              )
            )}
          </nav>

          <div className="settings-content-area">
            <div className="settings-scroll">
              {renderPanel()}
            </div>

            {!readOnlyPanel && (
              <div className="settings-save-bar">
                <span className="save-bar-info">
                  {panel === 'models'
                    ? 'Model and base URL changes write to config/providers.yaml — restart agents to apply.'
                    : 'Changes saved to browser local storage — no backend persistence for this panel yet.'}
                </span>
                <div className="save-bar-actions">
                  <button className="btn btn-ghost btn-sm" onClick={handleCancel}>Cancel</button>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSave}
                    disabled={saveState === 'saving'}
                    style={saveState === 'error' ? { background: 'var(--red)' } : saveState === 'saved' ? { background: 'var(--green)' } : {}}
                  >
                    {saveLabel}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Settings;
