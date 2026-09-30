# Thai held-out pilot results

Frozen JSON from the 2026-09-27 local run on the two public Thai reports in
[`heldout_thai_reference_v1.json`](../heldout_thai_reference_v1.json). The
PDFs, embedding vectors, temporary database, and local model files are not
bundled. `metrics.json` includes all 20 question-level search and answer
scores and timings. Prediction and answer files permit manual inspection.

`regex_bm25_metrics.json` and `regex_bm25_predictions.json` preserve the
initial retrieval-only pass before Thai word segmentation was added. The
main `metrics.json` uses PyThaiNLP `newmm` segmentation for BM25. Dense and
app hybrid methods used the same PDF chunks and embeddings in both passes.
`citation_audit.md` records a post-run check of alternative source pages
without changing the frozen score.

The benchmark indexed selectable PDF text. It did not run OCR or the normal
Typhoon/Gemini pipeline. Its app arm ran the local offline Gemma model against
an isolated PostgreSQL index; the structured DuckDB warehouse was not filled
with extracted tables. The one-page evidence labels can omit other valid
supporting pages. See [`docs/thesis-evaluation.md`](../../docs/thesis-evaluation.md)
for the interpretation, limitations, and reproduction commands.
