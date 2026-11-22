import type { ReactNode } from 'react';

import { SECTION_HEADER } from './classes';

export interface SectionHeaderProps {
  title: ReactNode;
  /** h2 for page sections, h3 inside them; the page keeps its single h1. */
  level?: 2 | 3;
  /** For aria-labelledby on the surrounding section. */
  id?: string;
  description?: ReactNode;
  action?: ReactNode;
}

/** Section title with an optional description and action; wraps at 320 px. */
export function SectionHeader({ title, level = 2, id, description, action }: SectionHeaderProps) {
  const Heading = level === 3 ? 'h3' : 'h2';
  return (
    <div className={SECTION_HEADER.root}>
      <div className="min-w-0">
        <Heading id={id} className={level === 3 ? SECTION_HEADER.title3 : SECTION_HEADER.title2}>
          {title}
        </Heading>
        {description && <p className={SECTION_HEADER.description}>{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
