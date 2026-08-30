import type { ComponentType } from 'react';

interface ContentStateProps {
  icon: ComponentType<{ className?: string; title?: string }>;
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
    shell: 'border-border/45 bg-surface/45',
    iconWrap: 'bg-accent/10 border-accent/10',
    icon: 'text-accent',
  },
  error: {
    shell: 'border-danger/20 bg-danger/5',
    iconWrap: 'bg-danger/10 border-danger/10',
    icon: 'text-danger',
  },
  muted: {
    shell: 'border-border/45 bg-surface/35',
    iconWrap: 'bg-surface/90 border-border/60',
    icon: 'text-fg-muted',
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
      className={`flex flex-col items-center justify-center border px-5 text-center ${styles.shell} ${
        compact ? 'py-5' : 'py-8'
      } ${className}`}
      style={{ borderRadius: 'var(--radius-surface)' }}
    >
      {!loading && (
        <div
          className={`mb-3 flex items-center justify-center border ${styles.iconWrap} ${
            compact ? 'h-10 w-10' : 'h-11 w-11'
          }`}
          style={{ borderRadius: 'var(--radius-control)' }}
        >
          <Icon className={`${styles.icon} ${compact ? 'h-4 w-4' : 'h-5 w-5'}`} />
        </div>
      )}
      <h3
        className={`${compact ? 'text-xs' : 'text-sm'} font-semibold ${
          loading ? 'shimmer-label' : 'text-fg'
        }`}
      >
        {title}
      </h3>
      {description && (
        <p className={`mt-1 max-w-sm text-fg-muted ${compact ? 'text-2xs' : 'text-xs'}`}>
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
