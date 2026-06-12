import { api } from '@/api/client';
import type {
  DataframePayload,
  Instructions,
  PreviewResult,
  Registry,
  UploadSessionResponse,
} from './types';

const BASE = '/dataframe';

export async function getRegistry(): Promise<Registry> {
  const { data } = await api.get<Registry>(`${BASE}/registry/`);
  return data;
}

export async function listPipelines(): Promise<DataframePayload[]> {
  const { data } = await api.get<DataframePayload[]>(`${BASE}/pipelines/`);
  return data;
}

export async function getPipeline(id: number): Promise<DataframePayload> {
  const { data } = await api.get<DataframePayload>(`${BASE}/pipelines/${id}/`);
  return data;
}

export interface SavePayload {
  name: string;
  description: string;
  instructions: Instructions;
}

export async function createPipeline(payload: SavePayload): Promise<DataframePayload> {
  const { data } = await api.post<DataframePayload>(`${BASE}/pipelines/`, payload);
  return data;
}

export async function updatePipeline(id: number, payload: SavePayload): Promise<DataframePayload> {
  const { data } = await api.put<DataframePayload>(`${BASE}/pipelines/${id}/`, payload);
  return data;
}

export async function deletePipeline(id: number): Promise<void> {
  await api.delete(`${BASE}/pipelines/${id}/`);
}

export async function uploadSession(file: File): Promise<UploadSessionResponse> {
  const fd = new FormData();
  fd.append('file', file);
  const { data } = await api.post<UploadSessionResponse>(`${BASE}/sessions/`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  await api.delete(`${BASE}/sessions/${sessionId}/`);
}

export interface SessionMetadata {
  session_id: string;
  filename: string;
  size: number;
  uploaded_at: string;
}

export async function getSession(sessionId: string): Promise<SessionMetadata> {
  const { data } = await api.get<SessionMetadata>(`${BASE}/sessions/${sessionId}/`);
  return data;
}

export interface PreviewArgs {
  instructions: Instructions;
  sessionId: string;
  upTo?: number;
  rowLimit?: number;
  offset?: number;
}

export async function previewPipeline(args: PreviewArgs): Promise<PreviewResult> {
  const body: Record<string, unknown> = {
    instructions: args.instructions,
    session_id: args.sessionId,
  };
  if (args.upTo !== undefined) body.up_to = args.upTo;
  if (args.rowLimit !== undefined) body.row_limit = args.rowLimit;
  if (args.offset !== undefined) body.offset = args.offset;
  const { data } = await api.post<PreviewResult>(`${BASE}/preview/`, body);
  return data;
}
