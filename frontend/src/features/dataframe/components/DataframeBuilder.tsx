import { useCallback, useEffect, useMemo } from 'react';
import { Grid, Stack } from '@mantine/core';
import { deleteSession } from '../api';
import { usePipelinePreview } from '../hooks/usePipelinePreview';
import type {
  Instructions,
  PreviewError,
  PreviewSuccess,
  Registry,
  TransformSpec,
} from '../types';
import { isPreviewError } from '../types';
import { PreviewPanel } from './PreviewPanel';
import { ReaderConfig } from './ReaderConfig';
import { SourcePicker } from './SourcePicker';
import { StepList } from './StepList';

export interface UploadedFileInfo {
  name: string;
  size: number;
}

export interface DataframeBuilderProps {
  registry: Registry;
  instructions: Instructions;
  /** Push a new snapshot (creates an undo entry when parent uses undoable state). */
  setInstructions: (next: Instructions) => void;
  /** Live edit — replaces current snapshot without creating a new undo entry. */
  replaceInstructions?: (next: Instructions) => void;
  /** Finalize live edits as a new snapshot (e.g. on input blur). */
  commitInstructions?: () => void;
  sessionId: string | null;
  setSessionId: (sid: string | null) => void;
  uploadedFile: UploadedFileInfo | null;
  setUploadedFile: (f: UploadedFileInfo | null) => void;
  selectedStep: number | null;
  setSelectedStep: (idx: number | null) => void;
  /** Notified whenever a successful preview lands (columns ready). */
  onPreviewSuccess?: (preview: PreviewSuccess) => void;
}

function newStep(spec: TransformSpec, overrides?: Record<string, unknown>) {
  const args: Record<string, unknown> = {};
  for (const a of spec.args) {
    if (a.default !== null && a.default !== undefined) args[a.name] = a.default;
  }
  if (overrides) Object.assign(args, overrides);
  return { func: spec.name, args };
}

function findColumnArg(spec: TransformSpec) {
  return spec.args.find((a) => a.type === 'column' || a.type === 'columns');
}

function columnAwareTransforms(transforms: TransformSpec[]) {
  return transforms
    .filter((t) => findColumnArg(t) !== undefined)
    .slice()
    .sort((a, b) => (a.label || a.name).localeCompare(b.label || b.name));
}

function detectReader(filename: string, readers: { name: string; extensions: string[] }[]) {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  return readers.find((r) => r.extensions.includes(ext))?.name ?? '';
}

function indexFromError(result: PreviewError, totalSteps: number): number | null {
  const idx = result.error.step_index;
  if (idx === null || idx === undefined) return null;
  return idx > 0 && idx <= totalSteps ? idx - 1 : null;
}

export function DataframeBuilder({
  registry,
  instructions,
  setInstructions,
  replaceInstructions,
  commitInstructions,
  sessionId,
  setSessionId,
  uploadedFile,
  setUploadedFile,
  selectedStep,
  setSelectedStep,
  onPreviewSuccess,
}: DataframeBuilderProps) {
  const replace = replaceInstructions ?? setInstructions;
  const commit = commitInstructions ?? (() => setInstructions(instructions));

  const upTo = selectedStep === null ? instructions.transforms.length : selectedStep + 1;
  const preview = usePipelinePreview({ instructions, sessionId, upTo });

  // Surface successful previews to parent (e.g. so it can read the column list).
  const firstPage = preview.data?.pages[0];
  useEffect(() => {
    if (firstPage && !isPreviewError(firstPage) && onPreviewSuccess) {
      onPreviewSuccess(firstPage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstPage]);

  const handleSourceUploaded = useCallback(
    (sid: string, file: UploadedFileInfo) => {
      setSessionId(sid);
      setUploadedFile(file);
      if (!instructions.reader.func) {
        const auto = detectReader(file.name, registry.readers);
        if (auto) {
          setInstructions({ ...instructions, reader: { func: auto, args: {} } });
        }
      }
    },
    [instructions, registry.readers, setInstructions, setSessionId, setUploadedFile],
  );

  const handleSourceReset = useCallback(() => {
    if (sessionId) deleteSession(sessionId).catch(() => undefined);
    setSessionId(null);
    setUploadedFile(null);
    setSelectedStep(null);
  }, [sessionId, setSessionId, setUploadedFile, setSelectedStep]);

  const errorStepIndex =
    firstPage && isPreviewError(firstPage)
      ? indexFromError(firstPage, instructions.transforms.length)
      : null;

  const colTransforms = useMemo(
    () => columnAwareTransforms(registry.transforms),
    [registry.transforms],
  );

  const handleColumnAction = useCallback(
    (column: string, transformName: string) => {
      const spec = registry.transforms.find((t) => t.name === transformName);
      if (!spec) return;
      const colArg = findColumnArg(spec);
      if (!colArg) return;
      const value = colArg.type === 'columns' ? [column] : column;
      setInstructions({
        ...instructions,
        transforms: [...instructions.transforms, newStep(spec, { [colArg.name]: value })],
      });
      // Focus the freshly added step so the user can tweak remaining args.
      setSelectedStep(instructions.transforms.length);
    },
    [instructions, registry.transforms, setInstructions, setSelectedStep],
  );

  const stepLabel = useMemo(() => {
    if (selectedStep === null) {
      const n = instructions.transforms.length;
      if (n === 0) return 'reader';
      return `все шаги (${n})`;
    }
    const step = instructions.transforms[selectedStep];
    const spec = registry.transforms.find((t) => t.name === step?.func);
    return spec?.label ?? step?.func ?? 'reader';
  }, [selectedStep, instructions.transforms, registry.transforms]);

  return (
    <Grid>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Stack gap="md">
          <SourcePicker
            sessionId={sessionId}
            uploadedFile={uploadedFile}
            onUploaded={handleSourceUploaded}
            onReset={handleSourceReset}
          />
          <ReaderConfig
            readers={registry.readers}
            reader={instructions.reader}
            selected={selectedStep === null && instructions.transforms.length === 0}
            onSelect={() => setSelectedStep(null)}
            onChangeFunc={(func) =>
              setInstructions({ ...instructions, reader: { func, args: {} } })
            }
            onChangeArgs={(args) =>
              replace({ ...instructions, reader: { ...instructions.reader, args } })
            }
            onCommit={commit}
          />
          <StepList
            steps={instructions.transforms}
            transforms={registry.transforms}
            selectedIndex={selectedStep}
            errorIndex={errorStepIndex}
            instructions={instructions}
            sessionId={sessionId}
            onSelect={setSelectedStep}
            onAdd={(spec) =>
              setInstructions({
                ...instructions,
                transforms: [...instructions.transforms, newStep(spec)],
              })
            }
            onRemove={(idx) => {
              setInstructions({
                ...instructions,
                transforms: instructions.transforms.filter((_, i) => i !== idx),
              });
              if (selectedStep === idx) setSelectedStep(null);
            }}
            onReorder={(next) => setInstructions({ ...instructions, transforms: next })}
            onChangeArgs={(idx, args) =>
              replace({
                ...instructions,
                transforms: instructions.transforms.map((s, i) =>
                  i === idx ? { ...s, args } : s,
                ),
              })
            }
            onCommit={commit}
          />
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 7 }}>
        <PreviewPanel
          data={preview.data}
          isLoading={preview.isLoading}
          isFetching={preview.isFetching}
          isError={preview.isError}
          errorMessage={
            (preview.error as { response?: { status?: number } })?.response?.status === 404
              ? 'Сессия истекла. Загрузите файл заново.'
              : preview.error instanceof Error
              ? preview.error.message
              : undefined
          }
          hasSession={!!sessionId}
          stepLabel={stepLabel}
          hasNextPage={preview.hasNextPage}
          isFetchingNextPage={preview.isFetchingNextPage}
          fetchNextPage={preview.fetchNextPage}
          columnTransforms={colTransforms}
          onColumnAction={handleColumnAction}
        />
      </Grid.Col>
    </Grid>
  );
}
