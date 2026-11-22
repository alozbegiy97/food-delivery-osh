import { fireEvent, render, screen } from '@testing-library/react';
import { useTranslation } from 'react-i18next';
import { describe, expect, it } from 'vitest';

import { LanguageSwitcher } from './LanguageSwitcher';

function Title() {
  const { t } = useTranslation();
  return <h1>{t('status.title')}</h1>;
}

describe('LanguageSwitcher', () => {
  it('switches the UI language between RU, KY and UZ', () => {
    render(
      <>
        <LanguageSwitcher />
        <Title />
      </>,
    );

    expect(screen.getByRole('heading')).toHaveTextContent('Состояние системы');
    expect(screen.getByRole('button', { name: 'Русский' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: 'Кыргызча' }));
    expect(screen.getByRole('heading')).toHaveTextContent('Системанын абалы');
    expect(document.documentElement.lang).toBe('ky');

    fireEvent.click(screen.getByRole('button', { name: 'Oʻzbekcha' }));
    expect(screen.getByRole('heading')).toHaveTextContent('Tizim holati');
    expect(screen.getByRole('button', { name: 'Oʻzbekcha' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
});
