# OCR diagnostic run — 2026-09-24

This is a **small diagnostic**, not a whole-report or cell-level accuracy
estimate. The inputs are the 20 physical pages listed in
`ocr_benchmark_gold.json`, sampled from four 50-page report excerpts. All
numeric reference anchors were checked again at readable render resolution
before the final score. The OCR run used `typhoon-ocr` at 300 DPI.

| Measure | Observed result |
| --- | ---: |
| Pages with correct table-present/table-absent decision | 18 / 20 |
| Table-containing pages on which OCR found a table | 17 / 19 |
| Diagram-only pages correctly left without a table | 1 / 1 |
| Visually checked numeric anchors present anywhere in raw OCR | 9 / 9 |
| Anchors present in parsed tables | 9 / 9 |
| Anchors present after the structured-data quality gate | 8 / 9 |
| Rows with applicable arithmetic checks | 0 |
| Rows quarantined as unresolved | 5 |
| Rows labeled unverified | 368 |

The one anchor absent from post-gate tables is a **chart label**, not a lost
financial table cell. It remains in the raw OCR audit text. The five
quarantined rows are two chart-derived pseudo-table rows and three malformed
rows on a dense bank-report table. Typhoon returned its own instruction prompt
instead of document text on two rotated/two-up bank-report pages (excerpt
pages 24 and 46). The upload code now rejects prompt echoes as page failures,
rather than indexing them. It also gives each page a wall-clock OCR deadline.

On the earlier `5Page_Test.pdf` upload (existing document 4), the new checks
identify seven unresolved rows on physical pages 1, 2, and 4. In one separate
400-DPI retry of page 1, the OCR changed `49,585` to the visually correct
`49,565`; one other contradictory row remained unresolved. This retry was a
diagnostic call and did **not** update the stored document.

Important interpretation: `9/9` is only **numeric-token recall for nine
selected answers**. It says nothing about whether all other cells are
correctly read, assigned to the right row/column, or missing. In particular,
368 unverified rows are still provisionally available in structured storage;
they are not certified values. A wrong value can pass an internal arithmetic
check when other OCR errors make the equation agree.

Reproduce the scoring without additional API calls:

```powershell
.\.venv\Scripts\python.exe scripts/run_ocr_benchmark.py --score-only
```

The cached raw OCR responses are local, git-ignored files under
`backend/eval/results/ocr_benchmark/`. Re-running OCR may produce different
outputs and use API credits.

Next evaluation work: create row/column-specific gold labels for financial
tables, add dedicated labels for chart facts, and test split-and-rotate
preprocessing on the two failed bank pages. Only after that should a numerical
accuracy rate or end-to-end financial-answer reliability be reported.
