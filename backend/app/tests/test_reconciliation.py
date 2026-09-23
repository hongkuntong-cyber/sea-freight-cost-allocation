from decimal import Decimal
from app.core import duty as duty_core
from app.core.reconciliation import build_reconciliation
from app.core.volume import allocate_sea_freight
from app.models import CustomsArticle, MatchResult, PackingItem, PackingRef


def _ref(rid, en, hs, qty, vol):
    it = PackingItem(ref_id=rid, box_spec="1", box_count=1, sku="S", en_name=en, cn_name="",
                     length_cm=10, width_cm=10, height_cm=10, weight_kg=1, single_qty=qty,
                     total_qty=qty, hs_code=hs, purchase_price=None, row_index=1,
                     single_volume_m3=Decimal(vol), box_type_volume_m3=Decimal(vol))
    return PackingRef(ref_id=rid, items=[it])


def _match(art_no, desc, hs, qty, duty, status, ref_id, hs_match):
    return MatchResult(article_key=f"M|{art_no}", mrn="M", article_no=art_no, description=desc,
                       hs_code=hs, declared_qty=qty, duty_eur=Decimal(duty), vat_eur=Decimal("0"),
                       status=status, ref_id=ref_id, hs_match=hs_match, qty_match=True, desc_match=True)


def test_reconciliation_balances():
    refs = [_ref("R1", "bathtub", "3922100000", 330, "33"),
            _ref("R2", "Baby enclosure", "3926909090", 400, "26"),
            _ref("R3", "vase", "7013990000", 664, "5"),
            _ref("R4", "Baby mattress", "6302329000", 160, "3")]
    matches = [
        _match("1", "bathtub", "3922100000", 330, "353.93", "auto", "R1", True),
        _match("2", "Baby enclosure", "9403208080", 400, "0.00", "pending", "R2", False),
        _match("3", "vase", "7013990090", 664, "328.68", "pending", "R3", False),
        _match("4", "Baby mattress", "6302329000", 160, "230.40", "auto", "R4", True),
    ]
    sea_alloc = allocate_sea_freight(Decimal("54485.80"), {r.ref_id: r.volume_m3 for r in refs})
    recon = build_reconciliation(
        sea_freight_input=Decimal("54485.80"), sea_allocated=sea_alloc,
        eur_duty_total=Decimal("913.01"), exchange_rate=Decimal("8.2"),
        rmb_duty_input=Decimal("7486.68"),
        duty_allocated={"R1": Decimal("2902.22"), "R4": Decimal("1889.28")},
        pending_duty=Decimal("2695.18"), matches=matches, refs=refs, customs_total_colli=4)
    assert recon["sea_freight_diff"] == Decimal("0.00")
    assert recon["duty_diff"] == Decimal("0.00")
    # 存在待确认 -> 未解决
    assert recon["unresolved_exceptions"] is True
    # HS 异常应记录两条
    assert len(recon["hs_anomalies"]) == 2
    assert recon["box_count_diff"] == 0
