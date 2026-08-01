"""Load the Gemini-re-read tables (from reocr_tables.py) into the warehouse.

The warehouse routes a table to ``fact_financial_metrics`` only when a header
matches a bare year (``_RE_YEAR`` is anchored), and Gemini returns the header
with its parent band attached — "งบการเงินรวม 2567". Feeding that straight in
would send every financial table to the key-value store instead.

So we split on the band: a table whose columns are

    งบการเงินรวม 2567 | งบการเงินรวม 2566 | งบการเงินเฉพาะธนาคาร 2567 | …

becomes two sub-tables, each with plain year headers. That is also the honest
data model — "กำไรสุทธิ 2567" means two different numbers depending on whether
the statement is consolidated or bank-only, and collapsing them is what makes
16% of (metric, year) pairs ambiguous in the current warehouse.

Old rows for the tables being replaced are deleted first, so re-running is
idempotent and the broken and fixed versions never coexist.

Usage:
    python -m backend.scripts.load_reocr_tables --in backend/eval/results/reocr_tables.json
    python -m backend.scripts.load_reocr_tables --in ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_YEAR_IN = re.compile(r"(?:25|20)\d{2}")
# A header is "just a year" once its decorations are stripped: "ปี 2567",
# "31 ธ.ค. 2567", "2567 (ล้านบาท)" all identify the same column.
_DECOR = re.compile(r"(ปี|พ\.ศ\.|ณ วันที่|\d+\s*(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|"
                    r"ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)|[()\[\]:,]|ล้านบาท|พันบาท|บาท)")


def _norm(text: str) -> str:
    """NFC-normalise and repair the SARA AM that OCR splits into two codepoints."""
    t = unicodedata.normalize("NFC", str(text or ""))
    return t.replace("ํา", "ำ").strip()


def _split_header(h: str) -> Tuple[str, str]:
    """Return (band, year) for a column header, band='' when it carries no year."""
    h = _norm(h)
    m = _YEAR_IN.search(h)
    if not m:
        return h, ""
    year = m.group()
    band = _DECOR.sub(" ", h.replace(year, " "))
    return re.sub(r"\s+", " ", band).strip(), year


def _plan_subtables(cols: List[str]) -> List[Tuple[str, List[Tuple[int, str]]]]:
    """Group year-bearing columns by band -> [(band, [(col_index, year), ...])]."""
    bands: Dict[str, List[Tuple[int, str]]] = {}
    for i, c in enumerate(cols):
        band, year = _split_header(c)
        if year:
            bands.setdefault(band, []).append((i, year))
    # A band with one year is not a time series; it is still a usable fact column.
    return [(b, cols_) for b, cols_ in bands.items() if cols_]


def _clean_rows(rows: List[dict], n_cols: int) -> List[Tuple[str, List[str]]]:
    """Keep rows that have a label and at least one non-empty value."""
    out = []
    for r in rows or []:
        label = _norm(r.get("row_label") or "")
        vals = [(_norm(v) if v is not None else "") for v in (r.get("values") or [])]
        vals = (vals + [""] * n_cols)[:n_cols]
        if not label or len(label) < 2:
            continue
        if not any(v for v in vals):
            continue
        out.append((label, vals))
    return out


def build_loads(pages: List[dict]) -> List[Dict[str, Any]]:
    """Turn the re-OCR JSON into load_table_into_warehouse() argument sets."""
    loads: List[Dict[str, Any]] = []
    for page in pages:
        pno = page.get("page")
        for ti, tbl in enumerate(page.get("tables") or []):
            cols = [_norm(c) for c in (tbl.get("columns") or [])]
            if not cols:
                continue
            title = _norm(tbl.get("title") or "") or f"ตารางหน้า {pno}"
            unit = _norm(tbl.get("unit") or "")

            # `columns` sometimes names the row-label column too ("ชื่อบริษัท",
            # "รายการ") and sometimes only the value columns. Decide from the
            # most common raw value width -- and before padding, or the padding
            # hides the very difference being measured.
            widths = [len(r.get("values") or []) for r in (tbl.get("rows") or [])
                      if (r.get("row_label") or "").strip()]
            typical = max(set(widths), key=widths.count) if widths else 0
            val_offset = 1 if typical == len(cols) - 1 else 0

            rows = _clean_rows(tbl.get("rows") or [], len(cols) - val_offset)
            if not rows:
                continue

            subtables = _plan_subtables(cols[val_offset:])
            if subtables:
                for band, ycols in subtables:
                    name = f"[p{pno}] {title}" + (f" — {band}" if band else "")
                    headers = ["รายการ"] + [y for _, y in ycols] + (["หน่วย"] if unit else [])
                    body = []
                    for label, vals in rows:
                        picked = [vals[i] for i, _ in ycols]
                        if not any(picked):
                            continue
                        body.append([label] + picked + ([unit] if unit else []))
                    if body:
                        loads.append({"table_name": name[:200], "title": title,
                                      "headers": headers, "rows": body,
                                      "kind": "fact", "page": pno})
            else:
                name = f"[p{pno}] {title}" if ti == 0 else f"[p{pno}] {title} ({ti + 1})"
                # With val_offset=1 cols[0] already names the label column, so
                # prefixing another one would shift every value right by a slot.
                headers = cols if val_offset else ["รายการ"] + cols
                body = [[label] + vals for label, vals in rows]
                # keep header/row widths in step
                width = max(len(headers), max(len(b) for b in body))
                headers = (headers + [f"column_{i}" for i in range(len(headers), width)])[:width]
                body = [(b + [""] * width)[:width] for b in body]
                loads.append({"table_name": name[:200], "title": title,
                              "headers": headers, "rows": body,
                              "kind": "lookup", "page": pno})
    return loads


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--document-id", type=int, default=83)
    ap.add_argument("--replace", help="comma-separated table_names to delete first")
    ap.add_argument("--replace-file", help="file holding the same list, one per line")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pages = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    loads = build_loads(pages)

    n_fact = sum(1 for l in loads if l["kind"] == "fact")
    n_rows = sum(len(l["rows"]) for l in loads)
    logger.info("built %d tables (%d fact / %d lookup), %d rows",
                len(loads), n_fact, len(loads) - n_fact, n_rows)

    if args.dry_run:
        for l in loads[:8]:
            logger.info("  %-6s %-58s %s", l["kind"], l["table_name"][:58], l["headers"])
            for r in l["rows"][:2]:
                logger.info("           %s", r)
        return 0

    from backend.services.duckdb_warehouse import _get_conn, load_table_into_warehouse

    stale: List[str] = []
    if args.replace:
        stale = [s.strip() for s in args.replace.split(",") if s.strip()]
    elif args.replace_file:
        stale = [s.strip() for s in Path(args.replace_file).read_text(encoding="utf-8").splitlines() if s.strip()]
    if stale:
        conn = _get_conn()
        for t in ("fact_financial_metrics", "dim_table_rows", "dim_tables"):
            conn.execute(
                f"DELETE FROM {t} WHERE document_id = ? AND table_name IN "
                f"({', '.join('?' for _ in stale)})",
                [args.document_id] + stale,
            )
        logger.info("deleted %d superseded tables", len(stale))

    total = 0
    for l in loads:
        try:
            total += load_table_into_warehouse(
                document_id=args.document_id,
                table_name=l["table_name"],
                headers=l["headers"],
                rows=l["rows"],
                title=l["title"],
            )
        except Exception as exc:
            logger.warning("load failed for %s: %s", l["table_name"][:50], exc)
    logger.info("inserted %d records", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
