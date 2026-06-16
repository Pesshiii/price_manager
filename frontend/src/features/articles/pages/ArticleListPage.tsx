import { Button, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { listArticles } from '../api';
import { articleKeys } from '../queryKeys';

export function ArticleListPage() {
  const { data: articles, isLoading } = useQuery({
    queryKey: articleKeys.lists(),
    queryFn: listArticles,
  });

  if (isLoading) return <Loader />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Статьи</Title>
        <Button leftSection={<IconPlus size={16} />} component={Link} to="/articles/new">
          Новая статья
        </Button>
      </Group>

      {!articles || articles.length === 0 ? (
        <Text c="dimmed">Статьи не найдены</Text>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Заголовок</Table.Th>
              <Table.Th>Автор</Table.Th>
              <Table.Th>Дата создания</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {articles.map((article) => (
              <Table.Tr key={article.id}>
                <Table.Td>
                  <Text component={Link} to={`/articles/${article.id}`} c="blue">
                    {article.title}
                  </Text>
                </Table.Td>
                <Table.Td>{article.author.username}</Table.Td>
                <Table.Td>{new Date(article.created_at).toLocaleDateString('ru-RU')}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
