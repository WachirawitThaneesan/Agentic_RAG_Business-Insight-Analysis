"""Copy the completed Step 8 pilot's small JSON records into the repository.

PDFs, embedding vectors, temporary databases, and private paths stay outside
the frozen result bundle. Existing output is never overwritten silently.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PureWindowsPath


FILES = {
    "heldout/metrics.json": "metrics.json",
    "heldout/corpus_manifest.json": "corpus_manifest.json",
    "heldout/bm25_predictions.json": "bm25_predictions.json",
    "heldout/dense_predictions.json": "dense_predictions.json",
    "heldout/app_hybrid_predictions.json": "app_hybrid_predictions.json",
    "heldout/bm25_rag_answers.json": "bm25_rag_answers.json",
    "heldout/app_agent_answers.json": "app_agent_answers.json",
    "environment.json": "environment.json",
    "long_synnex_278.json": "long_synnex_278.json",
    "long_bbikt_377.json": "long_bbikt_377.json",
    "process_restart_synnex_278.json": "process_restart_synnex_278.json",
    "render_bbikt_377.json": "render_bbikt_377.json",
    "local_ocr_sample.json": "local_ocr_sample.json",
    "local_ocr_memory_sample.json": "local_ocr_memory_sample.json",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.input_dir.resolve(strict=True)
    target = args.output_dir.resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Frozen result directory is not empty: {target}")

    records = {}
    for relative, name in FILES.items():
        path = source / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "pdf" in value:
            value["pdf"] = PureWindowsPath(value["pdf"]).name
        if name == "process_restart_synnex_278.json":
            for phase in ("crash", "resume"):
                value[phase]["log"] = PureWindowsPath(value[phase]["log"]).name
        records[name] = value
    if records["metrics.json"].get("n_answers") != 20:
        raise ValueError("Expected the completed 20-question answer comparison")
    if records["render_bbikt_377.json"].get("rasterized_pages") != 377:
        raise ValueError("Expected the full 377-page rasterization result")
    if records["local_ocr_memory_sample.json"].get("peak_worker_mb", 0) < 100:
        raise ValueError("Local OCR memory file appears to contain the invalid launcher-only reading")

    target.mkdir(parents=True, exist_ok=True)
    for name, value in records.items():
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    (target / "README.md").write_text(
        "# Step 8 frozen pilot results\n\n"
        "Small JSON records from the 2026-09-27 local run. `pdf` fields were "
        "reduced to filenames to avoid storing private local paths. The original "
        "PDF URLs and SHA-256 hashes are in `corpus_manifest.json` and the "
        "long-document records, including the fresh-process crash/resume run. "
        "Embedding vectors, PDFs, and live databases are "
        "not bundled. See `docs/thesis-evaluation.md` for scope, commands, and "
        "limitations.\n",
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
