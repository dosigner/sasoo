import type { ReactNode } from 'react';

export interface BadgeProps {
  variant: 'neutral' | 'accent' | 'danger' | 'warning' | 'success';
  children: ReactNode;
  className?: string;
}

const VARIANT_STYLES: Record<BadgeProps['variant'], string> = {
  neutral: 'bg-surface-hover text-fg-secondary',
  accent: 'bg-accent/10 text-accent',
  danger: 'bg-danger/10 text-danger',
  warning: 'bg-warning/10 text-warning',
  success: 'bg-success/10 text-success',
};

export default function Badge({ variant, children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium ${VARIANT_STYLES[variant]} ${className}`}
    >
      {children}
    </span>
  );
}
