# Provisional post-run rescore of the Thai final predictions

This bundle uses the **same saved predictions**, questions, models, and PDFs
as the 2026-09-27 frozen benchmark. It makes no model or network call. The
frozen v1 scores remain unchanged. The independent human second review in
[`heldout_thai_final_second_review_v2.md`](../heldout_thai_final_second_review_v2.md)
is **pending**, so these values are provisional and should not replace the
frozen scores in a thesis results table without that review.

A later [conservative AI PDF audit](../heldout_thai_final_ai_pdf_audit_v1.md)
found that the proposed SCBX page 111 for TF06 corroborates the number but
does not explicitly support the question's parent-attributable qualifier.
The [separate v3 rescore](../step8_thai_rescore_v3_ai_review/README.md)
excludes that page. This v2 bundle is retained unchanged as a historical
provisional interpretation.

The [adjudication overlay](../heldout_thai_final_adjudication_v2.json) adds
visually inspected alternate physical PDF pages for TF06 (SCBX p. 111), TF08
(SCBX p. 252), TF09 (SCBX p. 252), and TF14 (Thai Union p. 194). It declares
one-decimal, half-up rounding **only for TF14**: 4,984,894 thousand baht from
the consolidated financial note is 4.984894 billion baht, displayed as
5.0 billion baht in the infographic. The scorer also ignores the business
segment identifier `Gen 2` as an answer number while retaining sign, year,
unit, scale, and competing-value checks.

| Search Hit@5 | Frozen v1 | Provisional v2 |
| --- | ---: | ---: |
| Thai BM25 | 5/20 | 8/20 |
| Dense `bge-m3` | 3/20 | 6/20 |
| App hybrid | 3/20 | 6/20 |

| Answer arm, strict correct | Frozen v1 | Provisional v2 | v2 correct with accepted page |
| --- | ---: | ---: | ---: |
| BM25 + local Gemma | 0/20 | 1/20 | 1/20 |
| App offline Gemma | 1/20 | 1/20 | 1/20 |
| BM25 + Gemini | 6/20 | 7/20 | 7/20 |
| App Gemini | 2/20 | 4/20 | 4/20 |

The app Gemini changes are TF10 (`Gen 2` parser fix) and TF14 (declared
rounding); TF09 gains an accepted alternate citation without changing its
already correct fact verdict. TF06 similarly gains an accepted alternate
citation for the offline app. TF08 gives BM25 + Gemini an accepted alternate
page. The full `metrics.json` records every question-level change, the source
file hashes, and the new scorer hashes. Changed scores reflect **post-run
label/scorer adjudication**, not a model improvement. Even this provisional
reading remains poor for reliable financial question answering.

Reproduce from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.rescore_heldout_thai_v2
```

No OCR or document ingestion is evaluated by this rescore. After independent
human review, publish a new explicitly labeled adjudication version if any
candidate page or rule is rejected; leave both v1 and this provisional v2
bundle intact.
