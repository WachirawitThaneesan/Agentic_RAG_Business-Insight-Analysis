# Decisions — continuation 2026-10-05

| Evidence / hypothesis | Action | Result | Decision |
|---|---|---|---|
| Saved judge verdicts were downgraded when quotes could not be verified | Replay raw judgments with explicit states and exact context binding | 20 answers/56 claims; unresolved dimensions remain visible | Accept offline contract replay v2.2; never count uncertainty as automatic wrong/pass |
| Numeric101 labels existed but legacy numeric flags were all false | Connect labels by question and quantity; separate AI answer-review sidecar | Eight applicable tuples; four measurable, two correct | Keep 50% coverage and 2/4 diagnostic accuracy; captured app accuracy N/A |
| Judge proposed citations cannot establish actual emitted links | Require captured app claims, identical source list and actual mapping | 20/20 mappings missing; exclude 59 judge links | Complete success and actual citation accuracy N/A |
| Cancellation/retry tracing could contaminate nested/concurrent calls | Restore context in finally; record SDK attempt duration/status/usage | Mock regressions pass; real calls captured | Accept tracing fix; unknown usage stays null |
| PTT native text mixes headings | Visually inspect original page 3 | B0001 reference is Mission while question asks Vision | Create v5; one manual AI adjudication; preserve v4 scores and report review exposure |
| Failed initial ingestion and conservative thinking reservations blocked pages | Preserve raw run; correct reserve from explicit budget0 request; resume same isolated DB | Four pages eventually indexed; genuine answers four; failed exit retained | Use audited summary; do not relabel fallbacks or runner exit as success |
| Resume of completed jobs returns409 | Treat explicit409 as idempotency guard; independent API audit | Counts unchanged, zero new calls | Accept runner handling fix |
| A physical citation may point to the wrong page | Query unmodified UI and click actual citation | Sample2 corresponds to originalCPAXT38 | One physical-page/UI check accepted; no global entailment claim |
| Real table broadTHB heading conflicts with explicit row units | Baseline actual upload/OCR, then repair cell-unit precedence and replay same cached OCR in new warehouse | Values21/21 before; tuple0/21→21/21, answers0/3→3/3 | Accept narrow local unit fix; six-call validation cap; development only |
| Correct bank hash does not prove audit rows use those labels | Bind judged question/reference prefix to bank item | Stale reference tests fail as intended; v4/v5 replay20each succeeds | Accept v2.2 reference binding |
| Existing context candidates did not improve coverage | Preserve previous rejection/revert | Uniform10→7/20; firsttwo10→10/20 | Keep both rejected; no new context tuning |
| Gates for expanded answers/final unseen incomplete | Preserve candidates and stop expansion | No50paired≥95%coverage/actuallinks; no unseen score | Deliver bounded-run evidence with quality goal partial |

No global budgets reset; no new ranking variants; no production database edits/deletion, deployment, credentials changes or Git reset. Existing dirty/untracked work retained.
