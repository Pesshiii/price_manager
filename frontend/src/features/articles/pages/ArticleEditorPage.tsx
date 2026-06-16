import { Button, Group, Loader, Stack, TextInput, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { IconArrowLeft } from '@tabler/icons-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { createArticle, getArticle, updateArticle } from '../api';
import { ArticleEditor } from '../components/ArticleEditor';
import { articleKeys } from '../queryKeys';

export function ArticleEditorPage() {
  const { id } = useParams<{ id: string }>();
  const isEdit = Boolean(id);
  const articleId = id ? Number(id) : undefined;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const form = useForm({
    initialValues: { title: '', content: '' },
    validate: {
      title: (v) => (v.trim() ? null : 'Заголовок обязателен'),
    },
  });

  const { data: article, isLoading } = useQuery({
    queryKey: articleId !== undefined ? articleKeys.detail(articleId) : ['article', 'new'],
    queryFn: () => getArticle(articleId!),
    enabled: articleId !== undefined && Number.isFinite(articleId),
  });

  useEffect(() => {
    if (article) {
      form.setValues({ title: article.title, content: article.content });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [article]);

  const mutation = useMutation({
    mutationFn: (values: { title: string; content: string }) =>
      isEdit && articleId !== undefined
        ? updateArticle(articleId, values)
        : createArticle(values),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: articleKeys.all });
      notifications.show({ message: isEdit ? 'Сохранено' : 'Создано', color: 'green' });
      navigate(`/articles/${saved.id}`);
    },
    onError: () => {
      notifications.show({ message: 'Ошибка сохранения', color: 'red' });
    },
  });

  if (isEdit && isLoading) return <Loader />;

  return (
    <Stack>
      <Group>
        <Button
          variant="subtle"
          leftSection={<IconArrowLeft size={16} />}
          component={Link}
          to={isEdit && articleId !== undefined ? `/articles/${articleId}` : '/articles'}
        >
          Назад
        </Button>
        <Title order={2}>{isEdit ? 'Редактирование статьи' : 'Новая статья'}</Title>
      </Group>

      <form onSubmit={form.onSubmit((values) => mutation.mutate(values))}>
        <Stack>
          <TextInput
            label="Заголовок"
            required
            {...form.getInputProps('title')}
          />
          <ArticleEditor
            content={form.values.content}
            onChange={(value) => form.setFieldValue('content', value)}
          />
          <Group>
            <Button type="submit" loading={mutation.isPending}>
              {isEdit ? 'Сохранить' : 'Создать'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Stack>
  );
}
