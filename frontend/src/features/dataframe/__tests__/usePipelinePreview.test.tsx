import { describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/msw';
import { usePipelinePreview } from '../hooks/usePipelinePreview';
import type { Instructions } from '../types';

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const instructions: Instructions = {
  reader: { func: 'read_csv', args: {} },
  transforms: [],
};

describe('usePipelinePreview', () => {
  it('does not fire when sessionId is null', async () => {
    let called = 0;
    server.use(
      http.post('/api/dataframe/preview/', () => {
        called += 1;
        return HttpResponse.json({ columns: [], rows: [], total_rows: 0, returned_rows: 0 });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => usePipelinePreview({ instructions, sessionId: null, debounceMs: 50 }),
      { wrapper: wrapper(client) },
    );
    await new Promise((r) => setTimeout(r, 200));
    expect(result.current.isFetching).toBe(false);
    expect(called).toBe(0);
  });

  it('fires after debounce when sessionId provided', async () => {
    let calls = 0;
    server.use(
      http.post('/api/dataframe/preview/', async () => {
        calls += 1;
        return HttpResponse.json({
          columns: ['a'],
          rows: [['1']],
          total_rows: 1,
          returned_rows: 1,
        });
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(
      () => usePipelinePreview({ instructions, sessionId: 'sid', debounceMs: 50 }),
      { wrapper: wrapper(client) },
    );
    await waitFor(() => expect(result.current.data).toBeDefined(), { timeout: 2000 });
    expect(calls).toBe(1);
  });
});
