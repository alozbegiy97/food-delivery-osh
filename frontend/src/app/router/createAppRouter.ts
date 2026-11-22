import { createBrowserRouter } from 'react-router';

import { isMiniAppLocation, MINI_APP_BASENAME } from '../../shared/lib/miniAppMode';
import { miniAppRoutes } from './miniAppRoutes';
import { routes } from './routes';

/**
 * One router per page load (MA-4.0 / R1): the mode is decided from the
 * opened path first, then exactly one router is created — the site's
 * unchanged router, or the Mini App router under `/tg`.
 */
export function createAppRouter() {
  return isMiniAppLocation()
    ? createBrowserRouter(miniAppRoutes, { basename: MINI_APP_BASENAME })
    : createBrowserRouter(routes);
}
