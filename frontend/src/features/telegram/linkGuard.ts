import type { MouseEvent } from 'react';

import { isMiniAppPath } from '../../shared/lib/miniAppMode';

// Last line of defence for plain <a href> inside the Mini App (MA-4.0).
// Router links already stay under /tg (basename). A plain anchor could
// still point to a site page or to another site:
// - same origin outside /tg (e.g. /login, /admin): blocked — the Mini App
//   never leaves into the site (DEC-152 п. 1);
// - another origin over http(s) (e.g. the OpenStreetMap attribution):
//   opened outside the Mini App with Telegram's openLink, never inside it;
// - other schemes (tel:, mailto:) are left to the client.

export type LinkDecision = 'allow' | 'block' | 'external';

export function decideLink(href: string, origin: string = window.location.origin): LinkDecision {
  let url: URL;
  try {
    url = new URL(href, origin);
  } catch {
    return 'block';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return 'allow';
  }
  if (url.origin !== origin) {
    return 'external';
  }
  return isMiniAppPath(url.pathname) ? 'allow' : 'block';
}

/** onClickCapture handler for the Mini App layout. */
export function guardMiniAppLinks(event: MouseEvent<HTMLElement>): void {
  const anchor = (event.target as Element | null)?.closest?.('a[href]');
  if (!(anchor instanceof HTMLAnchorElement)) {
    return;
  }
  const decision = decideLink(anchor.getAttribute('href') ?? '');
  if (decision === 'allow') {
    return;
  }
  event.preventDefault();
  if (decision === 'external') {
    openExternalLink(anchor.href);
  }
}

/**
 * Opens an absolute http(s) URL outside the Mini App: Telegram's openLink
 * (external browser), or a new tab when the client does not support it.
 */
export function openExternalLink(url: string): void {
  const app = window.Telegram?.WebApp;
  if (app?.openLink) {
    app.openLink(url);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

/** Absolute URL of a site page (e.g. `/forgot-password`) on this origin. */
export function siteUrl(path: string): string {
  return new URL(path, window.location.origin).toString();
}
