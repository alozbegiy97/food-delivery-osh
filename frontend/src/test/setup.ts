import '@testing-library/jest-dom/vitest';
import '../shared/i18n';

import { cleanup, configure } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

import i18n from '../shared/i18n';

// Containers on Windows/Docker Desktop are slow on the first render of a file.
configure({ asyncUtilTimeout: 5000 });

beforeEach(async () => {
  await i18n.changeLanguage('ru');
});

afterEach(() => {
  cleanup();
});
