import { z } from 'zod';

import { isCompletePhone } from '../../shared/lib/phone';
import { fullName, registerSchema } from '../auth/validation';

/**
 * Name and phone of the Mini App profile (DEC-160 п. 2, DEC-141). The name
 * follows the registration rules. An empty phone is allowed only when the
 * profile has no phone yet (it means "do not change"); an existing phone may
 * be replaced but never removed. Messages are i18n keys; the backend makes
 * the final decision.
 */
export function profileDetailsSchema(hadPhone: boolean) {
  return z.object({
    full_name: fullName,
    phone: z
      .string()
      .refine((v) => v === '' || isCompletePhone(v), 'validation.phoneInvalid')
      .refine((v) => !(hadPhone && v === ''), 'validation.phoneCannotRemove'),
  });
}

export type ProfileDetailsValues = z.infer<ReturnType<typeof profileDetailsSchema>>;

/**
 * Email and password of a Telegram-only account (DEC-160 п. 5): exactly the
 * registration rules of these two fields (DEC-141, DEC-96), taken from
 * `registerSchema` without changing it. No password confirmation.
 */
export const credentialsSchema = registerSchema.pick({ email: true, password: true });

export type CredentialsValues = z.infer<typeof credentialsSchema>;
