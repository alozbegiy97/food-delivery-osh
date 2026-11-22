import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import type { SerializedError } from '@reduxjs/toolkit';

import type { ApiErrorBody, ApiFieldError } from '../types/api';

export interface ApiErrorInfo {
  code: string;
  fields: ApiFieldError[];
}

/** Error code and field errors from an RTK Query error (DEC-103). */
export function apiErrorInfo(
  error: FetchBaseQueryError | SerializedError | undefined,
): ApiErrorInfo | null {
  if (!error) {
    return null;
  }
  if ('status' in error) {
    const body = error.data as Partial<ApiErrorBody> | undefined;
    const code =
      body?.error?.code ?? (error.status === 'FETCH_ERROR' ? 'NETWORK_ERROR' : 'HTTP_ERROR');
    const details = body?.error?.details;
    const fields = Array.isArray(details)
      ? details.filter((d): d is ApiFieldError => typeof d?.field === 'string')
      : [];
    return { code, fields };
  }
  return { code: 'HTTP_ERROR', fields: [] };
}
