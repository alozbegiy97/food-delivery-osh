import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Navigate, useLocation } from 'react-router';

import { useMeQuery } from '../authApi';
import {
  selectPasswordChangeRequired,
  selectSessionStatus,
  sessionEnded,
  sessionStarted,
} from '../authSlice';
import { CHANGE_PASSWORD_PATH } from '../paths';
import { refreshAccessToken } from '../refreshSession';

/** Restores the session from the refresh cookie on application load (DEC-110). */
export function SessionBootstrap({ children }: { children: ReactNode }) {
  const dispatch = useDispatch();
  const status = useSelector(selectSessionStatus);

  useEffect(() => {
    if (status !== 'unknown') {
      return;
    }
    let cancelled = false;
    void refreshAccessToken().then((token) => {
      if (cancelled) {
        return;
      }
      dispatch(token ? sessionStarted(token) : sessionEnded());
    });
    return () => {
      cancelled = true;
    };
  }, [dispatch, status]);

  return children;
}

/** Protected route: waits for the session, sends guests to /login?returnTo=…,
 * and keeps users with a temporary password on the change screen (DEC-28). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const location = useLocation();
  const status = useSelector(selectSessionStatus);
  const mustChange = useSelector(selectPasswordChangeRequired);
  const { isLoading } = useMeQuery(undefined, { skip: status !== 'authenticated' });

  if (status === 'unknown' || (status === 'authenticated' && isLoading)) {
    return (
      <p role="status" className="text-ink-600">
        {t('auth.checkingSession')}
      </p>
    );
  }
  if (status === 'anonymous') {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  if (mustChange && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }
  return children;
}
