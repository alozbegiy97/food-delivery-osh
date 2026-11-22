import { z } from 'zod';

import { isCompletePhone } from '../../shared/lib/phone';

// Limits of DEC-148, the same as on the backend (which checks them again).
export const LIMITS = {
  customerName: 150,
  comment: 500,
  addressText: 500,
  addressComment: 500,
  label: 80,
  entrance: 30,
  floor: 20,
  apartment: 30,
  cancellationReason: 500,
} as const;

const optional = (max: number) => z.string().trim().max(max, 'checkout.validation.tooLong');

export const checkoutSchema = z
  .object({
    delivery_type: z.enum(['delivery', 'pickup']),
    address_mode: z.enum(['saved', 'new']),
    address_id: z.string(),
    address_text: optional(LIMITS.addressText),
    entrance: optional(LIMITS.entrance),
    floor: optional(LIMITS.floor),
    apartment: optional(LIMITS.apartment),
    address_comment: optional(LIMITS.addressComment),
    label: optional(LIMITS.label),
    save_address: z.boolean(),
    customer_name: z
      .string()
      .trim()
      .min(1, 'validation.required')
      .max(LIMITS.customerName, 'checkout.validation.tooLong'),
    customer_phone: z.string().refine(isCompletePhone, 'validation.phoneInvalid'),
    comment: optional(LIMITS.comment),
  })
  .superRefine((value, ctx) => {
    if (value.delivery_type !== 'delivery') {
      return;
    }
    if (value.address_mode === 'saved' && !value.address_id) {
      ctx.addIssue({
        code: 'custom',
        path: ['address_id'],
        message: 'checkout.validation.chooseAddress',
      });
    }
    if (value.address_mode === 'new' && !value.address_text) {
      ctx.addIssue({ code: 'custom', path: ['address_text'], message: 'validation.required' });
    }
  });

export type CheckoutForm = z.input<typeof checkoutSchema>;
export type CheckoutValues = z.output<typeof checkoutSchema>;

/** A key for one checkout attempt (1–128 of [A-Za-z0-9_-], DEC-109); a retry
 * after a network error reuses it. Works also outside secure contexts. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}
