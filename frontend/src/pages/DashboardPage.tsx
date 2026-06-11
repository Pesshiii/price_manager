import { Title, Text, Stack, Card } from '@mantine/core';

export function DashboardPage() {
  return (
    <Stack>
      <Title order={2}>Главная</Title>
      <Card withBorder>
        <Text>Добро пожаловать в Price Manager. Выберите раздел в меню слева.</Text>
      </Card>
    </Stack>
  );
}
