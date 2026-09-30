# Thesis evaluation: Step 8 pilots

The primary tests below use Thai reports and Thai questions. The earlier
English-language pilot and long-document resource tests remain later for
comparison. No percentage here estimates accuracy across unfamiliar annual
reports. The [Thai development-pilot bundle](../TestFile/step8_thai_results_v1/README.md)
and [earlier English JSON bundle](../TestFile/step8_results_v1/README.md)
preserve per-question predictions, answers, timings, and environment details.

## Historical untouched Thai test: frozen inputs

This run was untouched when recorded. The later
[retrieval development experiment](../TestFile/step2_thai_retrieval_dev_v1/README.md)
uses its exposed 20 questions for tuning, so SCBX and Thai Union are now a
**development set** for future work. A new final thesis test needs different
Thai reports.

The [final Thai reference](../TestFile/heldout_thai_final_reference_v1.json)
contains 20 Thai numeric questions from two reports that were not used to
choose Thai word segmentation: the 351-page [SCBX 2567 annual report](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf)
and the 217-page [Thai Union 2567 One Report](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf).
The facts span eight physical PDF pages: infographics, financial and business
tables, and narrative. Thai Union's PDF pages are two-page printed spreads, so
the reference identifies physical PDF pages explicitly. One reader checked
the rendered originals; the [independent review sheet](../TestFile/heldout_thai_final_review_v1.md)
remains pending. Multiple questions share a page and are correlated.

The [method lock](../TestFile/heldout_thai_final_method_lock_v1.json) records
the fixed tokenizer, models, chunking, scoring files, package versions, and
SHA-256 hashes before answer predictions. The PDFs are SHA-256 and page-count
verified. The comparison indexes selectable PDF text over all 568 pages,
without OCR or structured DuckDB tables. It compares segmented Thai BM25,
local `bge-m3` dense search, and the app's PostgreSQL hybrid retrieval. The
answer arms are BM25's top three passages with local `gemma3:4b` and the app's
offline agent with that model. This measures search and answering on these
reports, not the normal Typhoon/Gemini ingestion path.

The [frozen final result bundle](../TestFile/step8_thai_final_results_v1/README.md)
contains 1,460 indexed page chunks, every search ranking and answer, the
question-level scores, timings, software environment, and SQL error log. The
same 20 questions and full corpus were used for all methods. A Hit@5 means
the one preselected supporting PDF page appeared in the first five results.

| Search method | Hit@5 | nDCG@5 |
| --- | ---: | ---: |
| BM25 with Thai word segmentation | 5/20 (25%) | 0.225 |
| Dense `bge-m3` | 3/20 (15%) | 0.132 |
| App hybrid | 3/20 (15%) | 0.150 |

| Answer arm | Strict correct | Incorrect | Needs review | Correct + labeled page | Labeled-page exposure |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 + local Gemma | 0/20 | 17/20 | 3/20 | 0/20 | 5/20 |
| App offline agent | 1/20 | 19/20 | 0 | 0/20 | 3/20 |

These results are poor for this final sample. The BM25 arm found SCBX PDF page
9 for TF01 and TF02 but took the adjacent **net profit** and **capital ratio**
instead of **operating revenue** and **non-performing-loan ratio**. The agent
gave the correct **43.9 billion baht** for TF06 while citing SCBX page 111.
The later conservative AI PDF review excluded that page as complete evidence
because it does not state the parent-attributable qualifier. The agent also
attempted queries against a missing DuckDB view. TF18 exposed the labeled
Thai Union page 40 but abstained despite the visible **12%** fact. The
[post-run audit](../TestFile/step8_thai_final_results_v1/postrun_audit.md)
documents these cases without altering the frozen scores.
The five BM25 labeled-page hits were TF01, TF02, TF10, TF16, and TF17: two
wrong values from correct pages and three correct bare numbers awaiting unit
review. Dense and app hybrid each found the labeled page for only TF10, TF17,
and TF18. The agent cited those three labeled pages but did not give a strict
correct answer for any of them. This separates evidence-location failures
from answer failures after evidence was available.

Three BM25 answers gave the correct bare numbers **16**, **85**, and **9** on
the labeled pages but omitted the unit; the strict scorer marks them
`needs_review`. TF14 gave **4,984,894 thousand baht** from Thai Union's
consolidated financial-note page 194, which rounds to the preselected
infographic's **5.0 billion baht**. The fixed exact scorer marks it wrong.
These are post-run one-reader observations, not score adjustments. An
independent reviewer should adjudicate them, and a rounding rule must be
predeclared before another untouched test.

Generation took 386.4 seconds for simple RAG and 1,281.1 seconds for the app
agent over 20 questions; retrieval sections summed to 28.9 seconds. These
exclude setup and model loading. A separate full-page OCR job overlapped
embedding and TF01–TF04, then was paused; per-question timings and the
[run-conditions record](../TestFile/step8_thai_final_results_v1/run_conditions.json)
show that context. Do not treat the generation totals as isolated throughput.

To reproduce from the repository root with PostgreSQL/pgvector and local
Ollama models available:

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8-thai-final'
$corpus = Join-Path $out 'corpus'
.\.venv\Scripts\python.exe -m scripts.prepare_heldout_corpus --manifest TestFile/heldout_thai_final_reference_v1.json --output-dir $corpus
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout --manifest TestFile/heldout_thai_final_reference_v1.json --corpus-dir $corpus --output (Join-Path $out 'heldout') --thai-bm25 --answer-limit 20
```

The public PDFs are verified by SHA-256 and page count; keep downloaded PDFs,
embedding vectors, and temporary databases outside cloud-synced folders.
This is still only two publishers and 20 questions, with one reader's labels.
It needs more independently reviewed reports, descriptive and unanswerable
questions, and a real Typhoon/Gemini ingestion comparison before claiming
reliable Thai financial answering.
The earlier Thai development pilot scored 4/20 strict app answers on different
reports, compared with 1/20 here. These are different small samples, so the
change is not an estimated performance drop, but the unseen-report result
does not support generalization from the development pilot.

### Supplemental Gemini answer comparison

After inspecting the frozen offline scores, we ran the normal Gemini 2.5 Flash
answer provider on the **same** 20 Thai questions and selectable-text corpus.
This is a [post-hoc supplement](../TestFile/step8_thai_gemini_supplement_v1/README.md),
not another untouched final test. It used local Thai BM25 and `bge-m3`, Vertex
Gemini for answer generation and agent steps, and no cloud OCR.

| Answer arm | Strict correct | Incorrect | Labeled-page exposure | Correct + labeled page |
| --- | ---: | ---: | ---: | ---: |
| BM25 + Gemini | 6/20 | 14/20 | 5/20 | 5/20 |
| App online Gemini agent | 2/20 | 18/20 | 3/20 | 1/20 |

The run made 140 successful Gemini calls, using 847,277 input tokens and 18,717
output tokens. Instrumented generation sections summed to 112.8 seconds for
BM25 and 794.0 seconds for the agent; a local OCR job ran concurrently, so
these are not isolated speed measurements. The [post-run audit](../TestFile/step8_thai_gemini_supplement_v1/postrun_audit.md)
records a conservative scorer false negative: TF10 answered **16%** for
SCBX Gen 2 and exposed labeled page 33, but the grader treated the `2` in
`Gen 2` as a competing numeric answer. The saved 2/20 app score is unchanged.
Gemini did better than local Gemma on the simple BM25 arm in this sample, but
the app's normal-provider result still does not establish reliable answering.

With Vertex credentials already configured, PostgreSQL running, and the
offline benchmark's local embedding cache available, reproduce the supplement
from the repository root with:

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8-thai-final'
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout_gemini --manifest TestFile/heldout_thai_final_reference_v1.json --corpus-dir (Join-Path $out 'corpus') --embedding-cache (Join-Path $out 'heldout\embeddings.npz') --output (Join-Path $out 'gemini') --answer-limit 20
```

This reruns online Gemini calls. The saved predictions and token counts are in
the supplement bundle, so the thesis can be audited without rerunning them.

### Provisional label and scorer repair (Step 1 follow-up)

After the frozen runs, PDF inspection identified alternate supporting pages
for TF06, TF08, TF09, and TF14. The [v2 adjudication overlay](../TestFile/heldout_thai_final_adjudication_v2.json)
records those pages and a one-decimal, half-up rounding rule for TF14 only.
The numeric scorer now treats `Gen 2` as a business segment label, not a
competing answer value. Regression tests still reject wrong signs, years,
units, scales, and competing financial values. Original scorer source files
are saved in the [frozen method snapshot](../TestFile/step8_thai_final_results_v1/frozen_scorer_v1/README.md),
and the original result JSON files are unchanged.

The [separate v2 rescore](../TestFile/step8_thai_rescore_v2_provisional/README.md)
uses the same saved predictions, with no new model or OCR calls:

| Measure | Frozen v1 | Provisional v2 |
| --- | ---: | ---: |
| Thai BM25 page Hit@5 | 5/20 | 8/20 |
| Dense page Hit@5 | 3/20 | 6/20 |
| App hybrid page Hit@5 | 3/20 | 6/20 |
| BM25 + local Gemma strict answers | 0/20 | 1/20 |
| App offline Gemma strict answers | 1/20 | 1/20 |
| BM25 + Gemini strict answers | 6/20 | 7/20 |
| App Gemini strict answers | 2/20 | 4/20 |

The change is **post-run label and scorer adjudication**, not an improvement
to retrieval or answer generation. One reader inspected the new evidence;
the [blind second-review sheet](../TestFile/heldout_thai_final_second_review_v2.md)
must be completed by a different human reader before these provisional
figures are used as corrected thesis results. The small sample and low scores
still do not establish reliable Thai financial answering.

On 2026-09-28, a further [AI visual audit](../TestFile/heldout_thai_final_ai_pdf_audit_v1.md)
checked **all 20** primary labels on their original Thai PDF pages. Each
primary value, year, unit, and measure matched. The audit accepted SCBX page
252 for TF08/TF09 and Thai Union page 194 with declared rounding for TF14.
It rejected SCBX page 111 as a *complete* TF06 citation: that narrative states
consolidated net profit but not explicitly profit attributable to SCBX.
The [conservative v3 rescore](../TestFile/step8_thai_rescore_v3_ai_review/README.md)
therefore gives page Hit@5 of **8/20 BM25, 5/20 dense, and 5/20 app hybrid**.
Strict answer scores remain **1/20 local BM25, 1/20 offline app, 7/20 Gemini
BM25, and 4/20 Gemini app**; the offline app's sole correct answer has no
accepted page in v3. Both v2 and v3 are post-run reinterpretations of saved
predictions. The original frozen v1 metrics remain intact. An AI second pass
can improve engineering confidence, but it is not independent human sign-off
for a thesis claim.

### Retrieval development after the frozen run

The [Thai retrieval development bundle](../TestFile/step2_thai_retrieval_dev_v1/README.md)
inspected all 15 conservative v3 app misses and reran the same 20 exposed
questions after changing retrieval only. Frozen app page Hit@5 was **3/20**
under original labels and **5/20** under the later v3 AI evidence review. The
revised app found an accepted page within five results for **18/20** questions
under v3. Thai-normalized BM25 across both reports scored 15/20; adding an
explicit issuer scope scored 18/20. Dense `bge-m3` on the saved run scored
5/20. A strict first-mentioned-year filter reduced the normalized scoped
result to 15/20, because the 2567 reports include prior-year comparison data.

The separate page-aware layout test found 14/20 with captions attached to
detected PDF regions and 5/20 with table rows alone. Neither was incorporated
into the chosen app search path. The full [miss audit](../TestFile/step2_thai_retrieval_dev_v1/miss_audit.md)
lists the original 15 failures and the remaining TF01 and TF07 strict misses.
This is a **development-set improvement**, not unseen-report accuracy. No OCR
or answer generation was rerun, and correct-page retrieval does not validate
the row/year/value relationship. Freeze this search version before building a
new final set from different Thai issuers and reports.

## Thai reports: frozen inputs and method

The [Thai reference](../TestFile/heldout_thai_reference_v1.json) has 20 Thai
numeric questions on 12 physical PDF pages from two newly collected reports:
the 174-page [Bank of Thailand 2567 annual report](https://www.bot.or.th/th/research-and-publications/reports/annual-report/report-2024.html)
and the 220-page [TPAC 2567 One Report](https://tpacpackaging.com/th/investor-relations/).
Four TPAC questions concern chart values; BOT questions include infographics,
narrative, and tables. One reader checked the answers against rendered original
PDF pages. The [second-review sheet](../TestFile/heldout_thai_review_v1.md)
remains pending. Questions sharing pages are correlated.

[`benchmark_heldout.py`](../scripts/benchmark_heldout.py) indexes **selectable
PDF text**, producing 696 chunks across 394 pages. It bypasses OCR. It compares
BM25, dense cosine search with local `bge-m3`, and the app's PostgreSQL hybrid
retrieval on the same chunks. BM25's initial regex tokenizer treated long Thai
character runs as single tokens. A second pass used PyThaiNLP `newmm` Thai word
segmentation. Search scores locate a labeled original PDF page in the first
five hits; they do not establish correct row, column, or chart interpretation.

| Search method | Hit@5 | nDCG@5 |
| --- | ---: | ---: |
| BM25, regex tokens (initial diagnostic) | 2/20 (10%) | 0.057 |
| BM25, Thai word segmentation | 6/20 (30%) | 0.207 |
| Dense `bge-m3` | 10/20 (50%) | 0.363 |
| App hybrid | 8/20 (40%) | 0.338 |

The answer comparison used the segmented BM25 top three passages with local
`gemma3:4b` as a simple RAG baseline, and the app's offline agent with the
same local model and PostgreSQL index. Its numeric grader requires the correct
sign, scale, unit, and stated year. The structured DuckDB warehouse was **not
filled** from these selectable-text chunks; several agent SQL attempts failed
on a missing view or invalid types. These scores measure this text-backed
offline setup, not the normal Typhoon text OCR, Gemini table extraction, or
Gemini tool-selection path.

| Answer arm | Strict correct | Incorrect | Needs review | Correct + labeled page | Labeled-page exposure |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 + local Gemma | 2/20 | 18/20 | 0 | 0/20 | 5/20 |
| App offline agent | 4/20 | 16/20 | 0 | 1/20 | 8/20 |

The app's correct TH10 answer gave **80%** and exposed the labeled BOT PDF page
53. On TH06 it exposed the correct BOT page 23 but answered **-0.0%** rather
than the chart's **-1.6%**. Simple RAG answered TH11's **7,214 million baht**;
the agent abstained. The simple RAG citations exposed TPAC page 57, where the
same revenue appears, but the question explicitly asked for the chart on page
10. These are saved in the [Thai presentation replay](thesis-demo.md).

The citation score uses **one preselected page per question**. A post-run
inspection found additional valid statements on BOT pages 33 (TH01) and 44
(TH07), and the TPAC cash-flow table on page 65 (TH13). The
[post-run audit](../TestFile/step8_thai_results_v1/citation_audit.md) records
the observations. Those pages contain
the correct facts but were not labeled as acceptable evidence before scoring.
The frozen strict score remains unchanged; broader citation quality requires
an independently annotated set of all supporting pages and a second reviewer.
Answer generation took 333.29 seconds for simple RAG and 1,303.61 seconds for
the app agent over 20 questions. Retrieval across all three methods took
28.17 seconds. These are sums of measured sections, excluding setup and model
load.

The initial regex pass was inspected before adding Thai segmentation. This is
therefore a **development pilot**, not an untouched final test. The next thesis
evaluation should freeze the method first, then use new Thai reports that were
never used to adjust it. It also needs more publishers, independent label
review, descriptive and unanswerable questions, and end-to-end Typhoon/Gemini
and local-OCR comparisons.

To reproduce this Thai pilot from the repository root with PostgreSQL/pgvector
and local Ollama available:

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8-thai'
$corpus = Join-Path $out 'corpus'
.\.venv\Scripts\python.exe -m scripts.prepare_heldout_corpus --manifest TestFile/heldout_thai_reference_v1.json --output-dir $corpus
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout --manifest TestFile/heldout_thai_reference_v1.json --corpus-dir $corpus --output (Join-Path $out 'heldout') --thai-bm25 --answer-limit 20
```

The preparation script verifies the frozen PDF hashes and page counts. The
benchmark creates and drops an isolated PostgreSQL database, writes every
prediction and answer, and caches embeddings by model and chunk fingerprint.
Keep outputs outside cloud-synced folders. The [Thai discovery benchmark](pdf-discovery.md)
is a separate test: its final bounded run found 17/20 known Thai annual-report
PDFs or Thai chapters, with three access-restricted misses.

## Earlier Step 8 experiments

## Earlier pilot inputs and environment

The [held-out reference](../TestFile/heldout_reference_v1.json) contains 20
fact questions (15 English, five Thai) on 12 distinct pages from two reports that were not used to
develop the OCR extractor: the 67-page World Bank Group 2025 annual report and
the 174-page NVIDIA 2024 annual review. One reviewer checked each answer
against rendered original PDF pages. The reference records the public source
URL, SHA-256, 1-based physical PDF page, answer, and required evidence page.
These labels need a second review before thesis submission. Several questions
share pages, so they are not independent samples.

The long-document tests use the existing 278-page Synnex and 377-page BBIKT
reports. Their SHA-256 hashes are recorded in the output JSON. The machine was
Windows 11, Python 3.12, 12 logical CPUs, and 15.3 GB RAM. The exact package
versions and local Ollama model IDs are in `environment.json` in the results
directory.

## Long-document recovery

[`benchmark_long_document.py`](../scripts/benchmark_long_document.py) uses the
real PDF page count, upload processing function, page status records,
PostgreSQL, and resume queue. It deliberately substitutes PDF selectable text
for OCR and fixed vectors for embeddings. It injects one cancellation at a
chosen page, then invokes the same resume function used at application startup.
This tests checkpoint behavior, not a separate operating-system process crash,
real OCR speed, answer quality, or the memory of Ollama and PostgreSQL.

| Report | Pages | Interrupted page | Final indexed / empty | Repeat attempts | Processing time before + after resume | Peak test-process working set |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Synnex 2025 | 278 | 140 | 275 / 3 | Only page 140 twice; all other pages once | 17.76 + 11.36 s | 252.5 MB |
| BBIKT One Report | 377 | 190 | 377 / 0 | Only page 190 twice; all other pages once | 22.32 + 18.98 s | 319.6 MB |

Both jobs finished after the injected interruption, with no missing or
duplicated page processing. The three Synnex pages marked empty are PDF pages
2, 277, and 278; the stub returned no selectable text for those pages.
Machine-readable run records: `long_synnex_278.json` and
`long_bbikt_377.json` in the Step 8 results directory.

A separate [`benchmark_process_restart.py`](../scripts/benchmark_process_restart.py)
run terminated the Synnex worker abruptly with `os._exit(88)` at page 140,
then started a **new Python process** and invoked the startup resume queue.
It found 139 processed pages before restart (138 indexed, one empty), then
finished with 275 indexed and three empty pages. The interrupted page was
attempted twice; every other page once. The crash phase took 22.23 s with
238.8 MB peak process-tree RSS; the resume phase took 16.63 s with 219.2 MB.
This uses the same text-backed OCR stub and fixed embeddings, so it proves
durable page checkpoints across a process exit, not full-model recovery.
A repeat run had the same final page counts and attempt pattern.

## Earlier English-report retrieval pilot

[`benchmark_heldout.py`](../scripts/benchmark_heldout.py) takes selectable PDF
text and makes 1,800-character, 180-character-overlap chunks within each page.
The two PDFs yielded 651 chunks across 241 physical pages. It compares:

1. A small BM25 implementation with no Thai word segmentation. It returns no
   passage when every term has zero score.
2. Dense cosine search with local `bge-m3` embeddings.
3. The application's current `vector_search` hybrid retrieval, indexed in an
   isolated PostgreSQL database with the same chunks and vectors.

All methods use the same question text and original-PDF page labels. A Hit@5
means at least one required original PDF page appears among the first five
results; nDCG@5 also rewards earlier ranking. These are evidence-location
scores, not answer scores.

| Method | Hit@5 | nDCG@5 |
| --- | ---: | ---: |
| BM25 | 13/20 (65%) | 0.535 |
| Dense | 15/20 (75%) | 0.588 |
| App hybrid | 12/20 (60%) | 0.488 |

During review, BM25 was found to return arbitrary zero-score passages. It was
corrected and the complete comparison was rerun. The Hit@5 aggregate happened
to remain unchanged; the final predictions and scores are the corrected run.
The app hybrid missed the labeled page on eight questions, including five
NVIDIA financial questions (H13-H16 and H18). The dense baseline
had the best Hit@5 on this sample. No search parameters were tuned on these
held-out reports after observing the failures.

## Earlier English-report answer comparison

The simple RAG baseline supplies BM25's top three passages to local
`gemma3:4b`, with a short evidence-only prompt. The app arm runs its offline
`agent_query` with the same model and index. The numerical grader checks signs,
values, scales, currencies, years, and units. Other wording can be marked
`needs_review` rather than automatically wrong. Source-page coverage reflects
the passages exposed by each system; it does **not** prove the answer sentence
itself cites the exact supporting cell.

| Arm | Correct | Incorrect | Needs review | Correct **and** labeled page exposed | Labeled-page exposure |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 + local Gemma | 6/20 | 13/20 | 1/20 | 4/20 | 12/20 |
| App offline agent | 8/20 | 11/20 | 1/20 | 5/20 | 9/20 |

The strict lower bounds for fact correctness are 30% and 40%, respectively;
the one `needs_review` answer in each arm must be checked by a human. The app
arm took 813.36 seconds across 20 answers, versus 156.54 seconds for the
simple RAG generation calls. Per-question retrieval across all three methods
took 25.82 seconds. These are sums of instrumented sections, not whole-run
wall-clock times; model load and database setup are excluded.

Concrete examples from the [saved presentation replay](thesis-demo.md):

- H01: The app correctly answered **300 million people** and exposed the
  labeled WBG PDF page 5.
- H07: The labeled WBG PDF page 11 states **$26.2 billion** for Sub-Saharan
  Africa operations. Simple RAG answered this correctly with page 11; the app
  answered **$39.9 billion** and exposed pages 53/51 instead.
- H14: NVIDIA PDF page 123 lists fiscal 2024 revenue as **$60,922 million**.
  The app said **$60.9 billion**, a rounded value from nearby prose. The
  strict table-value checker rejects it for this exact-cell question.

On H16 the agent attempted a DuckDB filter comparing a text `raw_value` to
numeric zero; DuckDB rejected that SQL and the agent continued. This is a
specific tool-selection/query-generation failure visible in the run log.

## Real local OCR and rasterization

[`benchmark_local_ocr_sample.py`](../scripts/benchmark_local_ocr_sample.py)
times real local Docling, EasyOCR Thai/English, and TableFormer processing on
selected pages. Initial Synnex observations were 88.76 s for page 40
(including startup), 60.16 s for page 140, and 38.55 s for page 250. These
three values do not establish a full-report runtime. A second run instrumented
the actual process tree: page 140 took 83.79 s and page 250 took 39.65 s;
combined parent-plus-worker peak RSS was **4,821.9 MB** (worker peak
4,738.4 MB). The first, launcher-only memory probe reported 90 MB and was
invalid; use `local_ocr_memory_sample.json` for the corrected result. Summed
RSS can count shared pages more than once. The later full Thai OCR run below
supersedes the earlier statement that full OCR completion was unmeasured.

[`benchmark_full_local_ocr.py`](../scripts/benchmark_full_local_ocr.py)
processed all **220 physical PDF pages** of the Thai [TPAC 2567 One Report](https://tpacpackaging.com/wp-content/uploads/2025/03/TPAC_One-Report_2024_TH.pdf)
with local Docling/TableFormer and Thai/English EasyOCR. The
[checkpoint and interruption records](../TestFile/step8_thai_long_ocr_v1/README.md)
show 220 pages with nonempty extracted output, zero recorded extraction errors,
and 155 detected tables. The summed per-page OCR time was **13,318.1 seconds
(3 h 42 min)**; median page time was **54.94 seconds**, and the sampled
parent-plus-worker peak was **5,068.4 MiB**. Memory was sampled every 0.5
seconds, and summed RSS can double-count shared pages. The four process phases
attempted 1, 35, 74, and 110 new pages, totaling 220; the final phase resumed
at PDF page 111 after a deliberate process stop at page 110. No checkpointed
page was attempted twice. The table count and nonempty status do **not** prove
cell accuracy. This benchmark does not index the OCR output or test complete
upload, retrieval, or answering.

[`benchmark_pdf_render.py`](../scripts/benchmark_pdf_render.py) rasterizes
every PDF page in order and samples process memory. It excludes recognition,
embedding, database, and LLM work. On the 377-page BBIKT report at 300 DPI,
all 377 pages rasterized without an exception in 16.41 seconds. Peak process
working set was 271.3 MB; sampled working set rose from 103.5 MB at page 25
to 248.2 MB at page 377. The largest bitmap was 24.9 MB. This shows that
sequential rendering completed, while the upward memory trend warrants a
full-OCR run before claiming bounded memory for production.

## Reproduction of the earlier pilot and resource tests

Run from the repository root with PostgreSQL/pgvector and local Ollama
available. Keep outputs outside a synced project folder. The public held-out
PDFs must still match the frozen hashes; a publisher changing a PDF will cause
the preparation command to stop rather than silently change the benchmark.

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8'
$corpus = Join-Path $out 'corpus'
.\.venv\Scripts\python.exe -m scripts.prepare_heldout_corpus --output-dir $corpus
.\.venv\Scripts\python.exe -m scripts.benchmark_heldout --corpus-dir $corpus --output (Join-Path $out 'heldout') --answer-limit 20
```

The first embedding pass may take several minutes. Subsequent runs reuse an
embedding cache tied to the model and chunk-text fingerprint. Each benchmark
run creates and drops its own PostgreSQL database. In normal completion the
held-out script writes `metrics.json`, predictions, answers, and timing rows.
To create a new frozen JSON bundle after a completed run, use
`python -m scripts.freeze_step8_results --input-dir $out --output-dir TestFile/step8_results_repeat`.

For the 200–500-page recovery check, provide the original report PDFs:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_long_document --pdf 'C:\path\to\AnnualSynnex2025_THA.pdf' --interrupt-at 140 --output (Join-Path $out 'long_synnex_278.json')
.\.venv\Scripts\python.exe -m scripts.benchmark_long_document --pdf 'C:\path\to\2025_105466_E_ONE_REPORT_BBIKT.pdf' --interrupt-at 190 --output (Join-Path $out 'long_bbikt_377.json')
.\.venv\Scripts\python.exe -m scripts.benchmark_process_restart --pdf 'C:\path\to\AnnualSynnex2025_THA.pdf' --interrupt-at 140 --output (Join-Path $out 'process_restart_synnex_278.json')
.\.venv\Scripts\python.exe -m scripts.benchmark_pdf_render --pdf 'C:\path\to\2025_105466_E_ONE_REPORT_BBIKT.pdf' --dpi 300 --output (Join-Path $out 'render_bbikt_377.json')
```

For a real local OCR page sample, use the predownloaded models and Python
environment from [Step 4](ocr-quality.md). This command is intentionally
separate from the fast checkpoint experiment:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_local_ocr_sample --pdf 'C:\path\to\AnnualSynnex2025_THA.pdf' --pages 40 140 250 --output (Join-Path $out 'local_ocr_sample.json') --private-dir (Join-Path $out 'private') --local-python 'C:\path\to\local-ocr\.venv\Scripts\python.exe' --models 'C:\path\to\local-ocr\models' --easyocr-cache 'C:\path\to\local-ocr\easyocr_cache'
```

## Limits to state in the thesis

- The two-report, 20-question held-out sample is too small for a general
  accuracy claim. It has no confidence interval and was labeled by one person.
- Each question has one required evidence page. This pilot does not test
  multi-page evidence gathering.
- Selectable PDF text bypasses OCR. The held-out comparison does not validate
  the production Typhoon/Gemini OCR path or local OCR on these reports.
- A separate process-exit test covers application startup resume. The Thai
  220-page OCR run covers engine throughput, sampled memory, and checkpoint
  continuation after a process stop. Neither proves power-loss recovery,
  concurrent uploads, or full-report upload-to-answer operation.
- Two chart-labeled facts are included, but text-backed indexing does not
  establish general chart interpretation. No unanswerable question tests safe
  abstention.
- The untouched final answer arm uses local offline Gemma. The later Gemini
  supplement measures the normal answer provider on the same selectable-text
  corpus, but still bypasses Typhoon/Gemini OCR and is post-hoc.
- Hardware usage reported for a Python process excludes separate PostgreSQL
  and Ollama processes. Do not quote it as total computer memory.
