from app.core.box_parser import parse_box_spec, detect_box_anomalies, BoxRange


def test_single():
    r = parse_box_spec("1")
    assert r.count == 1
    assert r.ranges == [BoxRange(1, 1, 1)]


def test_range():
    r = parse_box_spec("1-60")
    assert r.count == 60
    assert r.ranges[0].start == 1 and r.ranges[0].end == 60


def test_multi_range():
    r = parse_box_spec("64-99")
    assert r.count == 36


def test_combined():
    r = parse_box_spec("1-63,64-99")
    assert r.count == 63 + 36


def test_total_610():
    r = parse_box_spec("1-60")
    r2 = parse_box_spec("61-110")
    assert r.count + r2.count == 110


def test_duplicate_detection():
    issues = detect_box_anomalies([BoxRange(1, 5, 5), BoxRange(3, 7, 5)])
    assert any("重复" in i for i in issues)


def test_missing_detection():
    issues = detect_box_anomalies([BoxRange(1, 3, 3), BoxRange(5, 7, 3)])
    assert any("缺号" in i for i in issues)


def test_invalid_range():
    r = parse_box_spec("10-5")
    assert r.error is not None
