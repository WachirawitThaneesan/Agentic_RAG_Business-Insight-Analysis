# Presentation demo: final Thai report evidence and a live smoke test

Use the [Thai Step 8 evaluation](thesis-evaluation.md) to explain the aggregate
results before showing individual examples. The examples are selected for
inspection; they are not a replacement for the 20-question score. The saved
replay runs without a model call; the live offline smoke test is separate.

## Before presenting

1. Use the saved final Thai benchmark outputs. To reproduce the measured run,
   start PostgreSQL/pgvector and Ollama with `bge-m3` and `gemma3:4b` installed.
2. Run the backup preparation command below. It verifies the source-PDF hashes,
   renders the labeled PDF evidence pages, and saves the measured answers and
   retrieval rankings in one JSON file. It makes no model call.
3. Open the original PDFs at the physical PDF pages listed in the summary.
   Practice one supported answer and one failure. Explain any `needs_review`
   result as unresolved until a human checks its wording.

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8-thai-final'
$corpus = Join-Path $out 'corpus'
.\.venv\Scripts\python.exe -m scripts.prepare_heldout_corpus --manifest TestFile/heldout_thai_final_reference_v1.json --output-dir $corpus
.\.venv\Scripts\python.exe -m scripts.demo_thesis --manifest TestFile/heldout_thai_final_reference_v1.json --corpus-dir $corpus --results-dir TestFile/step8_thai_final_results_v1 --output-dir (Join-Path $out 'demo') --ids TF01 TF06 TF14 TF18
```

`demo_summary.json` contains the question, reference answer, the top five
retrieved PDF pages for BM25/dense/app hybrid, both generated answers, their
automatic fact statuses, and exposed source pages. PNGs show the original
report pages. A source-page hit only means the correct page was offered as
evidence; it does not prove every statement in the answer follows from it.

The [untouched Thai final results](../TestFile/step8_thai_final_results_v1/README.md)
give four examples:

- TF01: BM25 retrieved SCBX PDF page 9 but answered **43.9 billion baht**
  (net profit) instead of **172.4 billion baht** (operating revenue). This
  demonstrates that the right page alone is not enough.
- TF06: the app answered **43.9 billion baht** correctly. It cited SCBX PDF
  page 111, which a post-run visual check found also supports the fact, though
  only page 19 was labeled for strict citation scoring.
- TF14: BM25 answered **4,984,894 thousand baht** from Thai Union PDF page
  194. This rounds to the labeled infographic's **5.0 billion baht**, but the
  fixed exact grader marks it wrong. Show the [post-run audit](../TestFile/step8_thai_final_results_v1/postrun_audit.md)
  and do not change the frozen score.
- TF18: the app cited Thai Union PDF page 40, where **12%** is stated, but
  abstained. Evidence exposure and successful answering are distinct.

The [post-hoc Gemini supplement](../TestFile/step8_thai_gemini_supplement_v1/README.md)
uses the same public Thai selectable-text corpus. The BM25 + Gemini arm scored
6/20 strict answers and the normal Gemini app agent scored 2/20. For TF18,
Gemini answered **12%** and exposed Thai Union PDF page 40. For TF10, it gave
the labeled **16%** answer with SCBX page 33, but the frozen scorer rejected
the `2` in `Gen 2` as a competing number. Show the
[audit](../TestFile/step8_thai_gemini_supplement_v1/postrun_audit.md) with the
unchanged automatic score. A [separate provisional rescore](../TestFile/step8_thai_rescore_v2_provisional/README.md)
fixes that parser error and records alternate evidence pages; show it only
with its pending second-review status. These results were measured after
viewing the offline outcomes, so present them as supplemental.

A later [AI audit of all 20 original-page labels](../TestFile/heldout_thai_final_ai_pdf_audit_v1.md)
excluded SCBX page 111 as complete support for TF06's parent-attributable
wording. If presenting corrected page scores, use the separate
[conservative v3 bundle](../TestFile/step8_thai_rescore_v3_ai_review/README.md)
and identify it as a post-run AI interpretation, not a new held-out run.

The [earlier Thai development replay](../TestFile/step8_thai_results_v1/README.md)
remains available for comparison:

```powershell
$dev = Join-Path $env:LOCALAPPDATA 'rag-step8-thai'
.\.venv\Scripts\python.exe -m scripts.demo_thesis --manifest TestFile/heldout_thai_reference_v1.json --corpus-dir (Join-Path $dev 'corpus') --results-dir (Join-Path $dev 'heldout') --output-dir (Join-Path $dev 'demo') --ids TH10 TH06 TH11 TH13
```

Its four selected examples are:

- TH10: the app answered **80%** and exposed the labeled BOT PDF page 53.
- TH06: the app exposed BOT page 23 but answered **-0.0%** instead of **-1.6%**.
- TH11: simple RAG answered **7,214 million baht**; the app abstained. The
  question asked specifically about the TPAC chart on PDF page 10, while the
  baseline exposed another page containing the revenue value.
- TH13: both arms gave **1,143 million baht**. TPAC page 65 also supports the
  answer, although only page 11 was labeled before the benchmark. Explain why
  the strict page score does not count that post-run observation.

The previous English replay is retained for comparison:

```powershell
$older = Join-Path $env:LOCALAPPDATA 'rag-step8'
.\.venv\Scripts\python.exe -m scripts.demo_thesis --corpus-dir (Join-Path $older 'corpus') --results-dir (Join-Path $older 'heldout') --output-dir (Join-Path $older 'demo') --ids H01 H07 H14
```

## Live path

The live privacy smoke test from Step 6 uses a one-page synthetic PDF, local
Docling OCR, local embeddings, and local Gemma. It uploads the file through the
API, waits for processing, asks one question, and records the answer and page
status while external DNS and TCP are blocked. The saved result is in the
Step 6 output directory. Re-run it before presenting if the environment has
changed:

```powershell
$env:OFFLINE_MODE = 'true'
$env:OFFLINE_LLM_MODEL = 'gemma3:4b'
$env:EMBED_MODEL = 'bge-m3'
$env:LOCAL_OCR_PYTHON = 'C:\path\to\local-ocr\.venv\Scripts\python.exe'
$env:LOCAL_OCR_MODELS_DIR = 'C:\path\to\local-ocr\models'
$env:PRIVATE_DATA_DIR = Join-Path $out 'private'
.\.venv\Scripts\python.exe -m scripts.test_private_offline --pdf 'C:\path\to\synthetic-one-page.pdf' --output (Join-Path $out 'offline-smoke.json')
```

See [offline setup](offline-mode.md) for model downloads and the EasyOCR cache.
The prior run took about 63 seconds end to end. A separate Thai TPAC report
completed local OCR on all 220 pages over about 3 hours 42 minutes of summed
per-page processing, with checkpoint recovery after a process stop. The
[record](../TestFile/step8_thai_long_ocr_v1/README.md) measures OCR engine
completion, not a full upload-to-answer run. Show a long upload with its
progress indicator and keep the saved held-out summary available if model
startup or live processing exceeds the presentation slot.

## What to say when showing a result

- Show the Thai aggregate retrieval and answer scores from `metrics.json`.
- Read the question, show the exact physical PDF page, then show the response.
- Point out the retrieved rank and automatic fact status, including failures.
- State that the untouched final comparison indexes selectable text and uses
  offline Gemma. The later Gemini answer supplement uses the same text, and
  neither comparison measures the normal Typhoon/Gemini OCR path.

The Thai benchmark uses two public Thai reports and one reviewer. The original pages
and saved predictions make examples auditable, but a broader, second-reviewed
test set is needed for a thesis-level general claim.
