import type { HTMLAttributes } from 'react';

import { cardClasses, type CardPadding, type CardTone } from './classes';

export interface CardProps extends HTMLAttributes<HTMLElement> {
  /** The element keeps the page's semantics; a Card is never interactive. */
  as?: 'div' | 'section' | 'article' | 'li';
  tone?: CardTone;
  padding?: CardPadding;
}

/** A surface for content. A clickable card is a Link with cardClasses(). */
export function Card({
  as: Element = 'div',
  tone = 'default',
  padding = 'md',
  className,
  ...rest
}: CardProps) {
  return <Element {...rest} className={cardClasses({ tone, padding, className })} />;
}
