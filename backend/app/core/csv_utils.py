from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi.responses import Response

# 防止 Excel / LibreOffice CSV 公式注入攻击（OWASP CSV Injection）
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def render_csv_bytes(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> bytes:
    """生成带 UTF-8 BOM 的防公式注入 CSV 字节流（Excel 打开中文零乱码）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([sanitize_csv_cell(h) for h in headers])
    for row in rows:
        writer.writerow([sanitize_csv_cell(cell) for cell in row])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def build_csv_response(
    *,
    filename: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> Response:
    safe_name = "".join(c for c in filename if c.isalnum() or c in {"-", "_", "."}) or "export.csv"
    if not safe_name.endswith(".csv"):
        safe_name += ".csv"
    payload = render_csv_bytes(headers, rows)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "no-store",
        },
    )
