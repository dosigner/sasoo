import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { AppIcon } from '@/components/icons';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastOptions {
  duration?: number;
  /** 토스트 안에 보조 액션 버튼을 하나 보여준다 (예: "되돌리기"). */
  action?: { label: string; onClick: () => void };
  /** 액션 버튼이 아닌 경로(자동 만료, 수동 닫기)로 토스트가 사라질 때 호출된다. */
  onDismiss?: () => void;
}

interface Toast extends ToastOptions {
  id: string;
  type: ToastType;
  message: string;
  description?: string;
}

interface ToastContextValue {
  toast: {
    success: (message: string, description?: string, options?: ToastOptions) => void;
    error: (message: string, description?: string, options?: ToastOptions) => void;
    warning: (message: string, description?: string, options?: ToastOptions) => void;
    info: (message: string, description?: string, options?: ToastOptions) => void;
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
        toast.onDismiss?.();
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
    toast.onDismiss?.();
    setIsExiting(true);
    setTimeout(() => onRemove(toast.id), 200);
  };

  const handleActionClick = () => {
    // 액션(예: 되돌리기)이 스스로 처리를 끝내므로 onDismiss는 부르지 않는다.
    toast.action?.onClick();
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
            {toast.action && (
              <button
                onClick={handleActionClick}
                className="mt-1.5 text-xs font-semibold text-accent hover:underline"
              >
                {toast.action.label}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Close button */}
      <button
        onClick={handleClose}
        className="absolute top-3 right-3 p-1 rounded-sm transition-colors
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

  const addToast = useCallback(
    (type: ToastType, message: string, description?: string, options?: ToastOptions) => {
      const id = `${Date.now()}-${Math.random()}`;
      // 액션 버튼이 있는 토스트(예: 삭제 되돌리기)는 읽고 판단할 시간이 필요하니 6초를 기본값으로 둔다.
      const duration = options?.duration ?? (options?.action ? 6000 : undefined);
      const newToast: Toast = { id, type, message, description, ...options, duration };

      setToasts((prev) => {
        const updated = [newToast, ...prev];
        // Keep only the newest MAX_TOASTS
        return updated.slice(0, MAX_TOASTS);
      });
    },
    []
  );

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const contextValue: ToastContextValue = {
    toast: {
      success: (message, description, options) => addToast('success', message, description, options),
      error: (message, description, options) => addToast('error', message, description, options),
      warning: (message, description, options) => addToast('warning', message, description, options),
      info: (message, description, options) => addToast('info', message, description, options),
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
