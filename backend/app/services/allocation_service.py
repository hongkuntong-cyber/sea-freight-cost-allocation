"""编排服务：解析 → 匹配 → 分摊 → 对账 → 导出。

维护每个货柜的计算状态（存于 SQLite，全量 JSON）。所有金额使用 Decimal，
海运费与关税均通过最大余数法严格对平。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from ..core import duty as duty_core
from ..core import reconciliation as recon_core
from ..core import volume as vol_core
from ..core.decimal_utils import q2
from ..models import CustomsArticle, MatchResult, PackingItem, PackingRef
from ..parsers.excel_packing import parse_packing_excel_bytes
from ..parsers.pdf_customs import parse_customs_pdf_bytes, merge_customs_parses
from ..parsers.zip_handler import extract_zip_bytes
from ..storage import repository as repo


# ---------- 序列化 ----------
def _sanitize(o):
    if is_dataclass(o) and not isinstance(o, type):
        return {f.name: _sanitize(getattr(o, f.name)) for f in fields(o)}
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (list, tuple)):
        return [_sanitize(x) for x in o]
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    return o


def _d(v):
    return Decimal(str(v)) if v not in (None, "") else Decimal("0")


def _item_from_dict(d: dict) -> PackingItem:
    return PackingItem(
        ref_id=d["ref_id"], box_spec=d.get("box_spec", ""), box_count=int(d.get("box_count", 0)),
        sku=d.get("sku", ""), en_name=d.get("en_name", ""), cn_name=d.get("cn_name", ""),
        length_cm=_d(d.get("length_cm")) if d.get("length_cm") not in (None, "") else None,
        width_cm=_d(d.get("width_cm")) if d.get("width_cm") not in (None, "") else None,
        height_cm=_d(d.get("height_cm")) if d.get("height_cm") not in (None, "") else None,
        weight_kg=_d(d.get("weight_kg")) if d.get("weight_kg") not in (None, "") else None,
        single_qty=_d(d.get("single_qty")) if d.get("single_qty") not in (None, "") else None,
        total_qty=_d(d.get("total_qty")) if d.get("total_qty") not in (None, "") else None,
        hs_code=d.get("hs_code", ""),
        purchase_price=_d(d.get("purchase_price")) if d.get("purchase_price") not in (None, "") else None,
        row_index=int(d.get("row_index", 0)),
        warnings=list(d.get("warnings", [])),
        single_volume_m3=_d(d.get("single_volume_m3")) if d.get("single_volume_m3") not in (None, "") else None,
        box_type_volume_m3=_d(d.get("box_type_volume_m3")) if d.get("box_type_volume_m3") not in (None, "") else None,
    )


def _ref_from_dict(d: dict) -> PackingRef:
    return PackingRef(
        ref_id=d["ref_id"],
        items=[_item_from_dict(i) for i in d.get("items", [])],
        warnings=list(d.get("warnings", [])),
    )


def _article_from_dict(d: dict) -> CustomsArticle:
    return CustomsArticle(
        mrn=d.get("mrn", ""), declaration_no=d.get("declaration_no", ""),
        article_no=str(d.get("article_no", "")), description=d.get("description", ""),
        hs_code=d.get("hs_code", ""),
        declared_qty=_d(d.get("declared_qty")) if d.get("declared_qty") not in (None, "") else None,
        duty_eur=_d(d.get("duty_eur")),
        vat_eur=_d(d.get("vat_eur")),
        duty_base=_d(d.get("duty_base")) if d.get("duty_base") not in (None, "") else None,
        duty_rate=_d(d.get("duty_rate")) if d.get("duty_rate") not in (None, "") else None,
        vat_base=_d(d.get("vat_base")) if d.get("vat_base") not in (None, "") else None,
        vat_rate=_d(d.get("vat_rate")) if d.get("vat_rate") not in (None, "") else None,
        source_file=d.get("source_file", ""),
        masked=bool(d.get("masked", False)),
        reliable=bool(d.get("reliable", True)),
        notes=list(d.get("notes", [])),
    )


# ---------- 会话管理 ----------
def create_session(cabinet_no, sea_freight, rmb_duty, exchange_rate, note="") -> str:
    # 汇率可留空：留空时存空串，在 compute 时按 关税总额 ÷ 欧元关税总额 自动推算。
    rate_str = "" if exchange_rate in (None, "") else str(exchange_rate)
    state = {
        "cabinet_no": cabinet_no, "sea_freight": str(sea_freight),
        "rmb_duty": str(rmb_duty), "exchange_rate": rate_str, "note": note,
        "packing": None, "customs": None, "matches": [], "reconciliation": {},
        "article_rmb": {}, "sea_alloc": {}, "duty_alloc": {}, "pending_duty": "0.00",
        "confirmations": {}, "splits": {}, "manual_articles": [],
    }
    return repo.create_session(cabinet_no, sea_freight, rmb_duty,
                               float(exchange_rate) if exchange_rate else 0.0, note, state)


def _load(session_id: str) -> dict:
    s = repo.get_session(session_id)
    if not s:
        raise ValueError("会话不存在")
    return s


def parse_and_store_packing(session_id: str, file_bytes: bytes,
                            sheet_name: Optional[str] = None,
                            mapping: Optional[Dict[str, int]] = None) -> dict:
    s = _load(session_id)
    res = parse_packing_excel_bytes(file_bytes, sheet_name=sheet_name, mapping=mapping)
    s["data"]["packing"] = _sanitize(res)
    repo.update_session(session_id, s["data"])
    return res


def parse_and_store_customs(session_id: str, files: List[tuple]) -> dict:
    """files: [(filename, bytes, is_pdf), ...]（已解压或单文件）。"""
    s = _load(session_id)
    parses = []
    for fname, data, is_pdf in files:
        if is_pdf:
            parses.append(parse_customs_pdf_bytes(data, fname))
        # 非 PDF（如图片）跳过解析，提示人工补录
    merged = merge_customs_parses(parses)
    s["data"]["customs"] = _sanitize(merged)
    repo.update_session(session_id, s["data"])
    return merged


def parse_and_store_customs_zip(session_id: str, zip_bytes: bytes) -> dict:
    files = extract_zip_bytes(zip_bytes)
    return parse_and_store_customs(session_id, files)


# ---------- 计算 ----------
def compute(session_id: str) -> dict:
    s = _load(session_id)
    data = s["data"]
    if not data.get("packing") or not data.get("customs"):
        raise ValueError("请先上传装箱单与海关税单")

    refs = [_ref_from_dict(r) for r in data["packing"]["refs"]]
    articles = [_article_from_dict(a) for a in data["customs"]["articles"]]

    # 1) 匹配
    matches = duty_core.match_articles_to_refs(articles, refs)

    # 2) 各税项人民币关税（按原币比例 + 最大余数法）
    article_eur = [m.duty_eur for m in matches]
    shares = duty_core.allocate_article_rmb(article_eur, Decimal(data["rmb_duty"]))
    article_rmb = {m.article_key: q2(sh) for m, sh in zip(matches, shares)}

    # 3) 应用人工确认 / 拆分
    confirms = data.get("confirmations", {}) or {}
    splits = data.get("splits", {}) or {}
    matches = duty_core.apply_confirmations(matches, article_rmb, confirms, splits)

    # 4) 归集到货件
    duty_res = duty_core.compute_ref_duty(matches, article_rmb)

    # 5) 海运费按体积分摊
    ref_volumes = {r.ref_id: r.volume_m3 for r in refs}
    sea_alloc = vol_core.allocate_sea_freight(Decimal(data["sea_freight"]), ref_volumes)

    # 6) 汇率：未填写时按 关税总额 ÷ 欧元关税总额 自动推算
    eur_duty_total = sum((a.duty_eur for a in articles), Decimal("0"))
    rate_raw = str(data.get("exchange_rate") or "")
    if rate_raw and Decimal(rate_raw) > 0:
        rate = Decimal(rate_raw)
    else:
        rate = (Decimal(data["rmb_duty"]) / eur_duty_total) if eur_duty_total > 0 else Decimal("0")
    data["exchange_rate"] = str(rate)

    # 7) 对账
    recon = recon_core.build_reconciliation(
        sea_freight_input=Decimal(data["sea_freight"]),
        sea_allocated=sea_alloc,
        eur_duty_total=eur_duty_total,
        exchange_rate=rate,
        rmb_duty_input=Decimal(data["rmb_duty"]),
        duty_allocated=duty_res["allocated"],
        pending_duty=duty_res["pending_amount"],
        matches=matches,
        refs=refs,
        customs_total_colli=data["customs"].get("total_colli"),
    )

    # 保存结果
    data["matches"] = _sanitize(matches)
    data["article_rmb"] = {k: str(v) for k, v in article_rmb.items()}
    data["sea_alloc"] = {k: str(v) for k, v in sea_alloc.items()}
    data["duty_alloc"] = {k: str(v) for k, v in duty_res["allocated"].items()}
    data["pending_duty"] = str(duty_res["pending_amount"])
    data["reconciliation"] = recon
    repo.update_session(session_id, _sanitize(data))

    return {
        "session_id": session_id,
        "refs": _sanitize(refs),
        "matches": _sanitize(matches),
        "sea_freight_alloc": data["sea_alloc"],
        "article_rmb": data["article_rmb"],
        "duty_alloc": data["duty_alloc"],
        "pending_duty": data["pending_duty"],
        "reconciliation": recon,
    }


def apply_confirmations(session_id: str, confirmations: Dict[str, str],
                        splits: Dict[str, Dict[str, float]], actor: str = "local-operator") -> dict:
    s = _load(session_id)
    data = s["data"]
    data["confirmations"] = confirmations
    data["splits"] = {k: {rk: str(rv) for rk, rv in v.items()} for k, v in splits.items()}
    repo.update_session(session_id, data)
    repo.append_audit(session_id, actor, "confirm", {
        "confirmations": confirmations, "splits": splits})
    return compute(session_id)


def apply_adjustment(session_id: str, article_key: str, field: str, new_value: str,
                    reason: str = "", actor: str = "local-operator") -> dict:
    s = _load(session_id)
    data = s["data"]
    found = None
    for a in data["customs"]["articles"]:
        key = f"{a.get('mrn','')}|{a.get('article_no','')}"
        if key == article_key:
            found = a
            break
    if not found:
        raise ValueError("税项不存在")
    old = found.get(field)
    found[field] = new_value
    repo.update_session(session_id, data)
    repo.append_audit(session_id, actor, "adjust", {
        "article_key": article_key, "field": field, "old": old, "new": new_value, "reason": reason})
    return compute(session_id)


def add_manual_article(session_id: str, article: dict, actor: str = "local-operator") -> dict:
    s = _load(session_id)
    data = s["data"]
    mrn = data["customs"].get("mrn") or "MANUAL"
    art = {
        "mrn": mrn, "declaration_no": data["customs"].get("declaration_no") or "",
        "article_no": str(article.get("article_no", "")),
        "description": article.get("description", ""), "hs_code": article.get("hs_code", ""),
        "declared_qty": article.get("declared_qty"),
        "duty_eur": str(article.get("duty_eur", 0)),
        "vat_eur": str(article.get("vat_eur", 0)),
        "duty_base": None, "duty_rate": None, "vat_base": None, "vat_rate": None,
        "source_file": article.get("source_file", "manual"),
        "masked": False, "reliable": True, "notes": ["人工补录"],
    }
    data["customs"]["articles"].append(art)
    repo.update_session(session_id, data)
    repo.append_audit(session_id, actor, "add_manual_article", art)
    return compute(session_id)
