# Page context and issuer scope diagnostic — 2026-10-02

This package preserves both the regression during development and its repair. These reports have been inspected and used for tuning. They are **diagnostic**, not a new held-out thesis result. `run_context.json` takes precedence over inherited pilot wording in copied manifests/metrics saying “no tuning”. Raw copied files are unchanged.

## Changes

- Recognize three-character Latin issuer tokens and use alphanumeric boundaries, avoiding a short issuer matching the prefix of another.
- Expand ranked pages with nearby indexed, quality-gated chunks; retain the existing raw/quarantined-source exclusions.
- Filter to an explicitly requested Thai section when that heading occurs among retrieved pages.
- Carry page context through tool results, source extraction and final answer context. Bound each page to 12,000 characters and final context to 16,000.
- Ask the answer model to preserve company, section, year, currency and chart relationships; abstain when relations cannot be supported.

## Same-label diagnostic results

| Run | Fact + required page present | App successful model calls / attempts | Time | Scope |
|---|---:|---:|---:|---|
| Original frozen pilot | 10/16 | 16 / 24 | 149 s app arm | Before tuning, earlier label version |
| Separate rescore v2 | 12/16 | 0 new | no new inference | Same original answers, corrected labels/scorer; unchanged archive |
| This repair v1 | 7/16 | see raw calls | see raw timings | Exposed remaining truncation between tool/source/answer |
| This repair v2 | 15/16 | 16 / 22 | 162.87 s app arm | Context propagation repaired |
| BM25 + Gemini, same v2 run | 11/16 | 16 / 16 | see timings | Same labels/corpus |
| Legacy production DB rerun | 14/15 | 22 / 27 | 158.10 s runner | Same score as prior v7 (58.4 s); retry variability |

Retrieval page Hit@5: BM25 13/16, dense 10/16, app hybrid 16/16. Finding a page is not answer correctness. v2 whole-run time 305.98 s includes preparation and both arms using cached corpus embeddings. Runner peak RSS 456.45 MiB; sampled Ollama process 117.14 MiB is **not** total model RAM/VRAM. Legacy runner peak RSS 269.44 MiB.

## Remaining failures and validity limits

- **F10:** 78,824 million THB is present in the answer, but the additional 2,227 million USD is not permitted by the locked reference. It remains a fail; no post-hoc label relaxation.
- **F05:** answer prose names page 6 although reference physical page 5 is included in sources. The current source-list scorer does not catch this claim-level mismatch. The 15/16 score must not be described as complete citation correctness.
- **L11:** extracted 4,558,818 vs reference 4,558,618 million THB remains unresolved; do not patch the answer with a gold value.
- Only 16 questions, concentrated on 3 physical pages, with AI visual labels; human review pending.
- Native-text corpus does not test Typhoon/Gemini table extraction. Real offline OCR remains limited (separate 5-page test: 0/1 answer).
- API retries affect duration. No general speed or accuracy claim follows from these small runs.

## Verification and reproduction

206 tests passed, 5 live tests skipped. `regression.xml` records the result. Code hashes in each run identify runtime inputs. Original reports/embedding cache are referenced by the locked manifest and are not duplicated here.

```powershell
.venv/Scripts/python.exe -m pytest backend/services/tests backend/eval/tests -q
.venv/Scripts/python.exe -m scripts.benchmark_heldout_gemini --manifest TestFile/runtime_repair_2026-10-01_v1/fresh_rescore_v2/reference_v2.json --corpus-dir <frozen-corpus-directory> --embedding-cache <frozen-corpus-directory>/embeddings.npz --output <new-empty-output-directory> --answer-limit 16 --measure
.venv/Scripts/python.exe -m scripts.benchmark_live_diagnostic --manifest TestFile/postmerge_2026-10-01_v1/legacy_reference_reviewed_v3.json --output <new-empty-output-directory>
```

Rerunning invokes the configured Gemini provider and requires the local PostgreSQL/Ollama services. Keep old results unchanged and choose a new output directory.
