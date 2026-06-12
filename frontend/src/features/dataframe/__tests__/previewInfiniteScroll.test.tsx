import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { http, HttpResponse, server } from '@/test/msw';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PreviewPanel } from '../components/PreviewPanel';
import { usePipelinePreview } from '../hooks/usePipelinePreview';
import type { Instructions } from '../types';

vi.mock('react-virtuoso', () => ({
  TableVirtuoso: ({
    data,
    fixedHeaderContent,
    itemContent,
    endReached,
  }: {
    data: unknown[][];
    fixedHeaderContent: () => React.ReactNode;
    itemContent: (i: number, row: unknown[]) => React.ReactNode;
    endReached?: () => void;
  }) => (
    <table>
      <thead>{fixedHeaderContent()}</thead>
      <tbody data-testid="rows">
        {data.map((row, i) => (
          <tr key={i}>{itemContent(i, row)}</tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td>
            <button data-testid="end-reached" onClick={() => endReached?.()}>
              end
            </button>
          </td>
        </tr>
      </tfoot>
    </table>
  ),
}));

const instructions: Instructions = {
  reader: { func: 'read_csv', args: {} },
  transforms: [],
};

function Host() {
  const [sid] = useState<string | null>('sid');
  const preview = usePipelinePreview({ instructions, sessionId: sid, debounceMs: 10 });
  return (
    <PreviewPanel
      data={preview.data}
      isLoading={preview.isLoading}
      isFetching={preview.isFetching}
      isError={preview.isError}
      hasSession={true}
      stepLabel="reader"
      hasNextPage={preview.hasNextPage}
      isFetchingNextPage={preview.isFetchingNextPage}
      fetchNextPage={preview.fetchNextPage}
    />
  );
}

describe('preview infinite scroll', () => {
  it('appends rows from a second page when endReached fires', async () => {
    const calls: number[] = [];
    server.use(
      http.post('/api/dataframe/preview/', async ({ request }) => {
        const body = (await request.json()) as { offset?: number };
        const offset = body.offset ?? 0;
        calls.push(offset);
        if (offset === 0) {
          return HttpResponse.json({
            columns: ['a'],
            rows: [['r0'], ['r1']],
            total_rows: 4,
            returned_rows: 2,
            offset: 0,
            has_more: true,
          });
        }
        return HttpResponse.json({
          columns: ['a'],
          rows: [['r2'], ['r3']],
          total_rows: 4,
          returned_rows: 2,
          offset: 2,
          has_more: false,
        });
      }),
    );

    renderWithProviders(<Host />);

    await waitFor(() => expect(screen.getByText('r0')).toBeInTheDocument());
    expect(calls).toEqual([0]);

    fireEvent.click(screen.getByTestId('end-reached'));

    await waitFor(() => expect(screen.getByText('r2')).toBeInTheDocument());
    expect(screen.getByText('r3')).toBeInTheDocument();
    expect(calls).toEqual([0, 2]);
  });
});
