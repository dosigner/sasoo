import { useState, useEffect, useCallback } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { S } from '@/lib/strings';
import {
  Upload,
  Microscope,
  BookOpen,
  Settings,
  ChevronLeft,
  Bot,
} from 'lucide-react';
import logoImg from '@/assets/logo.png';
import { getSettings } from '@/lib/api';
import { fetchAllAgents } from '@/lib/agents';

// Components
import ErrorBoundary from '@/components/ErrorBoundary';
import { ToastProvider } from '@/components/Toast';
import Titlebar from '@/components/Titlebar';
import UpdateBanner from '@/components/UpdateBanner';

// Pages
import UploadPage from '@/pages/Upload';
import Workbench from '@/pages/Workbench';
import Library from '@/pages/Library';
import SettingsPage from '@/pages/Settings';
import Agents from '@/pages/Agents';

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  { to: '/', icon: Upload, label: S.app.upload, exact: true },
  { to: '/agents', icon: Bot, label: S.app.agents, exact: false },
  { to: '/library', icon: BookOpen, label: S.app.library, exact: false },
  { to: '/settings', icon: Settings, label: S.app.settings, exact: false },
];

// ---------------------------------------------------------------------------
// App Component
// ---------------------------------------------------------------------------

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  // Detect if we're on the workbench page (needs full screen)
  const isWorkbench = location.pathname.startsWith('/workbench');

  // Load theme: localStorage first (instant), then sync with backend
  useEffect(() => {
    function applyTheme(t: string) {
      if (t === 'light') {
        document.documentElement.classList.add('light');
        document.documentElement.classList.remove('dark');
      } else {
        document.documentElement.classList.add('dark');
        document.documentElement.classList.remove('light');
      }
    }

    // Phase 1: instant restore from localStorage (no flash)
    const cached = localStorage.getItem('sasoo-theme');
    applyTheme(cached || 'dark');

    // Phase 2: sync with backend as source of truth
    getSettings()
      .then((data) => {
        if (data?.theme && data.theme !== cached) {
          localStorage.setItem('sasoo-theme', data.theme);
          applyTheme(data.theme);
        }
      })
      .catch(() => {});

    // Phase 3: populate agent cache for all pages
    fetchAllAgents().catch(() => {});
  }, []);

  // Forward Python backend logs to DevTools console
  useEffect(() => {
    if (!window.electronAPI?.on) return;
    const unsub = window.electronAPI.on('backend:log', (...args: unknown[]) => {
      const level = args[0] as string;
      const message = args[1] as string;
      if (level === 'error') {
        console.error(`[Backend] ${message}`);
      } else {
        console.log(`[Backend] ${message}`);
      }
    });
    return unsub;
  }, []);

  // Load sidebar state from localStorage
  useEffect(() => {
    const savedCollapsed = localStorage.getItem('sasoo-sidebar-collapsed');
    if (savedCollapsed === 'true') {
      setSidebarCollapsed(true);
    }
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((c) => {
      const newValue = !c;
      localStorage.setItem('sasoo-sidebar-collapsed', String(newValue));
      return newValue;
    });
  }, []);

  // Keyboard shortcut: Ctrl+B to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleSidebar]);

  return (
    <ToastProvider>
      <ErrorBoundary>
        <div className="flex flex-col h-screen bg-surface-900 text-surface-200">
      <Titlebar />
      <UpdateBanner />
      <div className="flex flex-1 min-h-0">
      {/* Sidebar */}
      <aside
        className={`flex flex-col bg-surface-800/85 backdrop-blur-xl border-r border-surface-700/50 transition-all duration-300 shrink-0 ${
          sidebarCollapsed ? 'w-16' : 'w-56'
        }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 h-14 border-b border-surface-700 shrink-0">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0">
            <img src={logoImg} alt="Sasoo" className="w-8 h-8" />
          </div>
          {!sidebarCollapsed && (
            <div className="min-w-0">
              <h1 className="text-base font-bold text-surface-100 tracking-apple-tight">
                Sasoo
              </h1>
              <p className="text-2xs text-surface-500 truncate">
                {S.app.subtitle}
              </p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item, index) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.exact}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg transition-colors ${
                    sidebarCollapsed ? 'px-3 py-2.5 justify-center' : 'px-3 py-2.5'
                  } ${
                    isActive
                      ? 'bg-primary-500/10 text-primary-400 border border-primary-500/20'
                      : 'text-surface-400 hover:bg-surface-700/50 hover:text-surface-200 border border-transparent'
                  }`
                }
                title={sidebarCollapsed ? item.label : undefined}
                aria-label={item.label}
              >
                <Icon className="w-4.5 h-4.5 shrink-0" />
                {!sidebarCollapsed && (
                  <span
                    className="text-sm font-medium sidebar-label-enter"
                    style={{ animationDelay: `${index * 25}ms` }}
                  >
                    {item.label}
                  </span>
                )}
              </NavLink>
            );
          })}

          {/* Workbench link appears when viewing a paper */}
          {isWorkbench && (
            <div
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 bg-primary-500/10 text-primary-400 border border-primary-500/20 ${
                sidebarCollapsed ? 'justify-center' : ''
              }`}
            >
              <Microscope className="w-4.5 h-4.5 shrink-0" />
              {!sidebarCollapsed && (
                <span className="text-sm font-medium">{S.app.workbench}</span>
              )}
            </div>
          )}
        </nav>

        {/* Collapse toggle */}
        <div className="px-2 py-3 border-t border-surface-700 shrink-0">
          <button
            onClick={toggleSidebar}
            className={`flex items-center gap-2 w-full rounded-lg px-3 py-2 text-surface-500 hover:text-surface-300 hover:bg-surface-700/50 transition-colors ${
              sidebarCollapsed ? 'justify-center' : ''
            }`}
            title={sidebarCollapsed ? S.app.expandSidebar : S.app.collapseSidebar}
            aria-label={sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
          >
            <ChevronLeft
              className={`w-4 h-4 transition-transform duration-300 ${
                sidebarCollapsed ? 'rotate-180' : ''
              }`}
            />
            {!sidebarCollapsed && (
              <span className="text-xs">{S.app.collapse}</span>
            )}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 overflow-hidden">
        <div key={location.pathname} className="h-full w-full overflow-hidden animate-page-enter">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/workbench/:id" element={<Workbench />} />
            <Route path="/library" element={<Library />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </div>
      </main>
      </div>
        </div>
      </ErrorBoundary>
    </ToastProvider>
  );
}

export default App;
