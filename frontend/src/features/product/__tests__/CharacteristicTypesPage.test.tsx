import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { CharacteristicTypesPage } from '../pages/CharacteristicTypesPage';

interface CharRow {
  id: number;
  name: string;
  label: string;
  value_type: 'string' | 'integer' | 'float' | 'boolean' | 'choice';
  options: string[];
  unit: string;
  required: boolean;
  categories: number[];
  categories_detail?: Array<{ id: number; name: string; level: number }>;
}

function mkType(overrides: Partial<CharRow> = {}): CharRow {
  return {
    id: 1,
    name: 'weight',
    label: 'Вес',
    value_type: 'string',
    options: [],
    unit: 'кг',
    required: false,
    categories: [10],
    categories_detail: [{ id: 10, name: 'Инструменты', level: 0 }],
    ...overrides,
  };
}

function defaultCategoriesHandler() {
  return http.get('/api/products/categories/', () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [{ id: 10, name: 'Инструменты', slug: 'instr', parent: null, level: 0 }],
    }),
  );
}

function listHandler(
  capture: { url?: URL },
  results: CharRow[] = [mkType()],
) {
  return http.get('/api/products/characteristic-types/', ({ request }) => {
    capture.url = new URL(request.url);
    return HttpResponse.json({ count: results.length, next: null, previous: null, results });
  });
}

describe('CharacteristicTypesPage', () => {
  it('forwards filter inputs into the list query string', async () => {
    const capture: { url?: URL } = {};
    server.use(defaultCategoriesHandler(), listHandler(capture));
    renderWithProviders(<CharacteristicTypesPage />);

    // Wait for the initial fetch to land before driving the filters.
    await waitFor(() => expect(capture.url).toBeDefined());

    // value_type filter — the toolbar Select is uniquely identified by its placeholder.
    const valueTypeSelect = await screen.findByPlaceholderText('Любой');
    await userEvent.click(valueTypeSelect);
    await userEvent.click(await screen.findByRole('option', { name: 'integer' }));

    // required = "Да"
    await userEvent.click(screen.getByRole('radio', { name: 'Да' }));

    // search — wait for debounce (300ms)
    await userEvent.type(screen.getByPlaceholderText('по имени или метке'), 'вес');

    await waitFor(
      () => {
        const params = capture.url!.searchParams;
        expect(params.get('value_type')).toBe('integer');
        expect(params.get('required')).toBe('true');
        expect(params.get('search')).toBe('вес');
      },
      { timeout: 2000 },
    );
  });

  it('detail modal renders categories from categories_detail without extra fetch', async () => {
    const capture: { url?: URL } = {};
    server.use(defaultCategoriesHandler(), listHandler(capture));
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Просмотр'));

    // Modal headline = label
    const heading = await screen.findByRole('heading', { name: 'Вес' });
    expect(heading).toBeInTheDocument();
    // Category from categories_detail — scope to the dialog to avoid the
    // toolbar MultiSelect option that also renders the same text.
    const dialog = heading.closest('[role="dialog"]') ?? heading.parentElement!.parentElement!;
    expect(within(dialog as HTMLElement).getByText('Инструменты')).toBeInTheDocument();
  });

  it('safe-only edit sends a plain PATCH, no retype/rename calls', async () => {
    const capture: { url?: URL } = {};
    let patchBody: unknown = null;
    server.use(
      defaultCategoriesHandler(),
      listHandler(capture),
      http.patch('/api/products/characteristic-types/1/', async ({ request }) => {
        patchBody = await request.json();
        return HttpResponse.json(mkType({ label: 'Масса' }));
      }),
    );
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Редактировать'));
    await screen.findByText(/Редактировать «/);
    // Mantine TextInput links via id+for — match by role + accessible name.
    const labelInput = await screen.findByRole('textbox', { name: 'Метка' });
    await userEvent.clear(labelInput);
    await userEvent.type(labelInput, 'Масса');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(patchBody).toEqual({ label: 'Масса' }));
    // If anything would have called /retype/ or /rename/, MSW would error
    // (onUnhandledRequest: 'error'), failing the test.
  });

  it('retype with 0 conflicts skips the conflict screen and commits immediately', async () => {
    const capture: { url?: URL } = {};
    let commitBody: unknown = null;
    server.use(
      defaultCategoriesHandler(),
      listHandler(capture),
      http.post(
        '/api/products/characteristic-types/1/retype/preview/',
        async () =>
          HttpResponse.json({
            total_with_key: 3,
            invalid_count: 0,
            unique_invalid: [],
            truncated: false,
          }),
      ),
      http.post(
        '/api/products/characteristic-types/1/retype/commit/',
        async ({ request }) => {
          commitBody = await request.json();
          return HttpResponse.json(
            {
              id: 'job-uuid',
              kind: 'retype',
              status: 'success',
              stage: '',
              char_type: 1,
              payload: {},
              result: { updated: 3, dropped: 0 },
              error: '',
              created_at: '',
              started_at: '',
              finished_at: '',
            },
            { status: 202 },
          );
        },
      ),
      http.get('/api/products/characteristic-types/jobs/job-uuid/', () =>
        HttpResponse.json({
          id: 'job-uuid',
          kind: 'retype',
          status: 'success',
          stage: '',
          char_type: 1,
          payload: {},
          result: { updated: 3, dropped: 0 },
          error: '',
          created_at: '',
          started_at: '',
          finished_at: '',
        }),
      ),
    );
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Редактировать'));

    const dialog = (await screen.findByRole('dialog')) as HTMLElement;
    // Scope Select lookup to the edit dialog; the toolbar also has a "Тип значения" label.
    const valueTypeSelect = within(dialog).getByLabelText('Тип значения');
    await userEvent.click(valueTypeSelect);
    await userEvent.click(await screen.findByRole('option', { name: 'Целое число' }));

    await userEvent.click(within(dialog).getByRole('button', { name: 'Сохранить' }));

    await waitFor(() =>
      expect(commitBody).toMatchObject({ new_value_type: 'integer' }),
    );
  });

  it('retype with <10 conflicts sends value_map per row + fallback', async () => {
    const capture: { url?: URL } = {};
    let commitBody: any = null;
    server.use(
      defaultCategoriesHandler(),
      listHandler(capture),
      http.post('/api/products/characteristic-types/1/retype/preview/', () =>
        HttpResponse.json({
          total_with_key: 5,
          invalid_count: 2,
          unique_invalid: [
            { value: 'много', count: 1 },
            { value: 'мало', count: 1 },
          ],
          truncated: false,
        }),
      ),
      http.post(
        '/api/products/characteristic-types/1/retype/commit/',
        async ({ request }) => {
          commitBody = await request.json();
          return HttpResponse.json(
            {
              id: 'job-2',
              kind: 'retype',
              status: 'success',
              stage: '',
              char_type: 1,
              payload: {},
              result: { updated: 5, mapped: 1, dropped: 1 },
              error: '',
              created_at: '',
              started_at: '',
              finished_at: '',
            },
            { status: 202 },
          );
        },
      ),
      http.get('/api/products/characteristic-types/jobs/job-2/', () =>
        HttpResponse.json({
          id: 'job-2',
          kind: 'retype',
          status: 'success',
          stage: '',
          char_type: 1,
          payload: {},
          result: { updated: 5 },
          error: '',
          created_at: '',
          started_at: '',
          finished_at: '',
        }),
      ),
    );
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Редактировать'));
    const editDialog = (await screen.findByRole('dialog')) as HTMLElement;
    await userEvent.click(within(editDialog).getByLabelText('Тип значения'));
    await userEvent.click(await screen.findByRole('option', { name: 'Целое число' }));
    await userEvent.click(within(editDialog).getByRole('button', { name: 'Сохранить' }));

    // Wait for the retype wizard's conflict screen to render.
    await screen.findByText(/не приводятся к типу/);

    // Find the row for 'много' and fill the replacement input.
    const tables = screen.getAllByRole('table');
    const conflictTable = tables[tables.length - 1];
    const rowMany = within(conflictTable).getByText('много').closest('tr')!;
    const inputMany = within(rowMany).getByRole('textbox');
    await userEvent.type(inputMany, '100');

    // Leave 'мало' empty → falls through to fallback (default 'drop').
    await userEvent.click(within(conflictTable.parentElement!.parentElement!).getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(commitBody).not.toBeNull());
    expect(commitBody.new_value_type).toBe('integer');
    expect(commitBody.fallback).toBe('drop');
    expect(commitBody.value_map).toEqual({ 'много': '100' });
  });

  it('retype with >=10 conflicts shows fallback-only form', async () => {
    const capture: { url?: URL } = {};
    const unique = Array.from({ length: 12 }, (_, i) => ({
      value: `bad-${i}`,
      count: 1,
    }));
    let commitBody: any = null;
    server.use(
      defaultCategoriesHandler(),
      listHandler(capture),
      http.post('/api/products/characteristic-types/1/retype/preview/', () =>
        HttpResponse.json({
          total_with_key: 30,
          invalid_count: 12,
          unique_invalid: unique,
          truncated: false,
        }),
      ),
      http.post(
        '/api/products/characteristic-types/1/retype/commit/',
        async ({ request }) => {
          commitBody = await request.json();
          return HttpResponse.json(
            {
              id: 'job-3',
              kind: 'retype',
              status: 'success',
              stage: '',
              char_type: 1,
              payload: {},
              result: { updated: 30, defaulted: 12 },
              error: '',
              created_at: '',
              started_at: '',
              finished_at: '',
            },
            { status: 202 },
          );
        },
      ),
      http.get('/api/products/characteristic-types/jobs/job-3/', () =>
        HttpResponse.json({
          id: 'job-3',
          kind: 'retype',
          status: 'success',
          stage: '',
          char_type: 1,
          payload: {},
          result: { updated: 30 },
          error: '',
          created_at: '',
          started_at: '',
          finished_at: '',
        }),
      ),
    );
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Редактировать'));
    const editDialog = (await screen.findByRole('dialog')) as HTMLElement;
    await userEvent.click(within(editDialog).getByLabelText('Тип значения'));
    await userEvent.click(await screen.findByRole('option', { name: 'Целое число' }));
    await userEvent.click(within(editDialog).getByRole('button', { name: 'Сохранить' }));

    await screen.findByText(/не приводятся к типу/);

    // No per-value table for ≥10 unique invalids — the conflict view should
    // not contain any of the raw value rows.
    expect(screen.queryByText('bad-0')).not.toBeInTheDocument();

    // Switch fallback to 'default' and fill default_value. Mantine's Select
    // exposes both the visible label element and the hidden input under the
    // same accessible name — use the first match (the textbox combobox).
    const fallbackSelect = screen.getAllByLabelText(
      'Что делать с непреобразуемыми значениями',
    )[0];
    await userEvent.click(fallbackSelect);
    await userEvent.click(
      await screen.findByRole('option', { name: 'Подставить значение по умолчанию' }),
    );
    await userEvent.type(
      await screen.findByRole('textbox', { name: 'Значение по умолчанию' }),
      '0',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(commitBody).not.toBeNull());
    expect(commitBody.fallback).toBe('default');
    expect(commitBody.default_value).toBe('0');
    expect(commitBody.value_map).toBeUndefined();
  });

  it('rename with collisions exposes on_conflict choice', async () => {
    const capture: { url?: URL } = {};
    let commitBody: any = null;
    server.use(
      defaultCategoriesHandler(),
      listHandler(capture),
      // The safe-PATCH should NOT fire — name diff goes through rename.
      http.post('/api/products/characteristic-types/1/rename/preview/', () =>
        HttpResponse.json({
          total_to_rename: 2,
          collision_count: 1,
          collisions: [{ product_id: 42, sku: 'SKU-42' }],
        }),
      ),
      http.post(
        '/api/products/characteristic-types/1/rename/commit/',
        async ({ request }) => {
          commitBody = await request.json();
          return HttpResponse.json(
            {
              id: 'job-rn',
              kind: 'rename',
              status: 'success',
              stage: '',
              char_type: 1,
              payload: {},
              result: { renamed: 2, collisions: 1, skipped: 1 },
              error: '',
              created_at: '',
              started_at: '',
              finished_at: '',
            },
            { status: 202 },
          );
        },
      ),
      http.get('/api/products/characteristic-types/jobs/job-rn/', () =>
        HttpResponse.json({
          id: 'job-rn',
          kind: 'rename',
          status: 'success',
          stage: '',
          char_type: 1,
          payload: {},
          result: { renamed: 2 },
          error: '',
          created_at: '',
          started_at: '',
          finished_at: '',
        }),
      ),
    );
    renderWithProviders(<CharacteristicTypesPage />);

    await userEvent.click(await screen.findByLabelText('Редактировать'));
    await screen.findByText(/Редактировать «/);
    const nameInput = await screen.findByRole('textbox', { name: 'Ключ (slug)' });
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, 'mass');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    // Wizard pops with collision row visible.
    await screen.findByText(/уже есть ключ/);
    expect(screen.getByText('SKU-42')).toBeInTheDocument();

    // Pick "Оставить существующее"
    await userEvent.click(screen.getByRole('radio', { name: 'Оставить существующее' }));
    await userEvent.click(screen.getByRole('button', { name: 'Применить' }));

    await waitFor(() => expect(commitBody).not.toBeNull());
    expect(commitBody.new_name).toBe('mass');
    expect(commitBody.on_conflict).toBe('keep_existing');
  });
});
