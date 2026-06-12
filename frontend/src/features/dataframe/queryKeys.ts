export const dataframeKeys = {
  all: ['dataframe'] as const,
  registry: () => [...dataframeKeys.all, 'registry'] as const,
  pipelines: () => [...dataframeKeys.all, 'pipelines'] as const,
  pipeline: (id: number) => [...dataframeKeys.all, 'pipeline', id] as const,
  preview: (sessionId: string, upTo: number | undefined, body: unknown) =>
    [...dataframeKeys.all, 'preview', sessionId, upTo, body] as const,
  session: (id: string) => [...dataframeKeys.all, 'session', id] as const,
};
