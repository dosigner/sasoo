import { useState, useEffect, useCallback } from 'react';
import logoImg from '@/assets/logo.png';
import { AppIcon } from '@/components/icons';
import { S } from '@/lib/strings';

export default function Titlebar() {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    // Check initial maximized state
    window.electronAPI?.isMaximized?.().then(setIsMaximized).catch(() => {});

    // Listen for maximize/unmaximize events
    const unsub = window.electronAPI?.on?.('window:maximizeChanged', (maximized: unknown) => {
      setIsMaximized(maximized as boolean);
    });
    return () => { unsub?.(); };
  }, []);

  const handleMinimize = useCallback(() => {
    window.electronAPI?.minimizeWindow?.();
  }, []);

  const handleMaximize = useCallback(() => {
    window.electronAPI?.maximizeWindow?.();
  }, []);

  const handleClose = useCallback(() => {
    window.electronAPI?.closeWindow?.();
  }, []);

  // Only render in Electron environment
  const isElectron = typeof window !== 'undefined' && !!window.electronAPI;
  if (!isElectron) return null;

  const isMac = navigator.platform.toLowerCase().includes('mac');

  return (
    <div
      className="titlebar-drag flex items-center h-8 bg-surface-900/95 backdrop-blur-xl border-b border-surface-700/50 shrink-0 select-none"
      style={{ paddingLeft: isMac ? 76 : 12, paddingRight: isMac ? 12 : 0 }}
    >
      {/* Logo + Title (non-Mac) */}
      {!isMac && (
        <div className="flex items-center gap-2 mr-auto">
          <img src={logoImg} alt="Sasoo" className="w-4 h-4" />
          <span className="text-xs font-medium text-surface-400">
            {S.app.name}
          </span>
        </div>
      )}

      {/* Mac: centered title */}
      {isMac && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-xs font-medium text-surface-400">
            {S.app.name}
          </span>
        </div>
      )}

      {/* Window controls (Windows/Linux only) */}
      {!isMac && (
        <div className="titlebar-no-drag flex items-center h-full ml-auto">
          <button
            onClick={handleMinimize}
            className="flex items-center justify-center w-11 h-full text-surface-400 hover:bg-surface-700/50 hover:text-surface-200 transition-colors"
            title={S.titlebar.minimize}
            aria-label={S.titlebar.minimize}
          >
            <AppIcon name="minimize" className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleMaximize}
            className="flex items-center justify-center w-11 h-full text-surface-400 hover:bg-surface-700/50 hover:text-surface-200 transition-colors"
            title={isMaximized ? S.titlebar.restore : S.titlebar.maximize}
            aria-label={isMaximized ? S.titlebar.restore : S.titlebar.maximize}
          >
            {isMaximized ? (
              <AppIcon name="restore" className="w-3.5 h-3.5" />
            ) : (
              <AppIcon name="maximize" className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={handleClose}
            className="flex items-center justify-center w-11 h-full text-surface-400 hover:bg-red-600 hover:text-white transition-colors"
            title={S.titlebar.close}
            aria-label={S.titlebar.close}
          >
            <AppIcon name="close" className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
