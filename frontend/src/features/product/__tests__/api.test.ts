import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/msw';
import {
  commitImport,
  commitRetype,
  getCharMutationJob,
  listCharacteristicTypes,
  listProducts,
  previewImport,
  previewRetype,
  updateProduct,
} from '../api';
import { emptyFilters, type ProductFilters } from '../types';

describe('product api', () => {
  it('listProducts serializes filters and repeats char__ params', async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get('/api/products/products/', ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    const filters: ProductFilters = {
      ...emptyFilters(),
      q: 'drill',
      category: 7,
      brand: 3,
      status: 'active',
      chars: { color: ['red', 'blue'], size: ['L'] },
      page: 2,
      pageSize: 25,
    };
    await listProducts(filters);

    expect(capturedUrl).not.toBeNull();
    const params = capturedUrl!.searchParams;
    expect(params.get('q')).toBe('drill');
    expect(params.get('category')).toBe('7');
    expect(params.get('brand')).toBe('3');
    expect(params.get('status')).toBe('active');
    expect(params.get('page')).toBe('2');
    expect(params.get('page_size')).toBe('25');
    expect(params.getAll('char__color')).toEqual(['red', 'blue']);
    expect(params.getAll('char__size')).toEqual(['L']);
  });

  it('updateProduct uses PATCH', async () => {
    let method: string | null = null;
    let body: unknown = null;
    server.use(
      http.patch('/api/products/products/42/', async ({ request }) => {
        method = request.method;
        body = await request.json();
        return HttpResponse.json({
          id: 42,
          sku: 'SKU-42',
          name: 'New name',
          category: null,
          brand: null,
          description: '',
          status: '',
          characteristics: {},
          image_urls: [],
          created_at: '',
          updated_at: '',
        });
      }),
    );

    const result = await updateProduct(42, { name: 'New name', characteristics: {} });
    expect(method).toBe('PATCH');
    expect(body).toEqual({ name: 'New name', characteristics: {} });
    expect(result.name).toBe('New name');
  });

  it('previewImport sends the expected body', async () => {
    let body: unknown = null;
    server.use(
      http.post('/api/products/import/preview/', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          rows: [],
          total: 0,
          returned: 0,
          valid: 0,
          invalid: 0,
        });
      }),
    );

    await previewImport({
      session_id: 'sid',
      instructions: { reader: { func: 'r', args: {} }, transforms: [] },
      mapping: { sku: { column: 'A' }, characteristics: { color: { column: 'B' } } },
      row_limit: 50,
    });
    expect(body).toEqual({
      session_id: 'sid',
      instructions: { reader: { func: 'r', args: {} }, transforms: [] },
      mapping: { sku: { column: 'A' }, characteristics: { color: { column: 'B' } } },
      row_limit: 50,
    });
  });

  it('commitImport hits /import/commit/ and returns an ImportJob envelope', async () => {
    let called = false;
    server.use(
      http.post('/api/products/import/commit/', () => {
        called = true;
        return HttpResponse.json(
          {
            id: '11111111-1111-1111-1111-111111111111',
            kind: 'commit',
            status: 'pending',
            result: null,
            error: '',
            created_at: '2026-01-01T00:00:00Z',
            started_at: null,
            finished_at: null,
          },
          { status: 202 },
        );
      }),
    );
    const job = await commitImport({
      session_id: 'sid',
      instructions: {},
      mapping: {},
    });
    expect(called).toBe(true);
    expect(job.id).toBe('11111111-1111-1111-1111-111111111111');
    expect(job.kind).toBe('commit');
    expect(job.status).toBe('pending');
  });

  it('listCharacteristicTypes serializes multi-category + value_type + required', async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get('/api/products/characteristic-types/', ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await listCharacteristicTypes({
      category: [1, 2],
      value_type: 'integer',
      required: true,
      search: 'вес',
    });

    const params = capturedUrl!.searchParams;
    // category appears twice with different ids
    expect(params.getAll('category')).toEqual(['1', '2']);
    expect(params.get('value_type')).toBe('integer');
    expect(params.get('required')).toBe('true');
    expect(params.get('search')).toBe('вес');
  });

  it('previewRetype POSTs the new value_type and returns the conflict surface', async () => {
    let body: unknown = null;
    server.use(
      http.post('/api/products/characteristic-types/5/retype/preview/', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          total_with_key: 3,
          invalid_count: 2,
          unique_invalid: [{ value: 'много', count: 2 }],
          truncated: false,
        });
      }),
    );

    const result = await previewRetype(5, { new_value_type: 'integer' });
    expect(body).toEqual({ new_value_type: 'integer' });
    expect(result.invalid_count).toBe(2);
    expect(result.unique_invalid[0].value).toBe('много');
  });

  it('commitRetype returns a CharMutationJob envelope and accepts value_map', async () => {
    let body: unknown = null;
    server.use(
      http.post('/api/products/characteristic-types/5/retype/commit/', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(
          {
            id: 'job-uuid',
            kind: 'retype',
            status: 'pending',
            stage: '',
            char_type: 5,
            payload: {},
            result: null,
            error: '',
            created_at: '',
            started_at: null,
            finished_at: null,
          },
          { status: 202 },
        );
      }),
    );

    const job = await commitRetype(5, {
      new_value_type: 'integer',
      fallback: 'drop',
      value_map: { 'много': '100' },
    });
    expect(body).toEqual({
      new_value_type: 'integer',
      fallback: 'drop',
      value_map: { 'много': '100' },
    });
    expect(job.id).toBe('job-uuid');
    expect(job.kind).toBe('retype');
  });

  it('getCharMutationJob hits the jobs endpoint', async () => {
    let called = false;
    server.use(
      http.get('/api/products/characteristic-types/jobs/abc/', () => {
        called = true;
        return HttpResponse.json({
          id: 'abc',
          kind: 'retype',
          status: 'success',
          stage: '',
          char_type: 5,
          payload: {},
          result: { updated: 3 },
          error: '',
          created_at: '',
          started_at: '',
          finished_at: '',
        });
      }),
    );

    const job = await getCharMutationJob('abc');
    expect(called).toBe(true);
    expect(job.status).toBe('success');
    expect(job.result?.updated).toBe(3);
  });
});
