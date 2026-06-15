import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { ProductListPage } from '../pages/ProductListPage';

const PRODUCT = {
  id: 1,
  sku: 'SKU-1',
  name: 'Дрель',
  category: null,
  brand: null,
  description: '',
  status: 'active',
  characteristics: {},
  image_urls: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

describe('ProductListPage', () => {
  it('renders product rows from API', async () => {
    server.use(
      http.get('/api/products/products/', () =>
        HttpResponse.json({ count: 1, next: null, previous: null, results: [PRODUCT] }),
      ),
      http.get('/api/products/products/facets/', () => HttpResponse.json({})),
      http.get('/api/products/categories/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/products/brands/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/products/characteristic-types/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/pricing/price-types/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );

    renderWithProviders(
      <Routes>
        <Route path="/products" element={<ProductListPage />} />
      </Routes>,
      { route: '/products' },
    );

    await waitFor(() => {
      expect(screen.getByText('SKU-1')).toBeInTheDocument();
      expect(screen.getByText('Дрель')).toBeInTheDocument();
    });
  });

  it('shows empty state when API returns 0 products', async () => {
    server.use(
      http.get('/api/products/products/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/products/products/facets/', () => HttpResponse.json({})),
      http.get('/api/products/categories/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/products/brands/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/products/characteristic-types/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
      http.get('/api/pricing/price-types/', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );

    renderWithProviders(
      <Routes>
        <Route path="/products" element={<ProductListPage />} />
      </Routes>,
      { route: '/products' },
    );

    expect(await screen.findByText('Товары не найдены')).toBeInTheDocument();
  });
});
