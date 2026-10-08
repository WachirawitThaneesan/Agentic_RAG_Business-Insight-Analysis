# Stage3 checkpoint — 8 ตุลาคม 2026

Retrieval บน stable isolated development corpus เสร็จครบ 498 ข้อทั้ง baseline/candidate. `lexical_first` ผ่าน Hit@5 และ required Recall@5 ที่ 465/498 = 93.37% ทั้งสองฝั่ง. **Quality goal รวมยัง partial**; Stage5 actual ingestion ยังไม่ dispatch ณ checkpoint นี้.

| Paired table-data arm | strict searchable cells | Hit@5 | MRR | nDCG |
|---|---:|---:|---:|---:|
| baseline actual Gemini component | 123/169 | 465/498 | 0.830154 | 0.849889 |
| candidate2 exact raw + deterministic header repair | 166/169 | 465/498 | 0.829819 | 0.849626 |

Cell gain43/regressed0; Hit@5 recovered0/regressed0/unchanged498. ไม่อ้างว่า OCR repair เพิ่ม Hit@5. Rank B0348 ถอย2→3; แหล่งหลักฐานยังอยู่ Top5. Source facts/scorer v3 และ RAG labels/scorer/aliasesเดิมไม่เปลี่ยน. ชุดนี้ใช้พัฒนาแล้ว ไม่ใช่ final/unseen หรือ full-report OCR.

Freeze: paired_corpus_v2 baseline3613/candidate3614 chunks; เปลี่ยนเฉพาะ8mapped pages, Typhoon prose/corpusนอกหน้าเลือกคงเดิม. Corpusสร้างจาก actual saved region evidence ผ่าน production normalization/eligibility; BGE-M3 local inputsใหม่11, cloud0. Original/sample/source mappings/hashผ่าน.13policy regressionsเป็นอีก comparisonหนึ่ง ไม่ใช่ data regressions.

Existing policies บน candidate corpus/shared production candidate pool: hybrid_current421/498→lexical_first465/498; recovered57/regressed13, secondaryMRR/nDCGดีขึ้น. คง default lexical_firstเดิมตาม predeclared rule ไม่เพิ่มranking configsหรือweight sweeps. เก็บsource/rank reviewครบ13; มี4year/ordinal/zero relationsที่ไม่อยู่ lockednumericinventory, 3native-page supportsมีgarbling/uncertainty. ไม่ถือว่า numeric labels101ครอบคลุมทุกเลขใน498.

Remaining33misses:30ranking/page-budget;3outside saved top50 or scopeยังunknown. Distinct interleaved keyword/dense candidate union20 hits483/498 และ50 hits491/498; เป็นcandidate coverageที่budget20/50pages ไม่ใช่Top5accuracy. Per-channel50 unionครบ495; truncateddiagnosticsไม่พิสูจน์missing candidateทั้งหมด. Source-reference changes27itemsระหว่างhistoricalv5กับinheritedv11เปิดเผย; historicalrecordedOCRv3เคยlexical464อยู่แล้ว. ห้ามอ้าง425→465เป็น B gain.

Runtime I/O repair: defer unused embedding columnในSQL keyword/semantic entity projection;79preservedprefixอันดับ/scope/source text/metadataตรงทั้งหมด, similarity floating jitter≤3.33e-16เก็บdiffครบ. Stopped partialrun79records/initialcachemismatch/firstOllama-connect failureไม่ลบ.53focusedregressionsผ่าน; preflight46passed/5skippedไม่ถือว่าskipคือrealacceptance.

N/A prerequisite: historical raw_ocr_pagesผ่านtable strippingแล้ว จึงไม่ใช่unmodifiedTyphoonoutputและproviderattributionunknown. เพิ่มliteralN/A-only retentionเมื่อGeminiไม่คืนตาราง, ไม่กู้numericcellsจากunconfirmedtable;เก็บprovider_markdownในnonsearchablerawartifact.21routing-relatedtestsก่อนfinal53ผ่าน; patchนี้ไม่เปลี่ยนfrozencorpus/Stage3resultsและรอfreshStage5.

Human_confirmed=false; all AI review provisional. LedgerยังSDK≥3347/input≥54,473,794/output≥1,816,995,330failedusageunknown,74uniquepaidpagekeys;USD=N/A. ไม่มีreset/caps/deadlineใหม่. ไม่มีproductionDBwrite/deploy/push.

Next: actual upload + scraped-file→Typhoon/Gemini→store→retrieve→answer→citation/image32stratifiedpages/16questionsในDB/uploads/DuckDBแยก; native-routecontrolบนsame32pages/16questions; auditraw/storedcells169, source/hash/coverage, stagedrestart/idempotency/rollback และrealUIcitation.
