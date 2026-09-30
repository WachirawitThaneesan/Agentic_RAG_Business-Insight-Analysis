# Branch integration audit — 28 September 2026

## Scope and provenance

Source: `eval-accuracy-bge-m3` at `e92030e8b86a7d93533fe195e1a22a2e94f2bb93`.
Current branch: `auto1`, HEAD `5883362`, with extensive prior uncommitted work.
Common checkpoint: `aa1ae14`. The two source commits after that checkpoint are
`c0a563b` (three runtime fixes) and `e92030e` (three category golden files).
The current checkout was not switched, reset, cherry-picked wholesale, committed,
or pushed. Source was read from a separate bare reference repository.

## What already existed

The current branch already inherited bge-m3 embeddings, lexical/dense retrieval
and RRF, warehouse-derived table chunks, provider selection, exact row/table-section
selection and earlier fallback behavior. Treating those as new imports would
misrepresent the history. Current work also adds stronger scoring, page/cell
provenance, offline controls, Thai normalization, issuer scoping and tool budgets.

## Runtime changes ported and adapted

1. `tools._focus_excerpt`: score multiple term occurrences and long verbatim
   question spans. Preserve original text via a normalized-to-original offset
   mapping for Thai glyph artifacts, keep context before the match, deduplicate
   terms and bound anchor occurrences. An initial direct port failed an existing
   Thai regression; it was repaired before acceptance.
2. `agent`: one vector sweep before accepting a missing-data draft, including
   the current forced-tool short path. Require the vector index to be available,
   respect two top-level calls, and count failed attempts. Narrow refusal markers
   so a fact such as “no fraud was found” is not interpreted as missing data.
3. `answer_verifier._focus_violation`: deterministic single-value focus check,
   integrated with the final grounding guard and one bounded draft retry in the
   short answer path. Preserve legitimate comparisons, equivalent BE/CE years,
   signed percentages and comma-separated counts. Ambiguous evidence results in
   abstention; the upstream instruction to choose despite uncertainty was not kept.

No labels, frozen scores, extraction providers or embedding dimensions were
replaced. Existing records still need re-ingestion to recover missing metadata.
The verifier's older permissive numeric precheck remains only a preliminary
filter; the current strict `_grounded_answer` and evaluator are retained.

## Golden sets and score interpretation

`golden_auto_large.json`: 501 items: SQL 150, semantic 143, compare 100, EAV 78,
superlative 28, graph 2. Excluding graph gives the screenshot denominator 499.
New subsets are SQL 150, semantic 143 and combined 293. Counts and hashes are
recorded in `source_audit.json`; downloaded copies remain separate from current labels.

The user-supplied screenshot reports 474/499 (95.0%), including semantic
128/143 (89.5%), with a historical total of 458/499. Raw latest predictions were
not present in the tracked source tree or the local evaluation result directory.
This integration did not reproduce or independently rescore those answer outcomes.

Source `grade.py` still allows absolute-value equivalence and arbitrary
1e3/1e6 scaling without proving units. Its generated references originate in the
same warehouse/vector store under test. These are development/regression results,
not independent original-PDF OCR accuracy or new-report thesis accuracy.
Keep all saved scores unchanged and publish any stricter rescore separately.

## Verification

Command from the project root:
`.venv/Scripts/python.exe -m pytest backend/services/tests backend/eval/tests -q`

Final result: **160 passed, 5 skipped**. Six new tests cover late excerpts,
legitimate comparisons/equivalent years, refusal wording, SQL near-miss rescue,
unavailable vector search, and bounded ambiguous-answer correction. Existing tests
cover sign/scale/unit rejection, exact row evidence, Thai artifacts and source pages.
No cloud calls, full 499-question answer rerun or live call-count measurement were
made for this integration. The frozen 15/20 and diagnostic 20/20 retrieval files
are prior measurements and were not regenerated here.

## Presentation evidence

Read current-chat available finals and the complete available final/user-message
history of “Review project architecture and read”. Read the public Notion project
and related thesis, candidate, OCR diagnostic, baseline, commit and Fix pages.
Older Qwen, synchronous-upload and Celery descriptions were treated as historical;
current code and the user's Gemini/Typhoon instructions govern the presentation.
The presentation distinguishes old answer scores, tuned retrieval, OCR throughput,
privacy smoke tests, and software test results. Future Work includes stricter
rescoring, independent reference review, real ingestion-to-answer measurement,
new Thai held-out reports and resource/call-count experiments.
