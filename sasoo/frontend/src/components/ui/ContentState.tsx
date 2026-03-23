import type { LucideIcon } from 'lucide-react';
import { Loader2 } from 'lucide-react';

interface ContentStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  tone?: 'default' | 'error' | 'muted';
  loading?: boolean;
  compact?: boolean;
  className?: string;
}

const TONE_STYLES: Record<NonNullable<ContentStateProps['tone']>, {
  shell: string;
  iconWrap: string;
  icon: string;
}> = {
  default: {
    shell: 'border-surface-700/45 bg-surface-900/45',
    iconWrap: 'bg-primary-500/10 border-primary-500/10',
    icon: 'text-primary-400',
  },
  error: {
    shell: 'border-red-500/20 bg-red-500/5',
    iconWrap: 'bg-red-500/10 border-red-500/10',
    icon: 'text-red-400',
  },
  muted: {
    shell: 'border-surface-700/45 bg-surface-900/35',
    iconWrap: 'bg-surface-800/90 border-surface-700/60',
    icon: 'text-surface-500',
  },
};

export default function ContentState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  tone = 'default',
  loading = false,
  compact = false,
  className = '',
}: ContentStateProps) {
  const styles = TONE_STYLES[tone];

  return (
    <div
      className={`flex flex-col items-center justify-center rounded-[18px] border px-5 text-center ${styles.shell} ${
        compact ? 'py-5' : 'py-8'
      } ${className}`}
    >
      <div
        className={`mb-3 flex items-center justify-center rounded-2xl border ${styles.iconWrap} ${
          compact ? 'h-10 w-10' : 'h-11 w-11'
        }`}
      >
        {loading ? (
          <Loader2 className={`animate-spin ${styles.icon} ${compact ? 'h-4 w-4' : 'h-5 w-5'}`} />
        ) : (
          <Icon className={`${styles.icon} ${compact ? 'h-4 w-4' : 'h-5 w-5'}`} />
        )}
      </div>
      <h3 className={`${compact ? 'text-xs' : 'text-sm'} font-semibold text-surface-200`}>
        {title}
      </h3>
      {description && (
        <p className={`mt-1 max-w-sm text-surface-400 ${compact ? 'text-2xs' : 'text-xs'}`}>
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          className="btn-secondary mt-4 px-3 py-1.5 text-2xs"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
