import { Grid, Textarea } from '@mantine/core';
import { MarkdownRenderer } from './MarkdownRenderer';

interface ArticleEditorProps {
  content: string;
  onChange: (value: string) => void;
}

export function ArticleEditor({ content, onChange }: ArticleEditorProps) {
  return (
    <Grid>
      <Grid.Col span={6}>
        <Textarea
          value={content}
          onChange={(e) => onChange(e.currentTarget.value)}
          minRows={20}
          autosize
          label="Содержимое (Markdown)"
        />
      </Grid.Col>
      <Grid.Col span={6}>
        <MarkdownRenderer content={content} />
      </Grid.Col>
    </Grid>
  );
}
