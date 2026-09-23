"""荷兰海关 PDF 解析（UITNODIGING / TOESTEMMING / Aangifte 等）。

关键点：
    - 先按文件内容分类，再提取数据，避免把同一笔税款在多个 PDF 中重复累计。
    - 欧洲数字格式（1.295,96 -> 1295.96）与遮盖符号 '*' 处理。
    - Middel: Btw = 增值税（单独记录，不计入关税分摊）；
      Middel 含 Douane = 关税（分摊依据）。
    - 金额采用"Krediet/Verschuldigd"成对出现的顺序：第 i 个税项的应缴金额
      位于金额区的第 2*i+1 个数值（第 2*i 个为担保/抵免额）。
    - 扫描版/文本缺失：reliable=False，交由人工补录。
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Dict, List, Optional

import fitz  # PyMuPDF

from ..core.eu_number import parse_eu_number, has_mask

MRN_RE = re.compile(r"\b(\d{2}[A-Z]{2}[A-Z0-9]{14})\b")
MRN_COLON_RE = re.compile(r"MRN:\s*([A-Z0-9]{16,18})", re.I)
CONTAINER_RE = re.compile(r"Containers?\s*[:\s]*([A-Z]{4}[0-9]{6,10})")
ARTIKEL_RE = re.compile(r"Artikel:\s*(\d+)", re.I)
HS_RE = re.compile(r"Goederencode:\s*([0-9]+)")
DESC_QTY_RE = re.compile(r"([A-Za-z][A-Za-z \-\(\)/]*?)\s+([\d.,]+)\s*PCS", re.I)
BASE_RE = re.compile(r"Belastbare maatstaf:\s*([\d.,*]+)")
RATE_RE = re.compile(r"Tarief:\s*([\d.,*]+)\s*%?")
MIDDEL_RE = re.compile(r"Middel:\s*(.+)", re.I)
BEDRAG_RE = re.compile(r"Bedrag:\s*([\d.,*]+)")
TOTAAL_RE = re.compile(r"Totaal uitnodiging", re.I)


def _classify(text: str) -> str:
    t = text.upper()
    if "UITNODIGING TOT BETALING" in t:
        return "payment_invitation"
    if "TOESTEMMING TOT WEGVOERING" in t:
        return "release"
    if "AANGIFTE" in t or "CC429A" in t or "AI/" in t or "AI-" in t:
        return "declaration"
    if "DOUANE" in t:
        return "customs_other"
    return "unknown"


def _extract_mrn(text: str) -> Optional[str]:
    m = MRN_COLON_RE.search(text)
    if m:
        return m.group(1)
    ms = MRN_RE.findall(text)
    # 取最长的（18 位 MRN）
    ms = [x for x in ms if len(x) >= 16]
    if ms:
        return max(ms, key=len)
    return None


def _split_items(text: str):
    positions = [(m.start(), m.group(1)) for m in ARTIKEL_RE.finditer(text)]
    blocks = []
    for i, (pos, num) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        blocks.append((num, text[pos:end]))
    return blocks


def _parse_amount_region(block: str) -> List[Decimal]:
    # 仅取最后一个 Tarief 之后的金额区
    last_tarief = block.rfind("Tarief:")
    region = block[last_tarief:] if last_tarief >= 0 else block
    tokens = []
    for line in region.splitlines():
        s = line.strip()
        if not s or "€" in s:
            continue
        if re.search(r"[A-Za-z]", s):  # 含字母则是标签行，跳过
            continue
        cleaned = re.sub(r"[^0-9.,*]", "", s)
        if cleaned and re.search(r"\d", cleaned):
            val = parse_eu_number(cleaned)
            if val is not None:
                tokens.append(val)
    return tokens


def _parse_article(num: str, block: str, source_file: str) -> dict:
    desc_m = DESC_QTY_RE.search(block)
    description = desc_m.group(1).strip() if desc_m else ""
    declared_qty = parse_eu_number(desc_m.group(2)) if desc_m else None
    hs_m = HS_RE.search(block)
    hs_code = hs_m.group(1) if hs_m else ""

    # Middel 列表（顺序）
    middels = []
    for mm in MIDDEL_RE.finditer(block):
        # 取该 Middel 到下个 Middel 之间的 base/rate
        start = mm.end()
        nxt = MIDDEL_RE.search(block, start)
        seg = block[start:nxt.start() if nxt else len(block)]
        base_m = BASE_RE.search(seg)
        rate_m = RATE_RE.search(seg)
        middels.append({
            "name": mm.group(1).strip(),
            "base": parse_eu_number(base_m.group(1)) if base_m else None,
            "rate": parse_eu_number(rate_m.group(1)) if rate_m else None,
        })

    tokens = _parse_amount_region(block)
    duty_eur = Decimal("0")
    vat_eur = Decimal("0")
    duty_base = vat_base = None
    duty_rate = vat_rate = None
    masked = False
    reliable = True

    for i, md in enumerate(middels):
        due_idx = 2 * i + 1
        if due_idx >= len(tokens):
            reliable = False
            continue
        due = tokens[due_idx]
        name_l = md["name"].lower()
        if "btw" in name_l:
            vat_eur += due
            vat_base = md["base"]
            vat_rate = md["rate"]
        elif "douane" in name_l:
            duty_eur += due
            duty_base = md["base"]
            duty_rate = md["rate"]
        # 其他税种（如 Heffing）暂归为其他，不计入关税分摊

    # 遮盖检测
    if re.search(r"\*", block):
        masked = True

    return {
        "article_no": num,
        "description": description,
        "hs_code": hs_code,
        "declared_qty": declared_qty,
        "duty_eur": duty_eur,
        "vat_eur": vat_eur,
        "duty_base": duty_base,
        "duty_rate": duty_rate,
        "vat_base": vat_base,
        "vat_rate": vat_rate,
        "source_file": source_file,
        "masked": masked,
        "reliable": reliable,
        "notes": [],
    }


def parse_customs_pdf_bytes(data: bytes, filename: str = "") -> dict:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return {
            "file_type": "unknown", "mrn": None, "declaration_no": None,
            "container": None, "total_colli": None, "articles": [],
            "total_invitation_amount": None, "text_len": 0, "reliable": False,
            "warnings": [f"PDF 解析失败：{e}"], "filename": filename,
        }
    text = "\n".join(p.get_text() for p in doc)
    doc.close()

    file_type = _classify(text)
    mrn = _extract_mrn(text)
    container_m = CONTAINER_RE.search(text)
    container = container_m.group(1) if container_m else None

    declaration_no = None
    m = re.search(r"Aangiftenummer:\s*([0-9]+)", text)
    if m:
        declaration_no = m.group(1)
    if not declaration_no:
        m = re.search(r"AI[-/]?\d{4}[-/]?(\d+)", text)
        if m:
            declaration_no = m.group(1)

    total_colli = None
    if file_type == "release":
        # 荷兰海关表单里 "Totaal colli (6)" 的 (6) 是栏目编号而非件数，
        # 只有出现明确的数值形式（"Totaal colli: 320" / "Totaal colli 320"）才采信；
        # 否则宁可留空并在界面提示缺失，也不臆测一个数字（曾误取到 3199）。
        mc = re.search(
            r"Totaal[ \t]+(?:aantal[ \t]+)?colli[ \t]*(?:\([ \t]*\d{1,2}[ \t]*\))?[ \t]*:?[ \t]*(\d{1,6})\b",
            text, re.I)
        if mc:
            v = int(mc.group(1))
            if 0 < v < 100000:
                total_colli = v

    articles = []
    if file_type in ("payment_invitation", "release", "declaration"):
        for num, block in _split_items(text):
            art = _parse_article(num, block, filename)
            articles.append(art)

    total_invitation_amount = None
    if file_type == "payment_invitation":
        # 在 "Totaal uitnodiging" 之后找 Bedrag
        tm = TOTAAL_RE.search(text)
        if tm:
            rem = text[tm.end():]
            bm = BEDRAG_RE.search(rem)
            if bm:
                total_invitation_amount = parse_eu_number(bm.group(1))
        # 交叉校验：关税合计应等于 Totaal
        duty_sum = sum((a["duty_eur"] for a in articles), Decimal("0"))
        if total_invitation_amount is not None and abs(duty_sum - total_invitation_amount) > Decimal("0.02"):
            for a in articles:
                a["reliable"] = False
                a["notes"].append("关税合计与缴税通知总额不一致，请人工核对")

    reliable = text.strip() != "" and len(text) > 50 and file_type != "unknown"
    warnings = []
    if len(text.strip()) <= 50:
        warnings.append("PDF 几乎无可读文本，可能为扫描件，请人工补录税项")
        reliable = False

    return {
        "file_type": file_type,
        "mrn": mrn,
        "declaration_no": declaration_no,
        "container": container,
        "total_colli": total_colli,
        "articles": articles,
        "total_invitation_amount": total_invitation_amount,
        "text_len": len(text),
        "reliable": reliable,
        "warnings": warnings,
        "filename": filename,
    }


def merge_customs_parses(parses: List[dict]) -> dict:
    """合并多份海关文件解析结果，按 (MRN, article_no) 去重。

    缴税通知（含金额）优先；放行单/申报单（无金额）仅在无对应缴税通知时补充，
    用于交叉核对，绝不重复累计税款。
    """
    merged_articles: Dict[tuple, dict] = {}
    mrn = None
    declaration_no = None
    container = None
    total_colli = None
    file_summaries = []
    for p in parses:
        file_summaries.append({
            "filename": p.get("filename", ""),
            "file_type": p["file_type"],
            "mrn": p.get("mrn"),
            "articles": len(p.get("articles", [])),
            "reliable": p.get("reliable", False),
            "warnings": p.get("warnings", []),
        })
        if not mrn and p.get("mrn"):
            mrn = p["mrn"]
        if not declaration_no and p.get("declaration_no"):
            declaration_no = p["declaration_no"]
        if not container and p.get("container"):
            container = p["container"]
        if total_colli is None and p.get("total_colli") is not None:
            total_colli = p["total_colli"]
        for a in p.get("articles", []):
            key = (p.get("mrn") or mrn or "NA", a["article_no"])
            existing = merged_articles.get(key)
            if existing is None:
                merged_articles[key] = a
            else:
                # 已有金额则保留；否则用带金额的覆盖
                if (existing["duty_eur"] or 0) == 0 and (a["duty_eur"] or 0) > 0:
                    merged_articles[key] = a
                elif (existing["duty_eur"] or 0) == 0 and (a["duty_eur"] or 0) == 0:
                    # 两者都无金额，合并描述
                    if a["description"] and not existing["description"]:
                        existing["description"] = a["description"]

    return {
        "mrn": mrn,
        "declaration_no": declaration_no,
        "container": container,
        "total_colli": total_colli,
        "articles": list(merged_articles.values()),
        "file_summaries": file_summaries,
    }
