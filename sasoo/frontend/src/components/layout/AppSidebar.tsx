import { useState, useCallback } from 'react';
import { NavLink } from 'react-router-dom';
import { S } from '@/lib/strings';
import logoImg from '@/assets/logo.png';
import { AppIcon, type AppIconName } from '@/components/icons';

const COLLAPSE_KEY = 'sasoo-sidebar-collapsed';

interface NavItem {
  to: string;
  icon: AppIconName;
  label: string;
  exact: boolean;
}

const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: '작업',
    items: [
      { to: '/', icon: 'upload', label: S.app.home, exact: true },
      { to: '/library', icon: 'library', label: S.app.library, exact: false },
    ],
  },
  {
    title: '관리',
    items: [
      { to: '/agents', icon: 'agents', label: S.app.agents, exact: false },
      { to: '/settings', icon: 'settings', label: S.app.settings, exact: false },
    ],
  },
];

export default function AppSidebar() {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === 'true'
  );

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      localStorage.setItem(COLLAPSE_KEY, String(!prev));
      return !prev;
    });
  }, []);

  return (
    <aside
      className={`app-sidebar ${collapsed ? 'app-sidebar-collapsed' : ''}`}
      aria-label={S.app.name}
    >
      <div className="app-sidebar-brand">
        <img src={logoImg} alt="Sasoo" className="h-8 w-8 rounded-xl shrink-0" />
        {!collapsed && <span className="app-sidebar-brand-name">{S.app.name}</span>}
      </div>

      <nav className="app-sidebar-nav" aria-label="기본 내비게이션">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="app-sidebar-section">
            {!collapsed && <div className="app-sidebar-section-title">{section.title}</div>}
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  `app-sidebar-link ${isActive ? 'app-sidebar-link-active' : ''}`
                }
                title={item.label}
                aria-label={item.label}
              >
                <AppIcon name={item.icon} className="h-4 w-4 shrink-0" />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <button
        type="button"
        onClick={toggle}
        className="app-sidebar-collapse-btn"
        title={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
        aria-label={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
      >
        <AppIcon
          name="chevron-left"
          className={`h-4 w-4 transition-transform duration-150 ${collapsed ? 'rotate-180' : ''}`}
        />
      </button>
    </aside>
  );
}
