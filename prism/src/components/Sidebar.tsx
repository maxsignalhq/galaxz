import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../styles/tokens.css';

const NAV_ROUTES: Partial<Record<string, string>> = {
  dashboard:    '/dashboard',
  'task-queue': '/dashboard',
  'dev-console':'/dev-console',
  'task-ui':    '/task-ui',
  'review-queue':'/review-queue',
  orion:        '/orion',
  settings:     '/settings',
  docs:         '/',
};

/* ── Types ─────────────────────────────────────────────────── */

type NavId =
  | 'dashboard'
  | 'task-queue'
  | 'dev-console'
  | 'task-ui'
  | 'review-queue'
  | 'orion'
  | 'settings'
  | 'docs';

interface NavItem {
  id: NavId;
  label: string;
  icon: React.ReactNode;
  badge?: string | number;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

/* ── Icons ─────────────────────────────────────────────────── */

const IconGrid = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <rect x="1" y="1" width="4.5" height="4.5" rx="1" fill="currentColor" />
    <rect x="7.5" y="1" width="4.5" height="4.5" rx="1" fill="currentColor" />
    <rect x="1" y="7.5" width="4.5" height="4.5" rx="1" fill="currentColor" />
    <rect x="7.5" y="7.5" width="4.5" height="4.5" rx="1" fill="currentColor" />
  </svg>
);

const IconList = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <rect x="1" y="2" width="11" height="1.5" rx="0.75" fill="currentColor" />
    <rect x="1" y="5.75" width="11" height="1.5" rx="0.75" fill="currentColor" />
    <rect x="1" y="9.5" width="8" height="1.5" rx="0.75" fill="currentColor" />
  </svg>
);

const IconCode = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <path d="M4.5 4L1.5 6.5L4.5 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M8.5 4L11.5 6.5L8.5 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7.5 2.5L5.5 10.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

const IconChat = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <path d="M1.5 2.5C1.5 1.95 1.95 1.5 2.5 1.5H10.5C11.05 1.5 11.5 1.95 11.5 2.5V8C11.5 8.55 11.05 9 10.5 9H5L2.5 11V9H2.5C1.95 9 1.5 8.55 1.5 8V2.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
  </svg>
);

const IconUsers = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <circle cx="5" cy="4.5" r="2" stroke="currentColor" strokeWidth="1.3" />
    <path d="M1 11C1 9.07 2.79 7.5 5 7.5C7.21 7.5 9 9.07 9 11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="10" cy="4.5" r="1.5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M12 10.5C12 9.12 11.1 8 10 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

const IconActivity = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <polyline points="1,7 3.5,7 5,3.5 7,10.5 9,5 10.5,7 12,7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
);

const IconSignal = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <circle cx="6.5" cy="6.5" r="1.5" fill="currentColor" />
    <path d="M3.5 3.5C2.22 4.78 2.22 8.22 3.5 9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none" />
    <path d="M9.5 3.5C10.78 4.78 10.78 8.22 9.5 9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" fill="none" />
    <path d="M2 2C0.09 3.91 0.09 9.09 2 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" />
    <path d="M11 2C12.91 3.91 12.91 9.09 11 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" />
  </svg>
);

const IconFile = () => (
  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
    <path d="M3 1.5H7.5L10.5 4.5V11.5H3V1.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    <path d="M7.5 1.5V4.5H10.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    <line x1="5" y1="7" x2="8.5" y2="7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    <line x1="5" y1="9" x2="7.5" y2="9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

/* ── Nav data ──────────────────────────────────────────────── */

const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Platform',
    items: [
      { id: 'dashboard',    label: 'Dashboard',    icon: <IconGrid /> },
      { id: 'task-queue',   label: 'Task Queue',   icon: <IconList />, badge: 3 },
    ],
  },
  {
    label: 'Developer',
    items: [
      { id: 'dev-console',  label: 'Dev Console',  icon: <IconCode /> },
      { id: 'task-ui',      label: 'Task UI',      icon: <IconChat /> },
      { id: 'review-queue', label: 'Review Queue', icon: <IconUsers />, badge: 3 },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { id: 'orion',        label: 'Orion Analytics', icon: <IconActivity /> },
    ],
  },
  {
    label: 'System',
    items: [
      { id: 'settings',     label: 'Settings',     icon: <IconSignal /> },
      { id: 'docs',         label: 'Docs',         icon: <IconFile /> },
    ],
  },
];

/* ── Sidebar ───────────────────────────────────────────────── */

interface SidebarProps {
  activeId?: NavId;
  onNavigate?: (id: NavId) => void;
  extraNav?: React.ReactNode;
}

export function Sidebar({ activeId = 'dashboard', onNavigate, extraNav }: SidebarProps) {
  const [active, setActive] = useState<NavId>(activeId);
  const navigate = useNavigate();

  function handleNav(id: NavId) {
    setActive(id);
    onNavigate?.(id);
    const route = NAV_ROUTES[id];
    if (route) navigate(route);
  }

  return (
    <aside style={styles.sidebar}>
      {/* Logo row */}
      <div style={styles.logoRow}>
        <span style={styles.liveDot} />
        <span style={styles.logoText}>galaxz</span>
      </div>

      <div style={styles.divider} />

      {/* Nav sections */}
      <nav style={styles.nav}>
        {NAV_SECTIONS.map((section) => (
          <div key={section.label} style={styles.section}>
            <span style={styles.sectionLabel}>{section.label.toUpperCase()}</span>
            {section.items.map((item) => {
              const isActive = active === item.id;
              const activeColor = item.id === 'orion' ? '#ff6b9d' : '#4f8eff';
              const activeBg    = item.id === 'orion' ? 'rgba(255,107,157,0.1)' : 'rgba(79,142,255,0.1)';
              return (
                <button
                  key={item.id}
                  style={{
                    ...styles.navItem,
                    ...(isActive ? { background: activeBg, color: activeColor } : {}),
                  }}
                  onClick={() => handleNav(item.id)}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)';
                      (e.currentTarget as HTMLElement).style.color = '#edf0fa';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      (e.currentTarget as HTMLElement).style.background = 'transparent';
                      (e.currentTarget as HTMLElement).style.color = '#8a94b0';
                    }
                  }}
                >
                  <span style={{
                    ...styles.navIcon,
                    opacity: isActive ? 1 : 0.6,
                    color: isActive ? activeColor : 'inherit',
                  }}>
                    {item.icon}
                  </span>
                  <span style={styles.navLabel}>{item.label}</span>
                  {item.badge !== undefined && (
                    <span style={styles.badge}>{item.badge}</span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
        {extraNav && (
          <>
            <div style={{ height: 1, background: 'rgba(255,255,255,0.055)', margin: '8px 4px 4px' }} />
            {extraNav}
          </>
        )}
      </nav>

      {/* Footer */}
      <div style={styles.footer}>
        <div style={styles.divider} />
        <div style={styles.userRow}>
          <div style={styles.avatar}>M</div>
          <div style={styles.userInfo}>
            <span style={styles.userName}>Max</span>
            <span style={styles.userMeta}>Admin · v0.1.0</span>
          </div>
        </div>
      </div>
    </aside>
  );
}

/* ── Styles ────────────────────────────────────────────────── */

const styles: Record<string, React.CSSProperties> = {
  sidebar: {
    width: 216,
    minWidth: 216,
    height: '100vh',
    background: '#0b0e17',
    borderRight: '1px solid rgba(255,255,255,0.055)',
    display: 'flex',
    flexDirection: 'column',
    flexShrink: 0,
    overflow: 'hidden',
    animation: 'slide-in-left 0.25s ease',
  },

  logoRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    padding: '14px 14px 13px',
    flexShrink: 0,
  },

  liveDot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
    background: '#00d4a0',
    boxShadow: '0 0 7px #00d4a0',
    flexShrink: 0,
    /* CSS animation via keyframe defined in tokens.css */
    animation: 'pulse-dot 2.4s ease-in-out infinite',
  } as React.CSSProperties,

  logoText: {
    fontFamily: "'Geist', system-ui, sans-serif",
    fontSize: 14,
    fontWeight: 600,
    letterSpacing: '-0.3px',
    color: '#edf0fa',
    userSelect: 'none',
  },

  divider: {
    height: 1,
    background: 'rgba(255,255,255,0.055)',
    flexShrink: 0,
  },

  nav: {
    flex: 1,
    overflowY: 'auto',
    padding: '8px 6px',
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },

  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
    marginBottom: 4,
    paddingTop: 10,
  },

  sectionLabel: {
    fontFamily: "'Geist Mono', monospace",
    fontSize: 9,
    fontWeight: 500,
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    color: '#2e3650',
    padding: '2px 10px 6px',
    userSelect: 'none',
  } as React.CSSProperties,

  navItem: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '7px 10px',
    borderRadius: 6,
    background: 'transparent',
    border: 'none',
    color: '#8a94b0',
    fontSize: 12.5,
    fontFamily: "'Geist', system-ui, sans-serif",
    fontWeight: 400,
    cursor: 'pointer',
    transition: 'background 0.12s ease, color 0.12s ease',
    textAlign: 'left',
    lineHeight: 1,
  },

  navItemActive: {
    background: 'rgba(79,142,255,0.1)',
    color: '#4f8eff',
  },

  navIcon: {
    display: 'flex',
    alignItems: 'center',
    flexShrink: 0,
    transition: 'opacity 0.12s ease, color 0.12s ease',
  },

  navLabel: {
    flex: 1,
  },

  badge: {
    fontFamily: "'Geist Mono', monospace",
    fontSize: 9,
    fontWeight: 500,
    padding: '1px 6px',
    borderRadius: 10,
    background: 'rgba(255,77,106,0.15)',
    color: '#ff4d6a',
    letterSpacing: '0.02em',
    lineHeight: '14px',
  },

  footer: {
    flexShrink: 0,
  },

  userRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    padding: '11px 12px',
  },

  avatar: {
    width: 24,
    height: 24,
    borderRadius: '50%',
    background: 'linear-gradient(135deg, #4f8eff 0%, #9d7eff 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 10,
    fontWeight: 600,
    color: '#fff',
    flexShrink: 0,
    fontFamily: "'Geist', system-ui, sans-serif",
    letterSpacing: '-0.2px',
  },

  userInfo: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    minWidth: 0,
  },

  userName: {
    fontSize: 12,
    fontWeight: 500,
    color: '#edf0fa',
    fontFamily: "'Geist', system-ui, sans-serif",
    lineHeight: 1,
  },

  userMeta: {
    fontFamily: "'Geist Mono', monospace",
    fontSize: 9.5,
    color: '#48526e',
    lineHeight: 1,
  },
};

export default Sidebar;
