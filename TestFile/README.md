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

`ocr_cell_gold.json` is a separate, small exact-answer set: 16 table cells
with specific rows and columns, plus four chart facts. Run the cache-only
scorer with `.venv/Scripts/python scripts/score_ocr_cells.py --split all`.
The three added bank-page-46 person/position cells currently score as OCR
failures; the 13 other cells match their cached OCR rows and columns.
Chart facts are deliberately reported as unresolved until the system can
associate each visible value with its category; token presence alone is not
chart-fact accuracy. The scorer checks cached PDF hashes against the manifest.

The upload endpoint now returns a document ID and runs PDF pages in a
restart-resumable API-owned background queue. A 50-page integration test with
fake OCR verifies checkpoint resume, but these excerpts have not been
end-to-end uploaded with real Typhoon through that queue; test a small file first.

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

## Reference pages v1

`reference_pages_v1.json` contains 34 reference questions and answers from 32
physical pages (eight pages per report). It records the source and excerpt page
indices, exact row/column or section locators, answer components, and SHA-256
hashes for the four original PDFs and excerpts. The labels were checked by one
reader against rendered original PDF pages. Use `reference_review_v1.md` for a
second-reader or owner check before citing results in the thesis.

This is a development diagnostic set: all four reports were previously used by
the project. It is not an unseen-report final test set. The bank report sample
includes excerpt page 46, the known OCR failure.

## Public PDF discovery

`pdf_discovery_thai_sites_v5.json` lists 20 official Thai annual-report pages.
`pdf_discovery_thai_result_v7.json` is the primary Thai discovery run: 17/20
known Thai report PDFs or Thai chapters found. Earlier Thai manifests/results
preserve crawler and AIS-label revisions. The English 20-site sample below is
an earlier pilot, not a measure of Thai-document discovery.

`pdf_discovery_sites_v3.json` is the audited 20-publisher report-page sample.
`pdf_discovery_result_v3.json` records the HTTP-first and browser-fallback run;
`pdf_discovery_http_v2.json` records the earlier HTTP-only run. The original
v1 and v2 manifests remain available to inspect benchmark label corrections.
See `docs/pdf-discovery.md` for the method, scores, and access failures.

## Held-out thesis pilot

`heldout_thai_final_reference_v1.json` is the untouched Thai final comparison:
20 numeric questions from the 351-page SCBX 2567 and 217-page Thai Union 2567
reports. These reports were selected after the earlier Thai pilot fixed word
segmentation. The one-reader labels identify physical PDF pages, exact values,
years, and units; `heldout_thai_final_review_v1.md` is the page-linked second
review sheet. `heldout_thai_final_method_lock_v1.json` records the fixed
benchmark code hashes and settings before answer predictions. The PDFs are
public but are downloaded separately and verified by SHA-256; they are not
bundled here. This is a selectable-text search and answering comparison, not
an OCR accuracy test. `step8_thai_final_results_v1/` preserves the complete
20-question outputs and post-run evidence audit. The final app agent gave one
strict correct answer out of 20, so these results do not support a claim of
reliable Thai financial answering.

`step8_thai_gemini_supplement_v1/` holds a post-hoc comparison on those same
Thai reports using Gemini 2.5 Flash for answer generation and agent steps, with
no cloud OCR. Its strict automatic scores are 6/20 for BM25 + Gemini and 2/20
for the normal Gemini app agent; `postrun_audit.md` documents the TF10 scorer
false negative. `heldout_thai_gemini_supplement_method_v1.json` records the
supplemental method and code hashes.

`heldout_thai_final_adjudication_v2.json` records four candidate alternate
support pages and a one-decimal rounding rule for TF14. The separate
`step8_thai_rescore_v2_provisional/` bundle re-scores the saved predictions
with those rules and a `Gen 2` scorer fix; no model was rerun. Its result is
provisional until a different human reader completes the blind
`heldout_thai_final_second_review_v2.md` sheet. The frozen v1 scores remain
available unchanged.

`heldout_thai_final_ai_pdf_audit_v1.md` records a visual AI check of all 20
primary Thai labels and four proposed alternate pages. All primary labels
matched; SCBX p. 111 was excluded as complete evidence for TF06 because it
omits the parent-attributable qualifier. The corresponding conservative
`heldout_thai_final_adjudication_v3_ai_review.json` and
`step8_thai_rescore_v3_ai_review/` preserve a separate AI-reviewed score.
This does not count as independent human sign-off or a new model run.

`step2_thai_retrieval_dev_v1/` is a separate retrieval-only development
experiment on those now-exposed 20 questions. It records a per-miss audit,
the year-filter and page-layout tests, and the new app search run (18/20
conservative v3 page Hit@5). It does not change the frozen scores, test OCR,
or test answer correctness. SCBX and Thai Union must not be reused as the
untouched final thesis reports after this tuning; choose different Thai
issuers/reports and freeze the retrieval method first.

`step8_thai_long_ocr_v1/` holds the checkpoint for a complete local OCR pass
over all 220 physical PDF pages of the Thai TPAC 2567 report. It records page
status, time, sampled memory, and continuation after interruption. This is an
OCR engine test, not a full upload-to-answer test or cell-accuracy score.

`heldout_thai_reference_v1.json` freezes 20 Thai questions from the Thai
Bank of Thailand 2567 annual report and TPAC 2567 One Report. Every fact was
checked against a rendered original PDF page by one reviewer. Source hashes,
physical PDF pages, years, units, and exact answers are recorded. The
`step8_thai_results_v1/` bundle contains the 20-question run, including
the low 4/20 app-agent answer score. Retrieval and answer interpretation is
in `docs/thesis-evaluation.md`; the public PDFs are
downloaded separately with `scripts.prepare_heldout_corpus --manifest
TestFile/heldout_thai_reference_v1.json`. A second reviewer is needed before
thesis submission; `heldout_thai_review_v1.md` is the page-linked review sheet.

`heldout_reference_v1.json` freezes 20 fact questions from the public World Bank
Group 2025 annual report and NVIDIA 2024 annual review, with 1-based physical
PDF evidence pages, source URLs, SHA-256 hashes, and answer components. These
reports were held out from OCR development. One reader verified the labels
against original PDF pages; a second reader should review them before thesis
submission. The sample is too small to estimate general accuracy. See
`docs/thesis-evaluation.md` for the search/answer comparison and limitations.
