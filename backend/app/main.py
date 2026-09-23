"""FastAPI 主程序：海运费用归集与关税分摊系统后端。

提供：会话管理、装箱单/海关文件上传解析、计算、人工确认、调整、Excel 导出。
所有业务文件仅在本地解析，不上传任何外部服务。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from urllib.parse import quote

from . import schemas
from .services import allocation_service as svc
from .services.allocation_service import _sanitize
from .services.export_excel import export_session_excel, build_export_filename
from .storage import repository as repo, db as dbmod


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbmod.init_db()
    yield


app = FastAPI(title="海运费用归集与关税分摊系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 独立演示环境；正式 ERP 集成时请收紧为 ERP 域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decimals_to_float(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {k: _decimals_to_float(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_decimals_to_float(x) for x in o]
    return o


def _as_float(v):
    try:
        return float(v)
    except Exception:
        return v


def _normalize_numbers(out: dict) -> dict:
    """把金额/数量字段统一为 number，便于前端直接 toFixed（存储层仍用字符串 Decimal）。"""
    if not isinstance(out, dict):
        return out
    for k in ("sea_freight_alloc", "duty_alloc", "article_rmb"):
        if isinstance(out.get(k), dict):
            out[k] = {kk: _as_float(vv) for kk, vv in out[k].items()}
    if "pending_duty" in out:
        out["pending_duty"] = _as_float(out["pending_duty"])
    for r in out.get("refs", []) or []:
        if isinstance(r, dict) and r.get("volume_m3") is not None:
            r["volume_m3"] = _as_float(r["volume_m3"])
    for r in ((out.get("packing") or {}).get("refs") or []):
        if isinstance(r, dict) and r.get("volume_m3") is not None:
            r["volume_m3"] = _as_float(r["volume_m3"])
    for m in out.get("matches", []) or []:
        if not isinstance(m, dict):
            continue
        for k in ("duty_eur", "vat_eur"):
            if m.get(k) is not None:
                m[k] = _as_float(m[k])
        if m.get("declared_qty") is not None:
            m["declared_qty"] = _as_float(m["declared_qty"])
    rc = out.get("reconciliation")
    if isinstance(rc, dict):
        for r in rc.get("declared_qty_diff", []) or []:
            if isinstance(r, dict):
                for k in ("customs_qty", "packing_qty", "diff"):
                    if r.get(k) is not None:
                        r[k] = _as_float(r[k])
    return out


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- 海关数据可用性校验 ----------
# 目的：解析不出税项/税额时必须立刻报错并阻断计算，
# 绝不能静默产出「缺信息的空表」（曾导致导出表整列为空、汇率为 0）。
_NO_PDF_MSG = (
    "海关税金单里没有 PDF 文件。"
    "请上传荷兰海关「缴税通知 / UITNODIGING TOT BETALING」的 PDF，或包含该 PDF 的 ZIP；"
    "压缩包内若只有图片（JPG/PNG）或「放行单 / TOESTEMMING TOT WEGVOERING」，本系统无法处理。"
)
_ZERO_ARTICLE_MSG = (
    "海关税金单解析到 0 条税项，已停止计算（避免生成缺信息的空表）。常见原因："
    "① 上传的是扫描件/图片型 PDF（本系统不做 OCR）；"
    "② 上传的不是缴税通知 UITNODIGING TOT BETALING；"
    "③ PDF 版式特殊，暂未适配。"
)
_ZERO_AMOUNT_MSG = (
    "海关税金单识别到 {n} 条税项，但关税金额（Douanerechten）合计为 €0，无法据以分摊。"
    "常见原因：上传的是「放行单 / TOESTEMMING TOT WEGVOERING」（放行单不含税额），"
    "或该 PDF 的金额版式暂未适配。请改传缴税通知 UITNODIGING TOT BETALING；"
    "若本柜确实为零关税，请把关税总额填 0 再分析。"
)


def _assert_customs_usable(customs: dict, rmb_duty) -> None:
    """税单必须有可分摊的税项与金额，否则抛 400 阻断。"""
    arts = customs.get("articles") or []
    if not arts:
        raise HTTPException(400, _ZERO_ARTICLE_MSG)
    total_eur = sum((Decimal(str(a.get("duty_eur") or 0)) for a in arts), Decimal("0"))
    try:
        input_duty = Decimal(str(rmb_duty or 0))
    except Exception:
        input_duty = Decimal("0")
    if total_eur <= 0 and input_duty > 0:
        raise HTTPException(400, _ZERO_AMOUNT_MSG.format(n=len(arts)))


@app.post("/api/sessions", response_model=schemas.SessionSummary)
def create_session(inp: schemas.CabinetInput):
    sid = svc.create_session(inp.cabinet_no, inp.sea_freight, inp.rmb_duty,
                             inp.exchange_rate, inp.note)
    return {"session_id": sid, "cabinet_no": inp.cabinet_no, "status": "draft",
            "created_at": "", "note": inp.note}


@app.get("/api/sessions", response_model=List[schemas.SessionSummary])
def list_sessions():
    rows = repo.list_sessions()
    return [{"session_id": r["session_id"], "cabinet_no": r["cabinet_no"],
             "status": r["status"], "created_at": r["created_at"],
             "note": r.get("note") or ""} for r in rows]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    s = repo.get_session(session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    return {"session_id": session_id, "cabinet_no": s["cabinet_no"],
            "status": s["status"], "data": _decimals_to_float(s["data"])}


@app.post("/api/sessions/{session_id}/packing")
def upload_packing(session_id: str, file: UploadFile = File(...),
                   sheet_name: Optional[str] = Query(None),
                   mapping: Optional[str] = Query(None)):
    data = file.file.read()
    mp = None
    if mapping:
        import json as _json
        mp = _json.loads(mapping)
    res = svc.parse_and_store_packing(session_id, data, sheet_name=sheet_name, mapping=mp)
    return _decimals_to_float(_sanitize(res))


@app.post("/api/sessions/{session_id}/customs")
def upload_customs(session_id: str, files: List[UploadFile] = File(...)):
    parsed_any = False
    for f in files:
        content = f.file.read()
        if f.filename.lower().endswith(".zip"):
            svc.parse_and_store_customs_zip(session_id, content)
            parsed_any = True
        elif content[:5] == b"%PDF-":
            from .parsers.pdf_customs import parse_customs_pdf_bytes
            svc.parse_and_store_customs(session_id, [(f.filename, content, True)])
            parsed_any = True
        else:
            # 非 PDF/ZIP（如图片）：提示人工补录
            continue
    if not parsed_any:
        raise HTTPException(400, _NO_PDF_MSG)
    s = repo.get_session(session_id)
    out = _decimals_to_float(_sanitize(s["data"]["customs"] or {}))
    _assert_customs_usable(s["data"]["customs"] or {}, s["data"].get("rmb_duty"))
    return out


@app.post("/api/sessions/{session_id}/compute")
def compute(session_id: str):
    res = svc.compute(session_id)
    return _normalize_numbers(_decimals_to_float(res))


def _build_verification(out: dict) -> dict:
    """自核结论：把需要人工核对的点自动核一遍，前端直接展示结论，无需逐步点检。"""
    rc = out.get("reconciliation") or {}
    counts = {"auto": 0, "manual": 0, "pending": 0, "unmatched": 0}
    for m in out.get("matches", []):
        st = m.get("status", "unmatched")
        counts[st] = counts.get(st, 0) + 1

    def _ok(v):
        try:
            return abs(float(v)) < 0.005
        except Exception:
            return False

    return {
        "sea_balanced": _ok(rc.get("sea_freight_diff", 0)),
        "duty_balanced": _ok(rc.get("duty_diff", 0)),
        "match_counts": counts,
        "pending_count": counts.get("pending", 0) + counts.get("unmatched", 0),
        "box_count_diff": rc.get("box_count_diff"),
        "qty_diff_count": len(rc.get("declared_qty_diff") or []),
        "unresolved": bool(rc.get("unresolved_exceptions")),
        "data_quality": _build_data_quality(out),
    }


def _num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _build_data_quality(out: dict) -> dict:
    """数据完整性体检：让缺失项在分析后立刻可见，而不是打开导出的 Excel 才发现。"""
    refs = out.get("refs") or []
    customs = out.get("customs") or {}
    arts = customs.get("articles") or []
    rc = out.get("reconciliation") or {}

    total_box = sum(int(r.get("total_box_count") or 0) for r in refs)
    total_vol = sum(_num(r.get("volume_m3")) for r in refs)
    eur_total = sum(_num(a.get("duty_eur")) for a in arts)
    sku_count = sum(len(r.get("items") or []) for r in refs)

    warnings = []
    if not refs:
        warnings.append("装箱单未解析到任何货件，请检查上传的 Excel")
    if refs and total_box == 0:
        warnings.append("装箱单总箱数为 0（箱数列未识别）")
    if refs and total_vol <= 0:
        warnings.append("装箱单总体积为 0（尺寸列未识别，海运费将按 0 体积分摊）")
    if not arts:
        warnings.append("海关税金单未解析到税项")
    if not customs.get("mrn"):
        warnings.append("海关税金单缺少 MRN 报关号")
    if arts and eur_total <= 0 and _num(rc.get("rmb_duty_input")) > 0:
        warnings.append("税金单关税金额为 0（可能上传的是放行单），无法据以分摊")

    # 已知限制（不影响分摊正确性）：荷兰海关缴税通知通常不打印申报总件数
    notes = []
    if customs.get("total_colli") is None:
        notes.append(
            "缴税通知不含申报总件数（colli），箱数无法与海关交叉核对；"
            "如需核对，请把同一票的放行单（TOESTEMMING TOT WEGVOERING）一起上传。"
        )

    return {
        "ref_count": len(refs),
        "sku_count": sku_count,
        "total_box": total_box,
        "total_volume": round(total_vol, 6),
        "article_count": len(arts),
        "eur_duty_total": round(eur_total, 2),
        "exchange_rate": round(_num(rc.get("exchange_rate")), 4),
        "mrn": customs.get("mrn") or "",
        "customs_colli": customs.get("total_colli"),
        "warnings": warnings,
        "notes": notes,
    }


@app.post("/api/analyze")
def analyze(
    cabinet_no: str = Form(...),
    sea_freight: float = Form(...),
    rmb_duty: float = Form(...),
    exchange_rate: Optional[float] = Form(None),
    note: str = Form(""),
    packing: UploadFile = File(...),
    customs: List[UploadFile] = File(default=[]),
):
    """一步式分析：建会话 → 解析装箱单 → 解析海关税单 → 匹配分摊 → 自核。

    只需填柜号/海运费/关税总额（汇率可留空自动推算）并上传文件，
    一次请求返回分摊结果与自核结论。
    """
    sid = svc.create_session(cabinet_no, sea_freight, rmb_duty, exchange_rate, note)
    svc.parse_and_store_packing(sid, packing.file.read())

    from .parsers.zip_handler import extract_zip_bytes

    pdf_files: List[tuple] = []
    for f in customs or []:
        content = f.file.read()
        fname = f.filename or ""
        if fname.lower().endswith(".zip") or content[:2] == b"PK":
            pdf_files.extend(extract_zip_bytes(content))
        elif content[:5] == b"%PDF-":
            pdf_files.append((fname, content, True))
    if not any(is_pdf for _, _, is_pdf in pdf_files):
        raise HTTPException(400, _NO_PDF_MSG)

    merged = svc.parse_and_store_customs(sid, pdf_files)
    # 税项/税额缺失一律阻断：宁可报错，也不产出缺信息的空表
    _assert_customs_usable(merged, rmb_duty)

    res = svc.compute(sid)
    s = repo.get_session(sid)
    res["packing"] = s["data"].get("packing")
    res["customs"] = s["data"].get("customs")

    out = _normalize_numbers(_decimals_to_float(_sanitize(res)))
    out["cabinet_no"] = cabinet_no
    out["verification"] = _build_verification(out)
    return out


@app.post("/api/sessions/{session_id}/confirm")
def confirm(session_id: str, inp: schemas.ConfirmationInput):
    res = svc.apply_confirmations(session_id, inp.confirmations, inp.splits, inp.actor)
    return _normalize_numbers(_decimals_to_float(res))


@app.post("/api/sessions/{session_id}/adjust")
def adjust(session_id: str, inp: schemas.ManualAdjustment):
    res = svc.apply_adjustment(session_id, inp.article_key, inp.field,
                               str(inp.new_value), inp.reason)
    return _decimals_to_float(res)


@app.post("/api/sessions/{session_id}/manual-article")
def manual_article(session_id: str, article: schemas.ManualArticle):
    res = svc.add_manual_article(session_id, article.dict())
    return _decimals_to_float(res)


@app.get("/api/sessions/{session_id}/export")
def export(session_id: str, mode: str = Query("final")):
    try:
        content = export_session_excel(session_id, mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    s = repo.get_session(session_id)
    fname = build_export_filename(s["cabinet_no"], mode)
    # HTTP 头只能含 latin-1；中文文件名用 RFC 5987（filename*）编码，
    # 同时提供 ASCII 回退名，确保各浏览器都能正确下载。
    ascii_name = f"{s['cabinet_no']}_cost_allocation_{mode}.xlsx"
    disp = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disp},
    )


# ---------- 生产环境静态资源（Docker 内前端构建产物） ----------
_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_BUILD_DIR):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=os.path.join(_BUILD_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index = os.path.join(_BUILD_DIR, "index.html")
        return FileResponse(index)
