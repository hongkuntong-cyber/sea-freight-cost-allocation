"""货箱编号解析与箱数逻辑校验。

装箱单中"货箱编号"可能是：
    - 单号："1" 表示 1 箱
    - 连续区间："1-60" 表示 60 箱；"64-99" 表示 36 箱
    - 多个区间/单号用逗号或分号分隔："1-60,61-110"

不得将"商品总数量"误认为箱数。需识别同一 Reference ID 下箱号重复、缺号、
范围异常；不同 Reference ID 的箱号可分别从 1 开始，不得误判为跨货件重复。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class BoxRange:
    start: int
    end: int
    count: int


@dataclass
class BoxParseResult:
    count: int = 0
    ranges: List[BoxRange] = field(default_factory=list)
    raw: str = ""
    error: str | None = None
    # 展开后的单箱编号（用于异常检测，区间较大时可不展开以省内存）
    numbers: List[int] = field(default_factory=list)


_RANGE_SPLIT_RE = re.compile(r"[;,]")


def parse_box_spec(raw) -> BoxParseResult:
    """解析货箱编号规格，返回箱数与区间列表。"""
    if raw is None:
        return BoxParseResult(count=0, raw="", error="货箱编号为空")
    raw_str = str(raw).strip()
    if raw_str == "":
        return BoxParseResult(count=0, raw=raw_str, error="货箱编号为空")

    result = BoxParseResult(raw=raw_str, ranges=[])
    tokens = [t.strip() for t in _RANGE_SPLIT_RE.split(raw_str) if t.strip()]
    total = 0
    numbers: List[int] = []
    for tok in tokens:
        if "-" in tok:
            parts = tok.split("-", 1)
            try:
                a = int(parts[0].strip())
                b = int(parts[1].strip())
            except ValueError:
                result.error = f"箱号区间无法解析: {tok}"
                return result
            if a <= 0 or b <= 0:
                result.error = f"箱号必须为正整数: {tok}"
                return result
            if b < a:
                result.error = f"箱号区间结束小于起始: {tok}"
                return result
            cnt = b - a + 1
            result.ranges.append(BoxRange(start=a, end=b, count=cnt))
            total += cnt
            numbers.extend(range(a, b + 1))
        else:
            try:
                a = int(tok)
            except ValueError:
                result.error = f"箱号无法解析: {tok}"
                return result
            if a <= 0:
                result.error = f"箱号必须为正整数: {tok}"
                return result
            result.ranges.append(BoxRange(start=a, end=a, count=1))
            total += 1
            numbers.append(a)
    result.count = total
    result.numbers = numbers
    return result


def detect_box_anomalies(ranges: List[BoxRange]) -> List[str]:
    """基于同一 Reference ID 下的全部箱型区间，检测箱号重复/缺号/范围异常。

    不同 Reference ID 各自独立从 1 开始，不跨货件比较。
    """
    issues: List[str] = []
    if not ranges:
        issues.append("缺少箱号区间信息")
        return issues
    numbers: List[int] = []
    for r in ranges:
        numbers.extend(range(r.start, r.end + 1))
    if not numbers:
        issues.append("箱数为 0")
        return issues
    sorted_n = sorted(numbers)
    # 重复检测
    seen = set()
    dup = set()
    for n in sorted_n:
        if n in seen:
            dup.add(n)
        seen.add(n)
    if dup:
        issues.append(f"箱号存在重复: {','.join(str(x) for x in sorted(dup)[:20])}"
                      + ("…" if len(dup) > 20 else ""))
    # 缺号检测（仅当最小从 1 开始时才有意义）
    if sorted_n[0] == 1:
        full = set(range(1, sorted_n[-1] + 1))
        missing = sorted(full - seen)
        if missing:
            issues.append(f"箱号存在缺号: {','.join(str(x) for x in missing[:20])}"
                          + ("…" if len(missing) > 20 else ""))
    return issues
