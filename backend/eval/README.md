# Independent evaluation layers

`TestFile/reference_pages_v1.json` contains original-PDF labels for 34 facts on
32 selected pages. It is a development diagnostic set, not a held-out thesis
test. The same source reports were available during development, and each label
has one visual reviewer. Its `source_pdf_page` and `excerpt_page` fields are
**1-based physical PDF pages**.

Run each layer separately from the repository root:

```powershell
./.venv/Scripts/python.exe -m backend.eval.score_layers ocr-cache --out backend/eval/results/ocr_layers.json
./.venv/Scripts/python.exe -m backend.eval.score_layers search --predictions search_predictions.jsonl --k 5 --page-space excerpt --out backend/eval/results/search_layers.json
./.venv/Scripts/python.exe -m backend.eval.score_layers answers --predictions answer_predictions.jsonl --page-space excerpt --out backend/eval/results/answer_layers.json
```

`ocr-cache` reads `TestFile/ocr_cell_gold.json` and the existing Typhoon cache.
It scores exact row and column cells; OCR failures count in the denominator.
The four chart facts are reported as unresolved, never counted as correct.
This cache has 16 scored cells, which is narrower than the 34-fact reference.

`search` reads ranked retrieval results for every reference question. Each JSONL
line has an `id` from the reference and a ranked `results` array. Every result
needs a document identifier (`document`, or `filename` matching the reference)
and an unambiguous physical PDF page. For example:

```json
{"id":"RP01","results":[{"filename":"2025_105466_E_ONE_REPORT_BBIKT_selected50.pdf","page":5},{"filename":"2025_105466_E_ONE_REPORT_BBIKT_selected50.pdf","page":6}]}
```

Pass `--page-space excerpt` for excerpt PDF results or `--page-space source` for
original PDFs. A result can instead supply `excerpt_page` or `source_pdf_page`
directly. The scorer reports Hit@k, required-page Recall@k, nDCG@k, missing
predictions, and results whose document/page cannot be located. These are
**page-level evidence metrics**: a relevant page can contain more than one
passage, and passage relevance still needs human inspection. The retrieval
function now returns chunk `page` metadata when available; it does not infer a
page from chunk order.

`answers` reads an `answer` and a `citations` array for every `id`:

```json
{"id":"RP01","answer":"254.29 ล้านบาท","citations":[{"filename":"2025_105466_E_ONE_REPORT_BBIKT_selected50.pdf","page":5}]}
```

Fact correctness and citation correctness are independent. Numeric labels
check sign, magnitude, explicit unit, and any stated year. A money scale
conversion is accepted only when both units are explicit. A missing unit is
sent to `needs_review`; a conflicting unit is incorrect. Short text is
certified automatically only for an exact normalized match. Paraphrases and
more complex prose go to `needs_review` rather than becoming false failures or
unverified passes. Report `fact_accuracy_determined` together with the review
count and strict lower bound. Citation metrics require the labeled document
and physical page. The reference has no unanswerable questions, so unsupported
answer abstention stays `null` until those labels are added.

For an adjudicated reference, `evidence_options` may list alternative
**complete sets** of original PDF pages. One complete option is enough for
`citation_all_required_rate`; a partial option only contributes partial page
recall. Numeric labels can declare `answer_components.rounding_decimals` when
the original report displays a rounded value. The scorer then converts an
explicit answer unit to the reference unit and rounds half up to that many
decimal places. The default remains exact numeric matching. The Thai final
v2 overlay and its separate rescore demonstrate this without changing the
frozen v1 result files; see `TestFile/step8_thai_rescore_v2_provisional/`.

The legacy `golden_auto.json` runner remains separate. Its source labels were
often generated from extracted content and should not be used as independent
OCR ground truth. Its numeric grader now uses explicit units and years without
absolute-value or arbitrary scale matching. If a semantic judge is unavailable,
the answer is marked unscored, not accepted by keyword overlap. Empty answers
remain scored failures. Use `regrade.py` to update saved deterministic verdicts
without rerunning the agent; saved semantic judgments are retained, while old
low-confidence keyword-fallback verdicts become unscored.
