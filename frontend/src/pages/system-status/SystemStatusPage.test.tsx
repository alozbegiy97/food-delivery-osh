import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { jsonResponse, renderWithProviders } from '../../test/renderWithProviders';
import { SystemStatusPage } from './SystemStatusPage';

const errorBody = {
  error: { code: 'SERVICE_UNAVAILABLE', message: 'x', details: [], request_id: 'r1' },
};

describe('SystemStatusPage', () => {
  it('calls the health endpoint and shows the API status', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(jsonResponse({ status: 'ok', database: 'ok', postgis: '3.6.0' }));

    renderWithProviders(<SystemStatusPage />);

    expect(screen.getByText('Проверяем подключение к API…')).toBeInTheDocument();
    expect(await screen.findByText('3.6.0')).toBeInTheDocument();
    expect(screen.getAllByText('Работает')).toHaveLength(2);

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/health');
  });

  it('shows an error with a working retry button', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse(errorBody, 503))
      .mockResolvedValueOnce(jsonResponse({ status: 'ok', database: 'ok', postgis: '3.6.0' }));

    renderWithProviders(<SystemStatusPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить ответ API');

    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));

    expect(await screen.findByText('3.6.0')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
