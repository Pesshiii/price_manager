import { api } from '@/api/client';
import type { Article, ArticleListItem, CreateArticleInput, UpdateArticleInput } from './types';

const BASE = '/articles';

export const listArticles = () =>
  api.get<ArticleListItem[]>(BASE + '/').then(r => r.data);

export const getArticle = (id: number) =>
  api.get<Article>(`${BASE}/${id}/`).then(r => r.data);

export const createArticle = (data: CreateArticleInput) =>
  api.post<Article>(BASE + '/', data).then(r => r.data);

export const updateArticle = (id: number, data: UpdateArticleInput) =>
  api.patch<Article>(`${BASE}/${id}/`, data).then(r => r.data);

export const deleteArticle = (id: number) =>
  api.delete(`${BASE}/${id}/`);
