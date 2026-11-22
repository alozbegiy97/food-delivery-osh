import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import type { TFunction } from 'i18next';

import { apiErrorInfo } from '../../shared/api/errors';
import type { ApiErrorBody, CartIssueOut } from '../../shared/types/api';

/** One problem of a cart line or of a selection, in the current language. */
export function issueText(t: TFunction, issue: CartIssueOut): string {
  return t(`cart.issues.${issue.code}`, {
    defaultValue: t('cart.issues.default'),
    group: issue.group_name ?? '',
    name: issue.modifier_name ?? '',
    limit: issue.limit ?? '',
  });
}

function issuesOf(error: FetchBaseQueryError | SerializedError | undefined): CartIssueOut[] {
  if (!error || !('status' in error)) {
    return [];
  }
  const details = (error.data as Partial<ApiErrorBody> | undefined)?.error?.details;
  return Array.isArray(details)
    ? details.filter((d): d is CartIssueOut => typeof (d as CartIssueOut)?.code === 'string')
    : [];
}

/** Text lines for a failed cart request (API §1.1 codes, DEC-146 limits). */
export function cartErrorLines(
  t: TFunction,
  error: FetchBaseQueryError | SerializedError | undefined,
): string[] {
  const info = apiErrorInfo(error);
  if (!info) {
    return [];
  }
  if (info.code === 'ITEM_UNAVAILABLE' || info.code === 'MODIFIER_CONSTRAINT_VIOLATION') {
    const lines = issuesOf(error).map((issue) => issueText(t, issue));
    return [t(`cart.errors.${info.code}`), ...new Set(lines)];
  }
  if (info.code === 'VALIDATION_ERROR') {
    const fields = new Set(info.fields.map((field) => field.field));
    if (fields.has('cart')) {
      return [t('cart.errors.tooManyLines')];
    }
    if (fields.has('quantity')) {
      return [t('cart.errors.lineQuantity')];
    }
  }
  if (info.code === 'FORBIDDEN') {
    return [t('cart.staffOnly')];
  }
  if (info.code === 'NOT_FOUND') {
    return [t('cart.errors.lineGone')];
  }
  return [t(`errors.codes.${info.code}`, { defaultValue: t('errors.codes.default') })];
}
