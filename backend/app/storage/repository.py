"""SQLite 仓库（参数化查询，防止 SQL 注入；会话以 UUID 为键，防止越权访问）。"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Optional

from .db import get_conn


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def create_session(cabinet_no: str, sea_freight, rmb_duty, exchange_rate, note: str,
                   data: dict, db_path: Optional[str] = None) -> str:
    session_id = uuid.uuid4().hex
    conn = get_conn(db_path)
    try:
        conn.execute(
            """INSERT INTO calc_sessions
               (session_id, cabinet_no, status, input_sea_freight, input_rmb_duty,
                exchange_rate, note, data, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (session_id, cabinet_no, "draft", float(sea_freight), float(rmb_duty),
             float(exchange_rate), note, json.dumps(data, ensure_ascii=False), _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def update_session(session_id: str, data: dict, status: Optional[str] = None,
                   db_path: Optional[str] = None):
    conn = get_conn(db_path)
    try:
        if status:
            conn.execute(
                "UPDATE calc_sessions SET data=?, status=?, updated_at=? WHERE session_id=?",
                (json.dumps(data, ensure_ascii=False), status, _now(), session_id),
            )
        else:
            conn.execute(
                "UPDATE calc_sessions SET data=?, updated_at=? WHERE session_id=?",
                (json.dumps(data, ensure_ascii=False), _now(), session_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_session(session_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT session_id, cabinet_no, status, input_sea_freight, input_rmb_duty, "
            "exchange_rate, note, data, created_at, updated_at FROM calc_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data"]) if d["data"] else {}
        return d
    finally:
        conn.close()


def list_sessions(db_path: Optional[str] = None) -> list:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT session_id, cabinet_no, status, note, created_at FROM calc_sessions "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def append_audit(session_id: str, actor: str, action: str, detail: dict,
                db_path: Optional[str] = None):
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO audit_log (session_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
            (session_id, _now(), actor, action, json.dumps(detail, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def get_audit(session_id: str, db_path: Optional[str] = None) -> list:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT id, ts, actor, action, detail FROM audit_log WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
