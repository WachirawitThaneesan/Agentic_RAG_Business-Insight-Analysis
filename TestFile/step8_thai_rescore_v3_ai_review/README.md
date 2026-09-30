# Conservative AI-reviewed Thai rescore

The [AI PDF audit](../heldout_thai_final_ai_pdf_audit_v1.md) checked all 20
primary reference facts against rendered pages from the two original Thai
reports. It found all 20 primary labels consistent with their cited pages.
It accepted SCBX page 252 for TF08 and TF09 and Thai Union page 194 with
one-decimal rounding for TF14. It **excluded** SCBX page 111 as complete
evidence for TF06 because that narrative does not explicitly state that
the 43.9-billion-baht consolidated net profit is *attributable to SCBX*,
as the question requests. The audit is by an AI assistant, not an independent
human reviewer.

This `metrics.json` reuses the exact saved predictions. No model, OCR,
retrieval, or ingestion reran. The frozen v1 scores and historical provisional
v2 scores remain unchanged. This is a **post-run scoring interpretation**, so
it is not a new held-out test or a model improvement.

| Search page Hit@5 | Frozen v1 | AI-reviewed v3 |
| --- | ---: | ---: |
| Thai BM25 | 5/20 | 8/20 |
| Dense `bge-m3` | 3/20 | 5/20 |
| App hybrid | 3/20 | 5/20 |

| Answer arm | Frozen v1 strict correct | AI-reviewed v3 strict correct | v3 correct with accepted page |
| --- | ---: | ---: | ---: |
| BM25 + local Gemma | 0/20 | 1/20 | 1/20 |
| App offline Gemma | 1/20 | 1/20 | 0/20 |
| BM25 + Gemini | 6/20 | 7/20 | 7/20 |
| App Gemini | 2/20 | 4/20 | 4/20 |

The fixed numeric parser no longer treats the `2` in `Gen 2` as a competing
answer value. Rounding is declared for TF14 only. The
[v3 adjudication file](../heldout_thai_final_adjudication_v3_ai_review.json)
records the accepted and excluded pages. `metrics.json` includes all
question-level changes and source/code SHA-256 hashes.

Reproduce offline from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.rescore_heldout_thai_ai_review_v3
```

This 20-question set covers only eight distinct physical PDF pages. Its
selectable-text benchmark bypasses the production Typhoon/Gemini OCR path.
The low answer scores still do not establish reliable Thai financial
question answering. A separate qualified human review can add assurance
before the AI-adjudicated figures are used as final thesis results.
