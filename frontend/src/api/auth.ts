import { AxiosError } from 'axios';
import { api, fetchCsrf } from './client';

export interface CurrentUser {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_staff: boolean;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  await fetchCsrf();
  try {
    const { data } = await api.post<CurrentUser>('/auth/login/', { username, password });
    return data;
  } catch (e) {
    if (e instanceof AxiosError && e.response?.status === 401) {
      throw new Error('Неверный логин или пароль');
    }
    throw e;
  }
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout/');
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  try {
    const { data } = await api.get<CurrentUser>('/auth/me/');
    return data;
  } catch {
    return null;
  }
}
