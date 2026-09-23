"""装箱单 Excel 解析（基于表头名识别，支持手动字段映射回退）。

不依赖固定列位置。先扫描各 Sheet 寻找"表头行"（命中已知表头别名最多的一行），
建立 canonical 字段到列号的映射；数据行从该表头行之后开始解析。
关键字段（Reference ID、箱号、尺寸、HS Code）缺失时给出告警，绝不自行补造。
"""
from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

import openpyxl

from ..core.box_parser import parse_box_spec, detect_box_anomalies
from ..core.volume import box_single_volume_m3, box_type_volume_m3
from ..models import PackingItem, PackingRef

# canonical 字段 -> 表头别名（小写包含匹配）
FIELD_ALIASES = {
    "ref_id": ["reference id", "reference", "货件编号", "货件号", "货件"],
    "box_spec": ["货箱编号", "箱号", "箱编号", "carton", "box no", "box number", "箱"],
    "sku": ["sku"],
    "en_name": ["英文品名", "英文名称", "english name", "english", "品名", "description", "商品名称"],
    "cn_name": ["中文品名", "中文名称", "chinese name", "chinese"],
    "length": ["货箱长度", "长(cm)", "长", "length"],
    "width": ["货箱宽度", "宽(cm)", "宽", "width"],
    "height": ["货箱高度", "高(cm)", "高", "height"],
    "weight": ["货箱重量", "重量", "weight"],
    "single_qty": ["单箱数量", "每箱数量", "qty per box", "数量/箱"],
    "total_qty": ["总数量", "总件数", "total qty", "total quantity"],
    "hs_code": ["产品海关编码", "海关编码", "hs code", "hs", "海关编码(清关)"],
    "purchase_price": ["采购单价", "采购价", "purchase price"],
}

KEY_FIELDS = ["ref_id", "box_spec", "length", "width", "height", "hs_code"]


def _norm_header(text) -> str:
    if text is None:
        return ""
    return str(text).strip().lower().replace("*", "")


def _detect_header_row(ws, max_scan=40) -> (int, Dict[str, int], List):
    """返回 (header_row_index, mapping, header_values)。"""
    best = (-1, {}, [])
    best_hits = 2  # 至少命中 3 个才算表头
    for ri, row in enumerate(ws.iter_rows(values_only=True)):
        if ri > max_scan:
            break
        hits = 0
        mapping: Dict[str, int] = {}
        header_vals = [c for c in row]
        norm_cells = [_norm_header(c) for c in row]
        for field, aliases in FIELD_ALIASES.items():
            for ci, nc in enumerate(norm_cells):
                if not nc:
                    continue
                if any(alias in nc for alias in aliases):
                    mapping[field] = ci
                    hits += 1
                    break
        if hits > best_hits:
            best_hits = hits
            best = (ri, mapping, header_vals)
    return best


def _to_decimal(v) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            return None
    s = str(v).strip().replace(",", ".").replace(" ", "")
    if s == "":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_packing_excel_bytes(data: bytes,
                             sheet_name: Optional[str] = None,
                             mapping: Optional[Dict[str, int]] = None) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    sheets = wb.sheetnames

    target = sheet_name or sheets[0]
    if target not in sheets:
        # 退回到第一个
        target = sheets[0]
    ws = wb[target]

    header_ri, detected_map, header_vals = _detect_header_row(ws)
    if header_ri < 0:
        return {
            "sheets": sheets, "detected_sheet": target, "headers": [],
            "mapping": {}, "items": [], "refs": [],
            "warnings": ["未能识别装箱单表头，请手动指定字段映射"], "total_box_count": 0,
        }

    use_map = mapping if mapping else detected_map

    items: List[PackingItem] = []
    file_warnings: List[str] = []
    # header_ri 为 0-based 行号；数据行从表头下一行（1-based = header_ri + 2）开始
    for ri in range(header_ri + 2, ws.max_row + 1):
        row = [c for c in next(ws.iter_rows(min_row=ri, max_row=ri, values_only=True))]
        if not any(c is not None and str(c).strip() != "" for c in row):
            continue

        def get(field):
            ci = use_map.get(field)
            if ci is None or ci >= len(row):
                return None
            return row[ci]

        ref_id = (str(get("ref_id")).strip() if get("ref_id") is not None else "")
        if not ref_id:
            # 跳过无 Reference ID 的行（可能是合计/备注行）
            continue

        box_spec = (str(get("box_spec")).strip() if get("box_spec") is not None else "")
        bp = parse_box_spec(box_spec)
        box_count = bp.count if bp.error is None else 0

        length = _to_decimal(get("length"))
        width = _to_decimal(get("width"))
        height = _to_decimal(get("height"))
        single_vol = None
        box_type_vol = None
        if length is not None and width is not None and height is not None and box_count > 0:
            single_vol = box_single_volume_m3(length, width, height)
            box_type_vol = box_type_volume_m3(single_vol, box_count)

        warnings: List[str] = []
        if bp.error:
            warnings.append(f"箱号解析: {bp.error}")
        for kf in KEY_FIELDS:
            if kf == "box_spec":
                if not box_spec or box_count == 0:
                    warnings.append("缺少有效箱号")
            elif get(kf) is None:
                label = {"ref_id": "Reference ID", "length": "长", "width": "宽",
                         "height": "高", "hs_code": "HS Code"}[kf]
                warnings.append(f"缺少关键字段：{label}")

        item = PackingItem(
            ref_id=ref_id,
            box_spec=box_spec,
            box_count=box_count,
            sku=(str(get("sku")).strip() if get("sku") is not None else ""),
            en_name=(str(get("en_name")).strip() if get("en_name") is not None else ""),
            cn_name=(str(get("cn_name")).strip() if get("cn_name") is not None else ""),
            length_cm=length, width_cm=width, height_cm=height,
            weight_kg=_to_decimal(get("weight")),
            single_qty=_to_decimal(get("single_qty")),
            total_qty=_to_decimal(get("total_qty")),
            hs_code=(str(get("hs_code")).strip() if get("hs_code") is not None else ""),
            purchase_price=_to_decimal(get("purchase_price")),
            row_index=ri + 1,
            warnings=warnings,
            single_volume_m3=single_vol,
            box_type_volume_m3=box_type_vol,
        )
        items.append(item)

    # 聚合为货件并做箱号异常检测
    refs = _aggregate_refs(items, file_warnings)

    total_box_count = sum(r.total_box_count for r in refs)
    if total_box_count == 0:
        file_warnings.append("未解析到任何有效箱数，请检查装箱单内容")

    return {
        "sheets": sheets,
        "detected_sheet": target,
        "headers": [_norm_header(h) for h in header_vals],
        "mapping": use_map,
        "items": items,
        "refs": refs,
        "warnings": file_warnings,
        "total_box_count": total_box_count,
    }


def _aggregate_refs(items: List[PackingItem], warnings: List[str]) -> List[PackingRef]:
    by_ref: Dict[str, List[PackingItem]] = {}
    order: List[str] = []
    for it in items:
        if it.ref_id not in by_ref:
            by_ref[it.ref_id] = []
            order.append(it.ref_id)
        by_ref[it.ref_id].append(it)
    refs: List[PackingRef] = []
    for rid in order:
        rit = by_ref[rid]
        ref_warns: List[str] = []
        ranges = []
        for it in rit:
            bp = parse_box_spec(it.box_spec)
            if bp.error is None:
                ranges.extend(bp.ranges)
        anomalies = detect_box_anomalies(ranges)
        ref_warns.extend(anomalies)
        refs.append(PackingRef(ref_id=rid, items=rit, warnings=ref_warns))
    return refs
