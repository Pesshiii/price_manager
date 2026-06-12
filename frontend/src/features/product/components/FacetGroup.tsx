import { Badge, Checkbox, Group, Stack, Text } from '@mantine/core';
import type { FacetBucket } from '../types';

export interface FacetGroupProps {
  label: string;
  unit?: string;
  buckets: FacetBucket[];
  selected: string[];
  onToggle: (value: string) => void;
}

export function FacetGroup({ label, unit, buckets, selected, onToggle }: FacetGroupProps) {
  if (buckets.length === 0) return null;
  return (
    <Stack gap={4}>
      <Text size="sm" fw={600}>
        {label}
        {unit ? ` (${unit})` : ''}
      </Text>
      {buckets.map((bucket) => {
        const value = String(bucket.value);
        return (
          <Checkbox
            key={value}
            checked={selected.includes(value)}
            onChange={() => onToggle(value)}
            label={
              <Group gap={6} wrap="nowrap">
                <Text size="sm">{value}</Text>
                <Badge size="xs" variant="light" color="gray">
                  {bucket.count}
                </Badge>
              </Group>
            }
          />
        );
      })}
    </Stack>
  );
}
