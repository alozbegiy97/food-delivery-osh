import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import { telegramRetried, type TelegramPhase } from '../telegramSlice';

// Service screens of the Mini App (UI_UX §3 "Служебные экраны"; decisions
// Q2, Q6). None of them links to the site, to /login or to logout.

function Screen({
  title,
  text,
  role = 'alert',
  children,
}: {
  title: string;
  text: string;
  role?: 'alert' | 'status';
  children?: ReactNode;
}) {
  return (
    <section
      role={role}
      aria-live={role === 'status' ? 'polite' : 'assertive'}
      className="mx-auto flex w-full max-w-md flex-col items-center gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-6 text-center"
    >
      <h1 className="text-xl font-bold text-ink-900">{title}</h1>
      <p className="text-ink-600">{text}</p>
      {children}
    </section>
  );
}

export function TelegramLoadingScreen() {
  const { t } = useTranslation();
  return (
    <Screen role="status" title={t('telegram.loading.title')} text={t('telegram.loading.text')} />
  );
}

export function TelegramPhaseScreen({
  phase,
}: {
  phase: Exclude<TelegramPhase, 'idle' | 'ready' | 'not_linked'>;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  if (phase === 'loading') {
    return <TelegramLoadingScreen />;
  }
  return (
    <Screen title={t(`telegram.${phase}.title`)} text={t(`telegram.${phase}.text`)}>
      {phase === 'error' && (
        <button
          type="button"
          onClick={() => dispatch(telegramRetried())}
          className="min-h-11 rounded-full bg-accent-700 px-5 font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t('telegram.retry')}
        </button>
      )}
    </Screen>
  );
}
