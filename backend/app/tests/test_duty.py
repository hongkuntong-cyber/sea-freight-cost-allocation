from decimal import Decimal
from app.core import duty as duty_core
from app.models import CustomsArticle, PackingItem, PackingRef


def _ref(rid, en, hs, qty, vol):
    it = PackingItem(ref_id=rid, box_spec="1", box_count=1, sku="S", en_name=en, cn_name="",
                     length_cm=10, width_cm=10, height_cm=10, weight_kg=1, single_qty=qty,
                     total_qty=qty, hs_code=hs, purchase_price=None, row_index=1,
                     single_volume_m3=Decimal(vol), box_type_volume_m3=Decimal(vol))
    return PackingRef(ref_id=rid, items=[it])


def _art(mrn, no, desc, hs, qty, duty, vat):
    return CustomsArticle(mrn=mrn, declaration_no="452975", article_no=no, description=desc,
                          hs_code=hs, declared_qty=qty, duty_eur=Decimal(duty), vat_eur=Decimal(vat),
                          duty_base=None, duty_rate=None, vat_base=None, vat_rate=None,
                          source_file="t", masked=False, reliable=True)


def test_match_008_like():
    refs = [
        _ref("R1", "bathtub", "3922100000", 330, "33"),
        _ref("R2", "Baby enclosure", "3926909090", 400, "26"),
        _ref("R3", "vase", "7013990000", 664, "5"),
        _ref("R4", "Baby mattress", "6302329000", 160, "3"),
    ]
    arts = [
        _art("M", "1", "bathtub", "3922100000", 330, "353.93", "1217.77"),
        _art("M", "2", "Baby enclosure", "9403208080", 400, "0.00", "1176.00"),
        _art("M", "3", "vase", "7013990090", 664, "328.68", "696.50"),
        _art("M", "4", "Baby mattress", "6302329000", 160, "230.40", "451.58"),
    ]
    matches = duty_core.match_articles_to_refs(arts, refs)
    by_no = {m.article_no: m for m in matches}
    assert by_no["1"].status == "auto" and by_no["1"].ref_id == "R1"
    # HS 不一致但数量/名称匹配 -> 以税单 HS 为准，仍为自动匹配（不再判待确认）
    assert by_no["2"].status == "auto" and by_no["2"].ref_id == "R2"
    assert "待确认" not in by_no["2"].reason and "税单" in by_no["2"].reason
    assert by_no["3"].status == "auto" and by_no["3"].ref_id == "R3"
    assert "待确认" not in by_no["3"].reason and "税单" in by_no["3"].reason
    assert by_no["4"].status == "auto" and by_no["4"].ref_id == "R4"
    # 零关税商品：duty_eur=0，归集金额为 0
    assert by_no["2"].duty_eur == Decimal("0.00")


def test_match_tie_split_evenly():
    """009 镜子场景：两个同描述/HS/数量货件，税项仅申报 12，无法区分 -> 按数量均摊。"""
    refs = [
        _ref("MA", "mirror", "7009920000", 12, "2"),
        _ref("MB", "mirror", "7009920000", 12, "2"),
    ]
    arts = [_art("M", "1", "mirror", "7009920000", 12, "400.00", "945.42")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    m = matches[0]
    assert m.status == "auto"
    assert m.split_weights == {"MA": Decimal("12"), "MB": Decimal("12")}
    # 关税 400 -> 各 200，分毫不差
    res = duty_core.compute_ref_duty(matches, {"M|1": Decimal("400.00")})
    assert res["allocated"]["MA"] == Decimal("200.00")
    assert res["allocated"]["MB"] == Decimal("200.00")
    assert res["pending_amount"] == Decimal("0.00")


def test_match_qty_variance_still_auto():
    """漏装/加装导致数量误差（海关 540 vs 装箱 402）：归属唯一即自动归属，不挂待确认。"""
    refs = [_ref("R1", "Artificial plants", "6702100000", 402, "20")]
    arts = [_art("M", "2", "Artificial plants", "6702100000", 540, "362.20", "0")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    m = matches[0]
    assert m.status == "auto" and m.ref_id == "R1"
    assert "540" in m.reason and "402" in m.reason  # 差异写明在理由里


def test_match_split_with_qty_variance():
    """同 HS 多货件且合计 != 申报（漏装/加装）：按装箱数量比例分摊整条税项。"""
    refs = [
        _ref("RA", "Heated Towel Rack", "8516299900", 16, "1"),
        _ref("RB", "Heated Towel Rack", "8516299900", 8, "1"),
    ]
    arts = [_art("M", "11", "Heated Towel Rack", "8516299900", 30, "100.00", "0")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    m = matches[0]
    assert m.status == "auto"
    assert m.split_weights == {"RA": Decimal("16"), "RB": Decimal("8")}
    assert "30" in m.reason and "24" in m.reason  # 海关 30 vs 装箱合计 24
    res = duty_core.compute_ref_duty(matches, {"M|11": Decimal("100.00")})
    assert res["allocated"]["RA"] == Decimal("66.67")
    assert res["allocated"]["RB"] == Decimal("33.33")
    assert res["pending_amount"] == Decimal("0.00")


def _ref_multi(rid, items):
    """一个货件内含多个（品名, HS, 数量, 体积）分组。"""
    its = [
        PackingItem(ref_id=rid, box_spec="1", box_count=1, sku="S", en_name=en, cn_name="",
                    length_cm=10, width_cm=10, height_cm=10, weight_kg=1, single_qty=q,
                    total_qty=q, hs_code=hs, purchase_price=None, row_index=i,
                    single_volume_m3=Decimal(vol), box_type_volume_m3=Decimal(vol))
        for i, (en, hs, q, vol) in enumerate(items, 1)
    ]
    return PackingRef(ref_id=rid, items=its)


def test_match_011_merged_declaration_auto_split():
    """011 真实结构：同 HS 合并报关，系统应按申报数量自动判定，不再要求人工确认。

    - 货件 R1 内含 6702100000/396 与 6702909000/280 两组；R2 为 6702100000/930。
    - 海关同 HS(6702100000) 拆成 396/280/930 三条，均能与货件分组精确对应。
    - 毛巾架 24 由 T1(16)+T2(8) 合并申报，按比例 16:8 拆分。
    """
    refs = [
        _ref_multi("R1", [("Artificial tree", "6702100000", 396, "10"),
                          ("Artificial tree", "6702909000", 280, "10")]),
        _ref("R2", "Artificial tree", "6702100000", 930, "10"),
        _ref("T1", "Heated Towel Rack", "8516299000", 16, "1"),
        _ref("T2", "Heated Towel Rack", "8516299000", 8, "1"),
    ]
    arts = [
        _art("M", "1", "Artificial plan", "6702100000", 396, "273.60", "0"),
        _art("M", "2", "Artificial plan", "6702100000", 280, "157.92", "0"),
        _art("M", "3", "Artificial plan", "6702100000", 930, "472.07", "0"),
        _art("M", "7", "Heated Towel  Rack", "8516299900", 24, "17.50", "0"),
    ]
    matches = duty_core.match_articles_to_refs(arts, refs)
    by_no = {m.article_no: m for m in matches}

    # 三条同 HS 税项按数量精确归属到对应货件，全部自动匹配
    assert by_no["1"].status == "auto" and by_no["1"].ref_id == "R1"
    assert by_no["2"].status == "auto" and by_no["2"].ref_id == "R1"
    assert by_no["3"].status == "auto" and by_no["3"].ref_id == "R2"

    # 合并报关（16+8=24）按数量比例自动拆分
    m7 = by_no["7"]
    assert m7.status == "auto"
    assert m7.split_weights == {"T1": Decimal("16"), "T2": Decimal("8")}
    assert m7.ref_id is None

    # 归集：拆分金额按 16:8 分配，且合计严格等于该税项金额
    article_rmb = {"M|1": Decimal("431.52"), "M|2": Decimal("305.86"),
                   "M|3": Decimal("914.20"), "M|7": Decimal("143.50")}
    res = duty_core.compute_ref_duty(matches, article_rmb)
    assert res["allocated"]["T1"] == Decimal("95.67")
    assert res["allocated"]["T2"] == Decimal("47.83")
    assert res["allocated"]["T1"] + res["allocated"]["T2"] == Decimal("143.50")
    # R1 收到税项 1+2，R2 收到税项 3
    assert res["allocated"]["R1"] == Decimal("431.52") + Decimal("305.86")
    assert res["allocated"]["R2"] == Decimal("914.20")
    assert res["pending_amount"] == Decimal("0.00")


def test_match_unmatched():
    refs = [_ref("R1", "bathtub", "3922100000", 330, "33")]
    arts = [_art("M", "1", "lamp", "9405200000", 50, "10.00", "2.10")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    assert matches[0].status == "unmatched"


def test_allocate_article_rmb_sum():
    shares = duty_core.allocate_article_rmb(
        [Decimal("353.93"), Decimal("0.00"), Decimal("328.68"), Decimal("230.40")],
        Decimal("7486.68"))
    assert sum(shares) == Decimal("7486.68")


def test_compute_ref_duty_respects_total():
    arts = [
        _art("M", "1", "bathtub", "3922100000", 330, "353.93", "0"),
        _art("M", "2", "vase", "7013990090", 664, "328.68", "0"),
    ]
    refs = [_ref("R1", "bathtub", "3922100000", 330, "33"),
            _ref("R3", "vase", "7013990000", 664, "5")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    # HS 不一致不再阻断：两者均按名称+数量自动匹配；此处确认仅为显式指定归属
    matches = duty_core.apply_confirmations(matches, {}, confirmations={"M|1": "R1", "M|2": "R3"})
    article_rmb = {"M|1": Decimal("2902.22"), "M|2": Decimal("2695.18")}
    res = duty_core.compute_ref_duty(matches, article_rmb)
    assert res["pending_amount"] == Decimal("0.00")
    assert (res["allocated"]["R1"] + res["allocated"]["R3"]) == Decimal("5597.40")
