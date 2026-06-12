import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions } from '@testing-library/react';
import { ReactElement, type ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';

interface WrapperOptions {
  route?: string;
}

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = '/', ...options }: WrapperOptions & RenderOptions = {},
) {
  const client = createTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MantineProvider defaultColorScheme="light">
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>
    );
  }
  return { ...render(ui, { wrapper: Wrapper, ...options }), client };
}
