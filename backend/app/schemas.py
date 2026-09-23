"""API 数据模型（Pydantic）。"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CabinetInput(BaseModel):
    cabinet_no: str = Field(..., description="柜号")
    sea_freight: float = Field(..., description="整柜海运费（人民币元）")
    rmb_duty: float = Field(..., description="实际人民币关税总额")
    exchange_rate: float = Field(..., description="货代结算汇率")
    note: str = ""


class FieldMapping(BaseModel):
    # canonical -> 列号（0 起）
    mapping: Optional[Dict[str, int]] = None
    sheet_name: Optional[str] = None


class ManualArticle(BaseModel):
    article_no: str
    description: str = ""
    hs_code: str = ""
    declared_qty: Optional[float] = None
    duty_eur: float = 0.0
    vat_eur: float = 0.0
    source_file: str = "manual"


class ManualAdjustment(BaseModel):
    article_key: str
    field: str  # e.g. duty_eur / declared_qty / hs_code
    new_value: str
    reason: str = ""


class ConfirmationInput(BaseModel):
    # article_key -> ref_id
    confirmations: Dict[str, str] = {}
    # article_key -> {ref_id: rmb_amount}
    splits: Dict[str, Dict[str, float]] = {}
    actor: str = "local-operator"


class SessionSummary(BaseModel):
    session_id: str
    cabinet_no: str
    status: str
    created_at: str
    note: str = ""


class UploadResult(BaseModel):
    session_id: str
    sheets: List[str] = []
    detected_sheet: str = ""
    headers: List[str] = []
    mapping: Dict[str, int] = {}
    items: List[dict] = []
    refs: List[dict] = []
    warnings: List[str] = []
    total_box_count: int = 0


class CustomsResult(BaseModel):
    session_id: str
    mrn: Optional[str] = None
    declaration_no: Optional[str] = None
    container: Optional[str] = None
    total_colli: Optional[int] = None
    articles: List[dict] = []
    file_summaries: List[dict] = []


class ComputeResult(BaseModel):
    session_id: str
    refs: List[dict] = []
    matches: List[dict] = []
    sea_freight_alloc: Dict[str, str] = {}
    article_rmb: Dict[str, str] = {}
    duty_alloc: Dict[str, str] = {}
    pending_duty: str = "0.00"
    reconciliation: dict = {}
