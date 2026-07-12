import * as RadixSelect from '@radix-ui/react-select';
import { AppIcon } from '@/components/icons';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  'aria-label'?: string;
}

export default function Select({
  value,
  onValueChange,
  options,
  placeholder,
  disabled,
  className = '',
  'aria-label': ariaLabel,
}: SelectProps) {
  return (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RadixSelect.Trigger
        className={`input flex w-full items-center justify-between gap-2 text-left data-[placeholder]:text-fg-muted ${className}`}
        aria-label={ariaLabel}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon>
          <AppIcon name="chevron-down" className="h-4 w-4 text-fg-muted" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          position="popper"
          sideOffset={4}
          className="z-50 max-h-[min(24rem,var(--radix-select-content-available-height))] w-[var(--radix-select-trigger-width)] overflow-hidden border border-border bg-surface shadow-lg rounded-surface animate-fade-in"
        >
          <RadixSelect.Viewport className="p-1">
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                className="relative flex cursor-pointer select-none items-center rounded-control px-2.5 py-1.5 text-sm text-fg outline-none data-[highlighted]:bg-surface-hover data-[state=checked]:text-accent focus-visible:ring-2 focus-visible:ring-accent"
              >
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
