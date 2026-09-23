"""FastAPI 主程序：海运费用归集与关税分摊系统后端。

提供：会话管理、装箱单/海关文件上传解析、计算、人工确认、调整、Excel 导出。
所有业务文件仅在本地解析，不上传任何外部服务。
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


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
        raise HTTPException(400, "未检测到可解析的 PDF 或 ZIP 文件")
    s = repo.get_session(session_id)
    return _decimals_to_float(_sanitize(s["data"]["customs"]))


@app.post("/api/sessions/{session_id}/compute")
def compute(session_id: str):
    res = svc.compute(session_id)
    return _decimals_to_float(res)


@app.post("/api/sessions/{session_id}/confirm")
def confirm(session_id: str, inp: schemas.ConfirmationInput):
    res = svc.apply_confirmations(session_id, inp.confirmations, inp.splits, inp.actor)
    return _decimals_to_float(res)


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
