> **Current update — 8 October 2026:** See [Evaluation Progress and Next Steps](EVALUATION_NEXT_STEPS_2026-10-08.md) and the [full498 English report](GEMINI_RAG_FULL498_REPORT_2026-10-08.md). All498 original outputs now have valid AI judgments; eight conservative RAG scores exceed80%. Numerical and complete-answer targets remain future work. Historical estimates, active-worker statements, and earlier no-push restrictions below are superseded where applicable; the user explicitly authorized publication to `auto1`. Docling remains deferred.

Latest quota clarification (2026-10-08): conserve Codex quota, not Gemini quota. Gemini calls necessary for evaluation and controlled improvements are allowed. Earlier statements restricting broad Gemini judgments for quota conservation reflect a superseded interpretation. Working targets remain >80%; preserve failed/unknown evidence and cumulative metering. See docs/EVALUATION_WORKING_POLICY_2026-10-08.json.

# Evaluation Plan — แผนแชทรับช่วง A/B/C

## คำสั่งล่าสุด: best effort และประหยัดโควต้า

ผู้ใช้ปรับทุกเกณฑ์เป็นเป้าหมายใช้งาน **มากกว่า80%ก็ยอมรับได้**; ให้ทำดีที่สุดอย่างคุ้มโควต้าก่อน และปรับให้ถึงเกณฑ์เดิมอย่างครบถ้วนภายหลัง. นโยบายนี้มีลำดับความสำคัญเหนือข้อความด้านล่างที่คงเกณฑ์เดิมเป็นข้อบังคับของ Gemini. เก็บเกณฑ์เดิมเป็น aspirationและไม่แก้คะแนนเก่า/labels/หลักฐานเพื่อเพิ่มผล. Policy: `docs/EVALUATION_WORKING_POLICY_2026-10-08.json`.

หยุด broad judge รอบcurrent50ที่67/100 recordsตามคำสั่งใหม่; เก็บผลและSDKledgerครบ. Cloud workerหยุดแล้ว; ใช้ offline diagnosis/replayก่อน. Current50capture hybrid96%, lexical94%; numericmeasured hybrid7/19, lexical5/20 ยังต่ำกว่า80%. ยังไม่อ้างว่าทุกเกณฑ์ผ่านหรือGeminiจบ; C/Doclingยังไม่เริ่ม. การหยุดรอบSDKเพื่อประหยัดโควต้าไม่ใช่การยกเลิกงานevaluationทั้งหมด.

## คำสั่งล่าสุด: ปิดรอบ Gemini ก่อน local Docling — 8 ตุลาคม 2026

ผู้ใช้ปรับลำดับให้เน้น evaluation ของ OCR Gemini และปิดรอบนี้ก่อนเริ่ม local Docling โดย **Gemini ยังคงใช้เป้าหมายเดิม** ในแผนหลัก ผู้ใช้ยืนยันว่าการไม่บังคับคะแนน >90% ใช้ **เฉพาะ local Docling**: ให้ปรับตัวชี้วัดให้ดีที่สุดจากการทดลองที่มีเหตุผลและรายงานข้อจำกัดตามจริง ไม่ลดความเข้มของ scorer หรือเปลี่ยน labels เพื่อเพิ่มคะแนน

อัปเดต recovery B: `docs/evaluation-B-2026-10-08/STAGE5_RECOVERY_REPORT_th.md`. Actual32 raw/storedcells166/169; restart/idempotency/rollbackผ่านบนสำเนาDB. Repairedintegration16 capture16/16แต่strictnumeric2/5; nativecontrol16ก็2/5. Current20paired40outputs capture100%, numericcoverage100%แต่strictcorrect3/8ทั้งสองวิธี; complete-answer hybrid13/20, lexical15/20จาก40savedjudgments. Source audit32หลังnecessary year guard118/185strict lower bound; unknown61 ไม่ใช้95%measuredเป็นทั้งชุด. Current50กำลังสร้างเฉพาะ30คู่ที่เหลือ โดย20คู่เดิมและprovidererrorsเก็บครบและcloneownedDB; labels/scorer/corpus/codeคงเดิม. C/Doclingยังไม่เริ่ม; quality goalยังไม่complete.

เริ่มจากแยกคุณภาพ extraction (ข้อความ/เซลล์/แถว/คอลัมน์/ปี/หน่วย/หน้า) ออกจาก retrieval และ answer quality ใช้ baseline/candidate บน source/labels/scorer เดียวกัน เก็บ regressions, missingness, เวลาและทรัพยากรทั้งหมด แล้วดำเนินงาน A/B/C ที่เกี่ยวข้องกับระบบ Gemini ต่อเป็นลำดับก่อนเริ่มรอบ Docling แยก ไม่เปิดสอง backend เป็นงานทดลองพร้อมกัน

ต้องระบุ provider scope ให้ตรงผลจริง: implementation online ปัจจุบันใช้ Typhoon อ่านข้อความและ Gemini อ่านตาราง ยังไม่มีหลักฐานว่าคือ Gemini-only OCR ทั้งหน้า หลังผู้ใช้สั่ง “ทำต่อเลย” ใช้ pipeline เดิมเป็น working assumption และแจ้ง scope ก่อน dispatch; ไม่ถือว่าผู้ใช้เลือก Gemini-only และยังไม่ได้ implement/evaluate Gemini prose. คำถามตัวเลือกเดิมไม่ได้รับคำตอบเฉพาะตัวเลือก จึงต้องรักษาข้อสมมติฐานนี้ในรายงาน

**Checkpoint A ล่าสุด:** `docs/evaluation-A-2026-10-08/REPORT_th.md` และ `METRICS.json`. Gemini table8physicalpages/10regions, frozen sourcecells169: same-v3 baseline123/169→candidate2raw+local header normalization166/169, recovered43/regressed0. Source-reference repairsเปิดเผยและเก็บv1/v2/v3; ไม่ใช้corrected labelsเป็นsystem gain. Capturev1.9: primarycaptured127/133,numericmeasurable109/114 แต่strictcorrect22/109. Broad323testsผ่าน;localstorage7tablesผ่าน. NewSDK36,สะสม≥3347/input≥54,473,794/output≥1,816,995;unknownusageคงไว้. Goalรวมยังpartial. B/C/Doclingยังไม่เริ่ม;handoffBอยู่reportdirectory โดยต้องfreeze stable source/corpusก่อนเริ่ม

Checkpoint งาน A ก่อนเปลี่ยนแผน: `TestFile/evaluation_A_2026-10-08/manifest.json` และ `baseline_code/`; อ่าน evidence เดิมแล้ว ยังไม่แก้ application code, new SDK=0, new OCR=0, ไม่มี owned evaluation worker ค้าง ผล final133 ที่ใช้ diagnosis เป็น development แล้ว งานเดิมและ cumulative ledger ยังคงอยู่

อัปเดตจากคำสั่งผู้ใช้ 8 ตุลาคม 2026 แผนนี้เป็นการจัดกลุ่มแชทล่าสุด ใช้แทนการแยกหนึ่งแชทต่อ Stage ในคำสั่งรับช่วงก่อนหน้า เกณฑ์คะแนนและขั้น 0–7 ในแผน Astra เดิมยังคงเดิม เป้าหมายคุณภาพยังไม่ complete

| ช่วงแชท | Stage รับช่วงที่รวม | ขอบเขต |
|---|---|---|
| A — แก้ข้อมูลและการผูกคำตอบ | 2 + 4 | Numeric binding/capture, หน่วย/ปี/หน้า/entity/measure และข้อมูล/context/ความสัมพันธ์ตารางที่เป็นสาเหตุร่วม |
| B — ค้นหาและตรวจ pipeline จริง | 3 + 5 | Retrieval บนข้อมูลที่นิ่งแล้ว และ ingestion acceptance ผ่านเส้นทางจริงใน test/staging environment |
| C — Final evaluation และส่งผล | 6 + 7 | Freeze ระบบ/ข้อมูล/labels ก่อนทดสอบรายงานใหม่ แล้วตรวจ metrics/รายงาน/แพ็กหลักฐาน |

ลำดับภายใน: **2 → 4 → 3 → 5 → 6 → 7** เก็บ checkpoint แยกแต่ละ Stage แม้อยู่ในแชทเดียวกัน ชื่อ Stage2–Stage7 เป็นเลขแชทรับช่วงของเรา ไม่ใช่การ renumber แผน Astra: Numeric/capture เกี่ยวข้องกับ original steps1/4; Context/table=step3; Retrieval=step2; Ingestion=step5; new reports=step6; delivery=step7

## เริ่มช่วง A

อ่าน `docs/STAGE2_EVALUATION_PLAN_HANDOFF_2026-10-07.md` โดยให้อัปเดต A/B/C นี้มีลำดับความสำคัญเหนือข้อเก่าที่สั่งหยุดก่อน Context/Table ใช้ goal เดิม `docs/goals/2026-10-05-01-rag-evaluation-continuation.md` ต่อ ไม่สร้าง goal/budget ใหม่เพียงเพราะย้ายแชท

เริ่มจาก saved numeric failure cases และต้นฉบับ PDF แยกปัญหา app binding, reference/scorer, extraction/layout และ context แก้ numeric/capture ที่มีหลักฐานก่อน จากนั้นซ่อมหน่วย หัวตาราง ปี และความสัมพันธ์ข้าม chunk เฉพาะส่วนที่จำเป็น ห้ามเติม gold facts ลง output ของแอป ห้ามเปลี่ยนเกณฑ์หรือเลือก best answer เพื่อเพิ่ม headline

ใช้ replay/local tests ก่อน cloud calls; เลือก subset ที่ครอบคลุม failure categories และกรณีเคยผ่านแบบประกาศล่วงหน้า แล้ววัด baseline/candidate ด้วย inputs/labels/scorer เดียวกัน หากจำเป็นต้อง OCR ใหม่ให้ทำเฉพาะหน้าที่มีปัญหาและเก็บ source/page mapping ไม่เปิด full-report OCR หรือ ranking sweeps พร้อมกัน หาก Stage4 ขยายเป็นงาน extraction กว้างมาก ให้ checkpoint และรายงานเหตุผลก่อนแบ่งหัวข้อเพิ่มตามความจำเป็น

เมื่อใช้ final133 วิเคราะห์หรือ tune ให้ถือเป็น development ห้ามอ้าง rerun ว่า unseen ช่วง C ต้องใช้รายงานใหม่และ freeze ใหม่

## การรับช่วงและทรัพยากร

- Evidence root: `TestFile/evaluation_completion_2026-10-07/`
- Latest report: `docs/evaluation-completion-2026-10-07/REPORT_th.md`; metrics: `METRICS.json`; next steps: `NEXT_ACTION.md`
- Completed execution:532 answers,496 valid/36 failed-unresolved judge outcomes; integrity/ZIP verification passed; quality targets remain unmet
- Active ledger: `TestFile/evaluation_completion_2026-10-07/resource_ledger.json`; lineage: `ledger_lineage.json` — use cumulative counters, no reset on chat transfer
- Recorded baseline SDK≥3311/input≥54,347,114/output≥1,802,576; possible interrupted usage remains unknown; cost USD=N/A
- User removed historical project count/token/deadline caps. Account/provider limits, metering, source isolation and quality gates still apply. Do not reimpose historical Oct5 deadline or reset counters
- Preserve dirty/untracked checkout on auto1/5060072 and all old evidence; no destructive production DB operations, push/deploy or human certification
- Verify RUN_STATE and owned processes before starting anything; do not rerun completed generation/final audit blindly

## ขอบเขตการแยกแชท

ผู้ใช้อนุญาตให้เริ่มแชทใหม่ช่วง A แล้ว เริ่มเพียง A ตอนนี้ ไม่เปิด B/C หรือ final test พร้อมกัน เมื่อเปลี่ยน A→B หรือ B→C ให้ทำ handoff สั้น พร้อม results, source/code/dataset versions, current ledger, process ownership, failed experiments และ next command ก่อนรับช่วงในแชทใหม่

รายงาน progress ตาม actual applicable metrics/denominators/unknowns; passing tests/finishing a run does not imply quality acceptance. หาก targets ยังไม่ครบให้คง quality objective เป็น partial


## แชทช่วง A ที่เปิดแล้ว

Thread: 01a11775-34bd-7bf1-b34f-468846d58730 (local). Ownership record: docs/EVALUATION_CHAT_OWNERS_2026-10-08.json. เริ่มเฉพาะ A; B/C ยังไม่เริ่ม ไม่ทำงาน A ซ้ำจากแชทต้นทาง
