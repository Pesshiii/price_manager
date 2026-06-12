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

describe('DataframeEditorPage session restore', () => {
  it('restores uploaded file metadata when ?session= is set in URL', async () => {
    server.use(
      http.get('/api/dataframe/registry/', () => HttpResponse.json(registry)),
      http.get('/api/dataframe/sessions/abc/', () =>
        HttpResponse.json({
          session_id: 'abc',
          filename: 'products.xlsx',
          size: 2048,
          uploaded_at: '2026-05-17T10:00:00Z',
        }),
      ),
    );

    renderWithProviders(<DataframeEditorPage />, { route: '/?session=abc' });

    await waitFor(() => expect(screen.getByText('products.xlsx')).toBeInTheDocument());
  });
});
