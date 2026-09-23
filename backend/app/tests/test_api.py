import io
import zipfile
from fastapi.testclient import TestClient
from app.main import app
from app.tests.conftest import (build_packing_excel_008, build_uitnodiging_pdf_008,
                                build_packing_excel_009, build_uitnodiging_pdf_009,
                                build_release_pdf_009)


def _client(tmp_db):
    return TestClient(app)


def test_health(tmp_db):
    c = _client(tmp_db)
    assert c.get("/api/health").json()["status"] == "ok"


def test_full_flow(tmp_db):
    c = _client(tmp_db)
    r = c.post("/api/sessions", json={"cabinet_no": "008", "sea_freight": 54485.80,
                                     "rmb_duty": 7486.68, "exchange_rate": 8.2, "note": "t"})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    # 上传装箱单
    xlsx = build_packing_excel_008()
    r = c.post(f"/api/sessions/{sid}/packing", files={"file": ("p.xlsx", xlsx,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert r.json()["total_box_count"] == 610

    # 上传海关 PDF
    pdf = build_uitnodiging_pdf_008()
    r = c.post(f"/api/sessions/{sid}/customs", files=[("files", ("c.pdf", pdf, "application/pdf"))])
    assert r.status_code == 200
    assert r.json()["mrn"] == "26NL8DWEQ6QRD5SDR2"

    # 计算
    r = c.post(f"/api/sessions/{sid}/compute")
    assert r.status_code == 200
    body = r.json()
    sea_sum = sum(float(v) for v in body["sea_freight_alloc"].values())
    assert abs(sea_sum - 54485.80) < 0.01

    # 新规则：HS 不一致不再判为待确认；008 全部按名称+数量自动匹配，无 pending
    pending = [m for m in body["matches"] if m["status"] in ("pending", "unmatched")]
    assert pending == [], f"008 不应有待确认/无法匹配项: {pending}"

    # 无待确认项时可直接导出最终版
    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 200
    assert "008" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"  # xlsx zip 头


def test_full_flow_009_auto_split_and_unmatched_blocks_export(tmp_db):
    """009：镜子税项两个货件数量相同 -> 自动均摊，可直接导出最终版；
    装箱单里完全没有的商品（加装场景）-> 需人工指定归属，且最终导出被拦截。"""
    c = _client(tmp_db)
    r = c.post("/api/sessions", json={"cabinet_no": "009", "sea_freight": 56965.80,
                                     "rmb_duty": 12284.50, "exchange_rate": 8.2, "note": "t"})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    c.post(f"/api/sessions/{sid}/packing", files={"file": ("p.xlsx", build_packing_excel_009(),
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    c.post(f"/api/sessions/{sid}/customs", files=[("files", ("c.pdf", build_uitnodiging_pdf_009(), "application/pdf"))])

    r = c.post(f"/api/sessions/{sid}/compute")
    assert r.status_code == 200
    body = r.json()
    assert not [m for m in body["matches"] if m["status"] in ("pending", "unmatched")], \
        "009 镜子应已自动均摊，无待确认"
    # 可直接导出最终版
    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 200
    assert "009" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"  # xlsx zip 头

    # 加装场景：补录一笔装箱单里完全没有的税项 -> unmatched，拦截最终导出
    r = c.post(f"/api/sessions/{sid}/manual-article", json={
        "article_no": "99", "description": "extra goods", "hs_code": "9503000090",
        "declared_qty": 10, "duty_eur": 100.0, "vat_eur": 0.0})
    assert r.status_code == 200
    r = c.post(f"/api/sessions/{sid}/compute")
    pending = [m for m in r.json()["matches"] if m["status"] in ("pending", "unmatched")]
    assert pending and pending[0]["status"] == "unmatched"

    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 400

    # 指定归属到第一个货件后，可导出最终版
    confirms = {m["article_key"]: body["refs"][0]["ref_id"] for m in pending}
    r = c.post(f"/api/sessions/{sid}/confirm", json={"confirmations": confirms, "splits": {}})
    assert r.status_code == 200
    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 200


def test_analyze_one_shot(tmp_db):
    """一步式分析：只填柜号/海运费/关税总额（汇率留空），上传文件即出结果与自核结论。"""
    c = _client(tmp_db)
    xlsx = build_packing_excel_008()
    pdf = build_uitnodiging_pdf_008()
    r = c.post(
        "/api/analyze",
        data={"cabinet_no": "008", "sea_freight": "54485.80", "rmb_duty": "7486.68"},
        files={
            "packing": ("p.xlsx", xlsx,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "customs": ("c.pdf", pdf, "application/pdf"),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cabinet_no"] == "008"
    assert body["packing"] and body["customs"]  # 解析结果一并返回
    assert abs(sum(body["sea_freight_alloc"].values()) - 54485.80) < 0.01
    # 汇率留空 -> 自动推算（关税总额 ÷ 欧元关税总额）
    assert float(body["reconciliation"]["exchange_rate"]) > 0
    # 自核结论：008 无待确认，海运费与关税均对平
    v = body["verification"]
    assert v["sea_balanced"] is True
    assert v["duty_balanced"] is True
    assert v["pending_count"] == 0
    assert v["unresolved"] is False
    # 金额字段应为 number，便于前端直接 toFixed
    assert isinstance(next(iter(body["sea_freight_alloc"].values())), float)


def _minimal_pdf(text="Niets", ) -> bytes:
    """不含任何税项的极简 PDF：模拟扫描件/未适配版式 -> 解析出 0 条税项。"""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((40, 60), text, fontname="courier", fontsize=9)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _analyze(c, cabinet_no="008", customs=(), sea="54485.80", duty="7486.68"):
    files = [
        ("packing", ("p.xlsx", build_packing_excel_008(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]
    files += [("customs", (name, content, ctype)) for name, content, ctype in customs]
    return c.post("/api/analyze", data={"cabinet_no": cabinet_no, "sea_freight": sea,
                                        "rmb_duty": duty}, files=files)


def test_analyze_rejects_no_pdf_customs(tmp_db):
    """压缩里只有图片等非 PDF 文件 -> 明确报错，不再静默产出空表。"""
    c = _client(tmp_db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    r = _analyze(c, customs=[("c.zip", buf.getvalue(), "application/zip")])
    assert r.status_code == 400
    assert "没有 PDF" in r.json()["detail"]


def test_analyze_rejects_zero_articles(tmp_db):
    """PDF 解析出 0 条税项 -> 阻断（曾导致导出表关税/汇率整列为 0）。"""
    c = _client(tmp_db)
    r = _analyze(c, customs=[("c.pdf", _minimal_pdf(), "application/pdf")])
    assert r.status_code == 400
    assert "0 条税项" in r.json()["detail"]


def test_analyze_rejects_zero_duty_amount(tmp_db):
    """放行单有税项但无关税金额 -> 阻断并提示改传缴税通知。"""
    c = _client(tmp_db)
    r = _analyze(c, cabinet_no="009",
                 customs=[("release.pdf", build_release_pdf_009(), "application/pdf")])
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "0 条税项" in detail or "Douanerechten" in detail or "放行单" in detail


def test_analyze_reports_data_quality(tmp_db):
    """正常数据 -> 体检结论齐全且无缺失告警；关键列不得为 0。"""
    c = _client(tmp_db)
    r = _analyze(c, customs=[("c.pdf", build_uitnodiging_pdf_008(), "application/pdf")])
    assert r.status_code == 200
    dq = r.json()["verification"]["data_quality"]
    assert dq["ref_count"] == 4 and dq["article_count"] == 4
    assert dq["total_box"] == 610 and dq["total_volume"] > 0
    assert dq["eur_duty_total"] > 0 and dq["exchange_rate"] > 0
    assert dq["mrn"] == "26NL8DWEQ6QRD5SDR2"
    assert dq["warnings"] == []
    # 缴税通知本就不含 colli：只作提示、不列为缺失告警
    assert dq["customs_colli"] is None and dq["notes"]


def test_colli_not_invented_from_form_number(tmp_db):
    """'Totaal colli (6)' 的 (6) 是栏目编号，不得被当成件数（旧逻辑曾误取 3199）。"""
    from app.parsers import pdf_customs
    c = _client(tmp_db)
    r = _analyze(c, customs=[("c.pdf", build_uitnodiging_pdf_008(), "application/pdf")])
    assert r.status_code == 200
    assert r.json()["verification"]["data_quality"]["customs_colli"] is None
    assert pdf_customs.parse_customs_pdf_bytes(build_release_pdf_009())["total_colli"] is None


def test_export_pending_when_unresolved(tmp_db):
    c = _client(tmp_db)
    r = c.post("/api/sessions", json={"cabinet_no": "008b", "sea_freight": 54485.80,
                                     "rmb_duty": 7486.68, "exchange_rate": 8.2})
    sid = r.json()["session_id"]
    c.post(f"/api/sessions/{sid}/packing", files={"file": ("p.xlsx", build_packing_excel_008(),
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    c.post(f"/api/sessions/{sid}/customs", files=[("files", ("c.pdf", build_uitnodiging_pdf_008(), "application/pdf"))])
    c.post(f"/api/sessions/{sid}/compute")
    r = c.get(f"/api/sessions/{sid}/export?mode=pending")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"  # xlsx zip 头
