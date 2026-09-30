# New Thai issuer retrieval run (v1.1)

Run date: 2026-09-28. Retrieval only, no OCR or generated answers.

| Corpus | Physical pages | Pages with selectable text |
| --- | ---: | ---: |
| CP Axtra 2567 One Report | 400 | 255 |
| EGCO 2567 One Report | 432 | 416 |

The 20 Thai questions cite 20 distinct primary PDF pages. Evidence options,
questions, source PDF hashes, code hashes, and scoring rules were frozen before
retrieval predictions. The reports had appeared only in public PDF discovery
records, not in the SCBX/Thai Union retrieval development set. Source PDF text
was indexed as 1,225 page-bound 1,800-character windows with 180-character
overlap. All three methods used physical PDF page Hit@5.

| Method | Page Hit@5 |
| --- | ---: |
| PyThaiNLP newmm BM25 | 14/20 |
| Local bge-m3 dense | 10/20 |
| Current app search | 15/20 |

`reference_v1_1.json` is the fixed question/evidence reference;
`method_lock_v1_1.json` contains input and code hashes. The three
`*_predictions.json` files retain all ranked pages. `metrics.json` has scores
per question and timings; `run_audit.json` checks the hashes, prediction IDs,
and page ranges. `benchmark.log` is the successful run log.

The initial v1 run reached scoring but failed because the manifest lacked
`excerpt_file`, which the existing scorer requires for filename matching.
Version 1.1 added that field, equal to `source_file`, to both document records.
The 20 questions and evidence labels are byte-for-byte identical between v1
and v1.1. The original v1 reference, lock, and failed-run log are retained in
the sibling work/output directories.

This is a selected two-issuer retrieval test with one AI reviewer for page
labels and selected rendered-page checks; it has no independent human sign-off.
The selectable-text corpus excludes OCR accuracy, answer correctness, and the
effect of CP Axtra's 145 pages without selectable text. Failure analysis is
deferred.
