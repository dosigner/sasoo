import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  helperText?: ReactNode;
  error?: string;
  endIcon?: ReactNode;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, helperText, error, endIcon, className = '', id, ...rest }, ref) => {
    const inputId = id || (label ? `input-${label.replace(/\s/g, '-').toLowerCase()}` : undefined);

    return (
      <div>
        {label && (
          <label htmlFor={inputId} className="text-xs text-surface-400 block mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          <input
            ref={ref}
            id={inputId}
            className={`input ${endIcon ? 'pr-10' : ''} ${error ? 'border-red-500 focus:border-red-500 focus:ring-red-500' : ''} ${className}`}
            aria-invalid={!!error}
            aria-describedby={error ? `${inputId}-error` : undefined}
            {...rest}
          />
          {endIcon && (
            <div className="absolute right-2 top-1/2 -translate-y-1/2">
              {endIcon}
            </div>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} className="text-2xs text-red-400 mt-1" role="alert">
            {error}
          </p>
        )}
        {helperText && !error && (
          <p className="text-2xs text-surface-600 mt-1">{helperText}</p>
        )}
      </div>
    );
  }
);

Input.displayName = 'Input';

export default Input;
