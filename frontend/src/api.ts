import axios from "axios";
import type {
  SessionSummary,
  PackingParseResult,
  CustomsParseResult,
  ComputeResult,
} from "./types";

const http = axios.create({ baseURL: "/api" });

export async function createSession(payload: {
  cabinet_no: string;
  sea_freight: number;
  rmb_duty: number;
  exchange_rate: number;
  note?: string;
}): Promise<SessionSummary> {
  const { data } = await http.post<SessionSummary>("/sessions", payload);
  return data;
}

export async function uploadPacking(
  sessionId: string,
  file: File,
): Promise<PackingParseResult> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await http.post<PackingParseResult>(
    `/sessions/${sessionId}/packing`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function uploadCustoms(
  sessionId: string,
  files: File[],
): Promise<CustomsParseResult> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const { data } = await http.post<CustomsParseResult>(
    `/sessions/${sessionId}/customs`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function compute(sessionId: string): Promise<ComputeResult> {
  const { data } = await http.post<ComputeResult>(`/sessions/${sessionId}/compute`);
  return data;
}

export async function confirm(
  sessionId: string,
  confirmations: Record<string, string>,
  splits: Record<string, Record<string, number>> = {},
): Promise<ComputeResult> {
  const { data } = await http.post<ComputeResult>(
    `/sessions/${sessionId}/confirm`,
    { confirmations, splits },
  );
  return data;
}

export function exportUrl(sessionId: string, mode: "final" | "pending"): string {
  return `/api/sessions/${sessionId}/export?mode=${mode}`;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const { data } = await http.get<SessionSummary[]>("/sessions");
  return data;
}
