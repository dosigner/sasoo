import type { ReactNode } from 'react';

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: ReactNode;
  disabled?: boolean;
}

export default function Toggle({ checked, onChange, label, description, disabled }: ToggleProps) {
  return (
    <div className="flex items-center justify-between">
      {(label || description) && (
        <div className="min-w-0 mr-3">
          {label && (
            <span className="text-xs text-fg-secondary">{label}</span>
          )}
          {description && (
            <p className="text-2xs text-fg-muted mt-0.5">{description}</p>
          )}
        </div>
      )}
      <button
        onClick={() => !disabled && onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
        } ${checked ? 'bg-accent' : 'bg-surface'}`}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
      >
        <span
          className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}
