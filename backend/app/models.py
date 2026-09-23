"""领域数据模型（纯 dataclass，便于核心计算与序列化）。

API 层在输入输出时使用 Pydantic（见 schemas.py），核心计算使用这里的定义，
避免核心逻辑依赖 Web 框架。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class PackingItem:
    """装箱单中一行（一个箱型）。"""
    ref_id: str
    box_spec: str
    box_count: int
    sku: str
    en_name: str
    cn_name: str
    length_cm: Optional[Decimal]
    width_cm: Optional[Decimal]
    height_cm: Optional[Decimal]
    weight_kg: Optional[Decimal]
    single_qty: Optional[Decimal]
    total_qty: Optional[Decimal]
    hs_code: str
    purchase_price: Optional[Decimal]
    row_index: int
    warnings: List[str] = field(default_factory=list)
    # 解析得到的单箱体积与箱型总体积（m³）
    single_volume_m3: Optional[Decimal] = None
    box_type_volume_m3: Optional[Decimal] = None


@dataclass
class PackingRef:
    """按 Reference ID 聚合后的货件。"""
    ref_id: str
    items: List[PackingItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_box_count(self) -> int:
        return sum(i.box_count for i in self.items)

    @property
    def total_qty(self) -> Decimal:
        return sum((i.total_qty or Decimal(0)) for i in self.items)

    @property
    def volume_m3(self) -> Decimal:
        return sum((i.box_type_volume_m3 or Decimal(0)) for i in self.items)

    @property
    def hs_codes(self) -> List[str]:
        return [i.hs_code for i in self.items if i.hs_code]

    @property
    def en_names(self) -> List[str]:
        return [i.en_name for i in self.items if i.en_name]

    @property
    def cn_names(self) -> List[str]:
        return [i.cn_name for i in self.items if i.cn_name]

    @property
    def skus(self) -> List[str]:
        return [i.sku for i in self.items if i.sku]


@dataclass
class CustomsArticle:
    """海关商品税项（一笔）。"""
    mrn: str
    declaration_no: str
    article_no: str
    description: str
    hs_code: str
    declared_qty: Optional[Decimal]
    # 原币（欧元）金额
    duty_eur: Decimal
    vat_eur: Decimal
    duty_base: Optional[Decimal]
    duty_rate: Optional[Decimal]
    vat_base: Optional[Decimal]
    vat_rate: Optional[Decimal]
    source_file: str
    masked: bool = False
    reliable: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """税项与货件的匹配结果。"""
    article_key: str          # mrn + article_no
    mrn: str
    article_no: str
    description: str
    hs_code: str
    declared_qty: Optional[Decimal]
    duty_eur: Decimal
    vat_eur: Decimal
    status: str               # auto / manual / pending / unmatched
    ref_id: Optional[str] = None
    candidate_refs: List[str] = field(default_factory=list)
    reason: str = ""
    hs_match: bool = False
    qty_match: bool = False
    desc_match: bool = False
    # 合并报关按数量比例拆分时的权重：{ref_id: 数量权重}
    # 非空表示本税项由多个货件合并申报，需按比例拆分归属。
    split_weights: Dict[str, Decimal] = field(default_factory=dict)
