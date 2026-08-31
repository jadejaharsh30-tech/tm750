"""Excel export.

Runs exactly the same query `/screen` runs, then writes it to a real .xlsx
instead of JSON. Sharing the compiler with `data.py` is the whole point: if
the grid shows 43 rows, the download has the same 43 rows, because the WHERE
clause was built by the same code rather than a second implementation that
drifts.

Numbers are written as numbers, not as pre-formatted strings, so the file is
still sortable and computable in Excel. Presentation is carried by Excel
number formats taken from the catalog, which is also where the on-screen
formatting comes from -- so a rupee column reads the same in both places.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import Field

from .. import db
from ..deps import as_of
from ..models import (DEFAULT_COLUMNS, ScreenRequest, build_order,
                      build_select, build_where)

router = APIRouter(tags=["export"], dependencies=[Depends(as_of)])

XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")

CRORE = 1e7

# "#,##,##0" is Excel's Indian digit grouping -- it produces 4,51,712 rather
# than the international 451,712, matching how the app renders on screen.
INDIAN_INT = "#,##,##0"
INDIAN_2DP = "#,##,##0.00"
RUPEE_2DP = '"\u20b9"#,##,##0.00'
# The stored value already carries the percent (12.5 means 12.5%), so the
# literal quoted sign is correct here. Excel's own "0.0%" would multiply by
# 100 and turn 12.5% into 1250%.
PCT_1DP = '0.0"%"'

HEAD_FILL = PatternFill("solid", fgColor="1F2933")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
THIN = Side(style="thin", color="D8DEE4")


class ExportRequest(ScreenRequest):
    """A screen request, plus the few things only a file needs."""

    filename: str = Field("tm750-export", max_length=80)
    sheet_title: str = Field("Data", max_length=28)
    context: str | None = Field(None, max_length=200)


def _safe_filename(stem: str) -> str:
    """Strip anything a filesystem or a Content-Disposition header would
    argue with. A blank result falls back rather than producing '.xlsx'."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    return cleaned or "tm750-export"


def _number_format(spec: dict) -> str | None:
    """Excel number format for a column, from its catalog spec."""
    unit, fmt = spec.get("unit"), spec.get("fmt")
    if unit in ("text", "date", "bool"):
        return None
    if fmt == "cr":
        return INDIAN_INT
    if fmt == "0.1f%":
        return PCT_1DP
    if fmt == "0,0":
        return INDIAN_INT
    if fmt == "0.2f":
        return RUPEE_2DP if unit == "inr" else INDIAN_2DP
    return INDIAN_2DP


def _header(spec: dict) -> str:
    """Column heading. Rupee columns are rescaled to crore on the way out,
    so the heading has to say so or the numbers are silently wrong."""
    label = spec.get("label") or spec.get("name")
    if spec.get("fmt") == "cr":
        return f"{label} (\u20b9 Cr)"
    return label


def _cell_value(raw, spec: dict):
    """Convert one stored value into what belongs in the cell."""
    if raw is None or raw == "":
        return None
    unit, fmt = spec.get("unit"), spec.get("fmt")
    if unit == "bool" or isinstance(raw, bool):
        return "Yes" if raw else "No"
    if unit == "text":
        return str(raw)
    if unit == "date":
        return str(raw)[:10]
    if fmt == "cr":
        try:
            return round(float(raw) / CRORE, 2)
        except (TypeError, ValueError):
            return raw
    if isinstance(raw, (int, float)):
        return raw
    # Numeric-looking strings still sort as text in Excel, so coerce.
    try:
        return float(raw)
    except (TypeError, ValueError):
        return str(raw)


def _column_width(spec: dict) -> int:
    name = spec.get("name")
    if name == "name":
        return 34
    if name == "symbol":
        return 14
    if spec.get("unit") == "text":
        return 22
    header_len = len(_header(spec))
    return max(12, min(header_len + 3, 30))


def _describe_filter(f, catalog: dict) -> str:
    """Filters in words, for the About sheet. A file that leaves the lab
    should be able to explain what it is a subset of."""
    label = catalog.get(f.field, {}).get("label", f.field)
    words = {
        "eq": "is", "ne": "is not", "gt": "greater than",
        "gte": "at least", "lt": "less than", "lte": "at most",
        "between": "between", "in": "is one of", "not_in": "is not one of",
        "contains": "contains", "is_null": "is blank",
        "not_null": "has a value",
    }
    op = words.get(f.op, f.op)
    if f.op in ("is_null", "not_null"):
        return f"{label} {op}"
    if f.op == "between":
        return f"{label} {op} {f.value[0]} and {f.value[1]}"
    if f.op in ("in", "not_in"):
        return f"{label} {op}: {', '.join(str(v) for v in f.value)}"
    return f"{label} {op} {f.value}"


def build_workbook(rows: list[dict], specs: list[dict], *,
                   sheet_title: str, snapshot: str | None,
                   filter_lines: list[str], context: str | None,
                   total: int | None) -> bytes:
    """Assemble the workbook. Kept free of FastAPI and DuckDB so it can be
    exercised directly with hand-made rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or "Data")[:31]

    ws.append([_header(s) for s in specs])
    for c in range(1, len(specs) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30

    for r in rows:
        masked = set(r.get("_masked_fields") or [])
        ws.append([
            "n/a" if s["name"] in masked else _cell_value(r.get(s["name"]), s)
            for s in specs
        ])

    for i, spec in enumerate(specs, start=1):
        letter = get_column_letter(i)
        ws.column_dimensions[letter].width = _column_width(spec)
        nf = _number_format(spec)
        if not nf:
            continue
        for row_i in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_i, column=i)
            # A masked cell holds the string "n/a"; applying a number format
            # to it is harmless but the border pass below still needs to run.
            if isinstance(cell.value, (int, float)):
                cell.number_format = nf

    for row_i in range(1, ws.max_row + 1):
        for col_i in range(1, len(specs) + 1):
            ws.cell(row=row_i, column=col_i).border = Border(
                bottom=THIN, right=THIN)

    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = (
            f"A1:{get_column_letter(len(specs))}{ws.max_row}")

    about = wb.create_sheet("About")
    about.column_dimensions["A"].width = 22
    about.column_dimensions["B"].width = 80
    lines = [
        ("Source", "tm750 \u2014 Nifty Total Market 750"),
        ("Snapshot", snapshot or "latest"),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Rows in file", len(rows)),
    ]
    if total is not None and total != len(rows):
        lines.append(("Rows matching", total))
    if context:
        lines.append(("View", context))
    if filter_lines:
        for i, line in enumerate(filter_lines):
            lines.append(("Filters" if i == 0 else "", line))
    else:
        lines.append(("Filters", "None \u2014 full universe"))
    lines.append(("Columns", ", ".join(s["name"] for s in specs)))

    for key, val in lines:
        about.append([key, val])
    for row_i in range(1, about.max_row + 1):
        about.cell(row=row_i, column=1).font = Font(bold=True, size=10)
        about.cell(row=row_i, column=2).alignment = Alignment(wrap_text=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/export/xlsx")
def export_xlsx(req: ExportRequest, snapshot: str | None = Depends(as_of)):
    """The screen result as a downloadable Excel workbook."""
    where, params = build_where(req.filters)
    select = build_select(req.columns)
    order = build_order(req.sort)

    sql = (f"SELECT {select} FROM companies {where} {order} "
           f"LIMIT {req.limit} OFFSET {req.offset}")
    rows = db.query(sql, params)

    total = db.query_one(
        f"SELECT count(*) AS n FROM companies {where}", params)["n"]

    if req.mask_finance:
        rows = db.apply_finance_mask(rows)

    idx = db.catalog_index()
    # build_select() appends "sector" for the finance mask; the file should
    # still show exactly the columns that were asked for, in that order.
    wanted = req.columns or DEFAULT_COLUMNS
    specs = [dict(idx.get(c, {}), name=c) for c in wanted]
    for s in specs:
        s.setdefault("label", s["name"])

    filter_lines = [_describe_filter(f, idx) for f in req.filters]

    data = build_workbook(
        rows, specs,
        sheet_title=req.sheet_title,
        snapshot=snapshot or (db.snapshots()[-1] if db.snapshots() else None),
        filter_lines=filter_lines,
        context=req.context,
        total=total,
    )

    stem = _safe_filename(req.filename)
    date_part = snapshot or (db.snapshots()[-1] if db.snapshots() else "")
    name = f"{stem}-{date_part}.xlsx" if date_part else f"{stem}.xlsx"

    return StreamingResponse(
        io.BytesIO(data),
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            # The browser cannot read Content-Disposition on a cross-origin
            # response unless it is explicitly exposed, and in dev the Vite
            # proxy is the only reason it is same-origin at all.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
