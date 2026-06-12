import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

export const handlers = [
  http.get('/api/auth/me/', () => HttpResponse.json(null, { status: 401 })),
];

export const server = setupServer(...handlers);
export { http, HttpResponse };
