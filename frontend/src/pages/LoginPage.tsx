import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  TextInput,
  Title,
  Alert,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useAuth } from '@/auth/AuthContext';

interface FormValues {
  username: string;
  password: string;
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<FormValues>({
    initialValues: { username: '', password: '' },
    validate: {
      username: (v) => (v.trim().length === 0 ? 'Введите логин' : null),
      password: (v) => (v.length === 0 ? 'Введите пароль' : null),
    },
  });

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/';

  async function handleSubmit(values: FormValues) {
    setError(null);
    setSubmitting(true);
    try {
      await login(values.username, values.password);
      navigate(from, { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка входа');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Center mih="100vh" bg="gray.0">
      <Paper shadow="md" p="xl" radius="md" w={400} withBorder>
        <Title order={2} mb="lg" ta="center">
          Price Manager
        </Title>
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack>
            <TextInput
              label="Логин"
              placeholder="admin"
              required
              {...form.getInputProps('username')}
            />
            <PasswordInput
              label="Пароль"
              placeholder="admin"
              required
              {...form.getInputProps('password')}
            />
            {error && (
              <Alert color="red" variant="light">
                {error}
              </Alert>
            )}
            <Button type="submit" loading={submitting} fullWidth>
              Войти
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
