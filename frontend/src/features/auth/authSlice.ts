import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

// The access token lives only in this in-memory store (DEC-110): never in
// localStorage, sessionStorage, IndexedDB or JS-readable cookies.
export type SessionStatus = 'unknown' | 'authenticated' | 'anonymous';

export interface AuthState {
  accessToken: string | null;
  status: SessionStatus;
  // Set when the API answers 403 PASSWORD_CHANGE_REQUIRED (DEC-28).
  passwordChangeRequired: boolean;
}

const initialState: AuthState = {
  accessToken: null,
  status: 'unknown',
  passwordChangeRequired: false,
};

export const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    sessionStarted(state, action: PayloadAction<string>) {
      state.accessToken = action.payload;
      state.status = 'authenticated';
    },
    sessionEnded(state) {
      state.accessToken = null;
      state.status = 'anonymous';
      state.passwordChangeRequired = false;
    },
    passwordChangeRequired(state, action: PayloadAction<boolean>) {
      state.passwordChangeRequired = action.payload;
    },
  },
});

export const { sessionStarted, sessionEnded, passwordChangeRequired } = authSlice.actions;

interface WithAuth {
  auth: AuthState;
}

export const selectAccessToken = (state: WithAuth) => state.auth.accessToken;
export const selectSessionStatus = (state: WithAuth) => state.auth.status;
export const selectPasswordChangeRequired = (state: WithAuth) => state.auth.passwordChangeRequired;
