"""关税（进口关税）匹配与人民币分摊。

规则（对应需求第七、九章）：
    - 以缴税通知中的"实际应缴关税"（Douanerechten）为主要依据，VAT 单独记录不计入分摊。
    - 综合 HS Code、商品名称、申报数量匹配税项与货件，不得仅凭 HS 或仅凭名称强制匹配。
    - 匹配状态：auto（自动匹配）/ manual（人工确认）/ pending（待确认）/ unmatched（无法匹配）。
    - 零关税商品归集金额为 0，不得为分摊整柜关税强行分配。
    - 人民币分摊：按各税项原币关税占原币关税总额的比例分配"实际人民币关税总额"，
      使用最大余数法处理尾差，保证 已归集 + 待确认 == 实际人民币关税总额。
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Dict, List, Optional

from .decimal_utils import largest_remainder, q2
from ..models import CustomsArticle, MatchResult, PackingRef


def normalize_hs(hs: Optional[str]) -> str:
    if not hs:
        return ""
    return re.sub(r"[\s.]", "", str(hs)).upper()


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (s or "").lower())


def _desc_similarity(a: str, b: str) -> float:
    """简单的名称相似度（基于词重叠），用于匹配辅助判断。"""
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.8
    # 取较长串，计算共有字符比例
    longer = max(na, nb, key=len)
    shorter = min(na, nb, key=len)
    common = sum(1 for c in shorter if c in set(longer))
    return common / len(longer) if longer else 0.0


def match_articles_to_refs(articles: List[CustomsArticle], refs: List[PackingRef]) -> List[MatchResult]:
    """将海关税项匹配到货件，返回匹配结果列表。"""
    results: List[MatchResult] = []
    for art in articles:
        a_hs = normalize_hs(art.hs_code)
        a_qty = art.declared_qty
        a_desc = art.description or ""

        scored = []  # (score, ref, hs_match, qty_match, desc_match)
        for ref in refs:
            ref_hs_set = {normalize_hs(h) for h in ref.hs_codes}
            hs_match = a_hs != "" and a_hs in ref_hs_set
            # HS 近匹配：前 8 位相同（末两位差异）
            hs_near = False
            if a_hs and len(a_hs) >= 8:
                for h in ref_hs_set:
                    if len(h) >= 8 and h[:8] == a_hs[:8] and h != a_hs:
                        hs_near = True
            qty_match = False
            if a_qty is not None:
                try:
                    qty_match = (Decimal(a_qty) == ref.total_qty)
                except Exception:
                    qty_match = False
            # 描述匹配：与任一英文/中文品名相似
            desc_best = 0.0
            for nm in list(ref.en_names) + list(ref.cn_names):
                desc_best = max(desc_best, _desc_similarity(a_desc, nm))
            desc_match = desc_best >= 0.8

            score = 0
            if hs_match:
                score += 100
            elif hs_near:
                score += 40
            if desc_match:
                score += 50
            if qty_match:
                score += 60
            scored.append((score, ref, hs_match, qty_match, desc_match))

        # 取最高分；若多个 ref 同分且均为正，则视为歧义（待确认）
        max_score = max((s[0] for s in scored), default=0)
        top = [s for s in scored if s[0] == max_score and max_score > 0]

        res = MatchResult(
            article_key=f"{art.mrn}|{art.article_no}",
            mrn=art.mrn, article_no=art.article_no, description=art.description,
            hs_code=art.hs_code, declared_qty=art.declared_qty,
            duty_eur=art.duty_eur, vat_eur=art.vat_eur,
            status="unmatched", reason="未找到可匹配的货件（税单有记录但装箱单无对应货件）",
        )

        if max_score <= 0 or not top:
            results.append(res)
            continue

        if len(top) > 1:
            # 多个货件并列，无法唯一确认
            res.status = "pending"
            res.candidate_refs = [t[1].ref_id for t in top]
            res.reason = "多个货件均匹配，无法自动确认，需人工指定归属"
            res.hs_match = top[0][2]
            res.qty_match = top[0][3]
            res.desc_match = top[0][4]
            results.append(res)
            continue

        ref = top[0][1]
        hs_m, qty_m, desc_m = top[0][2], top[0][3], top[0][4]
        res.ref_id = ref.ref_id
        res.hs_match = hs_m
        res.qty_match = qty_m
        res.desc_match = desc_m
        res.candidate_refs = [ref.ref_id]

        if hs_m and qty_m and desc_m:
            res.status = "auto"
            res.reason = "HS Code、申报数量与商品名称均匹配"
        elif (qty_m and desc_m) and not hs_m:
            res.status = "pending"
            res.reason = (f"申报数量与商品名称匹配，但 HS Code 不一致"
                         f"（海关 {art.hs_code} vs 装箱 {sorted(set(ref.hs_codes))}），需人工确认")
        elif qty_m and hs_m and not desc_m:
            res.status = "pending"
            res.reason = "HS Code 与申报数量匹配，但商品名称不一致，需人工确认"
        elif qty_m and not hs_m and not desc_m:
            res.status = "pending"
            res.reason = "仅申报数量匹配，HS 与名称均不一致，需人工确认"
        elif (hs_m or desc_m) and not qty_m:
            res.status = "pending"
            res.reason = (f"HS/名称匹配但申报数量不一致"
                         f"（海关 {art.declared_qty} vs 装箱 {ref.total_qty}），需人工确认")
        else:
            res.status = "pending"
            res.reason = "匹配证据不足，需人工确认"

        results.append(res)
    return results


def allocate_article_rmb(article_eur: List[Decimal], rmb_total: Decimal) -> List[Decimal]:
    """按原币关税比例，把实际人民币关税总额分配到各税项（最大余数法）。"""
    return largest_remainder([Decimal(e) for e in article_eur], q2(rmb_total))


def apply_confirmations(matches: List[MatchResult],
                        article_rmb: Dict[str, Decimal],
                        confirmations: Optional[Dict[str, str]] = None,
                        splits: Optional[Dict[str, Dict[str, Decimal]]] = None) -> List[MatchResult]:
    """应用人工确认结果，更新匹配状态与归属。

    confirmations: {article_key: ref_id}  将 pending/unmatched 指定到某货件。
    splits: {article_key: {ref_id: rmb_amount}}  将一个税项按金额拆分到多个货件。
    返回更新后的 matches（不修改入参）。
    """
    confirmations = confirmations or {}
    splits = splits or {}
    updated = []
    for m in matches:
        nm = MatchResult(**{k: v for k, v in m.__dict__.items()})
        if m.article_key in splits:
            nm.status = "manual"
            nm.ref_id = None
            nm.candidate_refs = list(splits[m.article_key].keys())
            nm.reason = "已人工按比例拆分分摊"
        elif m.article_key in confirmations and m.status in ("pending", "unmatched"):
            nm.status = "manual"
            nm.ref_id = confirmations[m.article_key]
            nm.candidate_refs = [confirmations[m.article_key]]
            nm.reason = "已人工确认归属"
        updated.append(nm)
    return updated


def compute_ref_duty(matches: List[MatchResult], article_rmb: Dict[str, Decimal]) -> Dict[str, object]:
    """根据匹配结果，把各税项人民币关税归集到货件。

    返回：
        allocated: {ref_id: 人民币关税}
        pending_amount: 待确认人民币关税合计
        pending_items: 待确认/无法匹配税项列表（含候选货件）
        unmatched_items: 无法匹配税项
    """
    allocated: Dict[str, Decimal] = {}
    pending_amount = Decimal("0")
    pending_items = []
    unmatched_items = []
    for m in matches:
        rmb = article_rmb.get(m.article_key, Decimal("0"))
        if m.status in ("auto", "manual") and m.ref_id:
            allocated[m.ref_id] = allocated.get(m.ref_id, Decimal("0")) + rmb
        else:
            pending_amount += rmb
            pending_items.append(m)
            if m.status == "unmatched":
                unmatched_items.append(m)
    return {
        "allocated": {k: q2(v) for k, v in allocated.items()},
        "pending_amount": q2(pending_amount),
        "pending_items": pending_items,
        "unmatched_items": unmatched_items,
    }
