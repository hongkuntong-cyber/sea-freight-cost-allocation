// 与后端 Pydantic / dataclass 对应的前端类型定义。

export interface SessionSummary {
  session_id: string;
  cabinet_no: string;
  status: string;
  created_at: string;
  note: string;
}

export interface PackingItem {
  ref_id: string;
  box_spec: string;
  box_count: number;
  sku: string;
  en_name: string;
  cn_name: string;
  length_cm: number | null;
  width_cm: number | null;
  height_cm: number | null;
  total_qty: number | null;
  hs_code: string;
  warnings: string[];
}

export interface PackingRef {
  ref_id: string;
  items: PackingItem[];
  warnings: string[];
  total_box_count: number;
  volume_m3: number;
}

export interface PackingParseResult {
  total_box_count: number;
  refs: PackingRef[];
  warnings: string[];
}

export interface CustomsArticle {
  article_no: string;
  description: string;
  hs_code: string;
  declared_qty: number | null;
  duty_eur: number;
  vat_eur: number;
  masked: boolean;
  reliable: boolean;
}

export interface CustomsParseResult {
  file_type: string;
  mrn: string | null;
  declaration_no: string | null;
  container: string | null;
  total_colli: number | null;
  articles: CustomsArticle[];
  total_invitation_amount: number | null;
  reliable: boolean;
  warnings: string[];
}

export interface MatchResult {
  article_key: string;
  article_no: string;
  description: string;
  hs_code: string;
  declared_qty: number | null;
  duty_eur: number;
  vat_eur: number;
  status: "auto" | "manual" | "pending" | "unmatched";
  ref_id: string | null;
  candidate_refs: string[];
  reason: string;
  hs_match: boolean;
  qty_match: boolean;
  desc_match: boolean;
}

export interface Reconciliation {
  original_sea_freight: number;
  allocated_sea_freight: number;
  sea_freight_diff: number;
  eur_duty_total: number;
  exchange_rate: number;
  rmb_duty_input: number;
  allocated_duty: number;
  pending_duty: number;
  duty_diff: number;
  box_count_packing: number;
  box_count_customs: number | null;
  box_count_diff: number | null;
  declared_qty_diff: Array<Record<string, any>>;
  hs_anomalies: Array<Record<string, any>>;
  tail_handling: string;
  unresolved_exceptions: boolean;
}

export interface Verification {
  sea_balanced: boolean;
  duty_balanced: boolean;
  match_counts: Record<string, number>;
  pending_count: number;
  box_count_diff: number | null;
  qty_diff_count: number;
  unresolved: boolean;
}

export interface AnalyzeResult extends ComputeResult {
  cabinet_no: string;
  packing: PackingParseResult | null;
  customs: CustomsParseResult | null;
  verification: Verification;
}

export interface ComputeResult {
  session_id: string;
  refs: PackingRef[];
  matches: MatchResult[];
  sea_freight_alloc: Record<string, number>;
  article_rmb: Record<string, number>;
  duty_alloc: Record<string, number>;
  pending_duty: number;
  reconciliation: Reconciliation;
}
