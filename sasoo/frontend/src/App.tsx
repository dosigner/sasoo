import { useState, useEffect, useCallback } from 'react';
import { Routes, Route, NavLink, useLocation } from 'react-router-dom';
import {
  Upload,
  Microscope,
  BookOpen,
  Settings,
  ChevronLeft,
  ChevronRight,
  Beaker,
} from 'lucide-react';

// Components
import ErrorBoundary from '@/components/ErrorBoundary';
import { ToastProvider } from '@/components/Toast';

// Pages
import UploadPage from '@/pages/Upload';
import Workbench from '@/pages/Workbench';
import Library from '@/pages/Library';
import SettingsPage from '@/pages/Settings';

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  {
    to: '/',
    icon: Upload,
    label: 'Upload',
    exact: true,
  },
  {
    to: '/library',
    icon: BookOpen,
    label: 'Library',
    exact: false,
  },
  {
    to: '/settings',
    icon: Settings,
    label: 'Settings',
    exact: false,
  },
] as const;

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
    const apiBase = window.location.protocol === 'file:' ? 'http://localhost:8000/api' : '/api';
    fetch(`${apiBase}/settings`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.theme && data.theme !== cached) {
          localStorage.setItem('sasoo-theme', data.theme);
          applyTheme(data.theme);
        }
      })
      .catch(() => {});
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

  return (
    <ToastProvider>
      <ErrorBoundary>
        <div className="flex h-screen bg-surface-900 text-surface-200">
      {/* Sidebar */}
      <aside
        className={`flex flex-col bg-surface-800/85 backdrop-blur-xl border-r border-surface-700/50 transition-all duration-300 shrink-0 ${
          sidebarCollapsed ? 'w-16' : 'w-56'
        }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 h-14 border-b border-surface-700 shrink-0">
          <div className="w-8 h-8 rounded-lg bg-primary-500/10 border border-primary-500/20 flex items-center justify-center shrink-0">
            <Beaker className="w-4.5 h-4.5 text-primary-400" />
          </div>
          {!sidebarCollapsed && (
            <div className="min-w-0">
              <h1 className="text-base font-bold text-surface-100 tracking-apple-tight">
                Sasoo
              </h1>
              <p className="text-2xs text-surface-500 truncate">
                Paper Analysis
              </p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
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
                  <span className="text-sm font-medium">{item.label}</span>
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
                <span className="text-sm font-medium">Workbench</span>
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
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={sidebarCollapsed ? '사이드바 펼치기' : '사이드바 접기'}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4" />
            ) : (
              <>
                <ChevronLeft className="w-4 h-4" />
                <span className="text-xs">Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 overflow-hidden">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/workbench/:id" element={<Workbench />} />
          <Route path="/library" element={<Library />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
        </div>
      </ErrorBoundary>
    </ToastProvider>
  );
}

export default App;
