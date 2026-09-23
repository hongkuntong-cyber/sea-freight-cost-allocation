from decimal import Decimal
from app.core.volume import box_single_volume_m3, box_type_volume_m3, allocate_sea_freight
from app.core.decimal_utils import largest_remainder, q2


def test_single_volume():
    # 80*58*65 / 1e6 = 0.3016
    assert box_single_volume_m3(80, 58, 65) == Decimal("0.301600")


def test_box_type_volume():
    sv = box_single_volume_m3(80, 58, 65)
    assert box_type_volume_m3(sv, 60) == Decimal("18.096000")


def test_sea_freight_sum_equals_total():
    freight = Decimal("54485.80")
    volumes = {"R1": Decimal("33.000000"), "R2": Decimal("26.000000"),
               "R3": Decimal("4.990000"), "R4": Decimal("2.830000")}
    alloc = allocate_sea_freight(freight, volumes)
    total = sum(Decimal(v) for v in alloc.values())
    assert total == freight
    for v in alloc.values():
        assert q2(v) == v


def test_largest_remainder_tail():
    # 100.03 按 1:2 分配 -> 33.34 + 66.69
    shares = largest_remainder([Decimal(1), Decimal(2)], Decimal("100.03"))
    assert sum(shares) == Decimal("100.03")
    assert shares[0] == Decimal("33.34")
    assert shares[1] == Decimal("66.69")


def test_tail_0_01():
    shares = largest_remainder([Decimal(1), Decimal(1), Decimal(1)], Decimal("100.01"))
    assert sum(shares) == Decimal("100.01")
    # 三笔：两笔 33.34，一笔 33.33（最大余数法确定性分配）
    assert sorted(shares) == [Decimal("33.33"), Decimal("33.34"), Decimal("33.34")]
