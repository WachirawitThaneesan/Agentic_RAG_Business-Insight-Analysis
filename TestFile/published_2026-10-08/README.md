# Published Gemini Evaluation Evidence — 8 October 2026

This package accompanies the [English full498 report](../../docs/GEMINI_RAG_FULL498_REPORT_2026-10-08.md) and the [updated development plan](../../docs/EVALUATION_NEXT_STEPS_2026-10-08.md).

## Readable Results

- [Metrics and coverage for all 498 questions](metrics498.json)
- [Per-question evaluation contracts for all 498 answers](contract_details498.json)
- [Numerical diagnostics for all 102 required relationships](numeric_diagnosis102.json)
- [Per-question capture and numerical outcomes](per_question498.json)
- [Evaluation figure](results498.png)
- [Controlled candidate98 comparison](candidate98_comparison.json) and [selection decision](selection_decision.json)
- [Cumulative resource-ledger snapshot](resource_ledger_snapshot.json)
- [Final operational judge failures](judge_failures_retained.json), an empty list after recovery

The eight conservative full-set RAG scores are 85.96–96.69%. Complete-answer and numerical relationship diagnostics remain future work. Results belong to the frozen full498 development run, not a new full498 evaluation of the current v1.22 application. All judgments are AI provisional; source PDFs and independent human validation are separate requirements.

## Lossless Selected Archives

| Archive | Contents |
|---|---|
| [Full498 generation](evidence/full498-generation.zip) | Original saved answers, model-call traces, labels, manifests, and frozen generation code |
| [Full498 final audit](evidence/full498-final-audit.zip) | Merged final judgments, actual citation audits, payloads, and validated reuse lineage |
| [Initial audit](evidence/full498-initial-audit.zip) | Original successful and failed judgment attempts |
| [Recovery v3](evidence/full498-audit-recovery-v3.zip) | Preserved failed attempts and successful operational recoveries |
| [Recovery v4](evidence/full498-audit-recovery-v4.zip) | Further operational recovery with matching valid verdicts retained |
| [Direct-quote recovery](evidence/full498-direct-recovery.zip) | Four unchanged answer inputs and direct-quote judgments completing the audit |
| [Numerical experiments](evidence/numeric-experiments.zip) | Rejected v20 prefix, completed v21 candidate98, preregistrations, comparison and decision |
| [Source review and checkpoints](evidence/source-review-and-checkpoints.zip) | Prepared blind review for 94 questions/102 locked relations and final checkpoints; review not yet completed |
| [Frozen corpus](evidence/frozen-corpus.zip) | Corpus, vectors, and recorded corpus provenance used in the development run |

Archive members retain their original repository-relative paths and bytes. [manifest.json](manifest.json) records each member's original SHA-256 and size, each archive's SHA-256 and size, and the source hashes of the readable result copies. Files exceeding the regular Git file-size limit are distributed inside lossless archives; every archive is below 100 MiB.

Verify the published evidence from the repository root:

```powershell
python -m scripts.verify_published_evidence
```

The verifier checks archive hashes and the original bytes of every archived member, as well as the readable copies. ZIP files can be downloaded and extracted into a separate directory to inspect the frozen records without overwriting an existing evaluation workspace.

## Scope and Reproduction

The package publishes selected full498 evidence and the latest controlled experiment. It **does not archive every local experiment**. All original local experiments remain intact, including older runs and intermediate replays. Earlier OCR/ingestion reports and their scope are documented in [Stage A](../../docs/evaluation-A-2026-10-08/REPORT_th.md) and [Stage B](../../docs/evaluation-B-2026-10-08/STAGE5_RECOVERY_REPORT_th.md); their complete local raw workspaces are not included in these nine archives.

Source annual-report PDFs, credentials, runtime databases, logs, temporary files, and the full local experiment collection are excluded. Hash verification and saved-evidence inspection are portable. A fresh system rerun requires the hash-matching source PDFs, configured services, model access, and paths appropriate to the new machine. Frozen manifests preserve original local paths and must not be silently rewritten as if they were the original run.

Publication introduces no new model/OCR evaluations and does not change the saved answers, reference labels, scoring contracts, or recorded percentages.
