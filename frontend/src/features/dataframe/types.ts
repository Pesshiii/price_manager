export type ArgType =
  | 'str'
  | 'int'
  | 'float'
  | 'bool'
  | 'list[str]'
  | 'dict[str,str]'
  | 'column'
  | 'columns'
  | 'column_mapping'
  | 'value_mapping';

export interface ArgSpec {
  name: string;
  type: ArgType;
  label: string;
  required: boolean;
  default: unknown;
  choices: string[] | null;
  help_text: string;
}

export interface ReaderSpec {
  name: string;
  label: string;
  extensions: string[];
  args: ArgSpec[];
}

export interface TransformSpec {
  name: string;
  label: string;
  args: ArgSpec[];
}

export interface Registry {
  readers: ReaderSpec[];
  transforms: TransformSpec[];
}

export interface Step {
  func: string;
  args: Record<string, unknown>;
}

export interface Instructions {
  reader: { func: string; args: Record<string, unknown> };
  transforms: Step[];
  source?: { type: 'upload' | 'url'; url?: string };
}

export interface DataframePayload {
  id: number;
  name: string;
  description: string;
  instructions: Instructions;
  created_at: string;
  updated_at: string;
}

export interface UploadSessionResponse {
  session_id: string;
  filename: string;
  size: number;
}

export interface PreviewSuccess {
  columns: string[];
  rows: unknown[][];
  total_rows: number;
  returned_rows: number;
  offset: number;
  has_more: boolean;
}

export interface PreviewError {
  error: { step_index: number | null; message: string };
}

export type PreviewResult = PreviewSuccess | PreviewError;

export function isPreviewError(result: PreviewResult): result is PreviewError {
  return 'error' in result;
}

export const emptyInstructions = (): Instructions => ({
  reader: { func: '', args: {} },
  transforms: [],
});
