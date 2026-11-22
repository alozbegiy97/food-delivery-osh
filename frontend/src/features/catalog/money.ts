// Money comes from the API as decimal strings ("550.00", DEC-73). For the
// preview price it is converted to integer tyiyn (1/100 som) so that sums
// never suffer from binary floating point errors.

export function toTyiyn(amount: string): number {
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(amount.trim());
  if (!match) {
    throw new Error(`Unexpected money value: ${amount}`);
  }
  const [, whole, fraction = ''] = match;
  return Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
}

/** "1 250" / "1 250,50" in the given locale; no currency sign. */
export function formatTyiyn(tyiyn: number, localeTag: string): string {
  const hasFraction = tyiyn % 100 !== 0;
  return new Intl.NumberFormat(localeTag, {
    minimumFractionDigits: hasFraction ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(tyiyn / 100);
}
