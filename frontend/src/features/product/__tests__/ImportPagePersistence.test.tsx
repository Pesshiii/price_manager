import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse, server } from '@/test/msw';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ImportPage } from '../pages/ImportPage';
import { STORAGE_KEY, defaultPersistedState } from '../persistence';

vi.mock('react-virtuoso', () => ({
  TableVirtuoso: () => <div data-testid="virtuoso" />,
}));

const PIPELINE = {
  id: 1,
  name: 'Test pipeline',
  description: '',
  instructions: { reader: { func: 'read_csv', args: {} }, transforms: [] },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function baseHandlers() {
  server.use(
    http.get('/api/dataframe/pipelines/', () => HttpResponse.json([PIPELINE])),
    http.get('/api/dataframe/registry/', () =>
      HttpResponse.json({
        readers: [{ name: 'read_csv', label: 'CSV', extensions: ['csv'], args: [] }],
        transforms: [],
      }),
    ),
    http.get('/api/products/categories/', () =>
      HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
    ),
    http.get('/api/products/characteristic-types/', () =>
      HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
    ),
  );
}

function renderImport() {
  return renderWithProviders(
    <Routes>
      <Route path="/products/import" element={<ImportPage />} />
    </Routes>,
    { route: '/products/import' },
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe('ImportPage persistence', () => {
  it('hydrates from localStorage and lands on the saved step with restored session', async () => {
    baseHandlers();
    server.use(
      http.get('/api/dataframe/sessions/abc/', () =>
        HttpResponse.json({
          session_id: 'abc',
          filename: 'products.csv',
          size: 1024,
          uploaded_at: '2026-05-17T10:00:00Z',
        }),
      ),
    );

    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...defaultPersistedState(),
        mode: 'saved',
        step: 1,
        sessionId: 'abc',
        filename: 'products.csv',
        pipelineId: 1,
        columns: ['sku', 'name'],
        mapping: { sku: { column: 'sku' } },
      }),
    );

    renderImport();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Проверить' })).toBeInTheDocument(),
    );
    // mapping step rendered and column label visible somewhere on screen
    expect(screen.getAllByText('sku').length).toBeGreaterThan(0);
  });

  it('falls back to step 0 and re-shows source picker when session is 404', async () => {
    baseHandlers();
    server.use(
      http.get('/api/dataframe/sessions/bogus/', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    );

    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...defaultPersistedState(),
        mode: 'saved',
        step: 1,
        sessionId: 'bogus',
        filename: 'gone.csv',
        pipelineId: 1,
        columns: ['sku'],
        mapping: { sku: { column: 'sku' } },
      }),
    );

    renderImport();

    // After 404 the page rewinds to step 0 — "Загрузить файл" button is visible there
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Загрузить файл/ })).toBeInTheDocument(),
    );
    // Mapping step "Проверить" should no longer be visible
    expect(screen.queryByRole('button', { name: 'Проверить' })).not.toBeInTheDocument();
  });
});
