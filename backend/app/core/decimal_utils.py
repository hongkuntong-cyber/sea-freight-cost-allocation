"""高精度十进制工具与确定性尾差（最大余数法）处理。

所有金额以人民币元为单位，最终保留两位小数。海运费、关税的归集必须严格对平，
因此使用最大余数法将"按比例的带小数分配"调整为"整数分（cent）层面的精确分配"，
同等余数时按输入顺序（稳定排序）分配，保证可复核、可复现。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext

# 提高全局精度，避免中间计算浮点误差
getcontext().prec = 28

# 人民币分位量化器（保留两位小数）
CENT = Decimal("0.01")


def q2(value) -> Decimal:
    """量化到两位小数（四舍五入）。"""
    if value is None:
        return Decimal("0.00")
    d = Decimal(str(value))
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def q6(value) -> Decimal:
    """量化到六位小数（用于体积等中间量，保留足够精度后再按分位分配金额）。"""
    if value is None:
        return Decimal("0.000000")
    d = Decimal(str(value))
    return d.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def to_cents(value) -> int:
    """将元转换为整数分（四舍五入）。"""
    return int(q2(value).shift(2))


def from_cents(cents: int) -> Decimal:
    """整数分转回元（两位小数）。"""
    return Decimal(cents).scaleb(-2)


def largest_remainder(weights, total: Decimal):
    """最大余数法：按 weights 比例把 total（元，两位小数）分配到各分项。

    参数
    ----
    weights: 可迭代的 Decimal/数值，第 i 项权重对应第 i 个分项。
    total:   待分配总额（Decimal，元）。

    返回
    ----
    list[Decimal]，每项两位小数，且 sum(result) == q2(total) 严格成立。
    当所有权重为 0 时，若 total 为 0 则全 0；若 total 非 0 则无法按比例分摊，
    返回全 0 并在调用方通过 reconciliation 暴露差异。

    同等余数时按索引（稳定）顺序分配，保证确定性、可复核。
    """
    total = q2(total)
    weights = [Decimal(str(w)) for w in weights]
    n = len(weights)
    if n == 0:
        return []
    total_cents = to_cents(total)
    sum_w = sum(weights)
    if sum_w <= 0:
        # 权重全为 0：无法按比例分摊，返回全 0（差异由调用方标记）
        return [Decimal("0.00") for _ in range(n)]

    # 每项应得整数分（向下取整）与小数部分
    floors = []
    remainders = []
    allocated = 0
    for w in weights:
        # num = total_cents * w，再除以 sum_w 得到该项应得整数分（向下取整）
        num = total_cents * w
        q = (num / sum_w).to_integral_value(rounding=ROUND_DOWN)
        f = int(q)
        r = num - Decimal(f) * sum_w  # 余数（用于排序，越大越优先）
        floors.append(f)
        remainders.append(r)
        allocated += f

    leftover = total_cents - allocated  # 需要再分配的整数分
    # 余数从大到小排序，余数相等时索引从小到大（稳定）
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    for k in range(leftover):
        floors[order[k]] += 1

    return [from_cents(f) for f in floors]


def sum_decimals(values) -> Decimal:
    """Decimal 求和并量化。"""
    s = Decimal("0")
    for v in values:
        if v is not None:
            s += Decimal(str(v))
    return q2(s)
