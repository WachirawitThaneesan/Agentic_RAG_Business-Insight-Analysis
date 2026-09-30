# Untouched Thai final benchmark results

These JSON files preserve the 2026-09-27 20-question run on SCBX and Thai Union 2567 reports. The question labels and method hashes are in `../heldout_thai_final_reference_v1.json` and `../heldout_thai_final_method_lock_v1.json`. The run indexed selectable PDF text, not OCR, and used local `bge-m3` and `gemma3:4b` models. It did not fill structured DuckDB tables. Public source PDFs, embeddings, and live databases are excluded. `run_conditions.json` records temporary overlap with a separate OCR workload. `retrieval_only_metrics.json` preserves the first pass before any answer generation; the full `metrics.json` is the final score. See `docs/thesis-evaluation.md` for interpretation and limitations.

The original scorer code is preserved in `frozen_scorer_v1/` to keep the
method-lock hashes reproducible. A separate, post-run provisional rescore is
in `../step8_thai_rescore_v2_provisional/`; it does not modify these scores.
