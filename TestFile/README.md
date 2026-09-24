# PDF OCR test inputs

This folder keeps the existing `5Page_Test.pdf` and four new 50-page excerpts:

| Excerpt | Original physical pages |
| --- | ---: |
| `2025_105466_E_ONE_REPORT_BBIKT_selected50.pdf` | 377 |
| `AnnualSynnex2025_THA_selected50.pdf` | 278 |
| `onereport_2568TH_selected50.pdf` | 328 |
| `y2025-onereport-th_selected50.pdf` | 180 |

The full source PDFs remain unchanged on the Desktop. `selection_manifest.json`
maps every excerpt page to its original **1-based physical PDF page**, records
why it was sampled, and includes file hashes. Printed page numbers may differ.
The PDFs are local test inputs and are not published with the Git repository;
only the labels, manifest, report, and scripts are versioned. On another
machine, obtain the four source reports, run
`scripts/prepare_pdf_test_corpus.py` into a new empty directory, verify the
excerpt hashes against this manifest, then place those excerpts in `TestFile/`.
The five-page test PDF is also local-only. Unit tests generate their own small
PDF fixture and do not require these report files.

These are diverse test inputs. `ocr_benchmark_gold.json` adds 20 visually
checked page-role labels and a limited set of visually checked numeric anchors.
It is a **small diagnostic benchmark**, not complete page transcription.
Numeric-anchor recall only checks whether a number appeared somewhere on the
page; it does not prove that the correct row and column were extracted. The
automatic selection used embedded text only as a sampling signal, never as
ground truth. Do not assume the selected visual pages are all charts.

The current upload endpoint processes PDF pages sequentially within one HTTP
request. Test small batches first; these excerpts have not been uploaded or OCR'd.

Selection is reproducible with `scripts/prepare_pdf_test_corpus.py` from the
repository root. It refuses to overwrite existing excerpts or the manifest.

Run a three-page Typhoon pilot from the repository root with
`.venv/Scripts/python scripts/run_ocr_benchmark.py --max-pages 3`, then score
cached outputs with `.venv/Scripts/python scripts/run_ocr_benchmark.py --score-only`.
Running without `--max-pages` OCRs the remaining 20-page set and may use API
credits. Raw benchmark responses are saved in the git-ignored
`backend/eval/results/ocr_benchmark/` directory. The runner does not upload
reports to PostgreSQL or DuckDB. It records page failures, too; use
`--retry-errors` to rerun failed pages and `--page-timeout 90` to set a
shorter benchmark-only wall-clock limit.
