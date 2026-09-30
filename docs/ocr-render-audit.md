# OCR input-image audit - 2026-09-24

This audit inspects the PNG bytes produced by the project's own PDF renderer
and region planner **before** they are sent to Typhoon. It does not treat
embedded PDF text as correct transcription. The diagnostic PNGs contain
user-provided report pages and are stored only under git-ignored `tmp/pdfs/`.

## Reproduce without Typhoon calls

```powershell
.\.venv\Scripts\python.exe scripts/audit_ocr_render.py TestFile/y2025-onereport-th_selected50.pdf 46 --dpi 300
```

The command saves each actual OCR input region and prints its physical page,
crop box, rotation, pixel dimensions, and PNG byte count. It uses the same
render and crop functions as `backend/services/ocr.py` but makes no API call.

## Findings

| Excerpt page | Actual 300-DPI OCR input | Visual observation |
| --- | --- | --- |
| Bluebik p5 | 2481 x 3508 full page | Table numbers and row labels are clear. |
| Synnex p19 | 2481 x 3449 full page | Financial table is clear. |
| Bank p24 | Two rotated regions, 3301 x 2293 and 3301 x 2750 | Green contents strip is trimmed; three previously labeled table cells match. |
| Bank p46 | Two upright regions, 2493 x 3301 and 2550 x 3301 | The input is not visibly blurry, but contains a very dense position matrix with tiny cells. |

The previous bank p46 left crop still included a large green contents strip
(3600 x 3301 pixels, 1.45 MB). The planner had trimmed that strip only on
rotated pages. It now trims the detected strip on upright two-up pages too.
The new left input is 2493 x 3301 pixels, 0.53 MB; visual inspection confirms
that the table and its row labels remain in the crop. This also improves the
same layout on bank excerpt p5. The crop is a layout heuristic, not a claim
that OCR has transcribed every cell correctly.
Across the 20 benchmark pages, the planner split only the five expected bank
two-up pages (p5, p24, p30, p36, p46); the other reports were not cropped.

A focused live Typhoon retry of p46 with the revised 300-DPI crop still hit
the 240-second page deadline; no OCR table was returned. The current 20-page
diagnostic remains at 19/20 table-presence decisions. The failure is therefore
not explained by the removed sidebar alone. The grid's complexity is a
plausible cause, but the timeout does not prove which part of the upstream
processing stalled.

Local renders at 200/300/400 DPI for p46's left region are respectively
1662 x 2200, 2493 x 3301, and 3324 x 4400 pixels. **No Typhoon accuracy
comparison at these three DPIs has been completed.** Increasing DPI for
every page would be an untested change, not an established fix.

## Follow-up probe: why p46 stalls

The exact 300-DPI left-region PNG is 2493 x 3301. We cropped a 2493 x 415
pixel band containing the matrix header and rows 1-4, then made **one**
bounded Typhoon request per prompt using `scripts/probe_typhoon_region.py`.
Private responses are kept under git-ignored `tmp/pdfs/`.

| Probe | Max output tokens | Time | Observed result |
| --- | ---: | ---: | --- |
| Project's full-page HTML prompt on row band | 4,096 | 38.02 s | 7,923 characters, including 3,390 slash characters; output stops mid-row and never closes the table. It invented slashes across mostly empty cells. |
| Compact sparse-matrix prompt on same band | 1,024 | 3.68 s | 464 characters; no slash loop, but it ignored the requested JSON schema and did not give trustworthy column mappings. |
| Sparse prompt on a 540 x 415 row-and-column tile | 1,024 | 1.94 s | Returned parseable JSON-like rows and positions, but misread two names and omitted visible slash marks in row 2. Fast is not accurate. |

This is direct evidence of a repetitive-generation failure on p46 and makes
the full-page timeout plausible: a much larger grid, an instruction to include
*all* cells as HTML, a 16,384-token allowance, and a non-streamed response can
keep generation running beyond the request deadline. It is **not proof** of
Typhoon's internal timeout cause. Network or provider load could still matter.
The configured repetition penalty was already 1.2, so merely raising that
setting is not an evidence-backed fix.
The 300-DPI input is visibly sharp; changing DPI alone has no evidence of fixing
this failure. No HTTP 429 was observed in these serial probes, so rate limiting
is not the leading explanation.

Typhoon's [OCR documentation](https://docs.opentyphoon.ai/en/ocr/) identifies
`typhoon-ocr` as OCR 1.5, with 2 requests/second and 20/minute. Its generic
[chat API reference](https://docs.opentyphoon.ai/en/api-reference/) lists a
maximum of 8,192 tokens shared by prompt and completion, while the project's
current OCR setting requests 16,384 output tokens. The OCR-specific limit is
not clarified there, so treat this as a configuration mismatch to test, not a
confirmed rejection: smaller requests were accepted. Typhoon's
[deployment benchmark](https://docs.opentyphoon.ai/en/deploy-hardware/) assumes
about 512 output tokens for an OCR image, far smaller than this wide matrix.

Three exact person/position cells from p46's visible PDF image are now in
`TestFile/ocr_cell_gold.json`. The scorer checks text in the correct person row
and position column; a name or role appearing elsewhere is insufficient.
The cached full-page OCR result remains a timeout, so these cells currently
score as `ocr_failed`, not correct. The experimental sparse response also
cannot be accepted as a matrix answer: it mixed labels and marks without
reliable row/column alignment.

The OCR service now rejects the observed 200-plus consecutive slash-token
loop without storing it or retrying the same malformed completion. This is a
fail-safe, not a recovery mechanism.

## Long-document checkpoint result

An opt-in live PostgreSQL/DuckDB integration test used the 50-page bank excerpt
with fake OCR. It confirmed that a failed page 27 is retried without duplicating
the other 49 pages. A second 50-page test simulated API cancellation on page 27,
then invoked the same per-document job entry point used after startup. Pages
1-26 were skipped and all 50 finished with exactly one raw OCR artifact each.
This verifies checkpoint/resume behavior, **not** a real Typhoon 50-page upload
or an actual OS process restart. The test uses a separate DuckDB path and
cleans up its PostgreSQL document records.

## Next experiment

Keep 300 DPI as the default. For p46, further compare **row-and-column tiles**
with overlapping person labels and numbered column headers, using a compact
output format that omits empty cells. The first such tile was fast but missed
marks, so try tighter grid alignment or a different extraction method; do not
assume splitting solves the accuracy problem. Check exact row, group, column
number, and mark against manually labeled PDF cells before enabling automatic
ingestion.
Increasing the timeout or reducing `max_tokens` alone cannot make hallucinated
matrix marks trustworthy. Until a tiled configuration passes the gold cells,
leave this page failed/unresolved and retain its source image for inspection.
