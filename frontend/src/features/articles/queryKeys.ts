export const articleKeys = {
  all: ['articles'] as const,
  lists: () => [...articleKeys.all, 'list'] as const,
  detail: (id: number) => [...articleKeys.all, 'detail', id] as const,
};
