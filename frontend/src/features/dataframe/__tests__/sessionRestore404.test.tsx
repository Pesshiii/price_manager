import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse, server } from '@/test/msw';
import { renderWithProviders } from '@/test/renderWithProviders';
import { DataframeEditorPage } from '../pages/DataframeEditorPage';

vi.mock('react-virtuoso', () => ({
  TableVirtuoso: () => <div data-testid="virtuoso" />,
}));

const registry = {
  readers: [{ name: 'read_csv', label: 'CSV', extensions: ['csv'], args: [] }],
  transforms: [],
};

describe('DataframeEditorPage session 404', () => {
  it('clears ?session= and re-shows dropzone when session metadata is 404', async () => {
    server.use(
      http.get('/api/dataframe/registry/', () => HttpResponse.json(registry)),
      http.get('/api/dataframe/sessions/bogus/', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );

    renderWithProviders(<DataframeEditorPage />, { route: '/?session=bogus' });

    await waitFor(() =>
      expect(screen.getByLabelText('Загрузить файл')).toBeInTheDocument(),
    );
  });
});
