import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { ProductFiltersSidebar } from '../components/ProductFiltersSidebar';
import { useProductFiltersFromUrl } from '../hooks/useProductFiltersFromUrl';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="search">{location.search}</div>;
}

function Host() {
  const { filters, patchFilters, toggleCharValue, resetFilters } = useProductFiltersFromUrl();
  return (
    <>
      <LocationProbe />
      <ProductFiltersSidebar
        filters={filters}
        patchFilters={patchFilters}
        toggleCharValue={toggleCharValue}
        resetFilters={resetFilters}
        priceTypes={[]}
      />
    </>
  );
}

function setupServer() {
  server.use(
    http.get('/api/products/categories/', () =>
      HttpResponse.json({
        count: 1,
        next: null,
        previous: null,
        results: [{ id: 1, name: 'Cat', slug: 'cat', parent: null, level: 0 }],
      }),
    ),
    http.get('/api/products/brands/', () =>
      HttpResponse.json({
        count: 1,
        next: null,
        previous: null,
        results: [{ id: 1, name: 'Brand', slug: 'brand' }],
      }),
    ),
    http.get('/api/products/products/facets/', () =>
      HttpResponse.json({
        color: {
          label: 'Цвет',
          unit: '',
          value_type: 'string',
          buckets: [
            { value: 'red', count: 5 },
            { value: 'blue', count: 2 },
          ],
        },
      }),
    ),
  );
}

describe('ProductFiltersSidebar', () => {
  it('toggling a facet writes char__color to the URL and shows the count badge', async () => {
    setupServer();
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Host />} />
      </Routes>,
    );

    await waitFor(() => expect(screen.getByText('Цвет')).toBeInTheDocument());
    expect(await screen.findByText('5')).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: /red/ }));
    await waitFor(() => {
      expect(screen.getByTestId('search').textContent).toContain('char__color=red');
    });
  });

  it('writes search query q= to URL on typing', async () => {
    setupServer();
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/" element={<Host />} />
      </Routes>,
    );
    const search = screen.getByLabelText('Поиск');
    await user.type(search, 'drill');
    await waitFor(() => {
      expect(screen.getByTestId('search').textContent).toContain('q=drill');
    });
  });
});
