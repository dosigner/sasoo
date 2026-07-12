import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { AppIcon } from '@/components/icons';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  description?: string;
  duration?: number;
}

interface ToastContextValue {
  toast: {
    success: (message: string, description?: string) => void;
    error: (message: string, description?: string) => void;
    warning: (message: string, description?: string) => void;
    info: (message: string, description?: string) => void;
  };
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
}

// ---------------------------------------------------------------------------
// Toast Item Component
// ---------------------------------------------------------------------------

interface ToastItemProps {
  toast: Toast;
  onRemove: (id: string) => void;
}

function ToastItem({ toast, onRemove }: ToastItemProps) {
  const [isExiting, setIsExiting] = useState(false);
  const duration = toast.duration || 3000;
  const barRef = useRef<HTMLDivElement>(null);
  const animRef = useRef<Animation | null>(null);
  const hoveredRef = useRef(false);

  useEffect(() => {
    // One WAAPI animation drives both the progress bar and auto-dismiss,
    // so pausing (hover, hidden window) keeps them in sync.
    const bar = barRef.current;
    if (!bar) return;

    const anim = bar.animate(
      [{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }],
      { duration, easing: 'linear', fill: 'forwards' },
    );
    animRef.current = anim;

    let exitTimer: ReturnType<typeof setTimeout> | undefined;
    anim.finished
      .then(() => {
        setIsExiting(true);
        exitTimer = setTimeout(() => onRemove(toast.id), 200);
      })
      .catch(() => {}); // cancelled on unmount

    const onVisibility = () => {
      if (document.hidden) {
        if (anim.playState === 'running') anim.pause();
      } else if (anim.playState === 'paused' && !hoveredRef.current) {
        anim.play();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      anim.cancel();
      if (exitTimer) clearTimeout(exitTimer);
    };
  }, [toast.id, duration, onRemove]);

  const handleMouseEnter = () => {
    hoveredRef.current = true;
    if (animRef.current?.playState === 'running') animRef.current.pause();
  };

  const handleMouseLeave = () => {
    hoveredRef.current = false;
    if (animRef.current?.playState === 'paused' && !document.hidden) animRef.current.play();
  };

  const handleClose = () => {
    setIsExiting(true);
    setTimeout(() => onRemove(toast.id), 200);
  };

  // Icon and color configuration
  const config = {
    success: {
      icon: 'success' as const,
      iconColor: 'text-success',
      progressBg: 'bg-success',
    },
    error: {
      icon: 'error' as const,
      iconColor: 'text-danger',
      progressBg: 'bg-danger',
    },
    warning: {
      icon: 'warning' as const,
      iconColor: 'text-warning',
      progressBg: 'bg-warning',
    },
    info: {
      icon: 'info' as const,
      iconColor: 'text-accent',
      progressBg: 'bg-accent',
    },
  };

  const { icon: Icon, iconColor, progressBg } = config[toast.type];

  return (
    <div
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className={`
        relative overflow-hidden rounded-xl shadow-lg border
        w-96 max-w-full
        transition-[opacity,transform] duration-200 ease-out
        ${isExiting ? 'opacity-0 translate-x-4' : 'opacity-100 translate-x-0 animate-slide-in-right'}
        toast-surface border-border/50
      `}
    >
      {/* Content */}
      <div className="p-4 pr-10">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <span className="icon-surface mt-0.5 h-9 w-9 shrink-0">
            <AppIcon name={Icon} className={`h-4.5 w-4.5 ${iconColor}`} />
          </span>

          {/* Text */}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-fg">
              {toast.message}
            </p>
            {toast.description && (
              <p className="mt-1 text-xs text-fg-muted">
                {toast.description}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Close button */}
      <button
        onClick={handleClose}
        className="absolute top-3 right-3 p-1 rounded transition-colors
          text-fg-muted hover:text-fg hover:bg-surface-hover"
        aria-label="Close notification"
      >
        <AppIcon name="close" className="w-4 h-4" />
      </button>

      {/* Progress bar */}
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-surface/20">
        <div
          ref={barRef}
          className={`h-full ${progressBg}`}
          style={{ transformOrigin: 'left' }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toast Provider
// ---------------------------------------------------------------------------

const MAX_TOASTS = 5;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string, description?: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    const newToast: Toast = { id, type, message, description };

    setToasts((prev) => {
      const updated = [newToast, ...prev];
      // Keep only the newest MAX_TOASTS
      return updated.slice(0, MAX_TOASTS);
    });
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const contextValue: ToastContextValue = {
    toast: {
      success: (message, description) => addToast('success', message, description),
      error: (message, description) => addToast('error', message, description),
      warning: (message, description) => addToast('warning', message, description),
      info: (message, description) => addToast('info', message, description),
    },
  };

  return (
    <ToastContext.Provider value={contextValue}>
      {children}

      {/* Toast container - bottom-right corner */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-3 pointer-events-none">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} onRemove={removeToast} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
