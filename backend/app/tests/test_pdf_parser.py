from decimal import Decimal
from app.parsers.pdf_customs import parse_customs_pdf_bytes, merge_customs_parses
from app.tests.conftest import (build_uitnodiging_pdf_008, build_uitnodiging_pdf_009,
                                build_release_pdf_009)


def test_parse_008_payment_invitation():
    data = build_uitnodiging_pdf_008()
    p = parse_customs_pdf_bytes(data, "NJEU.pdf")
    assert p["file_type"] == "payment_invitation"
    assert p["mrn"] == "26NL8DWEQ6QRD5SDR2"
    assert len(p["articles"]) == 4
    a1 = p["articles"][0]
    assert a1["description"] == "bathtub"
    assert a1["declared_qty"] == 330
    assert a1["hs_code"] == "3922100000"
    assert a1["duty_eur"] == Decimal("353.93")
    assert a1["vat_eur"] == Decimal("1217.77")
    # VAT 不得计入关税
    assert a1["duty_eur"] != a1["duty_eur"] + a1["vat_eur"]
    assert a1["masked"] is True


def test_008_duty_total_matches_invitation():
    data = build_uitnodiging_pdf_008()
    p = parse_customs_pdf_bytes(data, "NJEU.pdf")
    total = sum(a["duty_eur"] for a in p["articles"])
    assert total == Decimal("913.01")


def test_zero_duty_article():
    data = build_uitnodiging_pdf_008()
    p = parse_customs_pdf_bytes(data, "NJEU.pdf")
    a2 = p["articles"][1]
    assert a2["description"] == "Baby enclosure"
    assert a2["duty_eur"] == Decimal("0.00")
    assert a2["vat_eur"] == Decimal("1176.00")


def test_parse_009_pdf():
    data = build_uitnodiging_pdf_009()
    p = parse_customs_pdf_bytes(data, "009.pdf")
    assert p["mrn"] == "26NL9ABCDEFGHIJKLM"
    assert len(p["articles"]) == 2
    by_desc = {a["description"]: a for a in p["articles"]}
    assert by_desc["mirror"]["declared_qty"] == Decimal("12")
    assert by_desc["lamp"]["duty_eur"] == Decimal("1098.11")


def test_release_classification():
    data = build_release_pdf_009()
    p = parse_customs_pdf_bytes(data, "rel.pdf")
    assert p["file_type"] == "release"
    assert p["container"] == "COSU7771234567"
    # 放行单无金额
    assert all(a["duty_eur"] == Decimal("0") for a in p["articles"])


def test_dedupe_same_mrn():
    d1 = build_uitnodiging_pdf_008()
    d2 = build_uitnodiging_pdf_008()
    p1 = parse_customs_pdf_bytes(d1, "a.pdf")
    p2 = parse_customs_pdf_bytes(d2, "b.pdf")
    merged = merge_customs_parses([p1, p2])
    # 同一 MRN + 税项序号，去重后仍是 4 项，不得重复累计
    assert len(merged["articles"]) == 4
    total = sum(a["duty_eur"] for a in merged["articles"])
    assert total == Decimal("913.01")
