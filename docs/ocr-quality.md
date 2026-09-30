# OCR quality on previously unseen PDFs

The production path does **not** need a person to review each upload. It also
cannot prove that every OCR value is correct. This implementation reports what
the software can and cannot verify instead of assigning one confidence score
to an entire page.

For each extracted table row:

- `unresolved`: the table shape is malformed, a numeric field is invalid, a
  numeric row has no label, or reported year-to-year arithmetic contradicts
  the year values. The **whole row** is excluded from structured storage,
  table search, and DuckDB because the equation cannot identify which cell
  is wrong. Raw OCR remains available in the viewer as an audit artifact.
- `passed_checks`: at least one applicable printed relationship is internally
  consistent. This is **not** proof that the numbers match the PDF; two wrong
  OCR values can still agree with each other.
- `unverified`: no applicable relationship could check the row. It remains
  provisionally searchable and appears as unverified in the viewer.

Only a page with a reported arithmetic contradiction is automatically sent to
Typhoon a second time at higher render resolution. The retry is capped at
`PDF_QUALITY_REOCR_MAX_PAGES` (default 20) per document and skipped for very
large page images. A changed cell is accepted only when the row label and
table shape match, exactly one numeric cell changed, and the retried row now
passes the printed relationship. The original and retry OCR are retained.
This is an OCR-derived correction, not an independent source verification.
If the two aligned OCR passes disagree on another numeric cell, that row is
`unresolved` rather than silently keeping either guess.

An OCR response that repeats the Typhoon instruction prompt is rejected as a
page failure; it is never indexed as document text. Each PDF page has a
wall-clock OCR deadline, so a stalled request can fail that page and let the
remaining pages continue.

The 20-page diagnostic set is in `TestFile/ocr_benchmark_gold.json`. Run
`.venv/Scripts/python scripts/run_ocr_benchmark.py --max-pages 3` for a small
pilot, or omit `--max-pages` for all 20 pages. Existing responses are cached;
`--score-only` uses no API credits. The report measures table-presence
decisions and numeric-token recall for the few visually checked anchors.
It does **not** measure full table-cell alignment or whole-document accuracy.

Known remaining risks for a thesis evaluation:

1. An OCR error can be internally consistent, and a chart may have no table
   equivalent. Those values remain unverified, not automatically corrected.
2. The page viewer now fetches a 25-page status window and one selected page's
   data/image at a time. The legacy full-detail API still exists for older
   consumers and should not be used for 500-1,000-page viewer requests.
3. PDF uploads now run as API-owned background jobs with per-page checkpoints.
   Pending/interrupted jobs resume after an API restart. A live five-page
   PostgreSQL/DuckDB retry test passed with fake OCR. A separate 50-page test
   simulated cancellation at page 27 and successful checkpoint resume; actual
   OS process-crash recovery, multi-process coordination, and a full 500-page
   load test still need end-to-end verification. Run only one API process with
   this DuckDB design.
4. Sixteen exact table cells and four chart facts now have row/column or category
   labels. The 13/16 cached table score includes three OCR failures on bank
   page 46 and is still a tiny selected set; chart category
   extraction is not implemented, and more held-out reports are needed.
5. Two-up/rotated pages are now split and rotated before Typhoon. The focused
   live retry recovered bank excerpt page 24 after trimming its green sidebar:
   two tables appeared and three visually labeled cells matched their exact
   row/column/half. The rest of those tables remain unverified. Page 46 timed
   out after 300 seconds and remains failed.
