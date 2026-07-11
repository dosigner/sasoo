import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
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
  const [progress, setProgress] = useState(100);
  const duration = toast.duration || 3000;

  useEffect(() => {
    // Progress bar animation
    const startTime = Date.now();
    const timer = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, 100 - (elapsed / duration) * 100);
      setProgress(remaining);

      if (remaining === 0) {
        clearInterval(timer);
      }
    }, 16); // ~60fps

    // Auto-dismiss timer
    const dismissTimer = setTimeout(() => {
      setIsExiting(true);
      setTimeout(() => onRemove(toast.id), 200);
    }, duration);

    return () => {
      clearInterval(timer);
      clearTimeout(dismissTimer);
    };
  }, [toast.id, duration, onRemove]);

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
      className={`
        relative overflow-hidden rounded-xl shadow-lg border
        w-96 max-w-full
        transition-all duration-200
        ${isExiting ? 'opacity-0 translate-x-4' : 'opacity-100 translate-x-0 animate-slide-in-right'}
        bg-surface/90 backdrop-blur-lg border-border/50
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
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-surface-hover/20">
        <div
          className={`h-full ${progressBg} transition-all duration-75 ease-linear`}
          style={{ width: `${progress}%` }}
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
