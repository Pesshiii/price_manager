import { Button, Group, Loader, Stack, Text, Title } from '@mantine/core';
import { IconArrowLeft, IconEdit, IconTrash } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { deleteArticle, getArticle } from '../api';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { articleKeys } from '../queryKeys';

export function ArticleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const articleId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();

  const { data: article, isLoading } = useQuery({
    queryKey: articleKeys.detail(articleId),
    queryFn: () => getArticle(articleId),
    enabled: Number.isFinite(articleId),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteArticle(articleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: articleKeys.all });
      navigate('/articles');
    },
  });

  if (isLoading) return <Loader />;
  if (!article) return <Text c="dimmed">Статья не найдена</Text>;

  const isAuthor = user?.id === article.author.id;

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Button
            variant="subtle"
            leftSection={<IconArrowLeft size={16} />}
            component={Link}
            to="/articles"
          >
            К списку
          </Button>
          <Title order={2}>{article.title}</Title>
        </Group>
        {isAuthor && (
          <Group gap="xs">
            <Button
              variant="default"
              leftSection={<IconEdit size={16} />}
              component={Link}
              to={`/articles/${article.id}/edit`}
            >
              Редактировать
            </Button>
            <Button
              color="red"
              variant="light"
              leftSection={<IconTrash size={16} />}
              loading={deleteMutation.isPending}
              onClick={() => {
                if (confirm(`Удалить «${article.title}»?`)) deleteMutation.mutate();
              }}
            >
              Удалить
            </Button>
          </Group>
        )}
      </Group>

      <Text size="sm" c="dimmed">
        {article.author.username} · {new Date(article.created_at).toLocaleDateString('ru-RU')}
      </Text>

      <MarkdownRenderer content={article.content} />
    </Stack>
  );
}
