import io
from fastapi.testclient import TestClient
from app.main import app
from app.tests.conftest import (build_packing_excel_008, build_uitnodiging_pdf_008,
                                build_packing_excel_009, build_uitnodiging_pdf_009)


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


def test_full_flow_009_mirror_pending_blocks_export(tmp_db):
    """009：一笔镜子税项对应两个并列货件（真正歧义），应为待确认并拦截最终导出，
    人工确认归属后方可导出。"""
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
    pending = [m for m in body["matches"] if m["status"] == "pending"]
    assert pending, "009 镜子税项应为待确认（两个货件并列）"

    # 存在未解决异常时，最终导出被拦截
    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 400

    # 人工确认镜子归属后，可导出最终版
    confirms = {m["article_key"]: m["candidate_refs"][0] for m in pending}
    r = c.post(f"/api/sessions/{sid}/confirm", json={"confirmations": confirms, "splits": {}})
    assert r.status_code == 200

    r = c.get(f"/api/sessions/{sid}/export?mode=final")
    assert r.status_code == 200
    assert "009" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"  # xlsx zip 头


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
