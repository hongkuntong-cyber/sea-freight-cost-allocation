"""关税（进口关税）匹配与人民币分摊。

规则：
    - 以缴税通知中的"实际应缴关税"（Douanerechten）为主要依据，VAT 单独记录不计入分摊。
    - HS Code 以实际海关税金单为准；装箱单（头程发票）为初始版本、HS 可能变动，
      因此 HS 不一致不再作为待确认条件。
    - 装箱数量与海关申报数量存在误差属**正常业务差异**（漏装 / 装不下 / 加装其他货件），
      不作为待确认条件：归属唯一时自动归属，差异记录在「报关数量差异」中供核对。
    - 同 HS 合并报关：多个货件并列时按**装箱数量比例**拆分该税项（同 HS 同税率，
      按量分摊即为公允口径）；数量完全相同无法区分时均摊。
    - 仅当税项在装箱单里**完全找不到对应商品**（无任何候选）时才需要人工指定归属。
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
    """同 HS 合并报关 / 多货件并列时，按装箱数量自动拆分，避免无谓的人工确认。

    返回 (kind, payload)：
      - ("unique", ref_id)            申报数量与某货件的 HS 分组数量精确一致且唯一
      - ("split", {ref_id: 数量权重})  按装箱数量比例拆分（合计相等为精确拆分，
                                       不相等则视为漏装/加装等正常差异的比例分摊）
      - None                          候选货件没有任何数量信息，只能人工指定
    """
    a_qty = article.declared_qty
    buckets: List[tuple] = []
    for r in candidates:
        for q in _qty_buckets(r):
            buckets.append((r.ref_id, q))
    if not buckets:
        return None

    if a_qty is not None:
        a_qty = Decimal(a_qty)
        exact = [b for b in buckets if b[1] == a_qty]
        if len(exact) == 1:
            return ("unique", exact[0][0])

    # 同 HS 同税率：按装箱数量比例分摊即为公允口径（含合计相等/不等两种情形）。
    # 数量完全相同的多个货件（如两面镜子各 12）自然得到均摊结果。
    weights: Dict[str, Decimal] = {}
    for rid, q in buckets:
        weights[rid] = weights.get(rid, Decimal("0")) + q
    if sum(weights.values()) <= 0:
        return None
    return ("split", weights)


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
            status="unmatched",
            reason="装箱单里没有找到该商品（可能加装在其他货件），需要人工指定归属",
        )

        if max_score <= 0 or not top:
            results.append(res)
            continue

        if len(top) > 1:
            # 多个货件并列：按数量自动判定/拆分；完全没有数量信息才待确认
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
                    bucket_total = sum(payload.values())
                    res.reason = _split_reason(art, payload, bucket_total)
                results.append(res)
                continue

            # 候选货件没有任何数量信息，无法自动拆分
            res.status = "pending"
            res.candidate_refs = [t[1].ref_id for t in top]
            res.reason = "多个货件可能相关但均无数量信息，无法自动拆分，需人工指定归属"
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
        res.status = "auto"
        res.reason = _unique_reason(art, ref, hs_m, qty_m, desc_m)
        results.append(res)
    return results


def _qty_diff_txt(art: CustomsArticle, ref: PackingRef) -> str:
    if art.declared_qty is None:
        return ""
    try:
        d = Decimal(art.declared_qty) - Decimal(ref.total_qty)
        return f"（海关申报 {art.declared_qty} vs 装箱 {ref.total_qty}，差 {d}）"
    except Exception:
        return f"（海关申报 {art.declared_qty} vs 装箱 {ref.total_qty}）"


def _unique_reason(art: CustomsArticle, ref: PackingRef,
                   hs_m: bool, qty_m: bool, desc_m: bool) -> str:
    """唯一候选时的归属理由：数量误差视为正常业务差异，只说明、不阻断。"""
    if qty_m and desc_m:
        if hs_m:
            return "商品名称、申报数量与 HS Code 一致，自动匹配"
        return (f"商品名称与申报数量一致，已按税单 HS 自动匹配"
                f"（税单 HS {art.hs_code} 与装箱单 HS "
                f"{sorted(set(ref.hs_codes))} 不一致；装箱单为初始版本，以税单为准）")
    diff = _qty_diff_txt(art, ref)
    if desc_m and not qty_m:
        return ("商品名称一致，已自动归属该货件" + diff +
                "；数量差异多为漏装/装不下/加装等正常情况，已记录在「核对与异常」页")
    if qty_m and not desc_m:
        return "申报数量一致但商品名称写法不同（装箱单与税单口径不同），已自动归属该货件"
    if hs_m:
        return (f"HS Code {art.hs_code} 一致（同 HS 同税率，归属到哪个货件都不影响税额）；"
                "名称与数量有差异" + diff + "，已按税单归属该货件，差异记录在「核对与异常」页")
    return ("HS Code 近似（前 8 位相同，税单 " + str(art.hs_code) + "）；已按税单归属该货件" +
            diff + "，请留意「核对与异常」页差异")


def _split_reason(art: CustomsArticle, weights: Dict[str, Decimal],
                  bucket_total: Decimal) -> str:
    refs_txt = "、".join(f"{k}({v})" for k, v in weights.items())
    if art.declared_qty is None:
        return (f"多个货件合并相关（{refs_txt}），已按装箱数量比例分摊")
    if bucket_total == Decimal(art.declared_qty):
        return (f"同 HS 合并报关：多个货件合并申报"
                f"（装箱合计 {bucket_total} = 申报 {art.declared_qty}），"
                f"已按各货件数量比例自动拆分归属（{refs_txt}）")
    diff = Decimal(art.declared_qty) - bucket_total
    return (f"海关申报 {art.declared_qty}，装箱单对应合计 {bucket_total}"
            f"（差 {diff}，可能漏装/装不下/加装），已按装箱数量比例分摊到各货件（{refs_txt}），"
            "差异记录在「核对与异常」页")


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
