import { useState, useCallback } from 'react';
import { NavLink } from 'react-router';
import { Sun, Moon } from 'lucide-react';
import { S } from '@/lib/strings';
import { updateSettings } from '@/lib/api';
import appIcon32 from '@/assets/brand/app-icon-32.svg';
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
      { to: '/profile', icon: 'agents', label: S.app.profile, exact: false },
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

  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    localStorage.getItem('sasoo-theme') === 'dark' ? 'dark' : 'light'
  );

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === 'dark' ? 'light' : 'dark';
      localStorage.setItem('sasoo-theme', next);
      const root = document.documentElement;
      root.classList.toggle('dark', next === 'dark');
      root.classList.toggle('light', next === 'light');
      // 백엔드에도 동기화 (App.tsx는 localStorage를 우선하지만 신규 세션 대비)
      updateSettings({ theme: next }).catch(() => {});
      return next;
    });
  }, []);

  return (
    <aside
      className={`app-sidebar ${collapsed ? 'app-sidebar-collapsed' : ''}`}
      aria-label={S.app.name}
    >
      <div className="app-sidebar-brand">
        <img src={appIcon32} alt="Sasoo" className="h-8 w-8 shrink-0" />
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

      <div
        className={`mt-2 flex gap-1 ${
          collapsed ? 'flex-col items-center' : 'items-center justify-between'
        }`}
      >
        <button
          type="button"
          onClick={toggleTheme}
          className={`flex items-center rounded-control text-fg-secondary transition-colors duration-150 hover:bg-surface-hover hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface ${
            collapsed ? 'h-10 w-10 justify-center' : 'gap-2 px-2 py-1.5 text-sm'
          }`}
          title={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
          aria-label={theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
        >
          {theme === 'dark' ? (
            <Sun className="h-4 w-4 shrink-0" />
          ) : (
            <Moon className="h-4 w-4 shrink-0" />
          )}
          {!collapsed && (
            <span className="truncate">{theme === 'dark' ? '라이트 모드' : '다크 모드'}</span>
          )}
        </button>

        <button
          type="button"
          onClick={toggle}
          className="flex h-8 w-8 items-center justify-center rounded-control text-fg-muted transition-colors duration-150 hover:bg-surface-hover hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
          title={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
          aria-label={collapsed ? S.app.expandSidebar : S.app.collapseSidebar}
        >
          <AppIcon
            name="chevron-left"
            className={`h-4 w-4 transition-transform duration-150 ${collapsed ? 'rotate-180' : ''}`}
          />
        </button>
      </div>
    </aside>
  );
}
