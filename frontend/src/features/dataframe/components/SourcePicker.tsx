import { useState } from 'react';
import { Alert, Button, Card, Group, Loader, Stack, Text } from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { IconFileUpload, IconX } from '@tabler/icons-react';
import { uploadSession } from '../api';

interface UploadedFile {
  name: string;
  size: number;
}

interface Props {
  sessionId: string | null;
  uploadedFile: UploadedFile | null;
  onUploaded: (sessionId: string, file: UploadedFile) => void;
  onReset: () => void;
}

const ACCEPTED = {
  'text/csv': ['.csv'],
  'application/vnd.ms-excel': ['.xls'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'text/tab-separated-values': ['.tsv'],
  'text/plain': ['.txt'],
};

export function SourcePicker({ sessionId, uploadedFile, onUploaded, onReset }: Props) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDrop(files: File[]) {
    const file = files[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const resp = await uploadSession(file);
      onUploaded(resp.session_id, { name: resp.filename, size: resp.size });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить файл');
    } finally {
      setUploading(false);
    }
  }

  if (sessionId && uploadedFile) {
    return (
      <Card withBorder padding="sm">
        <Group justify="space-between" wrap="nowrap">
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              {uploadedFile.name}
            </Text>
            <Text size="xs" c="dimmed">
              {(uploadedFile.size / 1024).toFixed(1)} KB · session {sessionId.slice(0, 8)}…
            </Text>
          </Stack>
          <Button variant="subtle" size="xs" color="red" onClick={onReset}>
            Заменить
          </Button>
        </Group>
      </Card>
    );
  }

  return (
    <Stack gap="xs">
      <Dropzone
        onDrop={handleDrop}
        loading={uploading}
        accept={ACCEPTED}
        multiple={false}
        maxSize={50 * 1024 * 1024}
        aria-label="Загрузить файл"
      >
        <Group justify="center" gap="md" mih={80} style={{ pointerEvents: 'none' }}>
          {uploading ? <Loader size="sm" /> : <IconFileUpload size={28} />}
          <Stack gap={2}>
            <Text size="sm" fw={500}>
              Перетащите файл или нажмите для выбора
            </Text>
            <Text size="xs" c="dimmed">
              CSV, XLSX, XLS, TSV · до 50 MB
            </Text>
          </Stack>
        </Group>
      </Dropzone>
      {error && (
        <Alert color="red" icon={<IconX size={16} />} variant="light">
          {error}
        </Alert>
      )}
    </Stack>
  );
}
