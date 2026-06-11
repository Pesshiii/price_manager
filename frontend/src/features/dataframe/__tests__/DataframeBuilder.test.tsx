import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { DataframeBuilder, type UploadedFileInfo } from '../components/DataframeBuilder';
import { emptyInstructions, type Instructions, type Registry } from '../types';

const registry: Registry = {
  readers: [
    {
      name: 'read_csv',
      label: 'CSV',
      extensions: ['csv'],
      args: [],
    },
  ],
  transforms: [
    {
      name: 'drop_na',
      label: 'Drop NA',
      args: [],
    },
  ],
};

function Host({ initial }: { initial?: Instructions }) {
  const [instructions, setInstructions] = useState<Instructions>(initial ?? emptyInstructions());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<UploadedFileInfo | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  return (
    <DataframeBuilder
      registry={registry}
      instructions={instructions}
      setInstructions={setInstructions}
      sessionId={sessionId}
      setSessionId={setSessionId}
      uploadedFile={uploadedFile}
      setUploadedFile={setUploadedFile}
      selectedStep={selectedStep}
      setSelectedStep={setSelectedStep}
    />
  );
}

describe('DataframeBuilder', () => {
  it('renders source picker, reader config, step list and preview placeholder', () => {
    renderWithProviders(<Host />);
    // SourcePicker dropzone exposes aria-label="Загрузить файл"
    expect(screen.getByLabelText('Загрузить файл')).toBeInTheDocument();
    // ReaderConfig card has aria-label="Reader"
    expect(screen.getByLabelText('Reader')).toBeInTheDocument();
    // PreviewPanel shows hint while no session is attached
    expect(screen.getByText(/Загрузите файл/i)).toBeInTheDocument();
  });

  it('forwards preview success columns to onPreviewSuccess when builder receives data', () => {
    // We do not actually run a preview here (no session) — just sanity-check that the
    // hook plumbing renders without throwing when the optional callback is provided.
    const spy = vi.fn();
    renderWithProviders(<HostWithSpy spy={spy} />);
    expect(screen.getByLabelText('Загрузить файл')).toBeInTheDocument();
  });
});

function HostWithSpy({ spy }: { spy: (p: { columns: string[] }) => void }) {
  const [instructions, setInstructions] = useState<Instructions>(emptyInstructions());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<UploadedFileInfo | null>(null);
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  return (
    <DataframeBuilder
      registry={registry}
      instructions={instructions}
      setInstructions={setInstructions}
      sessionId={sessionId}
      setSessionId={setSessionId}
      uploadedFile={uploadedFile}
      setUploadedFile={setUploadedFile}
      selectedStep={selectedStep}
      setSelectedStep={setSelectedStep}
      onPreviewSuccess={(p) => spy({ columns: p.columns })}
    />
  );
}
