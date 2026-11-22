import type { ComponentProps } from 'react';

import { chipClasses } from './classes';

export interface ChipProps extends Omit<ComponentProps<'button'>, 'type' | 'aria-pressed'> {
  selected: boolean;
}

/**
 * Toggle chip (a filter): a button with aria-pressed. A chip that navigates
 * is a NavLink with chipClasses() and keeps the link's aria-current.
 */
export function Chip({ selected, className, ...rest }: ChipProps) {
  return (
    <button
      {...rest}
      type="button"
      aria-pressed={selected}
      className={chipClasses(selected, className)}
    />
  );
}
