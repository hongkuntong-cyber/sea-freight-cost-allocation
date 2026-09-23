from decimal import Decimal
from app.services import allocation_service as svc
from app.tests.conftest import (build_packing_excel_008, build_uitnodiging_pdf_008,
                                build_packing_excel_009, build_uitnodiging_pdf_009)


def test_008_end_to_end(tmp_db):
    sid = svc.create_session("008", 54485.80, 7486.68, 8.2, "回归")
    svc.parse_and_store_packing(sid, build_packing_excel_008())
    svc.parse_and_store_customs(sid, [("njeu.pdf", build_uitnodiging_pdf_008(), True)])
    res = svc.compute(sid)
    sea_sum = sum(Decimal(v) for v in res["sea_freight_alloc"].values())
    assert sea_sum == Decimal("54485.80")
    duty_sum = Decimal(res["reconciliation"]["allocated_duty"]) + Decimal(res["pending_duty"])
    assert duty_sum == Decimal("7486.68")
    # 存在 HS 不一致待确认
    assert Decimal(res["pending_duty"]) > 0
    # 确认待确认税项
    confirms = {}
    for m in res["matches"]:
        if m["status"] == "pending" and m["candidate_refs"]:
            confirms[m["article_key"]] = m["candidate_refs"][0]
    res2 = svc.apply_confirmations(sid, confirms, {})
    assert Decimal(res2["reconciliation"]["pending_duty"]) == 0
    assert res2["reconciliation"]["unresolved_exceptions"] is False
    # 已归集 + 待确认 仍严格等于输入
    duty_sum2 = Decimal(res2["reconciliation"]["allocated_duty"]) + Decimal(res2["pending_duty"])
    assert duty_sum2 == Decimal("7486.68")


def test_009_mirror_pending_not_forced(tmp_db):
    sid = svc.create_session("009", 56965.80, 12284.50, 8.2, "回归")
    svc.parse_and_store_packing(sid, build_packing_excel_009())
    svc.parse_and_store_customs(sid, [("009.pdf", build_uitnodiging_pdf_009(), True)])
    res = svc.compute(sid)
    sea_sum = sum(Decimal(v) for v in res["sea_freight_alloc"].values())
    assert sea_sum == Decimal("56965.80")
    duty_sum = Decimal(res["reconciliation"]["allocated_duty"]) + Decimal(res["pending_duty"])
    assert duty_sum == Decimal("12284.50")
    # 镜子税项必须待确认，且有两个候选货件
    mirror = next(m for m in res["matches"] if m["description"] == "mirror")
    assert mirror["status"] == "pending"
    assert set(mirror["candidate_refs"]) == {"RVG15056-260909-0001", "RVG15056-260909-0002"}
    # 在用户确认前，镜子关税不得归集到任一货件
    assert Decimal(res["duty_alloc"].get("RVG15056-260909-0001", "0")) == 0
    assert Decimal(res["duty_alloc"].get("RVG15056-260909-0002", "0")) == 0
    assert Decimal(res["pending_duty"]) > 0
