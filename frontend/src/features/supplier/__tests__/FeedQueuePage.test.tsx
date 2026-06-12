import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { FeedQueuePage } from '../pages/FeedQueuePage';

const SUPPLIER = { id: 1, name: 'ТестПоставщик' };

function makeEntry(overrides = {}) {
  return {
    id: 101,
    supplier_sku: 'XYZ-999',
    data: { name: 'Gear Pump', price: 450.0 },
    match_candidates: [
      {
        product_id: 42,
        score: 0.88,
        name: 'Gear Pump 100',
        sku: 'GP-001',
        category: 'Насосы',
        brand: 'Grundfos',
      },
    ],
    ...overrides,
  };
}

function makeQueuePage(entries = [makeEntry()], count?: number) {
  return { count: count ?? entries.length, next: null, previous: null, results: entries };
}

function baseHandlers(queueOverride = makeQueuePage()) {
  return [
    http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
    http.get('/api/supplier-feed/feeds/5/queue/', () => HttpResponse.json(queueOverride)),
  ];
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route
        path="/suppliers/:id/feeds/:feedId/queue"
        element={<FeedQueuePage />}
      />
    </Routes>,
    { route: '/suppliers/1/feeds/5/queue' },
  );
}

describe('FeedQueuePage', () => {
  it('renders entry list with supplier_sku, data fields, and candidates', async () => {
    server.use(...baseHandlers());
    renderPage();

    expect(await screen.findByText('ТестПоставщик')).toBeInTheDocument();
    expect(screen.getByText('XYZ-999')).toBeInTheDocument();
    expect(screen.getByText('Gear Pump')).toBeInTheDocument();
    expect(screen.getByText('Gear Pump 100')).toBeInTheDocument();
    expect(screen.getByText('GP-001')).toBeInTheDocument();
    expect(screen.getByText('Насосы')).toBeInTheDocument();

    expect(screen.getByRole('button', { name: /подтвердить/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /пропустить/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /найти вручную/i })).toBeInTheDocument();
  });

  it('"Подтвердить" calls POST resolve with product_id and removes the entry', async () => {
    let resolveBody: unknown;

    server.use(
      ...baseHandlers(),
      http.post('/api/supplier-feed/feeds/5/queue/101/resolve/', async ({ request }) => {
        resolveBody = await request.json();
        return HttpResponse.json({ ...makeEntry(), product_id: 42 });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('XYZ-999');
    await user.click(screen.getByRole('button', { name: /подтвердить/i }));

    await waitFor(() => expect(resolveBody).toEqual({ product_id: 42 }));
    await waitFor(() => expect(screen.queryByText('XYZ-999')).not.toBeInTheDocument());
  });

  it('last entry on last page resolved: redirects to feed page', async () => {
    server.use(
      ...baseHandlers(),
      http.post('/api/supplier-feed/feeds/5/queue/101/resolve/', async () => {
        return HttpResponse.json({ ...makeEntry(), skipped: true });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/suppliers/:id/feeds/:feedId/queue" element={<FeedQueuePage />} />
        <Route path="/suppliers/:id/feeds/:feedId" element={<div>Страница выгрузки</div>} />
      </Routes>,
      { route: '/suppliers/1/feeds/5/queue' },
    );

    await screen.findByText('XYZ-999');
    await user.click(screen.getByRole('button', { name: /пропустить/i }));

    await waitFor(() => {
      expect(screen.getByText('Страница выгрузки')).toBeInTheDocument();
    });
  });

  it('"Пропустить" calls POST resolve with skipped:true and removes the entry', async () => {
    let resolveBody: unknown;

    server.use(
      ...baseHandlers(),
      http.post('/api/supplier-feed/feeds/5/queue/101/resolve/', async ({ request }) => {
        resolveBody = await request.json();
        return HttpResponse.json({ ...makeEntry(), skipped: true });
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await screen.findByText('XYZ-999');
    await user.click(screen.getByRole('button', { name: /пропустить/i }));

    await waitFor(() => expect(resolveBody).toEqual({ skipped: true }));
    await waitFor(() => expect(screen.queryByText('XYZ-999')).not.toBeInTheDocument());
  });

  describe('"Найти вручную" modal', () => {
    beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
    afterEach(() => vi.useRealTimers());

    it('opens modal, debounced search fires, selecting result calls resolve', async () => {
      const PRODUCT_RESULTS = {
        count: 1,
        next: null,
        previous: null,
        results: [
          { id: 99, name: 'Найденный товар', sku: 'NT-001', category: { name: 'Насосы' } },
        ],
      };
      let searchQuery: string | null = null;
      let resolveBody: unknown;

      server.use(
        ...baseHandlers(),
        http.get('/api/products/products/', ({ request }) => {
          const url = new URL(request.url);
          searchQuery = url.searchParams.get('q');
          return HttpResponse.json(PRODUCT_RESULTS);
        }),
        http.post('/api/supplier-feed/feeds/5/queue/101/resolve/', async ({ request }) => {
          resolveBody = await request.json();
          return HttpResponse.json({ ...makeEntry() });
        }),
      );

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
      renderPage();

      await screen.findByText('XYZ-999');

      // open modal
      await user.click(screen.getByRole('button', { name: /найти вручную/i }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      // type into search — debounce hasn't fired yet
      const input = screen.getByRole('textbox');
      await user.type(input, 'насос');
      expect(searchQuery).toBeNull();

      // advance past debounce
      await act(async () => {
        vi.advanceTimersByTime(400);
      });

      await waitFor(() => expect(searchQuery).toBe('насос'));
      expect(await screen.findByText('Найденный товар')).toBeInTheDocument();

      // select the result
      await user.click(screen.getByText('Найденный товар'));

      await waitFor(() => expect(resolveBody).toEqual({ product_id: 99 }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
