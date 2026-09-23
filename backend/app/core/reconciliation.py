"""金额与数据对账（对应需求第十一章 Sheet 4）。

产出可用于核对与异常 Sheet 的全部字段：海运费对平、关税对平、箱数差异、
报关数量差异、HS Code 异常、尾差处理说明，以及"是否存在未解决关键异常"。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from .decimal_utils import q2
from .duty import normalize_hs
from ..models import MatchResult, PackingRef


def build_reconciliation(
    *,
    sea_freight_input: Decimal,
    sea_allocated: Dict[str, Decimal],
    eur_duty_total: Decimal,
    exchange_rate: Decimal,
    rmb_duty_input: Decimal,
    duty_allocated: Dict[str, Decimal],
    pending_duty: Decimal,
    matches: List[MatchResult],
    refs: List[PackingRef],
    customs_total_colli: Optional[int] = None,
) -> dict:
    sea_alloc_sum = q2(sum(sea_allocated.values()))
    sea_diff = q2(sea_freight_input - sea_alloc_sum)

    duty_alloc_sum = q2(sum(duty_allocated.values()))
    # 已归集 + 待确认 必须等于 实际人民币关税
    duty_diff = q2(rmb_duty_input - duty_alloc_sum - pending_duty)

    # 箱数差异：装箱单总箱数 vs 海关申报总件数（colli）
    packing_box_total = sum(r.total_box_count for r in refs)
    box_count_diff = None
    if customs_total_colli is not None:
        box_count_diff = packing_box_total - customs_total_colli

    # 报关数量差异：已匹配税项，海关申报数量 vs 装箱数量。
    # 比较口径：货件内该 HS 分组的数量（同 HS 合并报关），无该分组时退回货件总数量。
    # 数量误差属正常业务差异（漏装/装不下/加装），此处只记录供核对，不阻断归集。
    declared_qty_diff = []
    ref_by_id = {r.ref_id: r for r in refs}
    for m in matches:
        if m.status in ("auto", "manual") and m.ref_id and m.declared_qty is not None:
            ref = ref_by_id.get(m.ref_id)
            packing_qty = ref.total_qty if ref else Decimal("0")
            if ref is not None and m.hs_code:
                hs = normalize_hs(m.hs_code)
                bucket = sum((Decimal(it.total_qty) for it in ref.items
                              if it.total_qty is not None and normalize_hs(it.hs_code) == hs),
                             Decimal("0"))
                if bucket > 0:
                    packing_qty = bucket
            try:
                diff = Decimal(m.declared_qty) - packing_qty
            except Exception:
                diff = None
            if diff is not None and diff != 0:
                declared_qty_diff.append({
                    "ref_id": m.ref_id,
                    "article": f"{m.article_no}: {m.description}",
                    "customs_qty": q2(m.declared_qty),
                    "packing_qty": q2(packing_qty),
                    "diff": q2(diff),
                })
        elif m.status in ("auto", "manual") and getattr(m, "split_weights", None) \
                and m.declared_qty is not None:
            # 合并拆分税项：记录 海关申报数量 vs 装箱合计 的整体差异
            try:
                packing_qty = sum((Decimal(w) for w in m.split_weights.values()), Decimal("0"))
                diff = Decimal(m.declared_qty) - packing_qty
            except Exception:
                continue
            if diff != 0:
                declared_qty_diff.append({
                    "ref_id": "合并拆分：" + "/".join(m.split_weights.keys()),
                    "article": f"{m.article_no}: {m.description}",
                    "customs_qty": q2(m.declared_qty),
                    "packing_qty": q2(packing_qty),
                    "diff": q2(diff),
                })

    # HS Code 异常：仅列示仍未解决的（待确认/无法匹配 且 HS 不一致）
    hs_anomalies = []
    for m in matches:
        if m.status in ("pending", "unmatched") and m.ref_id and not m.hs_match:
            ref = ref_by_id.get(m.ref_id)
            packing_hs = sorted(set(ref.hs_codes)) if ref else []
            hs_anomalies.append({
                "ref_id": m.ref_id,
                "article": f"{m.article_no}: {m.description}",
                "customs_hs": m.hs_code,
                "packing_hs": packing_hs,
                "note": "归属仍未确认，需人工指定（HS 以税单为准，装箱单 HS 为初始版本仅供参考）",
            })

    # 未解决关键异常：存在 pending / unmatched，或海运费/关税对平差额不为 0。
    # （已自动/人工确认但 HS 不一致的项视为已解决，仅作记录，不阻断最终确认）
    has_pending = any(m.status in ("pending", "unmatched") for m in matches)
    unresolved_exceptions = has_pending or sea_diff != 0 or duty_diff != 0

    tail_note = (
        "海运费按各货件体积占比分配，使用最大余数法对整数分进行尾差处理，"
        "同等余数时按 Reference ID 稳定排序，保证各货件海运费合计严格等于整柜海运费；"
        "关税按各税项原币关税占原币关税总额的比例分配实际人民币关税总额，"
        "同样采用最大余数法，保证已归集关税与待确认关税之和严格等于实际人民币关税。"
    )

    return {
        "original_sea_freight": q2(sea_freight_input),
        "allocated_sea_freight": sea_alloc_sum,
        "sea_freight_diff": sea_diff,
        "eur_duty_total": q2(eur_duty_total),
        "exchange_rate": q2(exchange_rate),
        "rmb_duty_input": q2(rmb_duty_input),
        "allocated_duty": duty_alloc_sum,
        "pending_duty": q2(pending_duty),
        "duty_diff": duty_diff,
        "box_count_packing": packing_box_total,
        "box_count_customs": customs_total_colli,
        "box_count_diff": box_count_diff,
        "declared_qty_diff": declared_qty_diff,
        "hs_anomalies": hs_anomalies,
        "tail_handling": tail_note,
        "unresolved_exceptions": unresolved_exceptions,
    }
