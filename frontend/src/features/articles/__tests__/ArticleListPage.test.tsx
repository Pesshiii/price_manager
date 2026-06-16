import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/msw';
import { ArticleListPage } from '../pages/ArticleListPage';

const ARTICLE = {
  id: 1,
  title: 'Тестовая статья',
  author: { id: 1, username: 'admin' },
  created_at: '2026-01-01T00:00:00Z',
};

describe('ArticleListPage', () => {
  it('renders articles from API', async () => {
    server.use(
      http.get('/api/articles/', () => HttpResponse.json([ARTICLE])),
    );

    renderWithProviders(
      <Routes>
        <Route path="/articles" element={<ArticleListPage />} />
      </Routes>,
      { route: '/articles' },
    );

    await waitFor(() => {
      expect(screen.getByText('Тестовая статья')).toBeInTheDocument();
      expect(screen.getByText('admin')).toBeInTheDocument();
    });
  });

  it('shows empty state when API returns no articles', async () => {
    server.use(
      http.get('/api/articles/', () => HttpResponse.json([])),
    );

    renderWithProviders(
      <Routes>
        <Route path="/articles" element={<ArticleListPage />} />
      </Routes>,
      { route: '/articles' },
    );

    expect(await screen.findByText('Статьи не найдены')).toBeInTheDocument();
  });
});
