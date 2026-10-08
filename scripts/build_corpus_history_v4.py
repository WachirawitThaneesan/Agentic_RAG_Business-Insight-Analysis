"""Inventory report PDFs already exposed to earlier experiments."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pymupdf

from scripts.evaluate_comprehensive import save


EXPOSURES = {
    "ptt_2567_th.pdf": ("PTT", "diagnostic_498_current", "Current 498-question bank, ranking and answer tuning"),
    "pttep_2567_th.pdf": ("PTTEP", "diagnostic_498_current", "Current 498-question bank, ranking and answer tuning"),
    "cpaxtra_2567_th.pdf": ("CPAXT", "diagnostic_498_current", "Current 498-question bank and prior 20-question retrieval diagnosis"),
    "egco_2567_th.pdf": ("EGCO", "diagnostic_498_current", "Current 498-question bank and prior 20-question retrieval diagnosis"),
    "thai_union_one_report_2567_th.pdf": ("THAI_UNION", "prior_development", "Earlier table, retrieval and long-report experiments"),
    "scbx_annual_report_2567_th.pdf": ("SCBX", "prior_development", "Earlier table and answer errors inspected"),
    "tpac_one_report_2567_th.pdf": ("TPAC", "prior_development", "Former Thai held-out questions and 220-page Docling OCR test; results inspected"),
    "bot_annual_report_2567_th.pdf": ("BOT", "prior_development", "Former Thai held-out questions; results inspected"),
    "bts_report_language_check.pdf": ("BTS", "language_screened", "Previously opened for language screening; do not claim strict untouched status"),
    "wbg_annual_report_2025.pdf": ("WBG", "english_prior_baseline", "Earlier English baseline"),
    "nvidia_annual_review_2024.pdf": ("NVIDIA", "english_prior_baseline", "Earlier English baseline"),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    rows = []
    for path in sorted(a.work_root.rglob("*.pdf")):
        if path.name not in EXPOSURES:
            continue
        issuer, exposure, reason = EXPOSURES[path.name]
        with pymupdf.open(path) as pdf:
            pages = len(pdf)
        rows.append({"issuer": issuer, "filename": path.name, "path": str(path),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "physical_pages": pages, "exposure": exposure,
                     "excluded_from_strict_new_report_test": True, "reason": reason})
    missing = sorted(set(EXPOSURES) - {r["filename"] for r in rows})
    save(a.output, {"method": "Known report PDF files in prior experiments, confirmed by named paths and prior docs",
                    "reports": rows, "known_filenames_not_found": missing,
                    "selection_rule": "For a new final test, exclude these exact hashes and preferably these issuer families; verify any newly downloaded PDF against this history.",
                    "scope_limit": "This is an inventory of known local report PDFs, not a proof that a remote report was never observed by any model or person."})


if __name__ == "__main__":
    main()
