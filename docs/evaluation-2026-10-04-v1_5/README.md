# Comprehensive RAG evaluation v1.5

Experiment round: 4 October 2026. Publication finalized: 5 October 2026, Asia/Bangkok.
Repository branch: auto1. Application base before this evaluation work: 5060072.

## What was actually measured

- 500 Thai diagnostic retrieval questions on four known reports, 1600 PDF pages, 3194 native-text chunks. Questions have 124 labeled pages. This is not an unseen-report test.
- 50 sampled questions through the real app agent, 16 numeric and 8 unavailable-year controls through app and BM25, plus 8 multipage questions through both methods. This is 82 distinct fresh questions and 114 generated responses, not 500 generated answers.
- 55 historical responses retained, making 169 response records. Claim audit available for 149: 20 old CP/EGCO BM25 responses have no captured/saved context and remain N/A.
- Independent of answer/ranking results, a second same-family AI reference review flagged 119/500 labels. Separate 381-label sensitivity scores are published without changing the original 500 labels.
- 229 software tests passed, 5 live tests skipped. Offline replay reproduces the saved summary exactly. Neither fact certifies document accuracy.

Read `evaluation_report_th.docx` for the concise illustrated report and `evaluation_report_th.md` for the detailed methods. `summary.json` and `metric_summary.csv` are the machine-readable scores. Per-question CSVs preserve denominators and N/A values. CSV is UTF-8 with BOM.

## Definitions and limits

Custom metrics implement RAG/BEIR definitions; these are **not official Ragas execution scores**. Numeric matching checks signed value, declared unit/scale, year and physical PDF citations. Claim judgments use Gemini 2.5 Flash, temperature zero, thinking budget zero. The answer model and judges share a model family; human calibration and label certification are pending.

`faithfulness_ai_judged`, `factual_f1_focused_ai` and `context_recall_focused_ai` expose provisional AI entailment decisions. Corresponding quote-checked metrics lower a supported decision to insufficient when its claimed evidence span cannot be verified. This reflects both RAG errors and judge quote-copy errors; it is not a direct hallucination rate. Original spans/offsets, warnings and original AI verdicts are retained.

Answer coverage and context coverage are judged in separate calls. The answer judge cannot see retrieval context; the context judge cannot see generated answers. Short answers inherit unambiguous scope from the question; they need not repeat company/measure/year. Explicit wrong scope still fails. Response relevancy is judged without retrieval context. Refusal without claims on answerable questions receives relevance zero under a disclosed rule. Unavailable-year numeric controls require a refusal without alternative noncalendar answer quantities; calendar-year explanations are allowed.

Sanity controls: faithfulness direction 9/9 applicable cases; answer coverage 10/10; context coverage 10/10; response relevance after the abstention rule 9/10. These synthetic examples were used to develop the scorer, so they are not independent validation. The remaining relevance disagreement is documented in `calibration/score_report.json`.

Precision@5 on a question with one labeled page has a maximum of 0.2; it is not answer accuracy. Hybrid@10 is N/A because only five results were saved. Page bootstrap intervals describe variation within the four reports, not uncertainty on unseen reports. The original 499-question branch benchmark has **not** been regenerated under these rules; this new 500-question bank is a different diagnostic set.

This run reads the selectable PDF text layer. It does not re-run Typhoon/Gemini OCR on 500 questions. Historical OCR/table/offline results are separate sections. Full-page CER/WER, complete chart evaluation and final unseen OCR-to-answer tests remain unmeasured.

## Raw data map

The full workspace experiment root is the parent of this directory. Versioned failures and intermediate scores are retained.

| Folder | Contents |
| --- | --- |
| bank500_v2 | Locked 500 references, raw drafting outputs, mechanical PDF-span audit |
| bank500_run | 500 retrieval records, 50 answers, exact generation traces, timing, SDK calls, resources |
| live_ptt24 | Paired app/BM25 responses for 16 numeric and 8 unavailable-year questions |
| multi8_run | Paired app/BM25 responses and rankings for multipage questions |
| reference_quality500 | Blind-to-results AI label flags; no label edits |
| final_claim_audit_v1_3 | Preserved raw joint claim judgments and input payloads |
| final_response_audit | Focused response relevancy judgments |
| focused_answer_coverage_v2 | Final response-only required-fact coverage judgments |
| focused_context_coverage | Final context-only required-fact coverage judgments |
| consistent_audit_v1_5 | Final offline regrade with all per-question claim decisions |
| calibration | Synthetic controls, raw judgments and disagreement report |
| offline_replay_verified | Summary recomputed without model calls and compared exactly |

The repository saves final reports under `docs/evaluation-2026-10-04-v1_5` and a complete compressed audit snapshot under `TestFile/comprehensive_2026-10-04_v1_5`. The snapshot contains JSON/CSV/Markdown/DOCX/figure/test logs, including intermediate/failing runs. Source PDFs, model weights, embedding NPZ caches and DuckDB files are not in the compressed snapshot. Source download URLs and expected SHA256 hashes are in `bank_sources.json` and the reference manifests. Retrieve exactly those PDFs for a new inference experiment; a changed PDF must be treated as a new input version.

## Reproduce saved metric arithmetic without a model

Run in the repository root after extracting `complete_evaluation_artifacts.zip` into a new directory. The archive exposes its original experiment folder names.

```powershell
$env:PYTHONUTF8 = '1'
$evalData = 'C:\path\to\extracted-evaluation'
.venv\Scripts\python.exe -m scripts.replay_saved_evaluation `
  --audit "$evalData\consistent_audit_v1_5" `
  --expected-summary "$evalData\published_v1_5\summary.json" `
  --output "$evalData\my_new_offline_replay"
```

This checks metric arithmetic using frozen judgments; it does not rejudge claims or regenerate answers. The output directory must be new. For an actual new run, use the scripts below with new output directories and remap input paths in configuration files. Gemini calls require the configured Vertex environment; offline replay does not.

```text
python -m scripts.benchmark_large_retrieval --reference REFERENCE500 --sources SOURCES --output NEW_RUN --answer-limit 50
python -m scripts.benchmark_heldout_gemini --help
python -m scripts.evaluate_comprehensive --config CONFIG --output NEW_CLAIM_AUDIT --judge --judge-output-tokens 14000
python -m scripts.evaluate_response_relevance --audit NEW_CLAIM_AUDIT --output NEW_RELEVANCE
python -m scripts.evaluate_claim_coverage --audit NEW_CLAIM_AUDIT --mode answer --batch-size 10 --output NEW_ANSWER_COVERAGE
python -m scripts.evaluate_claim_coverage --audit NEW_CLAIM_AUDIT --mode context --batch-size 5 --output NEW_CONTEXT_COVERAGE
python -m scripts.apply_focused_audits --config CONFIG --claim-audit NEW_CLAIM_AUDIT --relevance-audit NEW_RELEVANCE --answer-coverage NEW_ANSWER_COVERAGE --context-coverage NEW_CONTEXT_COVERAGE --output NEW_CONSISTENT_AUDIT
python -m scripts.consolidate_comprehensive --root EXPERIMENT_ROOT --audit NEW_CONSISTENT_AUDIT --output NEW_PUBLICATION
```

The consolidation command expects this round's named cohorts and historical operational data; it is a publication helper for this experiment, not a universal benchmark template. For new documents, adjust the cohort definitions and dataset-specific narrative. Cloud outputs may differ on rerun even at temperature zero. Lock report-level held-out splits before tuning; the four reports here are diagnostic.

## Runtime and cost

The 500 retrieval plus 50 answer run used 1042.81 seconds. App responses had median 2.90 seconds and p95 5.51 seconds, with 50 successful model calls from 51 SDK attempts. Query embedding vectors were prepared in advance, so retrieval timing does not include fresh query embedding for every query.

RSS records runner/children and Ollama separately, excluding PostgreSQL in Docker and whole-system RAM. GPU values cover the entire device including other apps; no cloud RAM/GPU is measurable locally. Some judging runs overlapped. CPU cumulative counters remain in raw resource samples. The first live24 run did not measure GPU and reports N/A.

`model_usage_cost_estimate.csv` counts recorded SDK attempts, including failed/interrupted experiments; reused judgments are not charged again in the table. Token price estimate uses standard Gemini 2.5 Flash input US$0.30 and output/thinking US$2.50 per million, verified 4 October 2026. It is not an actual bill: cache discounts were not recorded and interrupted in-flight usage may be missing. Generation, drafting and evaluation are separate experiments.

## Files frozen and remaining review

Input PDF/reference/embedding hashes were checked before retrieval. Large-run inference code hashes were recorded after the run and are explicitly marked post-run; do not call this preregistration. Later regrades preserve raw judgments and record lineage. `.gitattributes` prevents newline conversion in saved snapshots.

Before a thesis conclusion, independently review the 119 flagged labels and alternate pages, measure judge agreement on a human-reviewed sample, investigate correct-label retrieval misses and multipage failures, then expand full answers and test new Thai reports through actual OCR. Scores here do not establish a project-wide 95% accuracy claim.
