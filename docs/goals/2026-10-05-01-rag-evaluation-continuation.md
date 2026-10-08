# Goal 2026-10-05-01: รับช่วง Thai RAG evaluation คืนแรก

สถานะ: **partial / checkpoint A delivered; Gemini evaluation ยังไม่ครบทั้งระบบ**; อัปเดต 8 ตุลาคม 2026 (Asia/Bangkok)

**คำสั่งล่าสุดมีลำดับความสำคัญเหนือเกณฑ์เดิมด้านล่าง:** ทุกเกณฑ์ทำให้ดีที่สุดอย่างคุ้มโควต้าก่อน; มากกว่า80%เป็นเป้าหมายใช้งานที่ยอมรับได้ และเกณฑ์เดิมเป็นเป้าหมายปรับละเอียดภายหลัง. ใช้ `docs/EVALUATION_WORKING_POLICY_2026-10-08.json`; ไม่ reset ledgerหรือเปลี่ยนหลักฐาน/scorerเพื่อเพิ่มคะแนน. Current50 generation100outputsเสร็จแล้ว; broad judgeหยุดตามคำสั่งใหม่ที่67/100recordsและไม่มีworkerค้าง. ทำ offline diagnosis/local fixesก่อน; C/Doclingยังไม่เริ่ม. Latestcapturev1.11ใช้native NUMBERเพื่อไม่ให้AAAเข้าnumericและรักษาdecimallexeme;68testsผ่านและ95oldcapturedoutputsยังbindingvalidทั้งหมด;newSDKหลังคำสั่งเปลี่ยนแผน=0. ไม่อ้างว่าaccuracyบนcloudดีขึ้นโดยยังไม่ได้วัด.

## เป้าหมาย
ทำตามแผนหลักโดยปรับคุณภาพตามหลักฐาน รักษาเกณฑ์เข้ม และส่ง REPORT_th.md/NEXT_ACTION.md พร้อมผลที่ทำซ้ำได้ เป้าหมายเดิมยังไม่เสร็จ การย้ายแชทไม่ใช่การเริ่มงบใหม่

- Repo: `C:\Users\nonga\OneDrive\Desktop\Project_2\Agentic_RAG_Business-Insight-Analysis`
- Branch: auto1; HEAD: 5060072892320ddf9a1ea4a3b4c317b424c3b33a; dirty/untracked จำนวนมาก ต้องเก็บทั้งหมด
- Raw results: `C:\Users\nonga\Documents\Codex\2026-09-25\i-would-currently-rate-the-project\outputs\ranking_evidence_2026-10-05_v3`
- แผนหลัก: [RAG plan](../RAG_EVALUATION_IMPROVEMENT_PLAN_2026-10-05.md)
- จุดรับช่วงฉบับละเอียด: [Handoff](../HANDOFF_2026-10-05.md)
- Model แชทรับช่วงที่ผู้ใช้เลือก: GPT-6.1 Sol / high
- Original app Goal: usageLimited; ไม่ใช่ completed; ไม่สร้าง Goal ซ้ำโดยอนุมานจากไฟล์นี้

## Latest steering / checkpoint — 8 ตุลาคม 2026 (Asia/Bangkok)

**Latest result after “ทำต่อเลย”:** OCR scopeเป็นGeminiตารางในpipelineเดิมTyphoon-text/Gemini-tablesตามworking assumptionที่แจ้งก่อนdispatch ไม่ใช่Gemini-onlyprose. ดู `docs/evaluation-A-2026-10-08/REPORT_th.md`/METRICS.json/HANDOFF_B.md. Stage2และStage4checkpointsแยกใน `TestFile/evaluation_A_2026-10-08/`.

- OCR169sourcecellsบน5numericpagesจาก8selecteddevelopmentpages/10regions: same-v3 baseline123→candidate2+deterministic raw replay166/169=98.22%, recovered43/regressed0. Prompt-onlycandidatesที่ไม่ดีเก็บครบ. Referencev1/v2/v3correctionsเปิดเผย, scoring functionsคงเดิม, no gold in inference. ยังไม่ใช่unseen/full-report/actualingestionacceptance;proseCER/WERและchartaccuracyN/A
- Capturev1.9rawreplay479/532,อีก53originalcaptureคงไว้, answer/claims/links/contextทุกrecordไม่เปลี่ยน. Primarycapture124→127/133,numericmeasurable106→109/114,strictcorrectยัง22/109. All-armscaptured498→508/532,numericmeasurable421→434/456,correct66→69;no regressions. Source6pages/4casesแยกliteral/company-subject/scope/duplicate-page;RAGlabels/scorer/aliasesไม่เปลี่ยน.18literal-onlycasesยังไม่reviewครบ;36oldjudgesยังunresolved
- Storedsource metadata/rawGemini tables repairและlocalreplay7/7tablesผ่าน;actualproduction-pathacceptanceอยู่B. Broadregression323passedและfocusedprovenance/chunk7passed(overlap). ไม่มีownedrunningevaluationprocess
- NewSDK36,knowninput126,680/output14,419,6failedusageunknown;activeledgerสะสมSDK≥3347/input≥54,473,794/output≥1,816,995,failedusageunknown330,paidpagekeys74.8sourcepagesถูกอ่านซ้ำ;ไม่resetoriginal/derivativekeysหรือinterruptedunknowns. USDN/A. Historical projectcapsไม่กลับมาใช้
- Qualitygoalยังpartial. ยังไม่เปิดB/C/Docling ไม่rerunfinal133 ไม่commit/push/deployและไม่เขียน/ลบproductionDB. HandoffBเตรียมแล้ว;ก่อนretrieval/realingestionต้องlockstablecorpusและเก็บremainingissuesตามจริง

ผู้ใช้สั่งให้เน้น OCR Gemini และปิด evaluation รอบ Gemini ก่อน local Docling. ยืนยันว่า Gemini ใช้เป้าหมายเดิม; การไม่บังคับ >90% ใช้เฉพาะ local Docling ซึ่งให้ปรับตัวชี้วัดให้ดีที่สุดอย่างมีหลักฐาน. ไม่ลด scorer strictness และไม่เปลี่ยน labels เพื่อเพิ่มคะแนน. Roadmap ล่าสุด: `docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md`.

รับช่วง A แล้ว: ตรวจ repo/HEAD/dirty changes, RUN_STATE และ processes; ไม่มี owned evaluation worker. เก็บ baseline code/hash/status และ inherited ledger ที่ `TestFile/evaluation_A_2026-10-08/`. Local diagnosis พบความต่างระหว่าง gold physical page กับ emitted source page และ capture rejection ของ numbered identifiers/compound percent unit; ยังไม่ได้แก้ application code หรือเปลี่ยน scorer. final133 เป็น development หลังใช้วินิจฉัย.

New SDK attempts=0; new paid OCR pages=0; ledger สะสมยัง SDK≥3311/input≥54,347,114/output≥1,802,576, unknown interrupted usage คงเดิม. Quality objective ยัง partial. ไม่เริ่ม Docling, B/C หรือ generation/audit เดิมซ้ำ.

รอ scope จากคำถามที่ส่งแล้ว: Gemini อ่านทั้งข้อความและตาราง หรือ online pipeline เดิม Typhoon-text/Gemini-tables. งานที่ขึ้นกับตัวเลือกนี้ยังไม่ dispatch. ไม่มีคำขออนุมัติ spending/deadline ใหม่; authorization เดิมยังใช้ต่อ

## เกณฑ์จบและสถานะ
| งาน | สถานะและหลักฐาน |
|---|---|
| Frozen reference/scorer contract | v5 labels AI provisional; contract v2.2 replay20 เสร็จ; actual app capture ยังไม่ครบ |
| Paired retrieval | เสร็จ diagnostic 373→415/498; ยังต่ำกว่า target 90% |
| Context/table evidence | partial; 2 contexts rejected/reverted; real table unit repair21/21 validated |
| Strict answer/citation evaluation | replay20 v4/v5 เสร็จ; AI numeric4/8; actual citation20 missing |
| Real ingestion path | selected5pages/API/UI measured; full reingest and30–50page scope pending |
| New Thai held-out reports | ดาวน์โหลด 3 candidates; ยังไม่ได้สอบ |
| Final report/package | continuation report/CSV/raw archive verified; quality targets remaining |

## งบติดตามต่อ
Deadline 2026-10-05 11:32:17 +07:00 จาก manifest เดิม; cloud 94/600 attempts; reported input 1,158,276/2,000,000; output 81,805/300,000; 2 failed calls usage unknown; paid OCR 0/60 pages; ranking 10 unique configs/12 (baseline เดิมนับแยก)

หากรับช่วงหลัง deadline ให้ทำเฉพาะตรวจ/สรุป/package ที่จำเป็น และแจ้งงานค้าง ห้ามเริ่มชุดทดลอง cloud ใหม่ด้วยการ reset เวลา

## ทำต่อทันที
1. ตรวจ repo/branch/dirty changes และอ่าน raw `smoke20_eval_judged/summary.json`, `details.json`, `answer_smoke20_audit/summary.json`, `labels_v4/evaluation_policy.json`; อย่าเริ่ม cloud run ทันที
2. ตรวจ contract v2 กับ scorer v1.5: replay คำตอบ 20 ข้อที่บันทึกแล้ว แยกผิดจริง / หลักฐานไม่พอ / quote ตรวจไม่ได้; เชื่อม numeric 101 ค่าและ actual claim→citation mapping; ถ้าไม่มี mapping ให้ N/A ห้ามใช้ judge-invented citations แทน
3. ตรวจ model-call tracing และ focused tests ก่อนใช้ผล calls/tokens เป็นหลักฐาน; จำแนก SDK-call latency, agent time, benchmark wall time ให้ถูก
4. วิเคราะห์ context ที่ขาดและ PTT text เพี้ยน โดยรักษา row/column/year/unit/page; ทดสอบ local ก่อนและเทียบทั้ง recovered/regressed; อย่านำ 2 context candidates ที่ reject กลับมาใช้โดยไม่มี evidence ใหม่
5. หากยังมีเวลางบ ให้ทดสอบ upload → Typhoon/Gemini → store → retrieve → answer → citation บน physical pages ที่เลือกไว้ โดยใช้ DB/run แยกและเก็บ page mapping; ยังไม่มีผลเส้นทางนี้ในรอบล่าสุด
6. ล็อก code/scorer ก่อน final unseen test; candidate PDFs ใหม่ยังต้องตรวจภาษาและ overlap; หากใช้ปรับระบบแล้วต้องเปลี่ยนสถานะเป็น development
7. ก่อน deadline เดิมจัดทำ REPORT_th.md, NEXT_ACTION.md, METRICS.csv และ artifact/hash index แม้ไม่ถึงเป้า ระบุ missing/failed/N/A ตามจริง ไม่ขยาย cloud budget เอง

## Decision log ที่ต้องรักษา
- รับ lexical_first จาก paired retrieval จริง; explicit hybrid_current ยังมีให้เปรียบเทียบ
- ปฏิเสธ uniform context (10→7/20 quote coverage); first-two ไม่มี gain (10→10/20); ทั้งคู่ revert แล้ว
- ไม่เทียบ smoke20 กับคะแนนคำตอบเก่า50แบบ delta; ไม่อ้างว่า source list correctness คือ actual claim citation
- เก็บ historical artifacts ไม่แก้ทับ; AI review ไม่ใช่ independent human review
- คำอนุญาตเดิมให้ตัดสินใจ local/code/eval ภายในงบโดยไม่ต้องถาม; ไม่รวม deploy/force push/ลบ production DB/เพิ่มวงเงิน

## Checkpoint
ไม่มี experiment ของรอบนี้ที่ค้างรันตามจุดส่งต่อ; local services อื่นอาจยังทำงาน อย่าหยุดโดยไม่ตรวจ
อัปเดตไฟล์นี้กับ RUN_STATE/NEXT_ACTION หลังผลถัดไป และบันทึกคำสั่งจริงที่ใช้ด้วย

## แชทรับช่วงที่สร้างแล้ว

- Thread ID: `01a109b2-94c8-7ec0-9c51-28b56816de40`
- Model: `gpt-6.1-sol`; reasoning: `high`; host: local
- ใช้ repo เดิมตาม absolute path; original chat หยุดการทดลองเพิ่มเติมหลังส่งต่อ
- การสร้างแชทส่งต่อสำเร็จไม่ใช่การยืนยันว่าทุกขั้นของ evaluation เสร็จ

## Continuation checkpoint 2026-10-05T08:43:29.083802+07:00

- รับช่วง repo/HEAD/dirty edits ตรง handoff;ไม่มี AGENTS.md พบใน repo/parent paths ที่ตรวจ
- Offline contract replay20/20 passed:56claims;numeric8tuples missing annotations;actual citation20missing;complete success N/A. All AI review provisional/human_confirmed=false.
- Added backend/eval/contract_replay.py and scripts/replay_contract_v2.py;historical scores untouched.
- Fixed llm trace cancellation reset;SDK attempt time excludes pacing/backoff. Focused11passed;eval/retrieval/context related regression140passed.
- Commands: .venv\Scripts\python.exe -m scripts.replay_contract_v2 --help; actual replay flags in output method_lock.json and forthcoming COMMANDS.json; .venv\Scripts\python.exe -m pytest backend/eval/tests backend/services/tests/test_llm_trace.py backend/services/tests/test_retrieval_rank.py backend/services/tests/test_page_context.py backend/services/tests/test_cross_report_evidence.py -q (exit0,140passed).
- Results: C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs\contract_replay20_v2
- No cloud added;original budget94calls/input1158276/output81805,2failedusageunknown,OCR0 unchanged.
- Next: isolated production ingestion sample inspection, then final report/package. Application capture gates and unseen tests remain pending.

## Experiment checkpoint 2026-10-05T09:00:34.844766+07:00

- Context scorer audit:200 returned sources vs87 captured prompt pageblocks across20questions. Legacy90% is answer relevancy rubric,not context relevance. All20 legacy numeric_reference flags false although8locked numeric tuples apply.
- Visual PDF review4 development pages: B0001 reference confused Vision/Mission; original v4scores unchanged; requireversionedcorrection. B0306 remainsกบง./กฟผ./lte200000ตัน; CPAXTPrivateLabelapprox16.0%; CPAXTintangibles10831ล้านบาทyear2567. AIprovisional/human_confirmed=false.
- Heldout3candidate hashes,pagecounts and sparseThai-languageprobe passed;distinct from11known development hashes. No labels/no final test/no tuning.
- Initial real API upload/job smoke: PTTpartial(onepageindexed/oneOCRfailed),CPAXTfailed due pre-dispatchbudgetguard;6actualnewcalls. No genuine new model answers;4app fallbackresponses recorded,not valid model generation.
- Meter correction: explicit request thinking_budget=0 releases reserve for3successfulcalls while thinking usage remainsnull;2actuallydispatchedphysicalpages,not4requestedpages. Attempts/known tokens unchanged100/1189359/86313;3failedusageunknown. Evidence budget_reservation_correction.json.
- Accepted retry uses same isolatedDB/uploads/DuckDB; preserves all indexedpages,old artifacts and failedattempts;remaining cap24newattempts oforiginal30smoke cap. Current exec session87332.
- Raw:C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs\ingestion_smoke4_v4;retry:C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs\ingestion_smoke4_v5_retry;meter focused7tests passed.

## Experiment checkpoint 2026-10-05T09:12:42.789653+07:00

- Retry smoke realingestion:4indexedpages/48chunks,PTTpartialtablewarning,CPAXTcompleted16chunks/0structuredrows;4genuineGeminianswers(saved). Added9SDKcalls;initial6calls preserved.
- Retryrunnerexit1 at expected409already-completedresume;fixedrunnerhandling and performed actualAPIpost-audit:unchangedrowcounts,noSDKcalls;didnot regenerateanswers tohideexit1.
- UIrealapp/testDB:onequeryCPAXT10831ล้านบาท andactualclick openssamplep2=originalp38;screenshotssaved;temporaryserverstopped. No fakeUI.
- AInumericanswertranscription sidecar:4of8fulltuples measurable,2correct/4=50% diagnostic,coverage50%;4missing. Originalapplicationstructurednumericcapture remainsmissing. AIprovisional/human_confirmed=false.
- StartingonedevelopmenttablepageCPAXT133,21frozencells and3queries. TableTHBheaderbutrowunitล้านบาท;inferenceplan excludesgold. Usesremaining14attempts of30totalintegrationcap,budgetnotreset. Currentexec48000.
- Report/packagepending;heldoutscorepending;500–1000answersnotstarted.


## Experiment checkpoint 2026-10-05T09:31:48.753881+07:00

- Real table baseline v6 completed exit0:onephysicalpage133,7structuredrows/21cells;values21/21,butrowunit0/21 andanswers0/3 because broadTHBheading overrodeexplicitล้านบาท.11calls;baseline retained.
- Accepted narrow warehouseunit repair;pairedcachedsameOCR into a newDuckDB copy:21/21units/values/years/pages;freshfullagentanswers3/3targetedchecks;6newcalls,0newOCR,baselinefilehashunchanged. Separatefollowupcap6;firstintegrationcap30 used27,globalbudget/deadlineunchanged.
- Labelv5 correctsB0001missionvsvision fromoriginalimage;497otheritems and101numericlabelbytes unchanged. Replaysaved20answers withoneversionedmanualAIadjudication:macro factual55.1667→50.1667%;faithfulness53.75%unchanged. Not a systemperformance delta.
- Replayv2.2now validatesjudgedquestion/referenceagainstbankitem,notonlyfilehash;staleauditnewlabelbankisrejected. Actualclaimcitation20missing;completeN/A;AI numeric2/4measured of8required,50%coverage.
- Finalrelatedtests239passed/1preexistingPydanticwarning;allAIreviewsprovisional/human_confirmed=false.
- Cumulativebudget127SDK/input1289312/output94084;3failedusageunknown withreserves300000/98304;5uniquepaidphysicalpages;ranking10configs. USDcost/RSS/GPU/cloudmemoryunmeasured.
- Stop expansion due50paired/schema/citationcoveragegate;threeThaiheldoutcandidates remainunexposed,not scored. Report/packageinprogress;qualityGoal remainspartial,originalGoalusageLimited.
- Commands: scripts.replay_table_unit_repair --help;actual--runcommandrecorded inCOMMANDS.md;pytest final239 JUnitoutputs/tests/regression_final.xml;replay20v4/v5exit0 each. No ownedprocess remainsrunning.


## Delivery checkpoint 2026-10-05T09:43:58.469687+07:00

- Bounded continuation delivered: REPORT_th.md/NEXT_ACTION.md/METRICS.csv/COMMANDS.md/raw evidence and ZIP/hash verification. Current outputroot C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs.
- Offline reproducibility verified:20savedanswers/v5,paired498 includingbootstrapCI,cachedstorage21cells;no newcloud calls.239tests passed.
- Publishsummary docs/rag-continuation-2026-10-05-v5/ and evidence TestFile/rag-continuation-2026-10-05-v5/. OriginalGoalusageLimited andqualitygoalpartial;not completed. No ownedrunningexperiments.
- Next: actualclaim/citation/numericcapture,exactcontextscope,50pairedcoveragegate,thenstratifiedingestion andfinalunseen. Budget127attempts/1289312input/94084output,3failedunknown,OCR5/60,originaldeadlineunchanged.


## Step2 checkpoint 2026-10-05T10:22:22.125887+07:00

- Source lock/branch/HEAD verified; dirty work preserved.
- Actual-generation capture, stable source IDs, guard invalidation, numeric binding and exact evidence-block evaluator implemented.
- Pre-cloud regression270 passed. No new cloud calls yet.
- Output: C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs; quality goal partial/usageLimited; original budget/deadline unchanged.


## Step2 paired experiment checkpoint 2026-10-05T10:42:31.697768+07:00

- New bounded native-text paired20 run with both existing rankings, same v5 labels/questions/capture/scorer. Cap60 was fixed before dispatch.
- 24 new SDK attempts (22 successful, 2 errors with unknown usage); 11 genuine pairs plus blocked B0289 pair records; 8 pairs not started.
- Actual links10 per arm, strict bound numeric0/8 required per arm; complete prose capture4/20 baseline and3/20 candidate. No citation entailment/headline accuracy measured. Gate50 failed, no expansion.
- Targeted B0001 regression: baseline Vision core vs candidate Mission-as-Vision; provisional, not blinded. Preserve selected lexical policy pending broader evidence.
- Cumulative151SDK/input1434906/output100481;5failed-usage-unknown,reserves500000input/163840output. Next input reservation would total2034906>2000000, so no more cloud under original budget. OCR5/60/ranking10 unchanged; deadline unchanged.
- Offline v1.1 schema repair adds native SDK JSON schema, stronger exact-answer instructions, bound citation page and percent prefix handling. It has no new cloud validation. Preserve frozen v1 run and its original summary; corrected diagnostic audit is separate.
- Outputs: C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs; original goal remains partial/usageLimited.


## Step2 delivery checkpoint 2026-10-05T14:20:07.816233+07:00

- Latest capturev1.1/scopescorerv1.6/replayv2.3:297tests+6frontendchecks passed; no post-fixcloud validation.
- Historical20metrics unchanged; scope200vs87reproduced; marker10/20->10/20quoteproxy unchanged.
- Outputs C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs:Thai report,nextaction,raw11genuinepairs+blocked+8missing,code lock/patch and resource ledger.
- Cloud remains stopped by original token guard and expired deadline. Global151SDK/input1434906/output100481,5failedunknown,reserves500000/163840;no reset. Goal quality remains partial/originalusageLimited.

## User-authorized full plan completion — 2026-10-05

Human instruction: ใช้ไปเลย เอาขีดจำกัดออก ฉันต้องการให้ evluation plan ที่วางแผนไว้เสร็จจบ
Original project spending/count/deadline caps removed explicitly; canonical cumulative usage is retained, not reset. Prior budget snapshot and exact authorization are saved in plan_completion_authorized_v1/AUTHORIZATION.json. Original archived evidence remains historical. Quality thresholds, reference isolation, no production DB deletion, no deployment/push and AI-provisional disclosures remain applicable. Fresh v1.1 completed20pairs but numeric capture0/8; v1.2 canonical rendering completed20pairs. v1.3 adds short/focused claims and one structured-binding repair. Selected32-page actual production ingestion and new-report visual-reference preparation are running next. Completion objective is full evaluation plan, not merely another bounded handoff.


## Authorized completion checkpoint 2026-10-05T10:01:48.002434+00:00

- Work continues under the user's removed project caps; cumulative accounting is retained. No completion or new held-out scores claimed.
- Initial32 and targeted7 actual page dispatches complete, real UI replay/citation click verified, staged legacy restart/idempotency and rollback verified; original DB/warehouse unchanged.
- Same-v5-question OCR37 data comparison:415/498 to425/498 Hit@5,14 recovered/4 regressed; paired CI and all regressions saved. OCR22 expansion is processing before final candidate choice.
- Source-only v8 references frozen:498questions/102numeric relations. Clarifies EGCO report-year scope and corrects CPAXT floating/fixed approximate25:75 relation; preserved old versions. Human confirmation remains0.
- Latest full regression368passed/5skipped. Local embedding batching retains cosine direction in two real endpoint probes; runtime probes competed with corpus preparation and are not controlled speed benchmarks. Cross-process ledger tested with six synthetic workers,60attempts; no real parallel SDK work yet.
- Whole new-issuer native corpus prepared:BCP/WHAUP/CPN,1980chunks. Blind references and final inference still pending; no new-report scores used to tune.
- Next: completed OCR22 data comparison, real capture20 and judge,50paired and judge,original-image relationship audit,new-report final test,final reports/evidence. Full plan completion remains the objective.


## Continuation checkpoint 2026-10-07 (Asia/Bangkok)

- Continuing the same plan under the user-authorized removed project caps; full access was selected by the user. No usage reset.
- New evidence root: TestFile/evaluation_completion_2026-10-07. Report checkpoint: docs/evaluation-completion-2026-10-07/REPORT_th.md.
- New app capture v1.8; scorer v1.9 and contract replay v2.8; source label corrections v9-v11 preserve previous raw results.
- Matched 50-pair generation v2 complete: both arms capture 49/50 (98%), required numeric measurable19/20 (95%). Actual-link judging plus verifiable original-fragment follow-up passed measured dispatch coverage gates. Quality targets remain unmet.
- 257 regression tests passed after the keyword-baseline nullable-similarity adapter repair.
- Live upload/scraped-file preparation matched all8 durable page checkpoints and source hashes in an isolated DB; zero newOCR/cloud calls for that check. Original real32-page Typhoon/Gemini evidence remains separately scoped.
- Three new Thai reports have133 questions/15controls and114 numeric tuples; full native corpus1980chunks. Final four-arm transfer is currently running with code/inputs frozen.
- First transfer attempt stopped on generic baseline adapter failure; seven question IDs had partial exposure. All first-attempt outputs retained. Fresh full comparison is final133_v2; record technical-repair repeat exposure and do not call it pristine never-exposed questions.
- Supervised follow-on waits for532 generated outputs, then performs actual-link/claim audit and verified evidence packaging. Do not start a duplicate run or tune the frozen app based on final answers.
- Quality objective is still partial; no500-1000 expansion, no thesis certification, no commit/push/deploy or production DB deletion.


## Final generation saved — 2026-10-07

- All133 questions ×4 systems =532 actual outputs saved in final133_v2. Every record/error/refusal remains in scope. New-report capture and numeric coverage are below95%; quality goal remains partial.
- Initial frozen retrieval on118 positive questions is measured with zero cloud calls. Controls15 are excluded from retrieval denominators.
- Original claim/citation audit is active; three separate processes of the unchanged audit code check future arms and publish only exact-payload caches. This is operational concurrency, not a model/scorer/prompt/label change. Original cached outcomes win; both measured and failed decisions are imported. All shard traces and any overlapping SDK attempts are retained.
- Windows file-lock recovery resumed the existing DB and185 saved paid outputs without regeneration. See FINAL_IO_REPAIR_DISCLOSURE.json.
- Approximate workflow completion is90%; final judging/package are pending. No100% quality acceptance claimed.


## Final evaluation delivery — 2026-10-07

All532 final answers and judge outcomes are saved; offline integrity/metric reproduction passed. See docs/evaluation-completion-2026-10-07/REPORT_th.md, COMPLETION_STATUS.md, METRICS.json and ARCHIVE_VERIFICATION.json. Approximate full-plan workflow completion90–95%; quality objective remains partial. This is native-report transfer with disclosed technical-repair exposure, not pristine never-exposed questions or certified full-report OCR. Interrupted accounting is preserved as lower bounds, not reset. No500–1000 expansion while quality gates fail. Next actions/commands are recorded in that report directory.


## Stage2 chat handoff prepared — 2026-10-07

User prefers a fresh chat at each major-topic boundary. Handoff: docs/STAGE2_EVALUATION_PLAN_HANDOFF_2026-10-07.md; proposed title: Stage2: Evaluation Plan — Numeric Binding & Capture Quality. This is the next chat round of the same quality objective, not a new budget or a renumbering of original plan steps. No new chat dispatched and no new evaluation/model calls started in this handoff preparation. Keep the verified evidence archive unchanged.


## User-approved A/B/C chat grouping — 2026-10-08

Latest controlling chat plan: docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md. A=Stage2+4 (numeric/capture and context/table), B=Stage3+5 (retrieval and real ingestion acceptance), C=Stage6+7 (new-report final evaluation and delivery). This supersedes earlier one-chat-per-stage transfer instructions; original Astra steps/targets and cumulative resource accounting remain intact. User authorized starting a new chat for A now. Use the existing goal, preserve the dirty checkout and old evidence, and do not launch B/C before their dependencies/gates.


## Stage B dispatched under continuing goal — 8 ตุลาคม 2026

ผู้ใช้สั่งทำต่อทีละstageจนจบและให้สร้างแชทใหม่เองที่topicboundary. เปิด B: Gemini Evaluation — Retrieval & Real Ingestion, thread01a117cb-521a-7950-8a74-9d3ffa1cbaaa, local projectเดิม. Ownershipdocs/EVALUATION_CHAT_OWNERS_2026-10-08.jsonย้ายB; Aไม่แก้appพร้อมB. Goalหลักยังactive/qualitypartial ไม่สร้างledger/budgetใหม่. BรับStage3+5และเตรียมCเมื่อdependenciesพร้อม;DoclingหลังจบGemini.


## Stage3 / B checkpoint 2026-10-08

Same-v11 paired498 complete: lexical465/498 in both table-data arms; sourcepayload123→166/169,0Hit regressions,MRRone-ranktradeoff preserved. Existingpolicy421→465,recovered57/regressed13 reviewed; no new rankingconfig/cloud. Source/table/N/A caveats and18literal/36oldjudgefailures retained. docs/evaluation-B-2026-10-08/STAGE3_REPORT_th.md and STAGE3_METRICS.json. Qualitygoalpartial; Stage5 real32 begins next, no Docling/C yet.
