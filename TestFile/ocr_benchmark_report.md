# OCR diagnostic run — 2026-09-24

This is a **small diagnostic**, not a whole-report accuracy
estimate. The inputs are the 20 physical pages listed in
`ocr_benchmark_gold.json`, sampled from four 50-page report excerpts. All
numeric reference anchors were checked again at readable render resolution
before the final score. The OCR run used `typhoon-ocr` at 300 DPI. The table
below includes a focused page-24 retry after two-up cropping.

| Measure | Observed result |
| --- | ---: |
| Pages with correct table-present/table-absent decision | 19 / 20 |
| Table-containing pages on which OCR found a table | 18 / 19 |
| Diagram-only pages correctly left without a table | 1 / 1 |
| Visually checked numeric anchors present anywhere in raw OCR | 9 / 9 |
| Anchors present in parsed tables | 9 / 9 |
| Anchors present after the structured-data quality gate | 8 / 9 |
| Rows with applicable arithmetic checks | 0 |
| Rows quarantined as unresolved | 5 |
| Rows labeled unverified | 427 |

The one anchor absent from post-gate tables is a **chart label**, not a lost
financial table cell. It remains in the raw OCR audit text. The five
quarantined rows are two chart-derived pseudo-table rows and three malformed
rows on a dense bank-report table. The first Typhoon run returned its own
instruction prompt on two rotated/two-up bank-report pages (excerpt pages 24
and 46). The revised page-24 split/crop retry succeeded; page 46 still times
out. The upload code rejects prompt echoes as page failures and gives each
page a wall-clock OCR deadline.

On the earlier `5Page_Test.pdf` upload (existing document 4), the new checks
identify seven unresolved rows on physical pages 1, 2, and 4. In one separate
400-DPI retry of page 1, the OCR changed `49,585` to the visually correct
`49,565`; one other contradictory row remained unresolved. This retry was a
diagnostic call and did **not** update the stored document.

Important interpretation: `9/9` is only **numeric-token recall for nine
selected answers**. It says nothing about whether all other cells are
correctly read, assigned to the right row/column, or missing. In particular,
427 unverified rows are still provisionally available in structured storage;
they are not certified values. A wrong value can pass an internal arithmetic
check when other OCR errors make the equation agree.

Reproduce the scoring without additional API calls:

```powershell
.\.venv\Scripts\python.exe scripts/run_ocr_benchmark.py --score-only
```

The cached raw OCR responses are local, git-ignored files under
`backend/eval/results/ocr_benchmark/`. Re-running OCR may produce different
outputs and use API credits.

Next evaluation work: grow the exact-cell gold set, implement chart
category/value extraction, and resolve the page-46 timeout. Only after much
broader held-out testing should a whole-report accuracy rate or end-to-end
financial-answer reliability be reported.

## Follow-up layout retry (2026-09-24)

The layout planner identified the two-up gutter on both pages and 90-degree
rotation on page 24. The first split attempt still failed: page 24's left crop
echoed Typhoon's prompt, and page 46 timed out after 300 seconds. After
trimming page 24's large green contents sidebar, a focused live retry returned
two OCR regions and two parsed tables. Three visually labeled bank cells were
found in the correct page half, row, and column. This is a useful recovery,
**not** proof that its other table cells are correct. Page 46 remains failed.
The image audit then found that p46's upright left region still included its
green contents strip. Trimming it reduced the OCR input from 3600 x 3301 to
2493 x 3301 pixels, but a focused 300-DPI retry still timed out after 240
seconds. See `docs/ocr-render-audit.md`; higher DPI has not been shown to help.

The new `ocr_cell_gold.json` set tests exact row/column placement for 16 table
cells (13/16 on the cached, selected pages; three page-46 cells fail OCR)
and records four chart facts. All
four chart numbers occur somewhere in raw OCR, but chart category/value
linking is not implemented, so chart fact accuracy is **unscored**. These
small denominators cannot support a general accuracy claim.
