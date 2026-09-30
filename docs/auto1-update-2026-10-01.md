# auto1 progress update — 1 October 2026

This checkpoint brings together document processing, evaluation repairs, Thai
retrieval improvements, private local processing, public PDF discovery, and
saved experiments. The code changes accumulated after commit `5883362`.
The checks below were rerun on 1 October 2026 (Asia/Bangkok). Historical
experiments remain dated and versioned separately from this software check.

## 1. Shared PDF ingestion and recovery

Uploads and downloaded PDFs now register physical PDF pages and use the same
saved-file job queue. The API owns the queue and DuckDB writes; interrupted
jobs can resume from PostgreSQL page checkpoints when the API restarts.
The old Celery PDF-processing path is retired; Celery still handles scraping
and optional graph builds.

Failed and partially processed pages retain their status, failing stage, and
raw OCR for inspection. Raw OCR is saved before embedding and table indexing.
The document viewer uses a 25-page status window and loads one selected page,
including its image, OCR, parsed tables, stored rows, and quality reasons.
This keeps long-document inspection bounded.

Key files: `backend/routes/documents.py`, `backend/services/document_jobs.py`,
`backend/models.py`, `backend/main.py`, `backend/tasks.py`,
`frontend/components/documents.js`.

## 2. Typhoon prose and Gemini table extraction

The online environment template selects Gemini 2.5 Flash for generation and
tool selection, Typhoon for prose OCR, and Gemini for table extraction.
The separate local mode selects Docling/TableFormer and Thai/English EasyOCR.
Embeddings still use Ollama's configured embedding model; changing generation
providers does not replace the vector index.

The rendering path handles detected two-up page gutters and sideways text
orientation. Transform metadata stays attached to the physical PDF page.
Table IDs include page and table identity, preventing similarly named tables
on different pages from overwriting each other.

Stored table evidence carries its row label, column/year, unit, value, page,
document/table identity, extraction provider, and internal quality status.
Rejected table data and raw OCR inspection artifacts are excluded from answer
retrieval and structured warehouse search. Passing internal checks does not
certify visual accuracy against the original PDF. Existing records missing
this metadata may require re-ingestion.

Key files: `backend/services/ocr.py`, `gemini_tables.py`, `table_utils.py`,
`duckdb_warehouse.py`, `pdf_layout.py`; see [OCR quality](ocr-quality.md).

## 3. Thai evidence retrieval

Search normalizes Thai font artifacts while preserving original evidence text.
Explicit company names and supported aliases scope candidates to the issuer;
unknown companies remain eligible across documents. BM25 ranks lexical
candidates, while local embeddings supply semantic candidates. Numeric
questions prioritize lexical evidence; qualitative questions use reciprocal
rank fusion. Results are deduplicated by document and physical page.

A strict first-mentioned-year filter was tested but not deployed: reports
contain comparison years, so a hard filter discarded useful evidence.
Page-aware region/table-row experiments are saved separately; they did not
justify replacing the chosen retrieval path.

The previously published SCBX/Thai Union development comparison remains in
[its original bundle](../TestFile/step2_thai_retrieval_dev_v1/README.md).
That corpus has 568 pages and differs from CP Axtra/EGCO below.

### CP Axtra / EGCO saved comparison

The corpus contains 832 physical pages, 1,225 selectable-text chunks and
20 Thai questions. Each metric uses document plus physical PDF page evidence.
A Page Hit@5 is a question whose accepted supporting page appears in the
first five results.

| Method | Initial v1.1 | Tuned v2 | Tuned v3 |
| --- | ---: | ---: | ---: |
| BM25 | 14/20 | 14/20 | 14/20 |
| Dense bge-m3 | 10/20 | 10/20 | 10/20 |
| App retrieval | 15/20 | 19/20 | 20/20 |

The five initial app misses were U02, U03, U06, U07 and U18. The issuer-aware
ranking, Thai term matching, and distinct-page selection address these
diagnostic failures. U02 illustrates evidence found by dense retrieval but
lost in app ranking; U03/U18 initially placed the required page below rank 5.

The [initial bundle](../TestFile/step9_thai_unseen_v1_1/README.md) preserves the
pre-prediction reference, method lock, rankings, and audit. Its original README
describes the state at that historical run; these questions were later inspected.
[v2 metrics](../TestFile/step9_thai_retrieval_dev_v2/metrics.json) and
[v3 metrics](../TestFile/step9_thai_retrieval_dev_v3/metrics.json) are new
retrieval measurements on the same exposed questions. Copied artifact hashes
were checked against the saved originals on 1 October.

These reports are now a development set. The 20/20 result does not establish
accuracy on new reports, OCR/table correctness, or answer generation. CP Axtra
has 145 pages without selectable text; those pages' OCR quality was not tested
by this retrieval experiment. Independent human label sign-off is pending.

Key files: `backend/services/rag.py`, `retrieval_rank.py`, `tools.py`.

## 4. Branch integration and agent safeguards

The source branch `eval-accuracy-bge-m3` was inspected at
`e92030e8b86a7d93533fe195e1a22a2e94f2bb93`. Current code already inherited
bge-m3-related retrieval work and earlier table-section selection.
Three later runtime fixes were selectively adapted:

1. Excerpts score multiple term positions and question phrases, retain context
   before the match, map normalized Thai offsets back to original text, and
   bound anchor occurrences.
2. One vector rescue search is allowed before accepting a missing-data answer,
   provided the vector tool is available and the call budget permits it.
3. A deterministic focus check detects multiple proposed values when the user
   asks for a single value, while preserving legitimate comparisons, equivalent
   Buddhist/Common Era years, signed percentages, and grouped counts.

Tools are offered only when their data sources are ready. Failed tool attempts
consume budget. Top-level tool calls are bounded to two, with separate bounds
on ReAct and multi-hop processing; this is not a measurement of total LLM calls.
Numeric answers require located supporting evidence, and exact SQL row context
takes precedence over similarly named measures. Ambiguous evidence can result
in abstention. These checks reduce specific failures but do not prove universal
answer correctness.

See [the integration audit](branch-upgrade-2026-09-28.md) and
`backend/services/tests/test_branch_upgrade.py`.

### Historical 499-question score

The supplied source-branch screenshot reports 474/499 (95.0%) overall, with
128/143 (89.5%) in the semantic category. The 499 denominator excludes two
graph smoke tests. Raw latest predictions were unavailable for independent
reproduction. The old grader admitted sign/scale matches without explicit
unit justification; generated references also came from the extracted store.

This checkpoint does not claim a new 95% result after integration. The full
499-question answer experiment has not been rerun under the stricter grader.

## 5. Evaluation repairs and frozen results

Evaluation now separates OCR/table cells, page retrieval, and final answer
facts/citations. Numeric grading checks sign, magnitude, explicit unit/scale
and stated year. Missing units or uncertified paraphrases can require review.
An unavailable semantic judge does not turn keyword overlap into a pass.

The Gen 2 false negative was repaired by distinguishing a segment label from
a competing answer value. Alternate page sets and declared half-up rounding
rules are supported. Original predictions/scores and the old scorer snapshot
are preserved; v2 and v3 rescoring is published separately. AI visual review
is identified as AI review, not independent human certification.

The initial diagnostic reference has 32 selected pages and 34 facts. The
16-cell OCR test is narrower than the full reference; four chart facts remain
unresolved. Earlier poor answer results are retained in
[the thesis evaluation record](thesis-evaluation.md), including the historical
140-call Gemini run. New call-budget code has not yet been measured with a
fresh end-to-end cloud benchmark.

Key files: `backend/eval/numeric.py`, `score_layers.py`, `grade.py`,
`regrade.py`, `run_accuracy.py`, and `TestFile/`.

## 6. Private local mode

`OFFLINE_MODE=true` selects local Docling OCR and Ollama generation, validates
localhost dependencies, disables cloud/web/graph routes and cloud fallbacks,
and binds the app to loopback. Private files and the warehouse use a directory
outside OneDrive. Prefetched model paths are explicit, and frontend remote
resource dependencies were removed. Network guards block outbound external
connections in the application and OCR worker processes.

| Saved local experiment | Result | Interpretation |
| --- | --- | --- |
| Docling/EasyOCR development table cells | 10/16 correct | Small labeled sample; local table accuracy needs improvement |
| Cached Typhoon/Gemini comparison | 16/16 correct | Same small labeled sample; no population accuracy claim |
| TPAC 2567 full OCR | 220/220 nonempty pages; 155 tables detected | Engine/checkpoint completion, not visual accuracy |
| Interrupt/resume | Stop after page 110, resume page 111 | Recovery was observed |
| Summed TPAC page OCR time | 13,318.1 s, about 3 h 42 min | Excludes upload/index/search/answer workflow |
| Maximum sampled parent + worker RSS | 5,068.4 MiB | Sampling may double-count shared memory |
| Private API smoke test | 1 synthetic page; 62.87 s; page 1 cited | Process-level external network block, not OS-wide isolation |

The [220-page checkpoint](../TestFile/step8_thai_long_ocr_v1/README.md)
includes per-page timings, statuses and interruptions.
A complete 220-page upload-to-answer offline test remains unmeasured.
See [offline setup and limits](offline-mode.md).

## 7. Public Thai PDF discovery

The bounded crawler follows links/sitemaps, checks robots rules, verifies PDF
bytes, removes duplicates by hash, and preserves download/discovery URLs and
timestamps. Browser rendering is a fallback when HTTP discovery is insufficient.
Downloaded PDFs then use the shared ingestion queue.

The saved final Thai discovery run found the expected report on 17/20 official
websites. Thai SEC and IRPC returned HTTP 403; Bangkok Bank was blocked by the
robots handling. These are explicit failed/blocked outcomes, not bypass attempts.
PDF probes did not establish complete ingestion or table accuracy.
See [the frozen run](../TestFile/pdf_discovery_thai_result_v7.md) and
[discovery design](pdf-discovery.md).

## 8. Citation UI and demo status

Chat sources now include document/page metadata and available table cell
context. A located citation opens the corresponding rendered PDF page image
at `/api/documents/{id}/pages/{page}/image`; missing page attribution is shown
as unresolved. SQL aggregates and legacy graph sources can remain unresolved.

The presentation's CP Axtra example cites about 2,800 Last-mile vehicles on
physical PDF page 18. It is a reference illustration. A fresh browser demo
showing that answer and the citation click has not been verified in this update;
it must not be presented as a newly observed live answer. See the
[demo runbook](thesis-demo.md).

## 9. Verification on 1 October 2026

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/services/tests backend/eval/tests -q
```

Result: **160 passed, 5 skipped, 1 warning in 6.94 seconds**. The warning is
Pydantic's deprecated class-based configuration. These are software checks;
they do not certify the accuracy of unfamiliar financial reports.

Saved result copies were hash-verified. Publication checks inspect changed
and newly added files for private keys, recognizable API tokens and forbidden
runtime artifacts. Local environment files, credentials, databases, model
caches and downloaded PDFs are excluded from new additions.

The changed/new-file scan reported no matching private-key/API-token patterns
or forbidden runtime artifacts. This is a targeted publication check, not a
guarantee against every possible secret format. Node syntax checks passed for
the changed chat, document and main frontend JavaScript files. Git diff checks
passed with Windows CRLF treated as end-of-line rather than trailing whitespace.

Remote verification using Git's OpenSSL TLS backend confirmed that
`origin/auto1` still points to
`5883362f56c2d28581ce975405ffca00fddc8bf5` at the time of the initial check.
The OpenSSL backend was selected for that invocation only, after Windows
Schannel could not obtain credentials inside the sandbox; certificate checks
were retained.

The Windows sandbox failure was resolved after the user backed up a malformed
`deny_read_acl_state.json`; a sandboxed command then ran successfully.
Git metadata writes remain subject to the task's sandbox permissions.

The initial publication attempt was blocked: fetch (creating `.git/FETCH_HEAD`)
and staging (creating `.git/index.lock`) were denied even after a folder-level
permission request. The user staged the changes in an external PowerShell
session; committing initially failed because no Git author was configured.

After sandbox escalation approvals became available, the approved Git command
created integration commit `3ae9846` with 216 changed files. The author is
`66070026-Jakkrapat <66070026@kmitl.ac.th>`, supplied by the user and applied
only to this commit invocation. The publication workflow uses a normal push
to `origin/auto1` and checks the remote branch hash against local HEAD.
This replaces the earlier blocked status; runtime sandbox protections remain.

## 10. Remaining work, in order

1. Obtain independent human review of original-PDF labels and acceptable pages.
2. Verify the real localhost question/answer/citation interaction and capture it.
3. Rerun the integrated online path with strict scoring, model-call counts,
   processing time and resource measurements.
4. Measure actual table relationships after Typhoon/Gemini ingestion and
   re-ingest legacy records lacking provenance.
5. Improve local complex tables/charts and expand private upload-to-answer
   tests on real Thai reports.
6. Freeze code/labels, then evaluate different Thai issuers with BM25, dense,
   simple RAG and the app under the same evidence rules.
7. Finalize reproducible setup, limitations, presentation/demo and report review.

Future validation is recorded separately from the completed implementation.
No numerical thesis-readiness estimate is treated as measured accuracy.
