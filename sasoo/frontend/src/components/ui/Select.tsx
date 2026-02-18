import { forwardRef, type SelectHTMLAttributes, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> {
  label?: string;
  helperText?: ReactNode;
  options: SelectOption[];
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, helperText, options, className = '', id, ...rest }, ref) => {
    const selectId = id || (label ? `select-${label.replace(/\s/g, '-').toLowerCase()}` : undefined);

    return (
      <div>
        {label && (
          <label htmlFor={selectId} className="text-xs text-surface-400 block mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            className={`input appearance-none pr-8 ${className}`}
            {...rest}
          >
            {options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-500 pointer-events-none" />
        </div>
        {helperText && (
          <p className="text-2xs text-surface-600 mt-1">{helperText}</p>
        )}
      </div>
    );
  }
);

Select.displayName = 'Select';

export default Select;
