import axios from 'axios';

function getCookie(name: string): string | null {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split('=')[1]) : null;
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
});

api.interceptors.request.use((config) => {
  const method = (config.method ?? 'get').toLowerCase();
  if (!['get', 'head', 'options'].includes(method)) {
    const token = getCookie('csrftoken');
    if (token) {
      config.headers.set('X-CSRFToken', token);
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error.config?.url ?? '';
    const isAuthProbe = url.startsWith('/auth/');
    if (error.response?.status === 401 && !isAuthProbe) {
      const path = window.location.pathname;
      if (path !== '/login') {
        window.location.assign('/login');
      }
    }
    return Promise.reject(error);
  },
);

export async function fetchCsrf(): Promise<void> {
  await api.get('/auth/csrf/');
}
