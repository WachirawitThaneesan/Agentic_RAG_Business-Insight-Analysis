# Full Thai local OCR checkpoint: TPAC 2567

`full_tpac_220.json` is the checkpoint from `scripts.benchmark_full_local_ocr`
on the 220-physical-page Thai TPAC 2567 One Report. Its source PDF SHA-256 is
`2867b2183ebed0001b4c6ed6513cc9128cefa18613fb3a92d9dbdcc09b8d79a5`,
matching `heldout_thai_reference_v1.json`. The original PDF and extracted
text are excluded. `ocr_interruptions.json` records the deliberate process
stop after page 110; the next run began at page 111.

| Measurement | Result |
| --- | ---: |
| Pages checkpointed | 220/220 |
| Nonempty / failed / empty | 220 / 0 / 0 |
| Tables detected | 155 |
| Summed per-page OCR time | 13,318.1 s (3 h 42 min) |
| Median / 95th percentile page time | 54.94 / 104.58 s |
| Maximum sampled parent-plus-worker RSS | 5,068.4 MiB |
| New pages attempted across four processes | 1 + 35 + 74 + 110 |

The job used local Docling/TableFormer and Thai/English EasyOCR with
`OFFLINE_MODE=true` and no cloud fallback. Memory was sampled every 0.5 s;
summed process RSS can count shared pages more than once. Per-page output
records status, time, character count, and table count. The two interrupted
process phases have no `finished_utc` field because they were stopped; their
completed pages were saved before restart. Each page appears once in the
checkpoint, and the four `pages_attempted` counts total 220.

This is an **OCR engine and checkpoint** measurement. Nonempty text and table
detections do not establish OCR or cell accuracy. The script does not index the
output, use the upload API, retrieve evidence, or answer questions. A full
220-page upload-to-answer test remains unmeasured.

To repeat with a verified copy of the same PDF and locally prefetched models:

```powershell
$out = Join-Path $env:LOCALAPPDATA 'rag-step8-thai-full-ocr'
.\.venv\Scripts\python.exe -m scripts.benchmark_full_local_ocr --pdf 'C:\path\to\tpac_one_report_2567_th.pdf' --output (Join-Path $out 'full_tpac_220.json') --private-dir (Join-Path $out 'private') --local-python 'C:\path\to\local-ocr\.venv\Scripts\python.exe' --models 'C:\path\to\local-ocr\models' --easyocr-cache 'C:\path\to\local-ocr\easyocr_cache'
```
