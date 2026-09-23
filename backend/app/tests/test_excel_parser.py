import io
from decimal import Decimal
import openpyxl
from app.parsers.excel_packing import parse_packing_excel_bytes
from app.tests.conftest import build_packing_excel_008, PACKING_HEADER, _packing_row


def test_parse_008_structure():
    data = build_packing_excel_008()
    res = parse_packing_excel_bytes(data)
    assert res["total_box_count"] == 610
    ref_ids = [r.ref_id for r in res["refs"]]
    assert "RVG15056-260508-0003" in ref_ids
    # 体积计算正确
    r260508 = next(r for r in res["refs"] if r.ref_id == "RVG15056-260508-0003")
    assert r260508.volume_m3 == Decimal("33.176000")


def test_header_detected_and_mapped():
    data = build_packing_excel_008()
    res = parse_packing_excel_bytes(data)
    # Reference ID 在第二列（索引1）
    assert res["mapping"]["ref_id"] == 1
    assert res["mapping"]["hs_code"] == 13


def test_missing_key_field_warning():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(PACKING_HEADER)
    # 缺箱号、缺尺寸
    ws.append(_packing_row("", "REFX", "", "", "", "", "thing", "东西", 1, 10, "SX", ""))
    buf = io.BytesIO()
    wb.save(buf)
    res = parse_packing_excel_bytes(buf.getvalue())
    assert any("有效箱号" in w for it in res["items"] for w in it.warnings)
    assert any("HS Code" in w for it in res["items"] for w in it.warnings)


def test_manual_mapping_override():
    # 故意把列顺序打乱，使用手动映射仍可解析
    data = build_packing_excel_008()
    # 强制指定错误映射应被覆盖：这里验证 mapping 参数能被接受且返回一致箱数
    res = parse_packing_excel_bytes(data, mapping={"ref_id": 1, "box_spec": 0, "hs_code": 13,
                                                  "length": 3, "width": 4, "height": 5,
                                                  "en_name": 6, "cn_name": 7, "total_qty": 11,
                                                  "sku": 12})
    assert res["total_box_count"] == 610
