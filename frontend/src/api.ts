import axios from "axios";
import type {
  SessionSummary,
  PackingParseResult,
  CustomsParseResult,
  ComputeResult,
  AnalyzeResult,
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

/** 一步式分析：填三个字段 + 上传文件，一次请求完成解析/匹配/分摊/自核。 */
export async function analyze(payload: {
  cabinet_no: string;
  sea_freight: number;
  rmb_duty: number;
  exchange_rate?: number;
  note?: string;
}, packingFile: File, customsFiles: File[]): Promise<AnalyzeResult> {
  const fd = new FormData();
  fd.append("cabinet_no", payload.cabinet_no);
  fd.append("sea_freight", String(payload.sea_freight));
  fd.append("rmb_duty", String(payload.rmb_duty));
  if (payload.exchange_rate) fd.append("exchange_rate", String(payload.exchange_rate));
  if (payload.note) fd.append("note", payload.note);
  fd.append("packing", packingFile);
  for (const f of customsFiles) fd.append("customs", f);
  const { data } = await http.post<AnalyzeResult>("/analyze", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
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
