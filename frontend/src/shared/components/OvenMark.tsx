/*
 * Brand mark of the "Печь" direction (DEC-161 rev. 47): the mouth of an oven
 * with the fire inside. Decorative (aria-hidden): the restaurant name next to
 * it is the accessible text. Coloured only through tokens: the arch uses the
 * fixed graphite `scrim`, so it stays dark in a dark Telegram theme too.
 */
export function OvenMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 30 34" aria-hidden="true" focusable="false" className={className}>
      <path d="M2 32V15a13 13 0 0 1 26 0v17Z" className="fill-scrim" />
      <path d="M8 32v-9a7 7 0 0 1 14 0v9Z" className="fill-accent-600" />
      <path d="M11 32v-6a4 4 0 0 1 8 0v6Z" className="fill-accent-100" />
    </svg>
  );
}
