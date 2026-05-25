# Galaxz — Claude Code Prompts
## All 7 Screens · Exact Implementation · Copy-Paste Ready

Each prompt is self-contained. Paste it directly into Claude Code.
Start with the **Design System prompt** first (shared foundation), then run each screen prompt independently.

---

---

# ── FOUNDATION ──────────────────────────────────────────────────────────────
# Run this FIRST before any screen. Creates the shared design system.
---

## PROMPT 0 — Design System & Shared Shell

```
Create the Galaxz shared design system. This is the foundation for all 7 UI screens.
Output: `src/styles/tokens.css` and `src/components/Sidebar.tsx` (or equivalent for your stack).

─── DESIGN SYSTEM TOKENS ───────────────────────────────────────────

CSS custom properties (use these exact values across every screen):

  Background layers:
    --bg:   #07090e    (page background)
    --bg1:  #0b0e17    (cards, sidebar, panels)
    --bg2:  #0f1420    (inputs, code blocks, nested panels)
    --bg3:  #141929    (chart bars, empty bars, hover fills)
    --bg4:  #1a2035    (deepest inset)

  Borders:
    --b1: rgba(255,255,255,0.055)   (default border)
    --b2: rgba(255,255,255,0.09)    (hover / focused border)
    --b3: rgba(255,255,255,0.14)    (active / pressed border)

  Text:
    --t1: #edf0fa    (primary text)
    --t2: #8a94b0    (secondary text / labels)
    --t3: #48526e    (muted text / metadata)
    --t4: #2e3650    (very muted / disabled)

  System colors (one per agent — use these consistently):
    --blue:   #4f8eff    (Andromeda, primary accent, CTAs)
    --green:  #00d4a0    (Vega, success, online, accept)
    --yellow: #f5c040    (Rigel, warning, review, escalate)
    --red:    #ff4d6a    (errors, reject, SLA urgent, fail)
    --purple: #9d7eff    (Pulsar skill registry)
    --teal:   #38a8ff    (Aether Redis bus)
    --orion:  #ff6b9d    (Orion Phase 3, pink)

  Typography:
    --sans: 'Geist', system-ui, sans-serif
    --mono: 'Geist Mono', monospace
    Import: https://fonts.googleapis.com/css2?family=Geist+Mono:wght@300;400;500;600&family=Geist:wght@300;400;500;600;700

─── SIDEBAR COMPONENT ──────────────────────────────────────────────

Shared sidebar used on ALL app screens (Dashboard, Dev Console, Task UI, Review Queue, Orion, Settings).
Width: 216px. Background: var(--bg1). Right border: 1px solid var(--b1). Full viewport height.

Sections and nav items (in order):

  Logo row (top):
    - Animated green dot (7px, border-radius 50%, background var(--green), box-shadow 0 0 8px var(--green))
    - Dot animates: opacity 1→0.5→1 with box-shadow 7px→3px→7px, 2.4s ease-in-out infinite
    - Text: "galaxz" — Geist, 14px, font-weight 600, letter-spacing -0.3px

  Section: Platform
    - Label: "PLATFORM" — mono, 9px, letter-spacing 0.25em, uppercase, color var(--t4)
    - Dashboard — icon: grid 2x2, label "Dashboard"
    - Task Queue — icon: list, label "Task Queue", badge: "3" (red badge, var(--red), if pending)

  Section: Developer
    - Label: "DEVELOPER"
    - Dev Console — icon: code brackets </>
    - Task UI — icon: chat bubble
    - Review Queue — icon: people/users, badge: "3" (red)

  Section: Intelligence
    - Label: "INTELLIGENCE"
    - Orion Analytics — icon: activity/pulse line

  Section: System
    - Label: "SYSTEM"
    - Settings — icon: radio/signal circle
    - Docs — icon: file text

  Footer (bottom, above border):
    - User row: avatar circle (24px, gradient blue→purple, initial "A"), name "Admin", role "Admin · v0.1.0"

Nav item styling:
  Default: padding 7px 10px, border-radius 6px, color var(--t2), font-size 12.5px
  Hover: background rgba(255,255,255,0.04), color var(--t1)
  Active: background rgba(79,142,255,0.1), color var(--blue)
  SVG icons: 13×13px, opacity 0.6 default, opacity 1 when active
  Badges: font-family mono, font-size 9px, padding 1px 6px, border-radius 10px, background rgba(255,77,106,0.15), color var(--red)

─── SHARED BUTTON STYLES ───────────────────────────────────────────

.btn-primary:    background var(--blue), color #fff, hover background #3d7aff + translateY(-1px) + shadow
.btn-outline:    background transparent, border 1px solid var(--b2), color var(--t2), hover border var(--b3) color var(--t1)
.btn-ghost:      background transparent, color var(--t2), hover background rgba(255,255,255,0.04)
.btn-accept:     background rgba(0,212,160,0.1), border rgba(0,212,160,0.25), color var(--green)
.btn-reject:     background rgba(255,77,106,0.08), border rgba(255,77,106,0.2), color var(--red)
.btn-rerun:      background rgba(79,142,255,0.08), border rgba(79,142,255,0.2), color var(--blue)

All buttons: font-family var(--sans), font-size 11–13px, border-radius 5–6px, transition all 0.15s, cursor pointer

─── TOPBAR PATTERN ─────────────────────────────────────────────────

Every app screen has a fixed topbar: height 48px, border-bottom 1px solid var(--b1), background var(--bg1), padding 0 24px.
Contains: page title (Geist 13px font-weight 600) + subtitle (11px var(--t3)) + right-side actions.

─── CARD PATTERN ───────────────────────────────────────────────────

.card: background var(--bg1), border 1px solid var(--b1), border-radius 8px, overflow hidden
.card-head: padding 12px 16px, border-bottom 1px solid var(--b1), flex row, space-between
  .card-title: 12px font-weight 600 color var(--t2)
  .card-meta: mono 10px color var(--t3)
.card-body: padding 14px 16px

─── CONFIDENCE BAR PATTERN ─────────────────────────────────────────

Used everywhere a confidence score appears:
  Track: flex-1, height 3–5px, border-radius 2–3px, background var(--bg3)
  Fill: same height, border-radius same, color based on value:
    ≥ 0.80: var(--green)
    0.60–0.79: var(--yellow)
    < 0.60: var(--red)
  Threshold marker: absolute positioned at 80% of track width, 1px wide, background rgba(245,192,64,0.6), height 11px, top -3px
  Value label: mono 11–12px, color matches fill color
```

---

---

# ── SCREEN 1 ────────────────────────────────────────────────────────────────
---

## PROMPT 1 — Landing Page
### `src/pages/Landing.tsx` (or `landing.html`)

```
Build the Galaxz public landing page. Dark, precision aesthetic — Cursor/Devin quality.
No sidebar. Full-width marketing page. Uses the Galaxz design system tokens from PROMPT 0.

─── NAVIGATION ─────────────────────────────────────────────────────

Fixed top nav. Height 52px. Background rgba(7,9,14,0.88) with backdrop-filter blur(14px).
Border-bottom 1px solid var(--b1). Position fixed, z-index 100.

Left: Logo — animated green dot (same animation as sidebar) + "galaxz" text (Geist 15px font-weight 600 letter-spacing -0.3px)

Center links (hidden mobile): Systems · How it works · Open source · Docs · Pricing
  Each: padding 6px 12px, border-radius 5px, font-size 13px, color var(--t2)
  Hover: color var(--t1), background rgba(255,255,255,0.04)

Right: "Sign in" (ghost btn) + "Get started" (primary btn with → arrow icon)
  Get started button: on hover, translateY(-1px), box-shadow 0 4px 18px rgba(79,142,255,0.28)

─── HERO ────────────────────────────────────────────────────────────

Max-width 1100px, margin auto, padding 120px 32px 80px.

Background grid overlay (CSS only, full page):
  background-image: linear-gradient(var(--b1) 1px, transparent 1px),
                    linear-gradient(90deg, var(--b1) 1px, transparent 1px)
  background-size: 60px 60px
  mask-image: radial-gradient(ellipse 80% 60% at 50% 30%, black 30%, transparent 80%)

Kicker badge (above title):
  Display: inline-flex, items-center, gap 8px
  Padding 5px 12px, border-radius 20px, border 1px solid var(--b2)
  Background rgba(0,212,160,0.06)
  Text: "Open Source · v0.1.0 · MIT License · Phase 2 complete"
  Font: mono 11px, color var(--green), letter-spacing 0.3px
  Left: 5px green dot

H1 title (two lines):
  "The open AI agent"  (line 1)
  "operating system"   (line 2, gradient text)
  Font: clamp(42px, 6vw, 68px), font-weight 700, letter-spacing -2.5px, line-height 1.06
  Gradient text: linear-gradient(135deg, var(--blue) 0%, var(--purple) 100%)
  Applied with -webkit-background-clip: text, -webkit-text-fill-color: transparent

Subtitle paragraph:
  "Orchestrate specialized AI agents at scale. Vega plans. Rigel builds. Andromeda routes. Orion learns. One platform. One bus. Infinite capability."
  Font-size 16px, color var(--t2), max-width 520px, line-height 1.65, margin-bottom 36px

CTA row:
  - "Star on GitHub" (primary btn lg, has GitHub icon SVG left)
  - "Read the docs" (outline btn lg)
  Gap 12px, margin-bottom 60px

Meta row below CTAs:
  Three items with 4px dots between: "Apache 2.0 license" · "Phase 2 shipped" · "docker-compose ready"
  Font: mono 12px, color var(--t3)

─── BOOT TERMINAL ───────────────────────────────────────────────────

Rendered below the hero text. Full width within hero max-width.

Terminal chrome:
  Background var(--bg1), border 1px solid var(--b2), border-radius 10px
  Box-shadow: 0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px var(--b1)

  Header bar: background var(--bg2), border-bottom 1px solid var(--b1), padding 10px 14px
    Three dots: 10px circles — red #ff5f57, yellow #ffbd2e, green #28ca41
    Center title: "galaxz — boot sequence" mono 11px color var(--t3)

  Body: padding 18px 18px 22px, font-family mono, font-size 12.5px, line-height 1.75

Exact terminal content (copy these lines exactly):

  $ git clone https://github.com/galaxz-ai/galaxz && cd galaxz
  Cloning into 'galaxz'...                                          [dim]

  $ docker-compose up -d && python boot.py
  Starting galaxz services...                                       [dim]

  ✓ PulsarRegistry        initialized · 6 skills registered         [green]
  ✓ AetherStream          redis://localhost:6379 · streams active    [green]
  ✓ Andromeda             router online · threshold 0.80             [green]
  ✓ RigelAgent            6 skills loaded · claude-sonnet-4-6        [green]
  ✓ Vega                  3 stages · analyzer → test_designer → bug_reporter  [green]

  → System ready. Andromeda listening on :8000                       [blue/teal]

  $ galaxz route --skill rigel.skill.code_generation
  ⟳ task_id: 26a5fc41-3ab4-4de5-aa35-2decf55dcc7a                   [yellow]
    routing → rigel · confidence: 0.84 · status: complete            [dim]
  ✓ FeedbackEvent emitted → aether · orion will ingest in Phase 3   [green]

  $  [cursor — blinking green block 7×13px, animation blink 1.1s step-end infinite]

Color coding:
  Prompts ($): var(--green)
  Success lines (✓): var(--green)
  Dim/output lines: var(--t3)
  System ready arrow (→): var(--teal)
  Task ID line (⟳): var(--yellow)

─── STATS BAR ───────────────────────────────────────────────────────

Below terminal. 4-column grid. Border 1px solid var(--b1), border-radius 10px, background var(--bg1).
Each cell: padding 22px 24px, border-right 1px solid var(--b1) (last has none)

Values (font: mono 28px font-weight 700 letter-spacing -1px):
  "3"     — Production agents
  "6"     — Rigel skills registered
  "0.80"  — Confidence threshold
  "∞"     — Composable via Aether

─── FEATURES SECTION ────────────────────────────────────────────────

Section label: "PLATFORM" (mono 11px uppercase letter-spacing 1.5px color var(--t3))
H2: "Built for scale.\nDesigned to be open." (clamp 28–40px, font-weight 700, letter-spacing -1.5px)
Subtitle: 15px, color var(--t2), max-width 500px

3×2 grid (6 cards). Background between grid cells: var(--b1) (1px gap gives grid line effect).
Border 1px solid var(--b1), border-radius 10px, overflow hidden.
Each card: background var(--bg1), padding 28px 26px, hover background var(--bg2)

Cards (icon emoji + background color + title + desc):
  1. 🌌  rgba(79,142,255,0.1)   Andromeda Router      — "Central intelligence. Routes every task to the right agent based on skill confidence scoring. Human escalation below 0.80."
  2. ⚡  rgba(245,192,64,0.1)   Rigel Engineering     — "6-skill software engineering agent. Code generation, PR review, test writing, refactoring, scaffolding, and debug triage."
  3. 🔬  rgba(0,212,160,0.1)    Vega QA               — "3-stage quality pipeline. Analyzer → Test Designer → Bug Reporter. Every output validated before it leaves the system."
  4. 〜  rgba(56,168,255,0.1)   Aether Bus            — "Redis Streams backbone. Every task contract flows through Aether. Replay, audit, and trace any event in the system."
  5. ◎  rgba(157,126,255,0.1)  Pulsar Registry       — "Typed skill contracts. Every agent declares its capabilities. No ad-hoc passing — every boundary is explicit."
  6. 🔭  rgba(255,107,157,0.1)  Orion Learning        — "Phase 3 — the refinery. Reads every FeedbackEvent from Aether. Builds training datasets. Routes get smarter over time."

─── HOW IT WORKS ────────────────────────────────────────────────────

4-column horizontal grid (same gap/border trick as features grid):

  01  Client submits task     — "Any client POSTs a TaskContract to Andromeda. Natural language or structured JSON."          tag: "POST /task"
  02  Andromeda routes        — "Scores confidence per registered skill. Routes above 0.80. Escalates below threshold."       tag: "PulsarRegistry"
  03  Agent executes          — "Rigel or Vega receives the contract via Aether. Executes. Writes AgentResult to the stream."  tag: "AetherStream"
  04  Orion learns            — "FeedbackEvent emitted. Orion ingests the signal. System routing improves."                   tag: "Phase 3"

Step number: mono 11px color var(--t3). Step tag: mono 10px, padding 3px 8px, border 1px solid var(--b2), border-radius 4px, color var(--t3).

─── AGENTS GRID ─────────────────────────────────────────────────────

Two rows of 3 agent cards each.
Card: background var(--bg1), border 1px solid var(--b1), border-radius 10px, padding 22px
Hover: border-color var(--b2), translateY(-2px)

Each card has:
  Header row: agent name (mono font-weight 600 13px, colored dot glow) + status badge (right)
  Description: 12.5px color var(--t2) line-height 1.6
  Meta row: mono 11px color var(--t3)

Row 1:
  andromeda  color var(--blue)   badge "active" green    — "Central router and orchestrator. Scores all incoming tasks against registered skills."     meta: "threshold: 0.80 · port: 8000"
  rigel      color var(--yellow) badge "active" green    — "Software engineering specialist. 6 declared skills. Powered by claude-sonnet-4-6."         meta: "6 skills · claude-sonnet-4-6"
  vega       color var(--green)  badge "phase 2" yellow  — "Quality assurance pipeline. 3-stage execution: analyzer → test_designer → bug_reporter."   meta: "3 stages · pipeline"

Row 2:
  aether     color var(--teal)   badge "active" green    — "Redis Streams bus. All task contracts and feedback events flow through Aether."             meta: "redis streams · :6379"
  pulsar     color var(--purple) badge "active" green    — "Skill registry. All agents declare capabilities via typed SkillContracts."                  meta: "6 registered · typed contracts"
  orion      color var(--orion)  badge "phase 3" pink    — "The learning layer. Passive consumer on Aether. Reads FeedbackEvents, builds training datasets." meta: "building..." (color var(--t4))
  (orion card border: rgba(255,107,157,0.12))

─── QUICKSTART ──────────────────────────────────────────────────────

Two-column grid of terminal panels.

Panel 1 — "Install & run":
  $ git clone https://github.com/galaxz-ai/galaxz
  $ cd galaxz
  # start all services
  $ docker-compose up -d
    Starting redis_1   ... done
    Starting galaxz_1  ... done
  # boot the OS
  $ python boot.py
  ✓ All systems online. Andromeda on :8000

Panel 2 — "Route your first task":
  $ galaxz route --skill rigel.skill.code_generation \
      --input "implement OAuth2 flow"

  task_id:    26a5fc41-3ab4-4de5-aa35-2decf55dcc7a
  agent:      rigel
  confidence: 0.84
  status:     complete
  skill:      code_generation

  ✓ FeedbackEvent emitted → aether

Each panel: background var(--bg1), border 1px solid var(--b1), border-radius 10px
Header: "Install & run" / "Route your first task" + "Copy" button
Body: mono 12px, line-height 1.8, color var(--t2) for output, var(--green) for prompts, var(--t3) for comments

─── OSS PANEL ───────────────────────────────────────────────────────

Two-column panel (text left, big stat right):
  Background var(--bg1), border 1px solid var(--b1), border-radius 10px, padding 40px 44px

Left:
  H3: "Built in the open.\nForever."  (26px font-weight 700 letter-spacing -1px)
  Paragraph: "Galaxz is MIT licensed and will always be free to use, modify, and extend..."
  Badges row: "MIT License" · "self-hostable" · "no vendor lock-in" · "bring your own LLM"
    Each badge: mono 11px, padding 4px 10px, border 1px solid var(--b2), border-radius 4px, color var(--t3)

Right (text-align center):
  "v0.1"  — mono 40px font-weight 700 letter-spacing -2px
  "First release" — 12px color var(--t3)

─── PRICING ─────────────────────────────────────────────────────────

3-column grid. Center card is "featured".

Card 1 — Open Source:
  Tier label: "OPEN SOURCE"
  Price: "$0" (mono 34px font-weight 700)
  Period: "forever · self-hosted"
  Features list (✓ green checkmarks):
    ✓ All agents (Andromeda, Rigel, Vega)
    ✓ Aether bus + Pulsar registry
    ✓ Bring your own LLM
    ✓ Full source code access
    ✓ Community support
  CTA: "Get the code" (outline btn, full width)

Card 2 — Cloud (FEATURED):
  Badge at top: "MOST POPULAR" — background var(--blue), white text, absolute positioned top-0 right-20px, border-radius 0 0 6px 6px
  Featured styling: border-color rgba(79,142,255,0.3), background linear-gradient(180deg, rgba(79,142,255,0.04) 0%, var(--bg1) 100%)
  Tier label: "CLOUD"
  Price: "$49" (mono 34px)
  Period: "per seat / month"
  Features:
    ✓ Everything in Open Source
    ✓ Managed hosting + uptime SLA
    ✓ Orion analytics (Phase 3)
    ✓ Team review queue
    ✓ Priority support
  CTA: "Start free trial" (primary btn, full width)

Card 3 — Enterprise:
  Tier: "ENTERPRISE"
  Price: "Custom"
  Period: "volume · on-premise · SLA"
  Features:
    ✓ Everything in Cloud
    ✓ On-premise deployment
    ✓ Custom agent certification
    ✓ JEDI Refinery managed service
    ✓ Dedicated support
  CTA: "Talk to us" (outline btn, full width)

─── FOOTER ──────────────────────────────────────────────────────────

3-column grid: brand info | 4 link columns | right branding
Border-top 1px solid var(--b1), padding 40px 32px, max-width 1100px margin auto

Brand (col 1):
  Logo (dot + "galaxz") + "The open AI agent operating system. Built to outlast any single company."

Link columns (col 2, span 4 cols inside):
  Product: Dashboard · Dev Console · Orion Analytics · Changelog
  Docs: Quickstart · Architecture · Agent API · Skill Contracts
  Open Source: GitHub · Contributing · Roadmap · MIT License
  Company: About · Blog · Pricing · Contact

Right (col 3):
  "GALAXZ" mono 11px letter-spacing 1px color var(--t3)
  "v0.1.0 · Phase 2 complete"
  "© 2025 Galaxz. MIT License."
```

---

---

# ── SCREEN 2 ────────────────────────────────────────────────────────────────
---

## PROMPT 2 — Dashboard
### `src/pages/Dashboard.tsx`

```
Build the Galaxz Dashboard page. This is the operator control center — the main screen after login.
Uses the shared sidebar from PROMPT 0. App shell layout: sidebar left (216px) + main content right.

─── LAYOUT ──────────────────────────────────────────────────────────

Full viewport height, overflow hidden. Two-column flex:
  Left: <Sidebar> with "Dashboard" nav item active
  Right: flex column — topbar (48px) + scrollable content area

Topbar: "Dashboard" (title) + "— live system view" (subtitle) + right actions: Search button (⌘K) + notification bell with red dot badge

─── REVIEW PENDING BANNER ───────────────────────────────────────────

First element in content area (above all metrics). HIGH VISIBILITY.
Background rgba(245,192,64,0.06), border 1px solid rgba(245,192,64,0.18), border-radius 7px, padding 12px 16px.

Contents: ⚠ icon + text block + CTA button
  Title: "3 tasks pending human review" — color var(--yellow), font-weight 600, 12px
  Sub: "Confidence below 0.80 threshold · oldest SLA expires in 18 min" — color var(--t2), 11px
  Button: "Open Review Queue →" — background rgba(245,192,64,0.12), border rgba(245,192,64,0.2), color var(--yellow)

─── METRICS STRIP ───────────────────────────────────────────────────

4-column grid. Gap 10px. Each: background var(--bg1), border 1px solid var(--b1), border-radius 8px, padding 16px 18px.
Hover: border-color var(--b2).

  1. Tasks today:       "1,284"  color var(--t1)    delta: "↑ 18% vs yesterday" green
  2. Avg confidence:    "0.86"   color var(--green)  delta: "↑ above threshold" green
  3. Human escalations: "3"      color var(--yellow) delta: "2.3% escalation rate" var(--t3)
  4. Aether throughput: "2,840"  color var(--teal)   delta: "msgs / sec" var(--t3)

Metric value: mono 24px font-weight 700 letter-spacing -1px. Label: 11px var(--t3). Delta: 11px.

─── MAIN GRID ───────────────────────────────────────────────────────

Two-column grid: left column (1fr) + right column (340px fixed). Gap 12px.

LEFT COLUMN — 3 cards stacked:

CARD 1 — Task Throughput (bar chart):
  Card head: "Task Throughput" / "last 24h · hourly"
  Body: 24 bars representing hourly task counts over 24h
  Bars: flex row, align-items flex-end, height 80px, gap 3px
  Bar styling: border-radius 2px 2px 0 0, background rgba(79,142,255,0.18)
  Hover: background rgba(79,142,255,0.4)
  Peak bars (hours 8–11): background rgba(79,142,255,0.35) (slightly brighter)
  Bar heights (approximate percentages for visual realism):
    35,28,42,38,55,62,48,70,88,92,95,100,82,75,68,72,65,58,74,80,71,63,55,48
  X-axis labels below: "00:00" "06:00" "12:00" "18:00" "now" — mono 9px color var(--t4)

CARD 2 — Agent Health:
  Card head: "Agent Health" / "live · heartbeat"
  5 rows (one per agent). Each row: 8px height separator bars except last.
  Row padding: 9px 0, border-bottom 1px solid var(--b1)

  Row layout: [colored dot] [name] [status text] [spacer] [stat 1] [stat 2] [mini heartbeat bars]

  Data:
    andromeda  var(--blue)    "online" green  8,241 routed   12ms latency
    rigel      var(--yellow)  "online" green  218/hr tasks   0.86 avg conf
    vega       var(--green)   "online" green  342/hr tasks   0.91 avg conf
    aether     var(--teal)    "online" green  2,840/s thru   0ms lag
    orion      var(--t4)      "phase 3" t4    "—" not built  "—"

  Heartbeat bars: 6 tiny bars (3px wide, spacing 2px) at various heights showing signal.
    Each agent has current-color bars. Orion has all very low/flat bars in var(--t4).

  Dot: 7px circle with box-shadow glow matching agent color.
  Name: mono 12px font-weight 500, min-width 90px, colored per agent.
  Stat values: mono 11px color var(--t2). Stat labels: 10px color var(--t4).

CARD 3 — Live Task Feed:
  Card head: "Live Task Feed" / "real-time · aether stream"
  6 rows of recent tasks (most recent first):

  Row layout: [status dot] [skill ID] [agent] [confidence bar] [conf value] [status badge] [time ago]
  Row: display flex, align-items center, gap 10px, padding 8px 0, border-bottom 1px solid var(--b1)
  Hover: background rgba(255,255,255,0.015), negative margin ±16px to bleed to edges

  Data (skill · agent · conf · status · time):
    rigel.skill.code_generation  rigel  0.84  complete  2s
    vega.stage.test_designer     vega   0.72  review    8s
    rigel.skill.pr_review        rigel  0.91  complete  15s
    rigel.skill.refactor         rigel  0.88  complete  22s
    vega.stage.analyzer          vega   0.68  review    31s
    rigel.skill.test_writing     rigel  0.93  complete  44s

  Status dot: 6px circle. green = complete, yellow = review.
  Skill ID: mono 11px color var(--t2), min-width 180px.
  Confidence bar: 48px wide, 3px tall, fill color matches threshold.
  Badge: "complete" green tinted, "review" yellow tinted — mono 9px.
  Time: mono 10px color var(--t4).

RIGHT COLUMN — 3 cards stacked:

CARD A — System Health:
  Head: "System Health" / "all services"
  6 rows (one per named system):

  [colored dot glow] [system name colored] [description] [ping/latency right]

    andromeda  var(--blue)    "router · :8000"        12ms  green
    rigel      var(--yellow)  "eng agent · 6 skills"  38ms  green
    vega       var(--green)   "QA · 3 stages"         54ms  green
    aether     var(--teal)    "redis streams"          0ms   green
    pulsar     var(--purple)  "skill registry"         3ms   green
    orion      var(--t4)      "phase 3 · offline"      "—"   t4

CARD B — Event Timeline:
  Head: "Event Timeline" / "last 5 min"
  7 events, oldest at bottom:

  [time] [emoji dot] [event text with bold agent name]

    now       🟢  rigel completed code_generation · conf 0.84
    8s        🟡  vega test_designer escalated to review queue
    15s       🟢  rigel completed pr_review · conf 0.91
    31s       🟡  vega analyzer conf 0.68 → review queue
    1m 4s     💬  FeedbackEvent emitted → aether stream
    2m 12s    🟢  rigel completed debug_triage · conf 0.89
    3m 40s    ⚙️  andromeda rerouted task · skill match updated

  Time: mono 10px color var(--t4), min-width 50px.
  Text: 11px color var(--t2). Bold agent names: color var(--t1).

CARD C — Orion Refinery (empty state):
  Head: "Orion Refinery" (color rgba(255,107,157,0.6)) / "phase 3" (color rgba(255,107,157,0.4))
  Empty state centered: 🔭 icon (28px) + "Orion is building" title + description text
  Badge: "phase 3 · not built" — mono 10px, background rgba(255,107,157,0.08), border rgba(255,107,157,0.18), color var(--orion) at 70% opacity
```

---

---

# ── SCREEN 3 ────────────────────────────────────────────────────────────────
---

## PROMPT 3 — Dev Console
### `src/pages/DevConsole.tsx`

```
Build the Galaxz Dev Console page. Engineer-facing. Split-panel layout.
Uses shared sidebar ("Dev Console" nav item active).

─── LAYOUT ──────────────────────────────────────────────────────────

Sidebar + main. Main = topbar + horizontal body split (list panel | detail panel).

Topbar: "Dev Console" + "— agent registry & manifests" + right actions: "+ New agent" btn + "Deploy" primary btn

─── LEFT PANEL — Agent List (264px wide) ────────────────────────────

Background var(--bg1), border-right 1px solid var(--b1). Full height.

Header: "Registered Agents" label (11px font-weight 600 color var(--t3) uppercase) + count "2" (mono 10px var(--t4))

Search input: background var(--bg2), border 1px solid var(--b1), border-radius 5px, padding 6px 10px
  Contains: search SVG icon (var(--t4)) + input placeholder "Search agents…"
  On focus: border-color var(--b2)

Agent list (scrollable):
  Two agents. Each item: padding 10px 10px, border-radius 6px, cursor pointer, margin-bottom 2px
  Default: transparent border. Hover: background rgba(255,255,255,0.03)
  Selected: background rgba(79,142,255,0.07), border 1px solid rgba(79,142,255,0.18)

  RIGEL (selected by default):
    Header: yellow dot (glow var(--yellow)) + "rigel" (mono 12.5px font-weight 500 var(--yellow)) + "v1.2.4" (mono 10px var(--t4))
    Meta: "Engineering Agent · 6 skills · 218/hr" (11px var(--t3), flex gap 8px)

  VEGA:
    Header: green dot (glow var(--green)) + "vega" (var(--green)) + "v1.4.2"
    Meta: "QA Agent · 3 stages · 342/hr"

─── RIGHT PANEL — Detail Panel (flex:1) ─────────────────────────────

DETAIL HEADER (for Rigel, shown by default):
  Padding 14px 22px, border-bottom 1px solid var(--b1)

  Title: "rigel" (18px font-weight 700 color var(--yellow)) + " Engineering Agent" (13px color var(--t3) normal weight, same line, margin-left 10px)

  Meta lines (mono 10.5px color var(--t3) line-height 1.7):
    "agent_id: rigel · registered in Pulsar · last heartbeat: 2s ago · boot.py → RigelAgent(registry)"
    "skills: code_generation, pr_review, test_writing, refactor, scaffold, debug_triage"

  Right actions: "View logs" btn + "Restart" btn + "Edit manifest" primary btn

TABS (below header):
  Four tabs: Manifest | Skills | LLM Config | Logs
  Tab bar: padding 0 22px, border-bottom 1px solid var(--b1), background var(--bg1)
  Each tab: padding 9px 14px, 12px, color var(--t3), border-bottom 2px solid transparent
  Active: color var(--t1), border-bottom-color var(--blue)
  Tabs are clickable and switch content panel

─── TAB: MANIFEST ───────────────────────────────────────────────────

Code block styled panel: background var(--bg2), border 1px solid var(--b1), border-radius 7px

Header: "core/contracts/skill_contract.py — rigel" (mono 10px var(--t3)) + "Copy" btn

Code body (mono 11.5px line-height 1.8, syntax highlighted):

  # Rigel SkillContract — registered in PulsarRegistry
  from core.contracts.skill_contract import SkillContract

  rigel_skills = [
    SkillContract(
      skill_id="rigel.skill.code_generation",
      agent_id="rigel",
      description="Generate production-ready code from a spec",
      input_schema={"spec": str, "language": str},
      output_schema={"code": str, "confidence": float},
      confidence_threshold=0.80,
      version="1.2.4",
    ),
    SkillContract(
      skill_id="rigel.skill.pr_review",
      agent_id="rigel",
      description="Review a pull request and produce structured feedback",
      input_schema={"diff": str, "context": str},
      output_schema={"review": str, "confidence": float},
      confidence_threshold=0.80,
      version="1.2.4",
    ),
    # ... test_writing, refactor, scaffold, debug_triage
  ]

Syntax colors:
  keywords (from, import, class): var(--purple) #9d7eff
  strings ("..."): var(--green) #00d4a0
  type names / identifiers: var(--blue) #4f8eff
  numbers/values (0.80, 1.2.4): var(--yellow) #f5c040
  comments (#): var(--t4)

─── TAB: SKILLS ─────────────────────────────────────────────────────

Table. Columns: Skill ID | Status | Success Rate | Avg Latency | Tasks (24h)

Headers: 10px color var(--t3) uppercase letter-spacing 0.5px, padding 8px 10px, border-bottom 1px solid var(--b1)
Rows: border-bottom 1px solid var(--b1), hover background rgba(255,255,255,0.02)

Data (6 rows):
  rigel.skill.code_generation  active (green dot)  84% bar  840ms  68
  rigel.skill.pr_review        active              91% bar  420ms  44
  rigel.skill.test_writing     active              88% bar  560ms  37
  rigel.skill.refactor         active              79% bar  720ms  29
  rigel.skill.scaffold         active              93% bar  380ms  22
  rigel.skill.debug_triage     active              82% bar  640ms  18

Skill ID: mono 11px color var(--t1)
Status: 6px green dot + "active" text 10px var(--green)
Success rate: 60px wide, 3px tall confidence bar (green fill)
Latency: mono 11px var(--t3)
Task count: mono 11px var(--t2)

─── TAB: LLM CONFIG ─────────────────────────────────────────────────

Info banner (top):
  Background rgba(79,142,255,0.05), border rgba(79,142,255,0.15), border-radius 6px, padding 10px 14px
  Text: "Global default: claude-sonnet-4-6 (Anthropic) — set in Settings → Models & Connections. Override per-skill below."
  "Global default:" is bold color var(--blue). Rest is 11px color var(--t2).

Section heading: "Per-Skill Model Overrides" — 11px uppercase letter-spacing 0.5px color var(--t3)

6 rows (one per skill). Each row:
  Background var(--bg2), border 1px solid var(--b1), border-radius 6px, padding 10px 14px, margin-bottom 6px
  Layout: left (skill name + desc) | right (model selector dropdown)

  Left:
    Skill name: mono 12px color var(--t1)
    Desc: 11px color var(--t3)
  Right:
    <select> element: background var(--bg3), border 1px solid var(--b2), border-radius 5px, color var(--t2), mono 11px, padding 4px 10px

  Rows:
    rigel.skill.code_generation  "Full code generation — needs highest capability"    selected: claude-sonnet-4-6
    rigel.skill.pr_review        "PR review — Sonnet quality sufficient"              selected: claude-sonnet-4-6
    rigel.skill.test_writing     "Test generation — Haiku fast enough"                selected: claude-haiku-4-5
    rigel.skill.refactor         "Refactoring — inheriting global default"            selected: ↑ global default
    rigel.skill.scaffold         "Scaffolding — inheriting global default"            selected: ↑ global default
    rigel.skill.debug_triage     "Debug — inheriting global default"                  selected: ↑ global default

  Dropdown options (same for all): claude-sonnet-4-6 | claude-opus-4-6 | claude-haiku-4-5 | gpt-4o | ollama/local | ↑ global default

─── TAB: LOGS ───────────────────────────────────────────────────────

Log viewer panel: background var(--bg2), border 1px solid var(--b1), border-radius 7px
Header: "rigel · live log output" (mono 10px var(--t3)) + "Clear" btn
Body: mono 11px line-height 2, max-height 260px, overflow-y auto

Exact log lines (timestamp · level · message):

  10:42:18.012  INFO   RigelAgent received task 26a5fc41 · skill: code_generation
  10:42:18.044  DEBUG  score_confidence() → component scores: [0.82, 0.86, 0.84]
  10:42:18.045  INFO   confidence: 0.84 · threshold: 0.80 · accept
  10:42:19.221  INFO   task_log written → aether stream · task_id: 26a5fc41
  10:42:19.222  INFO   FeedbackEvent emitted · Orion will ingest in Phase 3
  10:42:24.008  INFO   RigelAgent received task a3f2bc19 · skill: pr_review
  10:42:24.039  DEBUG  score_confidence() → component scores: [0.90, 0.91, 0.92]
  10:42:24.040  INFO   confidence: 0.91 · threshold: 0.80 · accept
  10:42:31.114  WARN   RigelAgent received task b9e1dc42 · skill: refactor
  10:42:31.148  DEBUG  score_confidence() → component scores: [0.72, 0.71, 0.74]
  10:42:31.149  WARN   confidence: 0.72 · below threshold 0.80 → human_review queue
  10:42:31.150  INFO   task_log written · escalation_path: human_review

Color coding:
  Timestamp: var(--t4). INFO level: var(--green). DEBUG: var(--blue). WARN: var(--yellow).
  Message text: var(--t2). Bold agent names: var(--t1). Skill names highlighted: var(--yellow).
```

---

---

# ── SCREEN 4 ────────────────────────────────────────────────────────────────
---

## PROMPT 4 — Task UI
### `src/pages/TaskUI.tsx`

```
Build the Galaxz Task UI page. This is where users submit tasks and see results.
Conversation-style layout. Uses shared sidebar ("Task UI" nav item active).

─── LAYOUT ──────────────────────────────────────────────────────────

Sidebar + main. Main = topbar + agent selector bar + chat area (scrollable, flex:1) + input bar (fixed bottom).

The sidebar on this screen also contains task history (see below).

─── SIDEBAR MODIFICATIONS ───────────────────────────────────────────

Below the standard nav sections, add a "RECENT TASKS" section with 4 task history items:

Each item: padding 8px 10px, border-radius 6px, cursor pointer, margin-bottom 2px
Selected state: background rgba(79,142,255,0.07)

  Skill name: mono 10.5px color var(--t2)
  Meta row: [colored dot 5px] + "status · confidence · agent · time ago" (10px color var(--t4))

Items:
  code_generation  complete(green)  0.84  rigel  2m ago    ← selected
  test_writing     complete(green)  0.91  rigel  8m ago
  vega.stage.analyzer  review(yellow)  0.68  vega  18m ago
  pr_review        complete(green)  0.88  rigel  34m ago

─── TOPBAR ──────────────────────────────────────────────────────────

"Task UI" + "— submit tasks · view routing trace · review results"
Right side: task ID display — mono 10px var(--t4): "task_id: 26a5fc41"

─── AGENT SELECTOR BAR ──────────────────────────────────────────────

Below topbar. Height auto. Padding 12px 20px. Border-bottom 1px solid var(--b1). Background var(--bg1).

Label: "Route via:" (11px var(--t3), margin-right 4px)

Three chip buttons:
  "Auto-route"           — active/selected state: background rgba(79,142,255,0.1) border rgba(79,142,255,0.3) color var(--blue)
  "Rigel (Engineering)"  — inactive but tinted: background rgba(245,192,64,0.07) border rgba(245,192,64,0.25) color var(--yellow)
  "Vega (QA)"            — inactive tinted: background rgba(0,212,160,0.07) border rgba(0,212,160,0.25) color var(--green)

Chip: padding 5px 12px, border-radius 20px, border 1px solid, font-size 11px, cursor pointer

─── CHAT AREA ───────────────────────────────────────────────────────

Scrollable flex:1. Padding 24px 24px 16px.

ELEMENT 1 — ROUTING TRACE CARD:
  Background var(--bg1), border 1px solid var(--b1), border-radius 8px, padding 14px 18px, margin-bottom 16px.
  Header: "routing trace · task 26a5fc41" (mono 11px var(--t3))

  6 nodes connected by lines (display flex, align-items center):
    client → andromeda → pulsar → aether → rigel → result

  Each node:
    Circle 32px × 32px, border 2px solid, border-radius 50%, flex column align-center
    All complete (green): background rgba(0,212,160,0.1) border var(--green) color var(--green) icon "✓"
    Rigel node: shows "R" instead of "✓"
    Label below: mono 9px var(--t3) (name)
    Time below: mono 9px var(--t4) (e.g. "+12ms")

  Connecting lines between nodes: flex:1 height 1px background var(--green) opacity 0.4, margin 0 6px, margin-bottom 20px (to vertically center with node top portion)

  Timing values:
    client: +0ms, andromeda: +12ms, pulsar: +15ms, aether: +16ms, rigel: +840ms, result: +856ms

ELEMENT 2 — USER TASK BUBBLE (right-aligned):
  Display flex, justify-content flex-end. Bubble max-width 540px.
  Background rgba(79,142,255,0.1), border 1px solid rgba(79,142,255,0.2)
  Border-radius: 8px 8px 2px 8px (sharp bottom-right corner)
  Padding 12px 16px

  Text (13px line-height 1.6): "Generate an OAuth2 authorization flow for a Python FastAPI backend. Include both the authorization endpoint and the token exchange endpoint. Handle refresh tokens."

  Meta row below text (10px var(--t3), flex gap 8px):
    "skill: rigel.skill.code_generation · auto-routed to rigel · 10:42 AM"

ELEMENT 3 — AGENT RESULT BUBBLE (left-aligned):
  Display flex, gap 10px.
  Avatar: 28px circle, background rgba(245,192,64,0.1), border rgba(245,192,64,0.25), contains "R", flex-shrink 0, margin-top 2px.
  Agent name above bubble: mono 10px var(--yellow): "rigel · code_generation · v1.2.4"

  Result card: background var(--bg1), border 1px solid var(--b1), border-radius 2px 8px 8px 8px (sharp top-left)
  Padding 14px 16px.

  Section A — CONFIDENCE BAR:
    Display flex, align-items center, gap 10px
    Padding-bottom 12px, margin-bottom 12px, border-bottom 1px solid var(--b1)

    Label: "confidence" (11px var(--t3), min-width 60px)
    Track: flex:1, height 5px, border-radius 3px, background var(--bg3), position relative
      Fill: 84% width, background var(--green)
      Threshold marker: absolute at left 80%, width 1px, height 11px, top -3px, background rgba(245,192,64,0.6)
    Value: "0.84" mono 12px font-weight 600 var(--green)
    Action buttons (margin-left auto, flex gap 7px):
      "✓ Accept" — btn-accept style
      "✗ Reject" — btn-reject style

  Section B — CODE OUTPUT:
    Background var(--bg2), border-radius 5px, padding 12px 14px, mono 11px line-height 1.8, margin-bottom 10px

    Exact code (syntax highlighted same colors as Dev Console):
      # OAuth2 Authorization Flow — FastAPI
      from fastapi import FastAPI, HTTPException, Depends
      from fastapi.security import OAuth2PasswordBearer
      from jose import JWTError, jwt

      app = FastAPI()
      oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

      @app.post("/authorize")
      async def authorize(response_type: str, client_id: str):
        # Generate authorization code ...
        return {"code": generate_auth_code(client_id)}

      @app.post("/token")
      async def token_exchange(code: str, client_secret: str):
        # Exchange code for access + refresh tokens ...
        return {"access_token": at, "refresh_token": rt, "expires_in": 3600}

  Section C — EXPLANATION TEXT:
    "Generated full OAuth2 flow with PKCE support. Authorization endpoint returns auth code, token endpoint handles exchange and issues JWT access + refresh token pair. Refresh token rotation included. Confidence 0.84 — implementation is complete but integration tests recommended."
    11px color var(--t2) line-height 1.7, margin-bottom 10px

  Section D — ORION NOTICE:
    Display flex, align-items center, gap 8px
    Padding 7px 12px, background rgba(255,107,157,0.04), border 1px solid rgba(255,107,157,0.1), border-radius 5px
    5px dot (background rgba(255,107,157,0.4)) + text:
    "FeedbackEvent emitted → aether · Orion will ingest in Phase 3 · task_id: 26a5fc41-3ab4-4de5-aa35-2decf55dcc7a"
    10.5px color var(--t3)

─── INPUT BAR (FIXED BOTTOM) ────────────────────────────────────────

Border-top 1px solid var(--b1), padding 14px 20px, background var(--bg1), flex-shrink 0.

Input wrap: background var(--bg2), border 1px solid var(--b1), border-radius 8px
  On focus-within: border-color var(--b2)

  Textarea (rows 2): padding 12px 14px, background transparent, no border/outline
    Placeholder: "Describe what you need. Galaxz will route to the right agent automatically."
    Placeholder color: var(--t4). Caret: var(--blue).

  Footer row inside wrap: padding 8px 12px, border-top 1px solid var(--b1), flex align-items-center
    Left buttons (flex gap 6px):
      "📎 Attach" — ghost micro btn with paperclip SVG
      "⟨⟩ Import spec" — ghost micro btn with code SVG
      "⋯ Options" — ghost micro btn with info SVG
      Each: padding 4px 9px, border-radius 4px, border 1px solid var(--b1), font-size 10px, gap 4px

    Right side:
      "Auto-route active" — 10px var(--t4), margin-right 8px
      Send button: "Send" + arrow SVG, background var(--blue), color white, padding 6px 14px, border-radius 5px
        Hover: background #3d7aff
```

---

---

# ── SCREEN 5 ────────────────────────────────────────────────────────────────
---

## PROMPT 5 — Review Queue
### `src/pages/ReviewQueue.tsx`

```
Build the Galaxz Human Review Queue. Operators review tasks that Andromeda escalated below confidence 0.80.
Split-panel layout. Uses shared sidebar ("Review Queue" nav item active, badge "3").

─── LAYOUT ──────────────────────────────────────────────────────────

Sidebar + main. Main = topbar + SLA warning banner + horizontal body split.
Left panel: 296px queue list. Right panel: flex:1 detail.

Topbar: "Review Queue" + "— tasks below confidence threshold · human review required"
Right: "Mark all reviewed" ghost btn

─── SLA WARNING BANNER ──────────────────────────────────────────────

Below topbar. Margin 14px 20px 0.
Background rgba(255,77,106,0.06), border rgba(255,77,106,0.2), border-radius 6px, padding 9px 14px.
⚠ icon + text: "Oldest task SLA expires in 18 minutes. Review and release or reject before deadline."
"Oldest task SLA expires in 18 minutes." in bold color var(--red).
Dismiss × button right-aligned (color var(--t4), removes banner on click).

─── LEFT PANEL — Queue List ─────────────────────────────────────────

Header: "Pending Review" (11px uppercase color var(--t3)) + count badge "3 tasks" (red tinted)

3 queue items. Each:
  Background transparent, border 1px solid transparent, border-radius 7px, padding 10px 12px, cursor pointer
  Hover: background rgba(255,255,255,0.03)
  Selected: background rgba(245,192,64,0.06) + border rgba(245,192,64,0.2)

  Top row: skill ID (mono 11px var(--t2)) + SLA chip (right, mono 9px, colored)
  Confidence row: flex bar (fill color var(--yellow)) + value (mono 10px var(--yellow))
  Meta row: "agent · task ID · time ago" (10px var(--t4))

  SLA chip colors:
    "18 min SLA" → background rgba(255,77,106,0.12) color var(--red)      [URGENT]
    "42 min SLA" → background rgba(245,192,64,0.1) color var(--yellow)    [WARN]
    "1h 10m SLA" → background rgba(0,212,160,0.08) color var(--green)     [OK]

Items:
  1. vega.stage.test_designer  conf 0.72  vega  task b9e1dc42  8m ago    SLA: "18 min" URGENT  ← selected
  2. rigel.skill.refactor      conf 0.68  rigel task a1c3fe91  18m ago   SLA: "42 min" WARN
  3. vega.stage.analyzer       conf 0.61  vega  task f4d2aa03  31m ago   SLA: "1h 10m" OK

─── RIGHT PANEL — Detail ────────────────────────────────────────────

DETAIL HEADER (Rigel selected, show task vega.stage.test_designer):
  Padding 14px 22px, border-bottom 1px solid var(--b1)

  Title row:
    "vega.stage.test_designer" (15px font-weight 700 letter-spacing -0.3px)
    + SLA chip inline: "SLA: 18 min" in red styling

  Meta (mono 10px var(--t3) line-height 1.8):
    "task_id: b9e1dc42 · agent: vega · stage: test_designer · escalated: 8m ago"
    "skill_contract: vega.skill.test_design · threshold: 0.80 · result: 0.72 → below threshold"

  Right actions (3 buttons):
    "✓ Accept & release"  — btn-accept (green tinted)
    "↺ Re-run"            — btn-rerun (blue tinted)
    "✎ Edit output"       — ghost btn

CONTENT (scrollable):

  BLOCK 1 — Confidence Breakdown card:
    Head: "CONFIDENCE BREAKDOWN" (11px uppercase var(--t3))
    3 factor rows:
      Coverage completeness    0.65  yellow bar at 65%
      Edge case detection      0.74  yellow bar at 74%
      Test assertion quality   0.78  yellow bar at 78%

    Each row: factor label (11px var(--t2) min-width 120px) + track (flex:1 4px height) + value (mono 11px var(--yellow))

    Overall row (below border-top):
      Left: "Overall confidence (weighted avg)" (11px var(--t2))
      Right: "0.72" (mono 14px font-weight 600 var(--yellow)) + " below 0.80 threshold" (11px var(--t3))

  BLOCK 2 — Why Vega Was Uncertain:
    Background rgba(245,192,64,0.04), border rgba(245,192,64,0.14), border-radius 7px, padding 12px 16px
    Title: "Why Vega was uncertain" — 11px font-weight 600 var(--yellow)
    Text (12px var(--t2) line-height 1.7):
      "Vega's test_designer stage identified 3 edge cases in the OAuth2 flow but could not determine with confidence whether all token expiry paths are covered. The test suite covers the happy path and basic error cases, but the refresh token rotation path has low coverage confidence. Reviewer should confirm whether token revocation on rotation is a requirement."

  BLOCK 3 — Flagged Test Cases:
    Card with header: "FLAGGED TEST CASES" + "3 flagged" (mono 10px var(--t4))
    3 flag items, each: padding 10px 16px, border-bottom 1px solid var(--b1), flex gap 10px

    Items:
      🟡  test_refresh_token_rotation_revokes_old_token
          "Token revocation not explicitly tested — may be requirement dependent"

      🟡  test_expired_access_token_returns_401
          "Clock-based test — may be flaky depending on execution environment"

      🔴  test_concurrent_refresh_token_use
          "Race condition scenario — Vega could not generate a reliable test for concurrent token use"

    Case name: mono 11px var(--t1). Reason: 11px var(--t3).
    🔴 = red flag (most severe), 🟡 = yellow flag (moderate)

  BLOCK 4 — Reviewer Notes:
    Card: header "REVIEWER NOTES" + textarea (3 rows, full width, transparent background, no border)
    Placeholder: "Add notes for this review. Your decision and notes will be sent to Orion as training signal…"
    Footer row inside card: "Your decision and notes will be included in the FeedbackEvent emitted to Orion (Phase 3)"
    Footer: 10.5px var(--t4), flex with small pink dot (5px, rgba(255,107,157,0.4)) prefix
```

---

---

# ── SCREEN 6 ────────────────────────────────────────────────────────────────
---

## PROMPT 6 — Settings
### `src/pages/Settings.tsx`

```
Build the Galaxz Settings page. Functional form UI.
Uses shared sidebar ("Settings" nav item active).

─── LAYOUT ──────────────────────────────────────────────────────────

Sidebar + main. Main = topbar ("Settings") + settings body.
Settings body: horizontal split — settings nav (200px left) + content area (flex:1 right).
Bottom of content: sticky save bar.

─── SETTINGS NAV (200px left) ───────────────────────────────────────

Nav items (clickable, switch content panel):
  Models & Connections  ← active by default
  Budget & Limits
  General
  ── Team (section label, mono 9px uppercase var(--t4)) ──
  Members
  API Keys
  ── Billing ──
  Plan & Usage

Nav item: padding 7px 10px, border-radius 5px, font-size 12.5px, color var(--t3)
Active: background rgba(79,142,255,0.08) color var(--blue)
Hover: background rgba(255,255,255,0.03) color var(--t2)

─── PANEL: MODELS & CONNECTIONS (default) ───────────────────────────

Title: "Models & Connections" (18px font-weight 700 letter-spacing -0.5px)
Subtitle: "Global LLM defaults used by all agents. Agents can override per-skill in Dev Console → LLM Config."

SECTION 1 — Default LLM Provider:
  Label: "DEFAULT LLM PROVIDER" (form section header style: 12px uppercase font-weight 600 color var(--t2) border-bottom)

  6 provider cards in 3-column grid. Each: background var(--bg2), border 1px solid var(--b1), border-radius 7px, padding 14px 16px, cursor pointer
  Active card: border rgba(79,142,255,0.35) background rgba(79,142,255,0.05)
  Active card has a checkmark badge: 14px circle, background var(--blue), white ✓, absolute top-right

  Cards:
    Anthropic (ACTIVE)    — "claude-sonnet-4-6, opus-4-6, haiku-4-5"
    OpenAI                — "gpt-4o, gpt-4o-mini, o3"
    Google Vertex         — "gemini-2.0-flash, pro, ultra"
    Mistral               — "mistral-large, medium, 8x7b"
    Ollama / Local        — "llama3, mistral, custom"
    Custom Endpoint       — "OpenAI-compatible API"

  Name: 12.5px font-weight 600. Models: 10.5px var(--t3).
  Clicking a card deselects others and selects the clicked one (JS).

SECTION 2 — Anthropic Configuration:
  2-column grid:
    API Key field (required *): type password, value "sk-ant-api03-••••••••••••••••••••••••", placeholder "sk-ant-api03-…"
      Hint: "Stored encrypted. Used as default by all agents unless overridden."
    Default Model select: options: claude-sonnet-4-6 (selected), claude-opus-4-6, claude-haiku-4-5
      Hint: "Per-agent overrides configured in Dev Console → Agent → LLM Config"

  2-column grid:
    API Base URL: value "https://api.anthropic.com"
    API Version: value "2023-06-01"

  Field label: 11px var(--t3), margin-bottom 6px
  Input: background var(--bg2), border 1px solid var(--b1), border-radius 6px, padding 8px 12px, 12px font
  Input focus: border-color var(--b2)
  Hint text: 10.5px var(--t4) margin-top 5px line-height 1.5

SECTION 3 — Connection Health (toggle rows):
  3 toggles in a vertical list. Each: flex space-between, padding 10px 0, border-bottom 1px solid var(--b1)

  Left side: label (12.5px font-weight 500) + description (11px var(--t3))
  Right side: toggle switch (36×20px pill)
    Toggle off: background var(--bg3), border var(--b2)
    Toggle on: background var(--blue), border var(--blue)
    Thumb: 14×14px white circle, left 2px (off) or left 18px (on), transition 0.2s
    Clicking toggles on/off

  Toggles:
    "Test connection on boot"         — on   — "Andromeda pings the configured LLM provider during python boot.py startup"
    "Fallback to secondary provider"  — off  — "If primary provider is unavailable, fall back to configured secondary"
    "Log all LLM calls to Aether"     — on   — "Emit LLMCallEvent to aether stream for every model invocation. Required for Orion."

─── PANEL: BUDGET & LIMITS ──────────────────────────────────────────

Title: "Budget & Limits"
Subtitle: "Set daily token budgets and cost caps. When limits are hit, choose what Galaxz does — queue, reject, or fall back to a cheaper model."

SECTION 1 — Daily Limits (3-column grid of budget cells):
  Each cell: background var(--bg2), border 1px solid var(--b1), border-radius 6px, padding 12px 14px

  Label (10.5px var(--t3))
  Value input: no border, border-bottom 1px solid var(--b2), 16px mono font-weight 600 var(--t1), full width, padding-bottom 6px
  Unit text: 10px var(--t3)

  Cells:
    Daily token budget  |  input: "2,000,000"  |  unit: "tokens / day across all agents"
    Daily cost cap      |  input: "$50.00"      |  unit: "USD / day — estimated"
    Concurrent limit    |  input: "24"           |  unit: "max parallel tasks"

SECTION 2 — Action Policy:
  Header: "ACTION POLICY — WHEN LIMITS ARE HIT"
  3 rows. Each: flex, padding 8px 0, border-bottom 1px solid var(--b1)
    Event text (flex:1, 12px) + <select> (right, background var(--bg2) border var(--b1) mono 11px)

  Rows:
    Daily token budget exceeded  →  Queue tasks (selected) / Reject with error / Fall back to Haiku
    Daily cost cap reached       →  Reject with error (selected) / Queue tasks / Fall back to Haiku
    Concurrent limit hit         →  Queue tasks (selected) / Reject with 429

SECTION 3 — Alerts (2 toggles):
  "Alert at 80% of daily budget"  — on   — "Notify via dashboard notification when daily token use reaches 80%"
  "Emit budget events to Aether"  — on   — "BudgetEvent emitted when thresholds are crossed. Orion can learn from budget constraints."

─── PANEL: GENERAL ──────────────────────────────────────────────────

Title: "General". Two 2-column rows:
  Row 1: Workspace name (value "Galaxz Dev") + Default confidence threshold (value "0.80", hint about per-SkillContract override)
  Row 2: Log level (select: INFO, DEBUG selected, WARN, ERROR) + Timezone (select: UTC selected)

─── OTHER PANELS ────────────────────────────────────────────────────

Members, API Keys, Plan & Usage: render just the title + a short subtitle. These are nav-reachable but content is minimal.

─── SAVE BAR (bottom, sticky) ────────────────────────────────────────

Border-top 1px solid var(--b1), padding 12px 36px, background var(--bg1), flex space-between
Left: "Changes are saved per workspace · agents will hot-reload updated config" (11px var(--t4))
Right: "Cancel" ghost btn + "Save changes" primary btn
```

---

---

# ── SCREEN 7 ────────────────────────────────────────────────────────────────
---

## PROMPT 7 — Orion Analytics
### `src/pages/OrionAnalytics.tsx`

```
Build the Galaxz Orion Analytics page. Phase 3 — Orion is not yet built.
Honest empty states where data doesn't exist. Uses shared sidebar ("Orion Analytics" active, color var(--orion) #ff6b9d not var(--blue)).

─── LAYOUT ──────────────────────────────────────────────────────────

Sidebar + main. Main = topbar + scrollable content.

Topbar: "Orion Analytics" + "— learning layer · feedback refinery · Phase 3"
Right: "Export events" ghost btn + "Run training" orion-tinted btn (disabled, opacity 0.5, cursor not-allowed)
  "Run training" style: background rgba(255,107,157,0.08) border rgba(255,107,157,0.2) color var(--orion)

─── PHASE 3 BANNER ──────────────────────────────────────────────────

Background rgba(255,107,157,0.05), border 1px solid rgba(255,107,157,0.14), border-radius 8px, padding 12px 18px.
Flex, items-center, gap 14px.

🔭 icon (20px, flex-shrink 0)
Text block:
  Title: "Orion is Phase 3 — currently building" (13px font-weight 600 var(--orion))
  Sub: "OrionService is not yet deployed. Aether is already emitting FeedbackEvents from every task — Orion will consume them once online. Drift monitor is active via Aether stream reading." (12px var(--t3) line-height 1.6)
Right badge: "phase 3 · not built" — mono 10px, background rgba(255,107,157,0.1), border rgba(255,107,157,0.2), color var(--orion), margin-left auto, white-space nowrap

─── METRICS STRIP ───────────────────────────────────────────────────

4-column grid. Margin-top 16px. Same card style as dashboard metrics.

  FeedbackEvents in Aether:  "1,284"  color var(--orion)  delta: "↑ queued for Orion" green
  OrionService training runs: "0"     color var(--t4)      delta: "awaiting Phase 3" color var(--orion)
  Routing improvement:        "—"     color var(--t4)      delta: "no baseline yet" var(--orion)
  Drift alerts (7d window):   "0"     color var(--green)   delta: "clean · drift monitor active" green

─── MAIN CONTENT ROWS ───────────────────────────────────────────────

ROW 1 (2-column grid):

CARD A — Feedback Event Volume (span 1 col, orion-colored border):
  Card border: rgba(255,107,157,0.12)
  Head: "Feedback Event Volume" (color rgba(255,107,157,0.7)) / "daily · last 30d · live from aether"

  Trend nums row:
    Total events: "1,284" (mono 18px font-weight 700 var(--orion))
    Per day avg: "43" (mono 18px var(--t2))
    Human-verified: "18.4%" (mono 18px var(--green))
    Labels: 10px var(--t3)

  Bar chart (24 bars, height 80px):
    Bars color: rgba(255,107,157,0.14) default, rgba(255,107,157,0.35) on hover, rgba(255,107,157,0.28) for peak bars
    Bar heights (% from left to right, showing growth trend):
      20,25,18,32,28,40,35,52,65,72,78,88,80,75,68,82,70,64,76,90,84,78,68,100
    X-axis labels: "Apr 1" "Apr 8" "Apr 15" "today" (mono 9px var(--t4))

CARD B — Training Runs (empty state):
  Same orion border style
  Empty state centered:
    🏋️ icon (32px, opacity 0.5)
    "No training runs yet" (13px font-weight 600 var(--t2))
    "Orion hasn't run any training cycles. Once OrionService is deployed in Phase 3, it will begin building routing heuristics from the 1,284 events already in Aether."
    Badge: "orionservice · phase 3"

ROW 2 (3-column grid):

CARD C — Drift Monitor:
  Head: "Drift Monitor" / "active · 7d window" (color var(--green))

  3 rows (one per agent):
    Row: [agent name colored mono 11px] [progress bar flex:1 4px green fill] [σ value mono 11px] [status badge]

    rigel     var(--yellow)  22% fill  σ 0.03  "clean" green badge
    vega      var(--green)   35% fill  σ 0.05  "clean" green badge
    andromeda var(--blue)    8% fill   σ 0.01  "clean" green badge

    Status badge colors:
      "clean" → background rgba(0,212,160,0.08) color var(--green)
      "drift" → background rgba(245,192,64,0.08) color var(--yellow) (none currently)

  Footer note: "Drift monitor reads confidence scores from Aether stream. No OrionService required for monitoring — only for training."
  11px var(--t4), line-height 1.6, margin-top 10px

CARD D — Dataset Breakdown (empty state):
  Empty state (compact, padding 22px 16px):
    📊 icon + "No dataset yet" title
    "OrionService builds structured training datasets from FeedbackEvents. Starts in Phase 3."
    Badge: "phase 3"

CARD E — Aether Stream Status:
  Head: "Aether Stream Status" / "live" (color var(--teal))

  5 rows. Each: [colored dot 6px] [key label 12px min-width 120px] [value mono 11px var(--t2) right]

    Stream            green dot    "galaxz-tasks · active" (var(--green))
    Consumer group    green dot    "orion (0 members)"
    Pending events    yellow dot   "1,284" (var(--yellow))
    Last event        teal dot     "4s ago"
    OrionService      t4 dot       "offline · phase 3" (var(--t4))

  Footer note below last row:
    "All 1,284 FeedbackEvents are retained in Aether. Orion will consume from position 0 when deployed."
    10.5px var(--t4) line-height 1.6 margin-top 10px

ROW 3 — Agent Performance (full-width card):

Head: "Agent Performance — from Feedback Events" / "current data from aether · routing improvements pending orion training"

3-column inner grid (background var(--b1) as gap, each cell background var(--bg1)):
  One cell per agent. Each cell: padding 16px 20px

  RIGEL (var(--yellow)):
    "rigel" (mono 11px var(--yellow))
    Avg confidence (current): "0.86" (mono 20px font-weight 700 var(--t1))
    Tasks this period: "218" (mono 14px var(--t2))
    Note: "Routing improvement will be calculated after first Orion training run." (10.5px var(--t4))

  VEGA (var(--green)):
    "vega" (mono 11px var(--green))
    Avg confidence: "0.91"
    Tasks: "342"
    Note: "Stage-level breakdown will be available after Orion processes the event stream."

  ANDROMEDA (var(--blue)):
    "andromeda" (mono 11px var(--blue))
    Routing decisions: "8,241"
    Escalation rate: "2.3%"
    Note: "Routing heuristics improve as Orion refines the confidence model from feedback data."
```

---

---

# ── IMPLEMENTATION NOTES ─────────────────────────────────────────────────────

```
General rules for Claude Code when implementing these screens:

1. STACK
   Use React + TypeScript + Tailwind CSS (or CSS modules with the token file).
   If Tailwind, extend the theme with the exact token values above.
   If plain CSS, import tokens.css on every page.

2. FONTS
   Add to index.html or layout: https://fonts.googleapis.com/css2?family=Geist+Mono:wght@300;400;500;600&family=Geist:wght@300;400;500;600;700
   Never substitute Inter, Roboto, or system-ui for body text. Geist only.

3. SIDEBAR
   Import <Sidebar> from PROMPT 0. Pass `activePage` prop to highlight the correct nav item.
   The sidebar is identical across all 6 app screens (screens 2–7). Landing page has no sidebar.

4. CONSISTENCY
   System colors are FIXED — never use var(--blue) for Rigel, never var(--yellow) for Andromeda.
   Agent → color mapping: andromeda=blue, rigel=yellow, vega=green, aether=teal, pulsar=purple, orion=pink(#ff6b9d)

5. REAL DATA ONLY
   Use the exact task IDs, skill names, confidence scores, and timestamps shown in the prompts.
   No lorem ipsum. No placeholder agent names. No made-up confidence values.
   If a value is "not yet built" (Orion), show the honest empty state — don't fabricate training run data.

6. INTERACTIVE ELEMENTS
   Dev Console: tabs must switch panels (Manifest / Skills / LLM Config / Logs)
   Settings: settings nav must switch content panels; provider cards must toggle selection; toggles must flip on click
   Review Queue: queue items must switch detail panel on click
   Task UI: agent selector chips must show active state on click
   All: hover states on cards, rows, buttons must work

7. FILE STRUCTURE (suggested)
   src/
     styles/tokens.css
     components/
       Sidebar.tsx
       Card.tsx
       ConfidenceBar.tsx
       Badge.tsx
       Toggle.tsx
     pages/
       Landing.tsx     ← PROMPT 1
       Dashboard.tsx   ← PROMPT 2
       DevConsole.tsx  ← PROMPT 3
       TaskUI.tsx      ← PROMPT 4
       ReviewQueue.tsx ← PROMPT 5
       Settings.tsx    ← PROMPT 6
       Orion.tsx       ← PROMPT 7

8. DO NOT
   - Add features not described in the prompt
   - Change colors from the token values
   - Use gradients decoratively (only the hero title gradient is intentional)
   - Use lorem ipsum anywhere
   - Add modals, drawers, or overlays not described
   - Fabricate Orion training data (it doesn't exist yet — show the honest empty state)
```
