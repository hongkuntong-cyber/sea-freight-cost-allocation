"""测试夹具构造器（脱敏 / 合成），不依赖也不包含任何真实业务文件。

- 008 大柜：结构复刻真实装箱单（箱号区间/尺寸/HS/数量），采购价与地址脱敏；
  合成荷兰缴税通知 PDF，金额带遮盖符号，验证解析与回归（海运费 54485.80 / 关税 7486.68）。
- 009 大柜：构造"镜子税项归属待确认"场景，验证该笔关税不被强行分配。
"""
from __future__ import annotations

import io
import os
import tempfile

import fitz
import openpyxl
import pytest


@pytest.fixture
def tmp_db(monkeypatch):
    import app.storage.db as dbmod
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    monkeypatch.setattr(dbmod, "DEFAULT_DB_PATH", path)
    dbmod.init_db()
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------- 装箱单 Excel（008 结构脱敏） ----------------
PACKING_HEADER = ['货箱编号*', 'Reference ID', '货箱重量(KG)', '货箱长度(CM)', '货箱宽度(CM)',
                  '货箱高度(CM)', '英文品名*', '中文品名*', '（单个产品）申报单价*', '采购单价*',
                  '单箱数量*', '总数量*', 'SKU', '产品海关编码(清关)*']


def _packing_row(box, ref, w, l, wi, h, en, cn, single, total, sku, hs):
    return [box, ref, w, l, wi, h, en, cn, '', '', single, total, sku, hs]


PACKING_008_ROWS = [
    _packing_row('1-60', 'RVG15056-260508-0003', 21, 80, 58, 65, 'bathtub', '浴盆支架灰色', 3, 180, 'YPZJ0001', '3922100000'),
    _packing_row('61-110', 'RVG15056-260508-0003', 21, 80, 58, 65, 'bathtub', '浴盆支架粉色', 3, 150, 'YPZJ0002', '3922100000'),
    _packing_row('1-200', 'RVG15056-260509-0003', 4.5, 61, 26, 36, 'Baby enclosure', '宝宝围栏', 1, 200, 'XWL00010', '3926909090'),
    _packing_row('201-400', 'RVG15056-260509-0003', 4.5, 85, 20, 40, 'Baby playpen', '宝宝围栏', 1, 200, 'XWL0009', '3926909090'),
    _packing_row('1-55', 'RVG15056-260518-0002', 17.3, 50, 33, 28, 'glass vase sets', '玻璃瓶', 8, 440, 'BLP0005', '7013990000'),
    _packing_row('56-83', 'RVG15056-260518-0002', 15, 55, 32, 45, 'vase', '花瓶', 8, 224, 'BLP0001', '7013990000'),
    _packing_row('1-7', 'RVG15056-260513-0001', 20, 55, 54.5, 46.5, 'Baby mattress', '儿童床垫', 10, 70, 'YEC0003', '6302329000'),
    _packing_row('8-12', 'RVG15056-260513-0001', 20, 55, 54.5, 46.5, 'Baby mattress', '儿童床垫', 10, 50, 'YEC0004', '6302329000'),
    _packing_row('13-17', 'RVG15056-260513-0001', 18, 80, 55, 52, 'cuddle nest', '儿童床垫', 8, 40, 'YEC0008', '6302329000'),
]


def build_packing_excel_008() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "整柜发票"
    ws.append(PACKING_HEADER)
    for r in PACKING_008_ROWS:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------- 合成荷兰缴税通知 PDF ----------------
def _lines_for_article(n, desc, qty, hs, duty_rate, duty_base, vat_rate, vat_base,
                       duty_str, vat_str):
    return [
        f"Aangiftenummer: 452975",
        f"Artikel: {n}",
        f"{desc} {qty} PCS",
        f"Goederencode: {hs}",
        "Middel: Douanerechten op industrieproducten",
        f"Belastbare maatstaf: {duty_base}",
        f"Tarief: {duty_rate}%",
        "Middel: Btw",
        f"Belastbare maatstaf: {vat_base}",
        f"Tarief: {vat_rate}%",
        "Krediet/zekerheid",
        "Verschuldigd",
        duty_str,
        "Douanerechten op industrieproducten",
        duty_str,
        "Krediet/zekerheid",
        "Verschuldigd",
        vat_str,
        "Btw",
        vat_str,
    ]


def build_uitnodiging_pdf_008() -> bytes:
    lines = [
        "DAGTEKENING: 31-7-2026",
        "UITNODIGING TOT BETALING",
        "MRN: 26NL8DWEQ6QRD5SDR2",
        "Aangiftenummer: 452975",
        "Totaal colli (6)",
    ]
    lines += _lines_for_article(1, "bathtub", 330, "3922100000", "6,50", "5.445,00",
                                "21,00", "5.798,93", "**.***.353,93", "**.**1.217,77")
    lines += _lines_for_article(2, "Baby enclosure", 400, "9403208080", "0,00", "5.600,00",
                                "21,00", "5.600,00", "**.***.**0,00", "**.**1.176,00")
    lines += _lines_for_article(3, "vase", 664, "7013990090", "11,00", "2.988,00",
                                "21,00", "3.316,68", "**.***.328,68", "**.***.696,50")
    lines += _lines_for_article(4, "Baby mattress", 160, "6302329000", "12,00", "1.920,00",
                                "21,00", "2.150,40", "**.***.230,40", "**.***.451,58")
    lines += ["Totaal uitnodiging(en)", "Bedrag: 913,01", "EINDE"]
    return _render_pdf(lines)


def build_uitnodiging_pdf_009() -> bytes:
    """009 大柜：含一笔"镜子 12 PCS"税项（对应两个镜子货件，待确认）与一笔灯 50 PCS。"""
    lines = [
        "DAGTEKENING: 15-8-2026",
        "UITNODIGING TOT BETALING",
        "MRN: 26NL9ABCDEFGHIJKLM",
        "Aangiftenummer: 460001",
    ]
    lines += _lines_for_article(1, "mirror", 12, "7009920000", "5,00", "1.200,00",
                                "21,00", "1.452,00", "**.***.400,00", "**.***.945,42")
    lines += _lines_for_article(2, "lamp", 50, "9405200000", "3,00", "2.300,00",
                                "21,00", "2.793,00", "**.***.1.098,11", "**.***.1.339,62")
    lines += ["Totaal uitnodiging(en)", "Bedrag: 1.498,11", "EINDE"]
    return _render_pdf(lines)


def build_release_pdf_009() -> bytes:
    """009 放行单（含柜号与货件描述，用于交叉核对；无金额）。"""
    lines = [
        "TOESTEMMING TOT WEGVOERING",
        "MRN: 26NL9ABCDEFGHIJKLM",
        "Containers",
        "COSU7771234567",
        "Artikel: 1",
        "mirror 12 PCS",
        "Goederencode: 7009920000",
        "Artikel: 2",
        "lamp 50 PCS",
        "Goederencode: 9405200000",
        "EINDE",
    ]
    return _render_pdf(lines)


def _render_pdf(lines) -> bytes:
    doc = fitz.open()
    # 页面高度需容纳全部文本行（A4 高度不足以放下 008 的 4 个税项），
    # 并改用等宽字体，避免遮盖符号 '*' 与逗号在抽取时被错断。
    height = max(842, len(lines) * 14 + 80)
    page = doc.new_page(width=600, height=height)
    y = 40
    for ln in lines:
        page.insert_text((40, y), ln, fontname="courier", fontsize=9)
        y += 12
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------- 009 装箱单 Excel ----------------
def build_packing_excel_009() -> bytes:
    rows = [
        _packing_row('1-12', 'RVG15056-260909-0001', 10, 50, 40, 30, 'mirror', '镜子A', 1, 12, 'MIR0001', '7009920000'),
        _packing_row('1-12', 'RVG15056-260909-0002', 10, 50, 40, 30, 'mirror', '镜子B', 1, 12, 'MIR0002', '7009920000'),
        _packing_row('1-50', 'RVG15056-260909-0003', 8, 60, 40, 35, 'lamp', '灯', 1, 50, 'LMP0001', '9405200000'),
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "整柜发票"
    ws.append(PACKING_HEADER)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
