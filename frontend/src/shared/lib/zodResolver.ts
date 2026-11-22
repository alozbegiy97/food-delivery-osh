import type { FieldErrors, FieldValues, Resolver } from 'react-hook-form';
import type { ZodType } from 'zod';

/**
 * Minimal React Hook Form resolver for Zod. Written here instead of adding
 * @hookform/resolvers: the stack approves RHF and Zod only. Errors are
 * nested by path (`translations.ru.name`) as RHF expects; messages are i18n
 * keys translated by components. Only the first error per field is kept.
 */
export function zodResolver<T extends FieldValues, I = T>(
  schema: ZodType<T, I>,
): Resolver<I & FieldValues, unknown, T> {
  return async (values) => {
    const result = schema.safeParse(values);
    if (result.success) {
      return { values: result.data, errors: {} };
    }
    const errors: Record<string, unknown> = {};
    for (const issue of result.error.issues) {
      if (issue.path.length === 0) {
        continue;
      }
      let node = errors;
      issue.path.forEach((part, index) => {
        const key = String(part);
        if (index === issue.path.length - 1) {
          if (!(key in node)) {
            node[key] = { type: issue.code, message: issue.message };
          }
        } else {
          node[key] = (node[key] as Record<string, unknown> | undefined) ?? {};
          node = node[key] as Record<string, unknown>;
        }
      });
    }
    return { values: {}, errors: errors as FieldErrors<I & FieldValues> };
  };
}
