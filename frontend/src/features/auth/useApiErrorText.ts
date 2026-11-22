import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { useTranslation } from 'react-i18next';

import { apiErrorInfo } from '../../shared/api/errors';

/** Localized text for an API error code (DEC-103: text by `code`). */
export function useApiErrorText() {
  const { t } = useTranslation();
  return (error: FetchBaseQueryError | SerializedError | undefined): string | null => {
    const info = apiErrorInfo(error);
    if (!info) {
      return null;
    }
    return t(`errors.codes.${info.code}`, { defaultValue: t('errors.codes.default') });
  };
}
