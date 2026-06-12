import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { CategoryDetailPage } from '../pages/CategoryDetailPage';

const CATEGORY = { id: 5, name: 'Электроинструменты', slug: 'electro', parent: null, level: 0 };

const CHAR_TYPE_1 = {
  id: 10,
  name: 'voltage',
  label: 'Напряжение',
  value_type: 'string',
  options: [],
  unit: 'В',
  required: false,
  categories: [5],
};
const CHAR_TYPE_2 = {
  id: 11,
  name: 'power',
  label: 'Мощность',
  value_type: 'integer',
  options: [],
  unit: 'Вт',
  required: false,
  categories: [5],
};
const UNASSIGNED_PRODUCT = {
  id: 99,
  sku: 'SKU-99',
  name: 'Шуруповёрт',
  category: null,
  brand: null,
  description: '',
  status: 'active',
  characteristics: {},
  image_urls: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

function baseHandlers() {
  return [
    http.get('/api/products/categories/5/', () => HttpResponse.json(CATEGORY)),
    http.get('/api/products/characteristic-types/', ({ request }) => {
      const url = new URL(request.url);
      if (url.searchParams.get('category') === '5') {
        return HttpResponse.json({ count: 2, next: null, previous: null, results: [CHAR_TYPE_1, CHAR_TYPE_2] });
      }
      return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
    }),
    http.get('/api/products/products/', () =>
      HttpResponse.json({ count: 1, next: null, previous: null, results: [UNASSIGNED_PRODUCT] }),
    ),
  ];
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/products/categories/:id" element={<CategoryDetailPage />} />
    </Routes>,
    { route: '/products/categories/5' },
  );
}

describe('CategoryDetailPage', () => {
  describe('Page header', () => {
    it('renders category name as page title', async () => {
      server.use(...baseHandlers());
      renderPage();
      expect(await screen.findByRole('heading', { name: 'Электроинструменты' })).toBeInTheDocument();
    });
  });

  describe('Characteristics section', () => {
    it('renders linked char-type rows', async () => {
      server.use(...baseHandlers());
      renderPage();
      expect(await screen.findByText('Напряжение')).toBeInTheDocument();
      expect(screen.getByText('Мощность')).toBeInTheDocument();
    });

    it('adds a char-type via the MultiSelect picker', async () => {
      const captured: { body?: unknown } = {};
      const NEW_CHAR = {
        id: 20,
        name: 'weight',
        label: 'Вес',
        value_type: 'string',
        options: [],
        unit: 'кг',
        required: false,
        categories: [],
      };
      server.use(
        http.get('/api/products/categories/5/', () => HttpResponse.json(CATEGORY)),
        http.get('/api/products/characteristic-types/', ({ request }) => {
          const url = new URL(request.url);
          if (url.searchParams.get('search')) {
            return HttpResponse.json({ count: 1, next: null, previous: null, results: [NEW_CHAR] });
          }
          return HttpResponse.json({ count: 2, next: null, previous: null, results: [CHAR_TYPE_1, CHAR_TYPE_2] });
        }),
        http.get('/api/products/products/', () =>
          HttpResponse.json({ count: 1, next: null, previous: null, results: [UNASSIGNED_PRODUCT] }),
        ),
        http.post('/api/products/categories/5/characteristics/', async ({ request }) => {
          captured.body = await request.json();
          return HttpResponse.json({}, { status: 201 });
        }),
      );
      renderPage();

      await screen.findByText('Напряжение');

      const picker = screen.getByPlaceholderText('Добавить тип...');
      await userEvent.click(picker);
      await userEvent.type(picker, 'вес');

      const option = await screen.findByRole('option', { name: 'Вес' }, { timeout: 2000 });
      await userEvent.click(option);

      await waitFor(() => {
        expect(captured.body).toEqual({ char_type_id: 20 });
      });
    });

    it('shows usage count popover on remove then deletes on confirm', async () => {
      const deleted: { charId: number } = { charId: 0 };
      server.use(
        http.get('/api/products/categories/5/', () => HttpResponse.json(CATEGORY)),
        http.get('/api/products/characteristic-types/', ({ request }) => {
          const url = new URL(request.url);
          if (url.searchParams.get('category') === '5') {
            return HttpResponse.json({ count: 2, next: null, previous: null, results: [CHAR_TYPE_1, CHAR_TYPE_2] });
          }
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
        }),
        http.get('/api/products/products/', () =>
          HttpResponse.json({ count: 1, next: null, previous: null, results: [UNASSIGNED_PRODUCT] }),
        ),
        http.get('/api/products/categories/5/characteristics/10/usage/', () =>
          HttpResponse.json({ count: 3 }),
        ),
        http.delete('/api/products/categories/5/characteristics/10/', () => {
          deleted.charId = 10;
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderPage();

      await screen.findByText('Напряжение');

      const trashBtns = screen.getAllByRole('button', { name: 'Удалить тип' });
      await userEvent.click(trashBtns[0]);

      expect(await screen.findByText(/Используется в 3 продуктах/)).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Удалить' }));

      await waitFor(() => expect(deleted.charId).toBe(10));
    });
  });

  describe('Products section', () => {
    it('renders unassigned products table', async () => {
      server.use(...baseHandlers());
      renderPage();
      expect(await screen.findByText('Шуруповёрт')).toBeInTheDocument();
      expect(screen.getByText('SKU-99')).toBeInTheDocument();
    });

    it('enables assign button after selecting a product and fires assign mutation', async () => {
      const captured: { body?: unknown } = {};
      server.use(
        ...baseHandlers(),
        http.post('/api/products/categories/5/assign-products/', async ({ request }) => {
          captured.body = await request.json();
          return HttpResponse.json({ assigned: 1 });
        }),
      );
      renderPage();

      await screen.findByText('Шуруповёрт');

      const assignBtn = screen.getByRole('button', { name: /Назначить/ });
      expect(assignBtn).toBeDisabled();

      await userEvent.click(screen.getByRole('checkbox', { name: 'Шуруповёрт' }));
      expect(assignBtn).toBeEnabled();

      await userEvent.click(assignBtn);

      await waitFor(() => {
        expect(captured.body).toEqual({ product_ids: [99] });
      });
    });
  });
});
