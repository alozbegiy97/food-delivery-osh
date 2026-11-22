// Phone input mask "+996 XXX XX XX XX" without a library (DEC-89). Accepts
// input with +996, 996, 0 or without a prefix. Normalization and the final
// check happen on the backend.
const LOCAL_DIGITS = 9;

function localDigits(raw: string): string {
  let digits = raw.replace(/\D/g, '');
  if (digits.startsWith('996')) {
    digits = digits.slice(3);
  } else if (digits.startsWith('0')) {
    digits = digits.slice(1);
  }
  return digits.slice(0, LOCAL_DIGITS);
}

export function formatPhoneInput(raw: string): string {
  const digits = localDigits(raw);
  if (!digits) {
    return '';
  }
  const parts = [digits.slice(0, 3), digits.slice(3, 5), digits.slice(5, 7), digits.slice(7, 9)];
  return `+996 ${parts.filter(Boolean).join(' ')}`;
}

export function isCompletePhone(value: string): boolean {
  return localDigits(value).length === LOCAL_DIGITS;
}
