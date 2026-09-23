"""SQLite 轻量存储初始化（含建表/迁移）。"""
from __future__ import annotations

import os
import sqlite3

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sea_freight.db")


def resolve_db_path(db_path: str | None = None) -> str:
    # 允许通过环境变量覆盖数据库位置（便于 Docker 挂载持久卷）。
    return os.path.abspath(
        db_path or os.environ.get("SEA_FREIGHT_DB") or DEFAULT_DB_PATH
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS calc_sessions (
    session_id      TEXT PRIMARY KEY,
    cabinet_no      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    input_sea_freight REAL NOT NULL DEFAULT 0,
    input_rmb_duty  REAL NOT NULL DEFAULT 0,
    exchange_rate   REAL NOT NULL DEFAULT 0,
    note            TEXT,
    data            TEXT,            -- JSON 全量计算状态
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    actor       TEXT,
    action      TEXT,
    detail      TEXT,             -- JSON
    FOREIGN KEY (session_id) REFERENCES calc_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_cabinet ON calc_sessions(cabinet_no);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);
"""


def get_conn(db_path: str | None = None):
    path = resolve_db_path(db_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None):
    conn = get_conn(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
