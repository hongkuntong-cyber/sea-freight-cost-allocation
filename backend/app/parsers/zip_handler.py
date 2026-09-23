"""ZIP 安全解压（防路径穿越 / ZIP SLIP）。

仅解压常规文件，拒绝绝对路径与 '..' 穿越；按文件类型（PDF 等）分类；
限制文件数量与单个大小，防止恶意压缩包。不依赖任何外部在线服务。
"""
from __future__ import annotations

import io
import os
import zipfile

MAX_FILES = 200
MAX_FILE_BYTES = 50 * 1024 * 1024  # 单文件 50MB


def _safe_name(name: str) -> str | None:
    # 拒绝绝对路径与路径穿越；先按段落检查，避免 normpath 折叠 ".." 后误判安全
    if name.startswith("/") or name.startswith("\\") or ":\\" in name:
        return None
    parts = name.replace("\\", "/").split("/")
    if any(p in ("..", ".", "") for p in parts[:-1]):
        return None
    base = parts[-1]
    if not base or base in ("..", "."):
        return None
    return base


def extract_zip_bytes(data: bytes) -> list:
    """解压 ZIP，返回 [(safe_name, bytes, is_pdf), ...]。"""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        if len(entries) > MAX_FILES:
            raise ValueError(f"ZIP 内文件过多（>{MAX_FILES}），已拒绝")
        for info in entries:
            name = _safe_name(info.filename)
            if name is None:
                continue
            if info.file_size > MAX_FILE_BYTES:
                continue
            content = z.read(info)
            if len(content) > MAX_FILE_BYTES:
                continue
            is_pdf = content[:5] == b"%PDF-"
            out.append((name, content, is_pdf))
    return out
