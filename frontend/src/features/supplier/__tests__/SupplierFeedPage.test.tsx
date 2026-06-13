import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { SupplierFeedPage } from '../pages/SupplierFeedPage';

const SUPPLIER = { id: 1, name: 'ТестПоставщик' };
const MAPPING = {
  id: 2,
  supplier: 1,
  name: 'Маппинг А',
  dataframe: 3,
  dataframe_detail: { id: 3, name: 'Пайп' },
  supplier_sku_column: 'sku',
  name_column: 'name',
  variable_columns: [],
  auto_match_threshold: 0.9,
  low_match_threshold: 0.5,
};

function makeFeed(overrides = {}) {
  return {
    id: 5,
    supplier: 1,
    feed_mapping: 2,
    status: 'draft',
    session_ids: [],
    error: null,
    created_at: '2026-05-31T10:00:00Z',
    total: 0,
    matched: 0,
    queued: 0,
    skipped: 0,
    ...overrides,
  };
}

function baseHandlers(feedOverride = makeFeed()) {
  return [
    http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
    http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
    http.get('/api/supplier-feed/feeds/5/', () => HttpResponse.json(feedOverride)),
  ];
}

function renderPage(pollInterval = 50) {
  return renderWithProviders(
    <Routes>
      <Route path="/suppliers/:id/feeds/:feedId" element={<SupplierFeedPage pollInterval={pollInterval} />} />
    </Routes>,
    { route: '/suppliers/1/feeds/5' },
  );
}

describe('SupplierFeedPage', () => {
  it('draft with no files: header renders, dropzone visible, Обработать disabled', async () => {
    server.use(...baseHandlers());
    renderPage();

    // Header: supplier name, mapping name, status badge
    expect(await screen.findByText('ТестПоставщик')).toBeInTheDocument();
    expect(await screen.findByText('Маппинг А')).toBeInTheDocument();
    expect(await screen.findByText('draft')).toBeInTheDocument();

    // Dropzone present
    expect(screen.getByLabelText('Загрузить файлы')).toBeInTheDocument();

    // Process button disabled
    const processBtn = screen.getByRole('button', { name: /обработать/i });
    expect(processBtn).toBeDisabled();
  });

  it('uploading a file appends it to the list and enables Обработать', async () => {
    const UPLOADED = {
      session_id: 'sess-abc',
      filename: 'prices.xlsx',
      size: 204800,
      uploaded_at: '2026-05-31T10:01:00Z',
    };
    let sessionIds: string[] = [];

    server.use(
      http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
      http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
      http.post('/api/supplier-feed/feeds/5/upload/', async () => {
        sessionIds = ['sess-abc'];
        return HttpResponse.json(UPLOADED, { status: 201 });
      }),
      http.get('/api/supplier-feed/feeds/5/', () =>
        HttpResponse.json(makeFeed({ session_ids: sessionIds })),
      ),
    );

    renderPage();
    await screen.findByText('ТестПоставщик');

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['data'], 'prices.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    fireEvent.change(input, { target: { files: [file] } });

    // File name appears
    expect(await screen.findByText('prices.xlsx')).toBeInTheDocument();

    // Обработать becomes active
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /обработать/i })).not.toBeDisabled();
    });
  });

  it('deleting a file calls DELETE endpoint and removes the file from the list', async () => {
    const UPLOADED = {
      session_id: 'sess-abc',
      filename: 'prices.xlsx',
      size: 204800,
      uploaded_at: '2026-05-31T10:01:00Z',
    };
    let sessionIds = ['sess-abc'];
    let deleteCalled = false;

    server.use(
      http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
      http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
      http.get('/api/supplier-feed/feeds/5/', () =>
        HttpResponse.json(makeFeed({ session_ids: sessionIds })),
      ),
      http.post('/api/supplier-feed/feeds/5/upload/', async () => {
        return HttpResponse.json(UPLOADED, { status: 201 });
      }),
      http.delete('/api/supplier-feed/feeds/5/files/sess-abc/', () => {
        deleteCalled = true;
        sessionIds = [];
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText('ТестПоставщик');

    // Upload a file first
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['data'], 'prices.xlsx', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [file] } });

    await screen.findByText('prices.xlsx');

    // Click the delete icon
    const deleteBtn = screen.getByRole('button', { name: /удалить файл/i });
    await user.click(deleteBtn);

    // DELETE was called
    await waitFor(() => expect(deleteCalled).toBe(true));

    // File removed from list
    await waitFor(() => {
      expect(screen.queryByText('prices.xlsx')).not.toBeInTheDocument();
    });
  });

  it('clicking Обработать calls POST /process/ and badge switches to Обработка...', async () => {
    const UPLOADED = {
      session_id: 'sess-xyz',
      filename: 'list.csv',
      size: 1024,
      uploaded_at: '2026-05-31T10:01:00Z',
    };
    let processCalled = false;
    let sessionIds: string[] = [];

    server.use(
      http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
      http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
      http.get('/api/supplier-feed/feeds/5/', () =>
        HttpResponse.json(
          makeFeed({
            session_ids: sessionIds,
            status: processCalled ? 'processing' : 'draft',
          }),
        ),
      ),
      http.post('/api/supplier-feed/feeds/5/upload/', async () => {
        sessionIds = ['sess-xyz'];
        return HttpResponse.json(UPLOADED, { status: 201 });
      }),
      http.post('/api/supplier-feed/feeds/5/process/', () => {
        processCalled = true;
        return HttpResponse.json(makeFeed({ status: 'processing', session_ids: ['sess-xyz'] }), {
          status: 202,
        });
      }),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText('ТестПоставщик');

    // Upload a file
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['data'], 'list.csv', { type: 'text/csv' });
    fireEvent.change(input, { target: { files: [file] } });
    await screen.findByText('list.csv');

    // Wait for button to be enabled
    const processBtn = await screen.findByRole('button', { name: /обработать/i });
    await waitFor(() => expect(processBtn).not.toBeDisabled());

    await user.click(processBtn);

    await waitFor(() => {
      expect(screen.getByText(/обработка/i)).toBeInTheDocument();
    });
  });

  it('polling processing → partial: queue button appears with correct count', async () => {
    let callCount = 0;

    server.use(
      http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
      http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
      http.get('/api/supplier-feed/feeds/5/', () => {
        callCount++;
        if (callCount <= 1) {
          return HttpResponse.json(
            makeFeed({ status: 'processing', session_ids: ['s1'] }),
          );
        }
        return HttpResponse.json(
          makeFeed({
            status: 'partial',
            session_ids: ['s1'],
            total: 50,
            matched: 35,
            queued: 15,
            skipped: 0,
          }),
        );
      }),
    );

    renderPage(50);

    // Wait for partial status with queue button
    await waitFor(
      () => {
        expect(screen.getByRole('link', { name: /разобрать очередь.*15/i })).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
  });

  it('polling processing → matched: success message and counters shown', async () => {
    let callCount = 0;

    server.use(
      http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
      http.get('/api/supplier-feed/mappings/2/', () => HttpResponse.json(MAPPING)),
      http.get('/api/supplier-feed/feeds/5/', () => {
        callCount++;
        if (callCount <= 1) {
          return HttpResponse.json(makeFeed({ status: 'processing', session_ids: ['s1'] }));
        }
        return HttpResponse.json(
          makeFeed({
            status: 'matched',
            session_ids: ['s1'],
            total: 40,
            matched: 40,
            queued: 0,
            skipped: 0,
          }),
        );
      }),
    );

    renderPage(50);

    await waitFor(
      () => {
        expect(screen.getByText(/все позиции сопоставлены/i)).toBeInTheDocument();
      },
      { timeout: 2000 },
    );

    expect(screen.getAllByText('40').length).toBeGreaterThanOrEqual(1); // counters
  });

  it('error status: renders error text and Удалить выгрузку button', async () => {
    server.use(
      ...baseHandlers(
        makeFeed({ status: 'error', error: 'Пайплайн завершился с ошибкой' }),
      ),
    );

    renderPage();

    expect(await screen.findByText('Пайплайн завершился с ошибкой')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /удалить выгрузку/i })).toBeInTheDocument();
  });

  it('clicking Удалить выгрузку calls DELETE /feeds/:id/ and navigates to supplier page', async () => {
    let deleteCalled = false;

    server.use(
      ...baseHandlers(makeFeed({ status: 'error', error: 'Ошибка' })),
      http.delete('/api/supplier-feed/feeds/5/', () => {
        deleteCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route
          path="/suppliers/:id/feeds/:feedId"
          element={<SupplierFeedPage pollInterval={50} />}
        />
        <Route path="/suppliers/:id" element={<div>Страница поставщика</div>} />
      </Routes>,
      { route: '/suppliers/1/feeds/5' },
    );

    await screen.findByText('Ошибка');
    await user.click(screen.getByRole('button', { name: /удалить выгрузку/i }));

    await waitFor(() => expect(deleteCalled).toBe(true));
    await waitFor(() => {
      expect(screen.getByText('Страница поставщика')).toBeInTheDocument();
    });
  });
});
