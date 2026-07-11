import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { S } from '@/lib/strings';
import { getSettings } from '@/lib/api';
import { fetchAllAgents } from '@/lib/agents';
import { AppIcon } from '@/components/icons';

// Components
import ErrorBoundary from '@/components/ErrorBoundary';
import { ToastProvider } from '@/components/Toast';
import Titlebar from '@/components/Titlebar';
import UpdateBanner from '@/components/UpdateBanner';
import AppSidebar from '@/components/layout/AppSidebar';
import PageScaffold from '@/components/layout/PageScaffold';
import WorkbenchScaffold from '@/components/layout/WorkbenchScaffold';
import { ContentState, TooltipProvider } from '@/components/ui';

// Pages
const UploadPage = lazy(() => import('@/pages/Upload'));
const Workbench = lazy(() => import('@/pages/Workbench'));
const Library = lazy(() => import('@/pages/Library'));
const SettingsPage = lazy(() => import('@/pages/Settings'));
const Agents = lazy(() => import('@/pages/Agents'));

function RouteFallback() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <ContentState
        icon={(props) => <AppIcon name="spinner" {...props} />}
        title={S.workbench.loading}
        description="화면을 준비하고 있습니다."
        loading
        tone="muted"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// App Component
// ---------------------------------------------------------------------------

function App() {
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
    applyTheme(cached || 'light');

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

  // Load density: localStorage-backed UI preference (no backend field), applied
  // the same way as theme so there is no flash on first paint.
  useEffect(() => {
    const cachedDensity = localStorage.getItem('sasoo-density');
    document.documentElement.classList.toggle('density-compact', cachedDensity === 'compact');
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

  return (
    <TooltipProvider>
      <ToastProvider>
        <ErrorBoundary>
          <div className="app-shell">
            <Titlebar />
            <UpdateBanner />
            <div className="flex flex-1 min-h-0">
              {!isWorkbench && <AppSidebar />}

              <main className="flex-1 min-w-0 overflow-hidden">
                <div key={location.pathname} className="h-full w-full overflow-hidden animate-page-enter">
                  <Suspense fallback={<RouteFallback />}>
                    <Routes>
                      <Route path="/" element={<PageScaffold variant="archive"><UploadPage /></PageScaffold>} />
                      <Route path="/agents" element={<PageScaffold variant="control"><Agents /></PageScaffold>} />
                      <Route path="/workbench/:id" element={<WorkbenchScaffold><Workbench /></WorkbenchScaffold>} />
                      <Route path="/library" element={<PageScaffold variant="archive"><Library /></PageScaffold>} />
                      <Route path="/settings" element={<PageScaffold variant="control"><SettingsPage /></PageScaffold>} />
                    </Routes>
                  </Suspense>
                </div>
              </main>
            </div>
          </div>
        </ErrorBoundary>
      </ToastProvider>
    </TooltipProvider>
  );
}

export default App;
