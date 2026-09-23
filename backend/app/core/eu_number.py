"""欧洲数字格式解析。

荷兰海关文档使用欧式数字格式：
    - 小数点用逗号 "," 表示：1.295,96 -> 1295.96
    - 千位分隔符用点 "." 表示
    - 金额可能被遮盖，遮盖位用 "*" 占位（如 **.***.353,93 -> 353.93）
    - 可能为负数、零值

核心规则：逗号为小数分隔符；仅当存在逗号时，点被视为千位分隔符。
若字符串仅含点（无逗号），按欧式惯例视为千位分隔符。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_DIGIT_SEP_RE = re.compile(r"[^0-9.,]")
_MASK_RE = re.compile(r"\*+")


def parse_eu_number(raw) -> Decimal | None:
    """解析欧式数字，返回 Decimal；无法解析返回 None。

    会保留遮盖符号 '*' 的识别（通过 has_mask 由调用方判断），本函数只做数值解析。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None

    s = str(raw).strip()
    if s == "" or s in ("-", "−", "*", "–"):
        return None

    negative = s.startswith("-") or "−" in s or "–" in s
    # 去掉遮盖符号与所有非数字/分隔符字符
    s2 = _MASK_RE.sub("", s)
    s2 = _DIGIT_SEP_RE.sub("", s2)
    if s2 == "":
        return None
    # 去掉遮盖导致的首尾多余点
    s2 = s2.strip(".")

    try:
        if "," in s2:
            # 欧式：最后一个逗号是小数点，其余点为千位分隔符
            int_part, dec_part = s2.rsplit(",", 1)
            int_part = int_part.replace(".", "")
            num_str = int_part + "." + dec_part
        elif "." in s2:
            # 仅含点：欧式千位分隔符（海关文档小数必带逗号）
            num_str = s2.replace(".", "")
        else:
            num_str = s2
        value = Decimal(num_str)
    except (InvalidOperation, ValueError):
        return None

    if negative:
        value = -value
    return value


def has_mask(raw) -> bool:
    """判断原始字符串是否含遮盖符号（提示需人工核对）。"""
    if raw is None:
        return False
    return bool(_MASK_RE.search(str(raw)))
