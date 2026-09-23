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
    # HS 不一致但数量/名称匹配 -> 待确认
    assert by_no["2"].status == "pending" and "HS" in by_no["2"].reason
    assert by_no["3"].status == "pending"
    assert by_no["4"].status == "auto" and by_no["4"].ref_id == "R4"
    # 零关税商品：duty_eur=0，归集金额为 0
    assert by_no["2"].duty_eur == Decimal("0.00")


def test_match_multiple_candidates():
    # 009 镜子场景：两个同描述/HS/数量货件，税项仅申报 12 -> 待确认且两个候选
    refs = [
        _ref("MA", "mirror", "7009920000", 12, "2"),
        _ref("MB", "mirror", "7009920000", 12, "2"),
    ]
    arts = [_art("M", "1", "mirror", "7009920000", 12, "400.00", "945.42")]
    matches = duty_core.match_articles_to_refs(arts, refs)
    m = matches[0]
    assert m.status == "pending"
    assert set(m.candidate_refs) == {"MA", "MB"}


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
    # 手动确认两者
    matches = duty_core.apply_confirmations(matches, {}, confirmations={"M|1": "R1", "M|2": "R3"})
    article_rmb = {"M|1": Decimal("2902.22"), "M|2": Decimal("2695.18")}
    res = duty_core.compute_ref_duty(matches, article_rmb)
    assert res["pending_amount"] == Decimal("0.00")
    assert (res["allocated"]["R1"] + res["allocated"]["R3"]) == Decimal("5597.40")
