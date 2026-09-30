# Snapshot of the original frozen scoring code

`numeric.py` and `score_layers.py` are byte-for-byte copies of the two scoring
modules used for the saved 2026-09-27 Thai final and Gemini supplement scores.
Their SHA-256 hashes match the corresponding entries in
`../../heldout_thai_final_method_lock_v1.json` and
`../../heldout_thai_gemini_supplement_method_v1.json`.

They are retained because the live evaluation modules now fix a `Gen 2`
false negative and support explicitly adjudicated alternate evidence and
rounding. The original `metrics.json` files and model predictions are
unchanged. This snapshot is historical code, not the scorer for new runs.
