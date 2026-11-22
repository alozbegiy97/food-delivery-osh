import type { ReactNode } from 'react';

import { BADGE_BASE, BADGE_TONES, joinClasses, type BadgeTone } from './classes';

export interface BadgeProps {
  /** The status in words: colour alone never carries the meaning. */
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}

/** Static label without a role; a live status adds role="status" around it. */
export function Badge({ children, tone = 'neutral', className }: BadgeProps) {
  return <span className={joinClasses(BADGE_BASE, BADGE_TONES[tone], className)}>{children}</span>;
}
