import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { SupplierDetailPage } from '../pages/SupplierDetailPage';

const SUPPLIER = { id: 1, name: 'ТестПоставщик' };
const MAPPING = {
  id: 2,
  supplier: 1,
  name: 'Маппинг 1',
  dataframe: 3,
  dataframe_detail: { id: 3, name: 'Пайп' },
  supplier_sku_column: 'sku',
  name_column: 'name',
  variable_columns: [],
  auto_match_threshold: 0.9,
  low_match_threshold: 0.5,
};
const FEED = {
  id: 10,
  supplier: 1,
  feed_mapping: 2,
  status: 'draft',
  session_ids: [],
  error: null,
  created_at: '2026-01-15T10:30:00Z',
};

function baseHandlers() {
  return [
    http.get('/api/suppliers/1/', () => HttpResponse.json(SUPPLIER)),
    http.get('/api/supplier-feed/mappings/', () => HttpResponse.json([MAPPING])),
    http.get('/api/supplier-feed/feeds/', () => HttpResponse.json([FEED])),
  ];
}

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
    </Routes>,
    { route: '/suppliers/1' },
  );
}

describe('SupplierDetailPage — feeds section', () => {
  it('renders feeds table with mapping name and created date', async () => {
    server.use(...baseHandlers());
    renderPage();

    expect(await screen.findByText('Выгрузки')).toBeInTheDocument();
    // Date is unique — only appears in the feeds table
    expect(screen.getByText('15.01.2026')).toBeInTheDocument();
    // Mapping name appears in both mappings table and feeds table
    expect(screen.getAllByText('Маппинг 1').length).toBeGreaterThanOrEqual(2);
  });

  it('shows a status badge matching the feed status', async () => {
    server.use(...baseHandlers());
    renderPage();

    await waitFor(() => {
      expect(screen.getByText('draft')).toBeInTheDocument();
    });
  });

  it('clicking a row navigates to the feed detail URL', async () => {
    server.use(...baseHandlers());
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        <Route path="/suppliers/:id/feeds/:feedId" element={<div>Страница фида</div>} />
      </Routes>,
      { route: '/suppliers/1' },
    );

    // Use the date cell (unique to the feeds table) to find the row
    const dateCell = await screen.findByText('15.01.2026');
    await user.click(dateCell.closest('tr')!);

    await waitFor(() => {
      expect(screen.getByText('Страница фида')).toBeInTheDocument();
    });
  });

  it('opens "Новая выгрузка" modal with mapping options in the Select', async () => {
    server.use(...baseHandlers());
    const user = userEvent.setup();
    renderPage();

    await screen.findByText('Выгрузки');
    await user.click(screen.getByRole('button', { name: /новая выгрузка/i }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('Маппинг')).toBeInTheDocument();
  });

  it('submitting the modal calls POST and redirects to the new feed URL', async () => {
    server.use(
      ...baseHandlers(),
      http.post('/api/supplier-feed/feeds/', async ({ request }) => {
        const body = await request.json() as Record<string, unknown>;
        expect(body).toMatchObject({ supplier: 1, feed_mapping: 2 });
        return HttpResponse.json({ ...FEED, id: 99 }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        <Route path="/suppliers/:id/feeds/:feedId" element={<div>Страница фида 99</div>} />
      </Routes>,
      { route: '/suppliers/1' },
    );

    await screen.findByText('Выгрузки');
    await user.click(screen.getByRole('button', { name: /новая выгрузка/i }));

    const dialog = await screen.findByRole('dialog');
    const combobox = dialog.querySelector('input')!;
    await user.click(combobox);
    const option = await screen.findByRole('option', { name: 'Маппинг 1' });
    await user.click(option);

    await user.click(screen.getByRole('button', { name: /создать/i }));

    await waitFor(() => {
      expect(screen.getByText('Страница фида 99')).toBeInTheDocument();
    });
  });

  it('"Управление связями" navigates to the links page', async () => {
    server.use(...baseHandlers());
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        <Route path="/suppliers/:id/links" element={<div>Страница связей</div>} />
      </Routes>,
      { route: '/suppliers/1' },
    );

    await screen.findByText('Выгрузки');
    await user.click(screen.getByRole('button', { name: /управление связями/i }));

    await waitFor(() => {
      expect(screen.getByText('Страница связей')).toBeInTheDocument();
    });
  });
});
