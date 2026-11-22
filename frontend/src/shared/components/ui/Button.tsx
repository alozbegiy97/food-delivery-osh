import type { ComponentProps } from 'react';

import { buttonClasses, type ButtonSize, type ButtonVariant } from './classes';

export interface ButtonProps extends Omit<ComponentProps<'button'>, 'type'> {
  /** Required: a button without a type submits its form by default. */
  type: 'button' | 'submit' | 'reset';
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Blocks clicks and marks the button busy; the label stays as given. */
  loading?: boolean;
  fullWidth?: boolean;
}

/** Always a real <button>; for links use buttonClasses() on the Link. */
export function Button({
  type,
  variant = 'primary',
  size = 'md',
  loading = false,
  fullWidth = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, fullWidth, className })}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="size-4 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent motion-reduce:animate-none"
        />
      )}
      {children}
    </button>
  );
}
