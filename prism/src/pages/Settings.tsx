import React, { useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';
import '../styles/settings.css';

/* ── Types ──────────────────────────────────────────────────── */

type Panel = 'models' | 'budget' | 'general' | 'members' | 'api-keys' | 'plan';

type NavEntry =
  | { kind: 'section'; label: string }
  | { kind: 'item';    id: Panel; label: string };

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
  { id: 'anthropic', name: 'Anthropic',       models: 'claude-sonnet-4-6, opus-4-6, haiku-4-5' },
  { id: 'openai',    name: 'OpenAI',           models: 'gpt-4o, gpt-4o-mini, o3'               },
  { id: 'google',    name: 'Google Vertex',    models: 'gemini-2.0-flash, pro, ultra'           },
  { id: 'mistral',   name: 'Mistral',          models: 'mistral-large, medium, 8x7b'            },
  { id: 'ollama',    name: 'Ollama / Local',   models: 'llama3, mistral, custom'                },
  { id: 'custom',    name: 'Custom Endpoint',  models: 'OpenAI-compatible API'                  },
];

/* ── Toggle ─────────────────────────────────────────────────── */

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button className={`toggle-btn${on ? ' toggle-on' : ''}`} onClick={onToggle}>
      <span className="toggle-thumb" />
    </button>
  );
}

/* ── Models & Connections panel ─────────────────────────────── */

function ModelsPanel({
  provider,
  setProvider,
  toggles,
  flipToggle,
}: {
  provider:    string;
  setProvider: (id: string) => void;
  toggles:     Record<string, boolean>;
  flipToggle:  (key: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Models & Connections</div>
      <div className="settings-panel-sub">
        Global LLM defaults used by all agents. Agents can override per-skill in Dev Console → LLM Config.
      </div>

      {/* Section 1 — Default LLM Provider */}
      <div className="form-section">
        <div className="form-section-hdr">Default LLM Provider</div>
        <div className="provider-grid">
          {PROVIDERS.map((p) => (
            <button
              key={p.id}
              className={`provider-card${provider === p.id ? ' provider-active' : ''}`}
              onClick={() => setProvider(p.id)}
            >
              {provider === p.id && <span className="provider-check">✓</span>}
              <div className="provider-name">{p.name}</div>
              <div className="provider-models">{p.models}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Section 2 — Anthropic Configuration */}
      <div className="form-section">
        <div className="form-section-hdr">Anthropic Configuration</div>
        <div className="form-2col">
          <div className="form-field">
            <label className="form-label">
              API Key <span className="form-label-req">*</span>
            </label>
            <input
              type="password"
              className="form-input"
              defaultValue=""
              placeholder="No key loaded from backend config"
            />
            <span className="form-hint">
              Stored encrypted. Used as default by all agents unless overridden.
            </span>
          </div>
          <div className="form-field">
            <label className="form-label">Default Model</label>
            <select className="form-select" defaultValue="not-configured">
              <option value="not-configured">No default loaded</option>
              <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
              <option value="claude-opus-4-6">claude-opus-4-6</option>
              <option value="claude-haiku-4-5">claude-haiku-4-5</option>
            </select>
            <span className="form-hint">
              Per-agent overrides configured in Dev Console → Agent → LLM Config
            </span>
          </div>
        </div>
        <div className="form-2col">
          <div className="form-field">
            <label className="form-label">API Base URL</label>
            <input
              type="text"
              className="form-input"
              defaultValue="https://api.anthropic.com"
            />
          </div>
          <div className="form-field">
            <label className="form-label">API Version</label>
            <input
              type="text"
              className="form-input"
              defaultValue="2023-06-01"
            />
          </div>
        </div>
      </div>

      {/* Section 3 — Connection Health */}
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
}: {
  toggles:    Record<string, boolean>;
  flipToggle: (key: string) => void;
  policies:   Record<string, string>;
  setPolicy:  (key: string, value: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-panel-title">Budget & Limits</div>
      <div className="settings-panel-sub">
        Set daily token budgets and cost caps. When limits are hit, choose what Galaxz does — queue,
        reject, or fall back to a cheaper model.
      </div>

      {/* Section 1 — Daily Limits */}
      <div className="form-section">
        <div className="form-section-hdr">Daily Limits</div>
        <div className="budget-grid">
          <div className="budget-cell">
            <span className="budget-cell-label">Daily token budget</span>
            <input type="text" className="budget-input" defaultValue="" placeholder="No limit loaded" />
            <span className="budget-unit">tokens / day across all agents</span>
          </div>
          <div className="budget-cell">
            <span className="budget-cell-label">Daily cost cap</span>
            <input type="text" className="budget-input" defaultValue="" placeholder="No cap loaded" />
            <span className="budget-unit">USD / day — estimated</span>
          </div>
          <div className="budget-cell">
            <span className="budget-cell-label">Concurrent limit</span>
            <input type="text" className="budget-input" defaultValue="" placeholder="No limit loaded" />
            <span className="budget-unit">max parallel tasks</span>
          </div>
        </div>
      </div>

      {/* Section 2 — Action Policy */}
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

      {/* Section 3 — Alerts */}
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

function GeneralPanel() {
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
            <input type="text" className="form-input" defaultValue="" placeholder="No workspace name loaded" />
          </div>
          <div className="form-field">
            <label className="form-label">Default confidence threshold</label>
            <input type="text" className="form-input" defaultValue="0.80" />
            <span className="form-hint">
              Tasks below this value are escalated for human review. Per-skill overrides available via SkillContract.
            </span>
          </div>
        </div>
        <div className="form-2col">
          <div className="form-field">
            <label className="form-label">Log level</label>
            <select className="form-select" defaultValue="DEBUG">
              <option value="INFO">INFO</option>
              <option value="DEBUG">DEBUG</option>
              <option value="WARN">WARN</option>
              <option value="ERROR">ERROR</option>
            </select>
          </div>
          <div className="form-field">
            <label className="form-label">Timezone</label>
            <select className="form-select" defaultValue="UTC">
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

/* ── Placeholder panels ─────────────────────────────────────── */

const PLACEHOLDERS: Partial<Record<Panel, { title: string; sub: string }>> = {
  members: {
    title: 'Members',
    sub:   'Manage team members and their access levels. Invite collaborators to your Galaxz workspace.',
  },
  'api-keys': {
    title: 'API Keys',
    sub:   'Generate and revoke API keys for programmatic access to the Galaxz platform and agent APIs.',
  },
  plan: {
    title: 'Plan & Usage',
    sub:   'View your current plan, usage metrics, and billing history. Upgrade or downgrade at any time.',
  },
};

function PlaceholderPanel({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="settings-placeholder">
      <div className="settings-panel-title">{title}</div>
      <div className="settings-placeholder-sub">{sub}</div>
    </div>
  );
}

/* ── Settings ───────────────────────────────────────────────── */

export function Settings() {
  const [panel, setPanel]       = useState<Panel>('models');
  const [provider, setProvider] = useState('anthropic');
  const [toggles, setToggles]   = useState<Record<string, boolean>>({
    testBoot:    true,
    fallback:    false,
    logAether:   true,
    alertBudget: true,
    emitBudget:  true,
  });
  const [policies, setPolicies] = useState<Record<string, string>>({
    tokenBudget:     'queue',
    costCap:         'reject',
    concurrentLimit: 'queue',
  });

  function flipToggle(key: string) {
    setToggles((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function setPolicy(key: string, value: string) {
    setPolicies((prev) => ({ ...prev, [key]: value }));
  }

  function renderPanel() {
    switch (panel) {
      case 'models':
        return (
          <ModelsPanel
            provider={provider}
            setProvider={setProvider}
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
          />
        );
      case 'general':
        return <GeneralPanel />;
      default: {
        const p = PLACEHOLDERS[panel];
        return p ? <PlaceholderPanel {...p} /> : null;
      }
    }
  }

  return (
    <div className="app-shell">
      <Sidebar activeId="settings" />

      <div className="app-main">
        {/* Topbar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">Settings</span>
          </div>
        </div>

        {/* Settings body */}
        <div className="settings-body">

          {/* Settings nav */}
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

          {/* Content + save bar */}
          <div className="settings-content-area">
            <div className="settings-scroll">
              {renderPanel()}
            </div>

            <div className="settings-save-bar">
              <span className="save-bar-info">
                Changes are saved per workspace · agents will hot-reload updated config
              </span>
              <div className="save-bar-actions">
                <button className="btn btn-ghost btn-sm">Cancel</button>
                <button className="btn btn-primary btn-sm">Save changes</button>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

export default Settings;
