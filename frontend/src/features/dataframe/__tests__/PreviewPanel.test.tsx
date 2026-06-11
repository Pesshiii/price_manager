import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PreviewPanel } from '../components/PreviewPanel';
import type { PreviewResult, TransformSpec } from '../types';

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
      <tbody>
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

function makeInfinite(pages: PreviewResult[]) {
  return { pages, pageParams: pages.map((_, i) => i) };
}

describe('PreviewPanel', () => {
  it('shows upload hint when no session', () => {
    renderWithProviders(
      <PreviewPanel
        data={undefined}
        isLoading={false}
        isFetching={false}
        isError={false}
        hasSession={false}
        stepLabel="reader"
      />,
    );
    expect(screen.getByText(/Загрузите файл/)).toBeInTheDocument();
  });

  it('shows loader while loading', () => {
    renderWithProviders(
      <PreviewPanel
        data={undefined}
        isLoading={true}
        isFetching={true}
        isError={false}
        hasSession={true}
        stepLabel="reader"
      />,
    );
    expect(screen.getByText(/Загружаем превью/)).toBeInTheDocument();
  });

  it('renders success data', () => {
    renderWithProviders(
      <PreviewPanel
        data={makeInfinite([
          {
            columns: ['a', 'b'],
            rows: [
              ['1', '2'],
              ['3', '4'],
            ],
            total_rows: 2,
            returned_rows: 2,
            offset: 0,
            has_more: false,
          },
        ])}
        isLoading={false}
        isFetching={false}
        isError={false}
        hasSession={true}
        stepLabel="reader"
      />,
    );
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('b')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
  });

  it('fires onColumnAction when a column-header menu item is clicked', async () => {
    const user = userEvent.setup();
    const onColumnAction = vi.fn();
    const transforms: TransformSpec[] = [
      {
        name: 'replace_values',
        label: 'Заменить значения',
        args: [
          { name: 'column', type: 'column', label: 'Колонка', required: true, default: null, choices: null, help_text: '' },
          { name: 'mapping', type: 'value_mapping', label: 'Mapping', required: true, default: null, choices: null, help_text: '' },
        ],
      },
    ];
    renderWithProviders(
      <PreviewPanel
        data={makeInfinite([
          {
            columns: ['price', 'qty'],
            rows: [['10', '2']],
            total_rows: 1,
            returned_rows: 1,
            offset: 0,
            has_more: false,
          },
        ])}
        isLoading={false}
        isFetching={false}
        isError={false}
        hasSession={true}
        stepLabel="reader"
        columnTransforms={transforms}
        onColumnAction={onColumnAction}
      />,
    );
    // Click on column header 'price' opens the dropdown
    await user.click(screen.getByRole('button', { name: /Действия с колонкой price/ }));
    // Pick "Заменить значения" from the menu
    await user.click(await screen.findByRole('menuitem', { name: /Заменить значения/ }));
    expect(onColumnAction).toHaveBeenCalledWith('price', 'replace_values');
  });

  it('renders error from PreviewError result', () => {
    renderWithProviders(
      <PreviewPanel
        data={makeInfinite([{ error: { step_index: 2, message: 'KeyError: foo' } }])}
        isLoading={false}
        isFetching={false}
        isError={false}
        hasSession={true}
        stepLabel="step #2"
      />,
    );
    expect(screen.getByText(/KeyError/)).toBeInTheDocument();
  });
});
