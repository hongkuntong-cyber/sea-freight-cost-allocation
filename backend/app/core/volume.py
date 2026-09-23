"""体积计算与海运费按体积比例分摊。

规则：
    - 单箱体积(m³) = 长×宽×高(cm) ÷ 1,000,000
    - 箱型总体积 = 单箱体积 × 箱数
    - 货件(Reference ID)总体积 = 该货件下全部箱型体积之和
    - 整柜总体积 = 全部货件总体积之和
    - 货件体积占比 = 货件总体积 ÷ 整柜总体积
    - 货件海运费 = 整柜海运费 × 货件体积占比
    - 使用最大余数法处理尾差，保证各货件海运费合计 == 整柜海运费（严格对平）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List

from .decimal_utils import largest_remainder, q2, q6


def box_single_volume_m3(length_cm, width_cm, height_cm) -> Decimal:
    """单箱体积（立方米），保留六位小数以保证分摊精度。"""
    l = Decimal(str(length_cm))
    w = Decimal(str(width_cm))
    h = Decimal(str(height_cm))
    return q6(l * w * h / Decimal("1000000"))


def box_type_volume_m3(single_volume: Decimal, box_count: int) -> Decimal:
    return q6(single_volume * Decimal(box_count))


def allocate_sea_freight(container_sea_freight, ref_volumes: Dict[str, Decimal]) -> Dict[str, Decimal]:
    """按体积比例分摊整柜海运费到各 Reference ID。

    返回 {ref_id: 海运费(元, 两位小数)}，合计严格等于 container_sea_freight。
    """
    freight = q2(container_sea_freight)
    refs = list(ref_volumes.keys())
    weights = [ref_volumes[r] for r in refs]
    if sum(weights) <= 0:
        # 体积全为 0：无法按体积分摊，等量分摊（最大余数法对全 0 权重返回全 0，
        # 这里改为等量分摊更合理，且仍严格对平）
        shares = largest_remainder([Decimal(1) for _ in refs], freight) if refs else []
        return dict(zip(refs, shares))
    shares = largest_remainder(weights, freight)
    return dict(zip(refs, shares))


def ref_volume_ratio(ref_volume: Decimal, total_volume: Decimal) -> Decimal:
    """体积占比（保留 6 位小数用于展示与复核，金额仍按分位精确分配）。"""
    if total_volume <= 0:
        return Decimal("0")
    return (ref_volume / total_volume).quantize(Decimal("0.000001"))
