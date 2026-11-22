import { z } from 'zod';

import { isCompletePhone } from '../../shared/lib/phone';

// Same rules as the backend (DEC-96, DEC-141): length in Unicode code
// points, any Unicode letter, any Unicode decimal digit. The backend makes
// the final decision. Messages are i18n keys.
const PASSWORD_MIN = 8;
const PASSWORD_MAX = 128;

const length = (value: string) => [...value].length;

export const newPassword = z
  .string()
  .refine(
    (v) => length(v) >= PASSWORD_MIN && length(v) <= PASSWORD_MAX,
    'validation.passwordLength',
  )
  .refine((v) => /\p{L}/u.test(v), 'validation.passwordLetter')
  .refine((v) => /\p{Nd}/u.test(v), 'validation.passwordDigit');

const email = z
  .string()
  .trim()
  .min(1, 'validation.required')
  .max(255, 'validation.emailInvalid')
  .pipe(z.email('validation.emailInvalid'));

export const fullName = z
  .string()
  .trim()
  .refine((v) => length(v) >= 1, 'validation.required')
  .refine((v) => length(v) <= 150, 'validation.nameTooLong')
  // eslint-disable-next-line no-control-regex
  .refine((v) => !/[\u0000-\u001f\u007f-\u009f]/.test(v), 'validation.nameInvalid');

export const loginSchema = z.object({
  email: z.string().trim().min(1, 'validation.required'),
  password: z.string().min(1, 'validation.required'),
});

export const registerSchema = z.object({
  email,
  full_name: fullName,
  phone: z.string().refine((v) => v === '' || isCompletePhone(v), 'validation.phoneInvalid'),
  password: newPassword,
});

export const forgotSchema = z.object({ email });

export const resetSchema = z
  .object({ new_password: newPassword, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, {
    message: 'validation.passwordsDiffer',
    path: ['confirm'],
  });

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'validation.required'),
    new_password: newPassword,
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, {
    message: 'validation.passwordsDiffer',
    path: ['confirm'],
  });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type ForgotValues = z.infer<typeof forgotSchema>;
export type ResetValues = z.infer<typeof resetSchema>;
export type ChangePasswordValues = z.infer<typeof changePasswordSchema>;
