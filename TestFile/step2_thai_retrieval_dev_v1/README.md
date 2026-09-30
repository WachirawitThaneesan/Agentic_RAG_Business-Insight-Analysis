# Thai evidence retrieval: development comparison

**Status:** the 20 questions have been inspected and used to choose retrieval
changes. These figures are diagnostic, **not** an untouched thesis test or a
population accuracy estimate. The frozen 2026-09-27 results and v3 AI PDF
adjudication remain unchanged. No independent human label sign-off is claimed.

The corpus is the two original Thai 2567 annual reports (SCBX and Thai Union):
568 physical PDF pages and 1,460 selectable-text chunks. The selectable text
benchmark bypasses Typhoon/Gemini OCR. The layout experiment extracted 374
captioned regions and 1,836 table rows **from every corpus page**, without
consulting question labels during indexing. Every method below uses the same
v3 accepted physical-page evidence options and Hit@5 scorer.

| Method on the exposed 20 questions | Page Hit@5 |
| --- | ---: |
| Frozen app hybrid, original locked labels | 3/20 |
| Frozen app hybrid, same saved output with v3 AI PDF labels | 5/20 |
| Frozen Thai BM25, v3 labels | 8/20 |
| Frozen dense `bge-m3`, v3 labels | 5/20 |
| New Thai-normalized BM25, all documents | 15/20 |
| New Thai-normalized BM25, explicit issuer scope | 18/20 |
| Same, with a strict first-mentioned-year filter | 15/20 |
| Page-aware layout regions with adjacent captions, issuer scope | 14/20 |
| Detected table rows alone, issuer scope | 5/20 |
| Revised app search, new run, v3 labels | **18/20** |

The revised app result is a **new retrieval-only run** on the exposed questions,
using the same selectable PDF corpus and local `bge-m3`. It does not include
new OCR or answer generation. The frozen scores were not overwritten. In this
run, the benchmark's combined retrieval loop (BM25, app search, and dense)
had median **1.405 seconds/question**, maximum **8.14 seconds**, and **37.79
seconds** summed over 20 questions. Those are not app-only latency figures.

## Changes selected from this development experiment

- Normalize broken Thai vowel/tone-mark sequences and short stray font glyphs
  for search matching. Preserve original evidence text for the answer and
  citation.
- Restrict candidates to a named issuer only when the question clearly names
  one. Current aliases explicitly cover the two development issuers; unknown
  issuer names leave all documents eligible.
- Rank keyword candidates with BM25, give numeric questions keyword evidence
  first, and return at most one chunk per physical PDF page in each top list.
- Store normalized search text on newly ingested semantic and table chunks.
  Existing chunks remain searchable through the in-memory normalization path
  when issuer scoping loads that document.

The year experiment was deliberately **not** deployed as a hard filter. The
2567 reports contain 2566 comparison columns, and year numbers recur in
headers and footers. TF05 specifically asks for 2566 inside the 2567 report.

The isolated page-aware table tests did not outperform normalized document
chunks overall. Table rows alone missed infographics and narrative pages;
captioned layout regions found some financial rows but lost other evidence.
The application already stores Gemini-extracted table chunks with page
metadata. This experiment does **not** establish their OCR accuracy or
row/column correctness, so the next table work should measure those directly.

## Per-question findings and limits

The [miss audit](miss_audit.md) covers all 15 frozen app misses. The revised
app still misses TF01 and TF07 under the strict v3 evidence labels. TF01's
new top result is SCBX page 19, which appears to state the same operating
revenue as target page 9; it has not been added as an accepted alternate.
TF07's source page 19 ranks seventh; the separate captioned-layout retrieval
ranked that page third. Do not treat either observation as a corrected score.

The 20 questions cover only eight distinct reference PDF pages. Issuer aliases
and retrieval ranking were selected with knowledge of these questions. For
the final thesis test, freeze code and scoring rules, then select **different
Thai annual reports from different issuers** that have not supplied development
questions, OCR samples, or retrieval tuning. Annotate evidence from the
original PDFs, include valid alternate pages before predictions, and run BM25,
dense, and app search once under the same page rule. Keep those new reports
out of this development set. Answer correctness and citation quality must be
measured separately after retrieval; this result does not establish either.

## Reproduce

From the repository root, with the two source PDFs verified by the hashes in
`metrics.json` and present in a local corpus directory:

```powershell
$corpus = 'C:\path\to\verified\thai_pdfs'
$run = 'C:\path\to\new_retrieval_run'
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout `
  --manifest TestFile\heldout_thai_final_reference_v1.json `
  --corpus-dir $corpus --output $run --answer-limit 0 --thai-bm25
.\.venv\Scripts\python.exe -m scripts.benchmark_thai_retrieval_dev `
  --corpus-dir $corpus --app-run $run `
  --output TestFile\step2_thai_retrieval_dev_v1
```

The first command needs local PostgreSQL/pgvector and Ollama `bge-m3`; no
cloud OCR or generation is called. The second command computes layout and
lexical comparisons from the PDFs and saved predictions. For an exact repeat
of the original app run, retain its embedding cache from the source run; the
new output records source and script SHA-256 hashes in `metrics.json`.
