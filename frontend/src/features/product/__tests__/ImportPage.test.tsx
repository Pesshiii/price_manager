import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { ImportPage } from '../pages/ImportPage';

const PIPELINE = {
  id: 1,
  name: 'Test pipeline',
  description: '',
  instructions: {
    reader: { func: 'read_csv', args: {} },
    transforms: [],
  },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function commonHandlers() {
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

describe('ImportPage', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults to saved mode and shows pipeline select', async () => {
    commonHandlers();
    renderImport();
    expect(
      await screen.findByRole('radio', { name: 'Сохранённый пайплайн' }),
    ).toBeChecked();
    expect(screen.getByPlaceholderText('Выберите сохранённый пайплайн')).toBeInTheDocument();
    expect(screen.queryByLabelText('Загрузить файл')).not.toBeInTheDocument();
  });

  it('switching to ad-hoc reveals DataframeBuilder', async () => {
    commonHandlers();
    const user = userEvent.setup();
    renderImport();

    await user.click(await screen.findByRole('radio', { name: 'Ad-hoc' }));

    // SourcePicker dropzone exposes aria-label="Загрузить файл"
    await waitFor(() =>
      expect(screen.getByLabelText('Загрузить файл')).toBeInTheDocument(),
    );
    // Reader picker from the builder is visible
    expect(screen.getByLabelText('Reader')).toBeInTheDocument();
    // Pipeline select from the saved mode is gone
    expect(
      screen.queryByPlaceholderText('Выберите сохранённый пайплайн'),
    ).not.toBeInTheDocument();
  });

  it('forking a saved pipeline switches mode to ad-hoc', async () => {
    commonHandlers();
    const user = userEvent.setup();
    renderImport();

    // Pick pipeline
    await user.click(await screen.findByPlaceholderText('Выберите сохранённый пайплайн'));
    await user.click(await screen.findByRole('option', { name: 'Test pipeline' }));

    // Fork button is enabled once instructions are loaded
    const forkBtn = await screen.findByRole('button', { name: 'Форкнуть в ad-hoc' });
    await waitFor(() => expect(forkBtn).not.toBeDisabled());
    await user.click(forkBtn);

    await waitFor(() =>
      expect(screen.getByRole('radio', { name: 'Ad-hoc' })).toBeChecked(),
    );
    expect(screen.getByLabelText('Загрузить файл')).toBeInTheDocument();
  });

  it('"Далее" is disabled until both a session and a pipeline are picked', async () => {
    commonHandlers();
    const user = userEvent.setup();
    renderImport();

    const nextBtn = await screen.findByRole('button', { name: 'Далее' });
    expect(nextBtn).toBeDisabled();

    // Picking pipeline alone is not enough (still no session)
    await user.click(await screen.findByPlaceholderText('Выберите сохранённый пайплайн'));
    await user.click(await screen.findByRole('option', { name: 'Test pipeline' }));
    expect(nextBtn).toBeDisabled();
  });
});
