import { forwardRef } from 'react';
import { Menu, Table, UnstyledButton } from '@mantine/core';
import { IconChevronDown } from '@tabler/icons-react';
import { TableVirtuoso, type TableComponents } from 'react-virtuoso';
import type { TransformSpec } from '../types';

interface Props {
  columns: string[];
  rows: unknown[][];
  maxHeight?: number;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  onEndReached?: () => void;
  /** Column-aware transforms shown in the per-header dropdown. */
  columnTransforms?: TransformSpec[];
  /** Fires when user picks an action on a column. */
  onColumnAction?: (column: string, transformName: string) => void;
}

function renderCell(value: unknown) {
  if (value === null || value === undefined) {
    return <span style={{ color: 'var(--mantine-color-gray-5)' }}>—</span>;
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

interface ColumnHeaderProps {
  name: string;
  transforms: TransformSpec[];
  onPick: (transformName: string) => void;
}

function ColumnHeader({ name, transforms, onPick }: ColumnHeaderProps) {
  if (transforms.length === 0) {
    return <span>{name}</span>;
  }
  return (
    <Menu shadow="md" position="bottom-start" withinPortal>
      <Menu.Target>
        <UnstyledButton
          aria-label={`Действия с колонкой ${name}`}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontWeight: 'inherit',
            color: 'inherit',
          }}
        >
          {name}
          <IconChevronDown size={12} />
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Действия с «{name}»</Menu.Label>
        {transforms.map((t) => (
          <Menu.Item key={t.name} onClick={() => onPick(t.name)}>
            {t.label || t.name}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}

const VirtuosoTableComponents: TableComponents<unknown[]> = {
  Table: (props) => (
    <Table
      withTableBorder
      withColumnBorders
      striped
      {...props}
      style={{ ...props.style, borderCollapse: 'separate' }}
    />
  ),
  TableHead: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <Table.Thead
      {...props}
      ref={ref}
      style={{ background: 'var(--mantine-color-gray-0)' }}
    />
  )),
  TableRow: (props) => <Table.Tr {...props} />,
  TableBody: forwardRef<HTMLTableSectionElement>((props, ref) => (
    <Table.Tbody {...props} ref={ref} />
  )),
};

export function PreviewTable({
  columns,
  rows,
  maxHeight = 480,
  hasNextPage = false,
  isFetchingNextPage = false,
  onEndReached,
  columnTransforms = [],
  onColumnAction,
}: Props) {
  const headerTransforms = onColumnAction ? columnTransforms : [];
  return (
    <TableVirtuoso
      style={{ height: maxHeight }}
      data={rows}
      components={VirtuosoTableComponents}
      endReached={() => {
        if (hasNextPage && !isFetchingNextPage && onEndReached) onEndReached();
      }}
      fixedHeaderContent={() => (
        <tr>
          {columns.map((c) => (
            <th key={c}>
              <ColumnHeader
                name={c}
                transforms={headerTransforms}
                onPick={(transformName) => onColumnAction?.(c, transformName)}
              />
            </th>
          ))}
        </tr>
      )}
      itemContent={(_index, row) =>
        columns.map((_c, ci) => <td key={ci}>{renderCell(row[ci])}</td>)
      }
    />
  );
}
