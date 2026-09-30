# Post-run citation audit (not part of frozen scores)

The benchmark's strict citation hit requires its single labeled PDF page.
After answers were saved, one reader inspected these other pages in the
original public PDFs. This audit must not be treated as an independently
scored citation metric.

| Question | Saved arm | Other exposed page | Observation |
| --- | --- | ---: | --- |
| TH01 | App agent | BOT PDF p.33 | The narrative states the policy rate was reduced to 2.25%. The frozen label was p.17. |
| TH07 | App agent | BOT PDF p.44 | The narrative states 35.5 million foreign tourists. The frozen label was p.23. |
| TH13 | Both arms | TPAC PDF p.65 | The cash-flow table lists 1,143 million baht for 2567 operating cash flow. The frozen label was p.11. |
| TH11 | Simple RAG | TPAC PDF p.57 | The revenue value 7,214 million baht appears here. The question explicitly asks about the chart on p.10, so this page does not meet that stricter location request. |

The first three observations show why the one-page hit measure can undercount
valid evidence. A future reference set should label all acceptable supporting
pages **before** predictions are run, and have those labels checked by another
reader. The published `metrics.json` remains unchanged.
