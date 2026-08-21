"""
Batch File I/O
---------------
Reads an uploaded CSV or XLSX of raw input rows into plain dicts, and
writes processed rows back out as a single XLSX with the exact fixed
header row required by the hackathon's Expected Output sheet.

No pandas dependency — openpyxl (already lightweight, one new
requirement) for XLSX, the stdlib csv module for CSV. Keeps the
deploy footprint small on a free-tier host.
"""
import csv
import io
from openpyxl import Workbook, load_workbook


def read_input_file(content: bytes, filename: str) -> list[dict]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return _read_csv(content)
    if lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        return _read_xlsx(content)
    raise ValueError(f"Unsupported file type: {filename}. Upload a .csv or .xlsx file.")


def _read_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")  # handles a leading BOM from Excel exports
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _read_xlsx(content: bytes) -> list[dict]:
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return []
    headers = [str(h).strip() if h is not None else "" for h in header_row]
    rows = []
    for raw in rows_iter:
        if raw is None or all(v is None for v in raw):
            continue
        row = {headers[i]: raw[i] for i in range(min(len(headers), len(raw)))}
        rows.append(row)
    return rows


def write_xlsx_bytes(rows: list[dict], headers: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Enriched Output"
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_csv_bytes(rows: list[dict], headers: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    return buf.getvalue().encode("utf-8-sig")