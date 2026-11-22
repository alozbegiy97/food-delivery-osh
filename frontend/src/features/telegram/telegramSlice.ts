import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

// State of the Mini App session (DEC-142, DEC-152). Kept apart from
// `auth` so the site's AuthState and its tests stay unchanged; the access
// token itself still lives only in `auth` (memory, DEC-110).
//
// - idle: site mode (the Mini App bootstrap never ran);
// - loading: SDK loading or initData exchange in progress;
// - ready: signed in with initData;
// - not_linked: 409 TELEGRAM_NOT_LINKED (choice of a new or an existing
//   account, MA-4.1);
// - forbidden: 403 (Mini App is for customers only);
// - restart: initData missing, invalid or expired — reopen the Mini App;
// - disabled: 409 TELEGRAM_DISABLED;
// - error: SDK, network, rate limit or server error — retry possible.
export type TelegramPhase =
  'idle' | 'loading' | 'ready' | 'not_linked' | 'forbidden' | 'restart' | 'disabled' | 'error';

export interface TelegramState {
  /** True once the Mini App bootstrap started: switches baseApi to initData. */
  active: boolean;
  phase: TelegramPhase;
  /** Incremented by "Повторить"; the bootstrap runs again. */
  attempt: number;
}

const initialState: TelegramState = { active: false, phase: 'idle', attempt: 0 };

export const telegramSlice = createSlice({
  name: 'telegram',
  initialState,
  reducers: {
    telegramStarted(state) {
      state.active = true;
      state.phase = 'loading';
    },
    telegramPhaseChanged(state, action: PayloadAction<TelegramPhase>) {
      state.phase = action.payload;
    },
    telegramRetried(state) {
      state.attempt += 1;
      state.phase = 'loading';
    },
  },
});

export const { telegramStarted, telegramPhaseChanged, telegramRetried } = telegramSlice.actions;

interface WithTelegram {
  telegram?: TelegramState;
}

export const selectTelegramActive = (state: WithTelegram) => state.telegram?.active ?? false;
export const selectTelegramPhase = (state: WithTelegram) => state.telegram?.phase ?? 'idle';
export const selectTelegramAttempt = (state: WithTelegram) => state.telegram?.attempt ?? 0;
