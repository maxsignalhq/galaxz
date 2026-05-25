import React from 'react';
import '../styles/tokens.css';
import '../styles/landing.css';

/* ── Static data ───────────────────────────────────────────── */

const NAV_LINKS = ['Systems', 'How it works', 'Open source', 'Docs'];

const FEATURES = [
  {
    emoji: '🌌',
    bg: 'rgba(79,142,255,0.1)',
    title: 'Andromeda Router',
    desc: 'Central intelligence. Routes every task to the right agent based on skill confidence scoring. Human escalation below 0.80.',
  },
  {
    emoji: '⚡',
    bg: 'rgba(245,192,64,0.1)',
    title: 'Rigel Engineering',
    desc: '6-skill software engineering agent. Code generation, PR review, test writing, refactoring, scaffolding, and debug triage.',
  },
  {
    emoji: '🔬',
    bg: 'rgba(0,212,160,0.1)',
    title: 'Vega QA',
    desc: '3-stage quality pipeline. Analyzer → Test Designer → Bug Reporter. Every output validated before it leaves the system.',
  },
  {
    emoji: '〜',
    bg: 'rgba(56,168,255,0.1)',
    title: 'Aether Bus',
    desc: 'Redis Streams backbone. Every task contract flows through Aether. Replay, audit, and trace any event in the system.',
  },
  {
    emoji: '◎',
    bg: 'rgba(157,126,255,0.1)',
    title: 'Pulsar Registry',
    desc: 'Typed skill contracts. Every agent declares its capabilities. No ad-hoc passing — every boundary is explicit.',
  },
  {
    emoji: '🔭',
    bg: 'rgba(255,107,157,0.1)',
    title: 'Orion Learning',
    desc: 'The learning layer. Reads every FeedbackEvent from Aether. Builds training datasets. Routes get smarter over time.',
  },
] as const;

const HOW_STEPS = [
  {
    num: '01',
    title: 'Client submits task',
    desc: 'Any client POSTs a TaskContract to Andromeda. Natural language or structured JSON.',
    tag: 'POST /task',
  },
  {
    num: '02',
    title: 'Andromeda routes',
    desc: 'Scores confidence per registered skill. Routes above 0.80. Escalates below threshold.',
    tag: 'PulsarRegistry',
  },
  {
    num: '03',
    title: 'Agent executes',
    desc: 'Rigel or Vega receives the contract via Aether. Executes. Writes AgentResult to the stream.',
    tag: 'AetherStream',
  },
  {
    num: '04',
    title: 'Orion learns',
    desc: 'FeedbackEvent emitted. Orion ingests the signal. System routing improves.',
    tag: 'FeedbackLoop',
  },
] as const;

const AGENTS = [
  {
    id: 'andromeda',
    color: '#4f8eff',
    badge: 'active',
    badgeType: 'green',
    desc: 'Central router and orchestrator. Scores all incoming tasks against registered skills.',
    meta: 'threshold: 0.80 · port: 8000',
    isOrion: false,
  },
  {
    id: 'rigel',
    color: '#f5c040',
    badge: 'active',
    badgeType: 'green',
    desc: 'Software engineering specialist. 6 declared skills. Powered by claude-sonnet-4-6.',
    meta: '6 skills · claude-sonnet-4-6',
    isOrion: false,
  },
  {
    id: 'vega',
    color: '#00d4a0',
    badge: 'active',
    badgeType: 'green',
    desc: 'Quality assurance pipeline. 3-stage execution: analyzer → test_designer → bug_reporter.',
    meta: '3 stages · pipeline',
    isOrion: false,
  },
  {
    id: 'aether',
    color: '#38a8ff',
    badge: 'active',
    badgeType: 'green',
    desc: 'Redis Streams bus. All task contracts and feedback events flow through Aether.',
    meta: 'redis streams · :6379',
    isOrion: false,
  },
  {
    id: 'pulsar',
    color: '#9d7eff',
    badge: 'active',
    badgeType: 'green',
    desc: 'Skill registry. All agents declare capabilities via typed SkillContracts.',
    meta: '6 registered · typed contracts',
    isOrion: false,
  },
  {
    id: 'orion',
    color: '#ff6b9d',
    badge: 'building',
    badgeType: 'orion',
    desc: 'The learning layer. Passive consumer on Aether. Reads FeedbackEvents, builds training datasets.',
    meta: 'building...',
    isOrion: true,
  },
] as const;

const FOOTER_COLS = [
  { label: 'Product',     links: ['Dashboard', 'Dev Console', 'Orion Analytics', 'Changelog'] },
  { label: 'Docs',        links: ['Quickstart', 'Architecture', 'Agent API', 'Skill Contracts'] },
  { label: 'Open Source', links: ['GitHub', 'Contributing', 'Roadmap', 'MIT License'] },
  { label: 'Company',     links: ['About', 'Blog', 'Contact'] },
] as const;

/* ── Icons ─────────────────────────────────────────────────── */

function GitHubIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <path d="M2.5 6H9.5M6.5 3L9.5 6L6.5 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function LiveDot({ size = 7 }: { size?: number }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: 'var(--green)',
        boxShadow: '0 0 7px var(--green)',
        display: 'inline-block',
        flexShrink: 0,
        animation: 'pulse-dot 2.4s ease-in-out infinite',
      }}
    />
  );
}

/* ── Landing page ───────────────────────────────────────────── */

export function Landing() {
  return (
    <div className="landing">
      {/* Full-page grid overlay */}
      <div className="grid-overlay" />

      {/* ══ NAV ══════════════════════════════════════════════ */}
      <nav className="land-nav">
        <a className="land-nav-logo" href="#">
          <LiveDot />
          <span className="land-nav-logo-text">galaxz</span>
        </a>

        <div className="land-nav-links">
          {NAV_LINKS.map(link => (
            <a key={link} className="land-nav-link" href="#">
              {link}
            </a>
          ))}
        </div>

        <div className="land-nav-right">
          <button className="btn btn-ghost btn-sm">Sign in</button>
          <button className="btn btn-primary btn-sm">
            Get started&nbsp;&nbsp;<ArrowIcon />
          </button>
        </div>
      </nav>

      {/* ══ HERO ═════════════════════════════════════════════ */}
      <section className="hero">
        {/* Kicker */}
        <div className="hero-kicker">
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--green)', display: 'inline-block', flexShrink: 0 }} />
          Open Source · v0.1.0 · MIT License
        </div>

        {/* Headline */}
        <h1 className="hero-h1">
          The open AI agent
          <span className="hero-h1-gradient">operating system</span>
        </h1>

        {/* Subtitle */}
        <p className="hero-sub">
          Orchestrate specialized AI agents at scale. Vega plans. Rigel builds.
          Andromeda routes. Orion learns. One platform. One bus. Infinite capability.
        </p>

        {/* CTAs */}
        <div className="hero-cta">
          <button className="btn btn-primary btn-lg">
            <GitHubIcon />
            Star on GitHub
          </button>
          <button className="btn btn-outline btn-lg">Read the docs</button>
        </div>

        {/* Meta */}
        <div className="hero-meta">
          <span>Apache 2.0 license</span>
          <span className="hero-meta-sep" />
          <span>multi-agent ready</span>
          <span className="hero-meta-sep" />
          <span>docker-compose ready</span>
        </div>

        {/* Boot terminal */}
        <div className="terminal">
          <div className="terminal-header">
            <span className="terminal-dot" style={{ background: '#ff5f57' }} />
            <span className="terminal-dot" style={{ background: '#ffbd2e' }} />
            <span className="terminal-dot" style={{ background: '#28ca41' }} />
            <span className="terminal-title">galaxz — boot sequence</span>
          </div>
          <div className="terminal-body">
            <span className="tl tc-prompt">{'$ git clone https://github.com/galaxz-ai/galaxz && cd galaxz'}</span>
            <span className="tl tc-dim">{'Cloning into \'galaxz\'...'}</span>
            <span className="tc-blank" />
            <span className="tl tc-prompt">{'$ docker-compose up -d && python boot.py'}</span>
            <span className="tl tc-dim">Starting galaxz services...</span>
            <span className="tc-blank" />
            <span className="tl tc-green">{'✓ PulsarRegistry        initialized · 6 skills registered'}</span>
            <span className="tl tc-green">{'✓ AetherStream          redis://localhost:6379 · streams active'}</span>
            <span className="tl tc-green">{'✓ Andromeda             router online · threshold 0.80'}</span>
            <span className="tl tc-green">{'✓ RigelAgent            6 skills loaded · claude-sonnet-4-6'}</span>
            <span className="tl tc-green">{'✓ Vega                  3 stages · analyzer → test_designer → bug_reporter'}</span>
            <span className="tc-blank" />
            <span className="tl tc-teal">{'→ System ready. Andromeda listening on :8000'}</span>
            <span className="tc-blank" />
            <span className="tl tc-prompt">{'$ galaxz route --skill rigel.skill.code_generation'}</span>
            <span className="tl tc-yellow">{'⟳ task_id: <returned by live backend>'}</span>
            <span className="tl tc-dim">{'  routing → <selected agent> · confidence: <live score> · status: <live status>'}</span>
            <span className="tl tc-green">{'✓ FeedbackEvent emitted when the backend completes the task'}</span>
            <span className="tc-blank" />
            <span className="tl tc-prompt">
              {'$ '}
              <span className="cursor" />
            </span>
          </div>
        </div>
      </section>

      {/* ══ STATS BAR ════════════════════════════════════════ */}
      <div className="stats-outer">
        <div className="stats-grid">
          {(
            [
              { val: '3',    lbl: 'Production agents' },
              { val: '6',    lbl: 'Rigel skills registered' },
              { val: '0.80', lbl: 'Confidence threshold' },
              { val: '∞',    lbl: 'Composable via Aether' },
            ] as const
          ).map(s => (
            <div key={s.lbl} className="stats-cell">
              <span className="stats-val">{s.val}</span>
              <span className="stats-lbl">{s.lbl}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ══ FEATURES ═════════════════════════════════════════ */}
      <div className="section-wrap">
        <span className="section-kicker">PLATFORM</span>
        <h2 className="section-h2">
          Built for scale.<br />Designed to be open.
        </h2>
        <p className="section-sub">
          Every system has a name, a contract, and a purpose. No black boxes.
        </p>

        <div className="features-grid">
          {FEATURES.map(f => (
            <div key={f.title} className="feature-card">
              <div className="feature-icon-wrap" style={{ background: f.bg }}>
                {f.emoji}
              </div>
              <div className="feature-title">{f.title}</div>
              <div className="feature-desc">{f.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ══ HOW IT WORKS ═════════════════════════════════════ */}
      <div className="section-wrap">
        <span className="section-kicker">HOW IT WORKS</span>
        <h2 className="section-h2">
          From request to result.<br />Every step observable.
        </h2>

        <div className="how-grid">
          {HOW_STEPS.map(s => (
            <div key={s.num} className="how-card">
              <span className="how-num">{s.num}</span>
              <div className="how-title">{s.title}</div>
              <p className="how-desc">{s.desc}</p>
              <span className="how-tag">{s.tag}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ══ AGENTS ═══════════════════════════════════════════ */}
      <div className="section-wrap">
        <span className="section-kicker">SYSTEMS</span>
        <h2 className="section-h2">
          Seven systems.<br />One architecture.
        </h2>
        <p className="section-sub" style={{ marginBottom: 28 }}>
          Every component has a name, a color, and a contract.
        </p>

        <div className="agents-grid">
          {AGENTS.map(agent => (
            <div
              key={agent.id}
              className={`agent-card${agent.isOrion ? ' agent-card-orion' : ''}`}
            >
              <div className="agent-card-header">
                <div className="agent-name-row">
                  <span
                    className="agent-glow-dot"
                    style={{ background: agent.color, boxShadow: `0 0 6px ${agent.color}` }}
                  />
                  <span className="agent-name" style={{ color: agent.color }}>
                    {agent.id}
                  </span>
                </div>
                <span className={`badge badge-${agent.badgeType}`}>{agent.badge}</span>
              </div>
              <p className="agent-desc">{agent.desc}</p>
              <span className={`agent-meta${agent.isOrion ? ' agent-meta-dim' : ''}`}>
                {agent.meta}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ══ QUICKSTART ═══════════════════════════════════════ */}
      <div className="section-wrap">
        <span className="section-kicker">QUICKSTART</span>
        <h2 className="section-h2">Up in two commands.</h2>
        <p className="section-sub" style={{ marginBottom: 28 }}>Clone, boot, route. That's it.</p>

        <div className="quickstart-grid">
          {/* Panel 1 */}
          <div className="qs-panel">
            <div className="qs-header">
              <span className="qs-title">Install &amp; run</span>
              <button className="btn btn-ghost btn-sm">Copy</button>
            </div>
            <div className="qs-body">
              <span className="qp">$ git clone https://github.com/galaxz-ai/galaxz</span>
              <span className="qp">$ cd galaxz</span>
              <span className="qc"># start all services</span>
              <span className="qp">$ docker-compose up -d</span>
              <span className="qo">{'  Starting redis_1   ... done'}</span>
              <span className="qo">{'  Starting galaxz_1  ... done'}</span>
              <span className="qc"># boot the OS</span>
              <span className="qp">$ python boot.py</span>
              <span className="qs">✓ All systems online. Andromeda on :8000</span>
            </div>
          </div>

          {/* Panel 2 */}
          <div className="qs-panel">
            <div className="qs-header">
              <span className="qs-title">Route your first task</span>
              <button className="btn btn-ghost btn-sm">Copy</button>
            </div>
            <div className="qs-body">
              <span className="qp">{'$ galaxz route --skill rigel.skill.code_generation \\'}</span>
              <span className="qp" style={{ paddingLeft: 16 }}>{'    --input "implement OAuth2 flow"'}</span>
              <span className="qb" />
              <span className="qo">{'task_id:    <returned by live backend>'}</span>
              <span className="qo">agent:      &lt;selected agent&gt;</span>
              <span className="qo">confidence: &lt;live score&gt;</span>
              <span className="qo">status:     &lt;live status&gt;</span>
              <span className="qo">skill:      code_generation</span>
              <span className="qb" />
              <span className="qs">✓ FeedbackEvent emitted → aether</span>
            </div>
          </div>
        </div>
      </div>

      {/* ══ OSS PANEL ════════════════════════════════════════ */}
      <div className="section-wrap">
        <div className="oss-panel">
          <div>
            <h3 className="oss-h3">
              Built in the open.<br />Forever.
            </h3>
            <p className="oss-desc">
              Galaxz is MIT licensed and will always be free to use, modify, and extend.
              No feature flags. No forced upgrades. Self-host it, fork it, build on it.
            </p>
            <div className="oss-badges">
              {(['MIT License', 'self-hostable', 'no vendor lock-in', 'bring your own LLM'] as const).map(b => (
                <span key={b} className="oss-badge">{b}</span>
              ))}
            </div>
          </div>
          <div className="oss-stat">
            <span className="oss-version-num">v0.1</span>
            <span className="oss-version-lbl">First release</span>
          </div>
        </div>
      </div>

      {/* ══ FOOTER ═══════════════════════════════════════════ */}
      <footer className="land-footer">
        <div className="land-footer-inner">
          {/* Brand */}
          <div className="footer-brand">
            <div className="footer-logo">
              <LiveDot />
              <span className="footer-logo-text">galaxz</span>
            </div>
            <p className="footer-brand-desc">
              The open AI agent operating system. Built to outlast any single company.
            </p>
          </div>

          {/* Link columns */}
          <div className="footer-links-grid">
            {FOOTER_COLS.map(col => (
              <div key={col.label}>
                <span className="footer-col-label">{col.label}</span>
                <ul className="footer-links">
                  {col.links.map(link => (
                    <li key={link}>
                      <a className="footer-link" href="#">
                        {link}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Right branding */}
          <div className="footer-right">
            <span className="footer-brand-name">GALAXZ</span>
            <span className="footer-version">v0.1.0</span>
            <span className="footer-copy">© 2025 Galaxz. MIT License.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default Landing;
