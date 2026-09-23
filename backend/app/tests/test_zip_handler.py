import io
import zipfile
from app.parsers.zip_handler import extract_zip_bytes


def _make_zip(names_and_data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in names_and_data:
            z.writestr(name, data)
    return buf.getvalue()


def test_safe_extraction_no_traversal():
    pdf = b"%PDF-1.4 fake pdf content"
    z = _make_zip([
        ("good.pdf", pdf),
        ("../evil.pdf", b"malicious"),
        ("folder/../escape.pdf", b"x"),
    ])
    out = extract_zip_bytes(z)
    names = [n for n, _, _ in out]
    assert "good.pdf" in names
    assert "evil.pdf" not in names
    assert "escape.pdf" not in names
    # PDF 被识别
    assert any(is_pdf for _, _, is_pdf in out)


def test_multiple_pdfs_in_zip():
    p1 = b"%PDF-1.4 a"
    p2 = b"%PDF-1.4 b"
    z = _make_zip([("a.pdf", p1), ("b.pdf", p2)])
    out = extract_zip_bytes(z)
    pdfs = [n for n, _, is_pdf in out if is_pdf]
    assert sorted(pdfs) == ["a.pdf", "b.pdf"]


def test_zip_size_limit_skips_oversized():
    big = b"%PDF-1.4 " + b"x" * (60 * 1024 * 1024)
    z = _make_zip([("big.pdf", big)])
    out = extract_zip_bytes(z)
    # 超大文件被跳过
    assert all(c < 50 * 1024 * 1024 for _, c, _ in out)
