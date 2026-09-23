"""关税（进口关税）匹配与人民币分摊。

规则（对应需求第七、九章）：
    - 以缴税通知中的"实际应缴关税"（Douanerechten）为主要依据，VAT 单独记录不计入分摊。
    - HS Code 以实际海关税金单为准；装箱单（头程发票）为初始版本、HS 可能变动，
      因此 HS 不一致不再作为待确认条件。匹配以「商品名称 + 申报数量」为主键，
      税单 HS 为权威 HS（装箱单 HS 仅作参考）。
    - 不得仅凭 HS 或仅凭名称强制匹配；仅在名称/数量不一致或货件并列等真正歧义时才待确认。
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


def _qty_buckets(ref: PackingRef) -> List[Decimal]:
    """货件按装箱 HS 分组的数量桶。

    同 HS 会合并报关，一个货件内部可能含多个 HS 分组（且装箱 HS 为初始版本可能变动），
    因此按"HS 分组数量"而非货件总数量来比对申报数量。
    """
    acc: Dict[str, Decimal] = {}
    for it in ref.items:
        if it.total_qty is None:
            continue
        key = normalize_hs(it.hs_code) or "_"
        acc[key] = acc.get(key, Decimal("0")) + Decimal(it.total_qty)
    return [q for q in acc.values() if q > 0]


def _resolve_merged_by_qty(article: CustomsArticle,
                           candidates: List[PackingRef]) -> Optional[tuple]:
    """同 HS 合并报关时，用申报数量反推归属，避免无谓的人工确认。

    返回 (kind, payload)：
      - ("unique", ref_id)            申报数量与某货件的 HS 分组数量精确一致且唯一
      - ("split", {ref_id: 数量权重})  候选货件分组数量合计 == 申报数量，按数量比例拆分
      - None                          无法唯一判定，保持待确认（绝不强行归集）
    """
    a_qty = article.declared_qty
    if a_qty is None:
        return None
    a_qty = Decimal(a_qty)

    buckets: List[tuple] = []
    for r in candidates:
        for q in _qty_buckets(r):
            buckets.append((r.ref_id, q))

    exact = [b for b in buckets if b[1] == a_qty]
    if len(exact) == 1:
        return ("unique", exact[0][0])
    if len(exact) > 1:
        # 多个货件数量都等于申报数量，无法区分（如 009 两面镜子各 12，仅申报 12）
        return None

    total = sum((b[1] for b in buckets), Decimal("0"))
    if buckets and total == a_qty and len(buckets) > 1:
        weights: Dict[str, Decimal] = {}
        for rid, q in buckets:
            weights[rid] = weights.get(rid, Decimal("0")) + q
        return ("split", weights)
    return None


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
            # 多个货件并列：先按"同 HS 合并报关"用申报数量自动判定，判不了才待确认
            resolved = _resolve_merged_by_qty(art, [t[1] for t in top])
            if resolved:
                kind, payload = resolved
                res.hs_match = top[0][2]
                res.qty_match = top[0][3]
                res.desc_match = top[0][4]
                res.status = "auto"
                if kind == "unique":
                    res.ref_id = payload
                    res.candidate_refs = [payload]
                    res.reason = ("同 HS 合并报关：申报数量 "
                                  f"{art.declared_qty} 与该货件完全一致，自动归属")
                else:
                    res.ref_id = None
                    res.candidate_refs = list(payload.keys())
                    res.split_weights = dict(payload)
                    res.reason = ("同 HS 合并报关：多个货件合并申报"
                                  f"（合计 {sum(payload.values())} = 申报 {art.declared_qty}），"
                                  "已按各货件数量比例自动拆分归属")
                results.append(res)
                continue

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

        # 业务规则：HS Code 以实际海关税金单为准；装箱单（头程发票）为初始版本，
        # 其 HS 可能变动，故 HS 不一致不再作为待确认条件。匹配以「商品名称 + 申报数量」
        # 为主键，命中即自动匹配并采用税单 HS；仅当名称或数量不一致、或货件并列等
        # 真正歧义时才待人工确认。
        if qty_m and desc_m:
            res.status = "auto"
            if hs_m:
                res.reason = "商品名称、申报数量与 HS Code 一致，自动匹配"
            else:
                res.reason = (
                    f"商品名称与申报数量一致，已按税单 HS 自动匹配"
                    f"（税单 HS {art.hs_code} 与装箱单 HS "
                    f"{sorted(set(ref.hs_codes))} 不一致；装箱单为初始版本，以税单为准）"
                )
        elif qty_m and not desc_m:
            res.status = "pending"
            res.reason = "申报数量一致但商品名称不一致，需人工确认归属"
        elif desc_m and not qty_m:
            res.status = "pending"
            res.reason = (f"商品名称一致但申报数量不一致"
                         f"（海关 {art.declared_qty} vs 装箱 {ref.total_qty}），需人工确认归属")
        elif hs_m and not (qty_m or desc_m):
            res.status = "pending"
            res.reason = "仅 HS Code 匹配，商品名称与申报数量均不一致，证据不足，需人工确认"
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
        if m.split_weights:
            # 合并报关：按各货件数量比例拆分，最大余数法保证拆分金额合计等于该税项金额
            shares = largest_remainder(list(m.split_weights.values()), q2(rmb))
            for rid, sh in zip(m.split_weights.keys(), shares):
                allocated[rid] = allocated.get(rid, Decimal("0")) + sh
        elif m.status in ("auto", "manual") and m.ref_id:
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
