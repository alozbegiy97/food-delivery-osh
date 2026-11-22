import { combineReducers, configureStore } from '@reduxjs/toolkit';

import { authSlice } from '../../features/auth/authSlice';
import { telegramSlice } from '../../features/telegram/telegramSlice';
import { baseApi } from '../../shared/api/baseApi';

const rootReducer = combineReducers({
  [baseApi.reducerPath]: baseApi.reducer,
  auth: authSlice.reducer,
  telegram: telegramSlice.reducer,
});

export type RootState = ReturnType<typeof rootReducer>;

/** `preloaded` lets tests start with a known session state. */
export function makeStore(preloaded?: Partial<RootState>) {
  return configureStore({
    reducer: rootReducer,
    preloadedState: preloaded,
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
  });
}

export const store = makeStore();

export type AppStore = ReturnType<typeof makeStore>;
export type AppDispatch = AppStore['dispatch'];
