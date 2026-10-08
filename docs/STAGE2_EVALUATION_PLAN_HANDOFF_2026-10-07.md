> **Current update — 8 October 2026:** See [Evaluation Progress and Next Steps](EVALUATION_NEXT_STEPS_2026-10-08.md) and the [full498 English report](GEMINI_RAG_FULL498_REPORT_2026-10-08.md). All498 original outputs now have valid AI judgments; eight conservative RAG scores exceed80%. Numerical and complete-answer targets remain future work. Historical estimates, active-worker statements, and earlier no-push restrictions below are superseded where applicable; the user explicitly authorized publication to `auto1`. Docling remains deferred.

# Stage2: Evaluation Plan — Numeric Binding & Capture Quality

**Checkpoint A delivered — 8 October 2026:** `docs/evaluation-A-2026-10-08/REPORT_th.md`/METRICS.json/HANDOFF_B.md supersede the pre-action status below. ScopedGeminiTABLEcells123→166/169on samev3references;capturev1.9primary127/133,numericmeasurable109/114,strictcorrect22/109.Qualitygoalpartial;B/C/Doclingnotstarted.Samecumulativeledger≥3347SDK. Readnewcheckpointbeforestarting/resuming anything

**Latest steering — 8 October 2026:** ปิด evaluation ของ OCR Gemini ก่อน local Docling ตามหัวข้อคำสั่งล่าสุดใน `docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md`. Gemini ใช้เป้าหมายเดิม; local Docling เน้นปรับผลให้ดีที่สุดโดยไม่บังคับ >90%. Scope ของ Gemini-only text+tables versus existing Typhoon-text/Gemini-tables ยังรอคำตอบผู้ใช้ ณ checkpoint นี้. งาน A เก็บ baseline แล้ว ยังไม่แก้ code หรือ dispatch cloud เพิ่ม

**Latest user update — 8 October 2026:** ช่วง A รวม Stage2 + Stage4 แล้ว ให้อ่าน `docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md` ก่อน คำสั่งเก่าที่ให้หยุดก่อน Context/Table ด้านล่างถูกแทนที่ด้วยแผน A/B/C นี้ ขอบเขตช่วง A คือ numeric/capture และ context/table ที่มีสาเหตุร่วม; ย้ายแชทเมื่อ A→B ไม่ต้องแยกแชทระหว่าง Stage2 กับ Stage4

ไฟล์รับช่วงสำหรับแชทใหม่ วันที่ 7 ตุลาคม 2026 เป้าหมายเดิมยังไม่ครบ quality targets

ชื่อ Stage2 หมายถึงรอบแชทรับช่วงที่สอง ไม่ใช่การเปลี่ยนลำดับขั้นในแผน Astra: งาน numeric/capture เกี่ยวข้องกับขั้น 1, 3 และ 4; ขั้น 2 ในแผนต้นฉบับคือ Retrieval ซึ่งมีผลประเมินแล้ว แต่ยังมี quality gaps

## อ่านเท่าที่จำเป็นก่อนลงมือ

Repository: `C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis`

- แผนหลัก: `docs/RAG_EVALUATION_IMPROVEMENT_PLAN_2026-10-05.md` โดยเฉพาะข้อ 4, 7.3, 9 และ 10
- สรุปล่าสุด: `docs/evaluation-completion-2026-10-07/COMPLETION_STATUS.md`
- รายงาน/งานต่อ: `docs/evaluation-completion-2026-10-07/REPORT_th.md` และ `NEXT_ACTION.md`
- Goal เดิม: `docs/goals/2026-10-05-01-rag-evaluation-continuation.md` อ่าน checkpoint ล่าสุดก่อน historical sections ไม่สร้าง Goal ซ้ำเพียงเพราะย้ายแชท
- Raw root: `TestFile/evaluation_completion_2026-10-07/`

ไม่ต้องโหลด transcript เก่าทั้งหมดหรืออ่านทุก artifact ตั้งแต่ต้น ให้เปิด per-question evidence เฉพาะกรณีที่จะวินิจฉัย

## สถานะที่พิสูจน์แล้ว

- Final run เสร็จ: 133 questions × 4 systems = 532 answers; 496 valid judge outcomes และ 36 failed/unresolved outcomes เก็บครบ ไม่มี evaluation worker ค้างตาม checkpoint ล่าสุด แต่ตรวจ RUN_STATE/PID ก่อนเริ่มเสมอ
- Frozen backend/inputs และ exact judge payload hashes ตรวจผ่าน; metric reproduction แบบ offline และ ZIP CRC/SHA ผ่าน
- Workflow completion estimate 90–95% เป็นการประมาณความคืบหน้างาน ไม่ใช่ accuracy; quality_goal_completed=false และ human_confirmed=false
- `lexical_first`: capture 124/133 = 93.23%; numeric measurable 106/114 = 92.98%; strict literal tuple correct 22/106 = 20.75%; initial Hit@5 97/118 = 82.20%; answerable complete lower bound 36/118 = 30.51%
- Numeric decomposition: 78 bound tuples มี checks; value+unit ผ่าน 57/78; literal company/measure-only failures 20; physical-page failures 28 (failure dimensions ซ้อนกันได้)
- Literal identity-only failures ยังไม่ได้พิสูจน์ว่าเป็น synonyms ที่ถูกต้อง ห้ามถือว่าทั้ง 20 กรณีควรผ่าน
- Branch `auto1`, HEAD `5060072`; มี dirty/untracked work เดิมจำนวนมาก ห้าม reset/discard หรือถือว่าทั้งหมดเป็นงานของแชทใหม่

## งานของแชท Stage2

1. ใช้ `final_numeric_components/details.json`, saved answers และ source evidence แยกสาเหตุ: ผิด entity/measure จริงหรือ literal-name mismatch; cited source ID กับ physical page ไม่ตรง; value/unit/year/comparator ผิด; required relation ไม่ถูกส่ง; capture/schema fail
2. ตรวจ source PDF/metadata ของกรณีที่เลือก แยก bug ของ app กับ bug ของ reference/scorer อย่าเพิ่ม aliases หรือเปลี่ยนเกณฑ์เพื่อให้ headline สูงขึ้น หากต้องแก้ label จริงให้ version และเก็บ old raw scores/หลักฐานต้นฉบับ
3. แก้ app numeric binding ด้วยข้อมูลที่แอปมีจริง เช่น registered physical page จาก actual emitted source ID และตรวจความสอดคล้องกับ prose; ห้ามเติมค่าจาก gold/reference ลง output ของแอป
4. ปิด capture gaps และตรวจ failure reasons ของ 36 judges แยก infrastructure/empty response ออกจาก invalid claims/quotes จัด retry อย่างมีเหตุผลด้วย protocol เดิม พร้อมเก็บ failed outcomes และ call journals เดิม
5. ทดสอบ regression ของ bug ที่แก้ แล้ววัด baseline/candidate บน development inputs/labels/scorer เดียวกัน แสดง numerators, denominators, unknowns, recovered และ regressions
6. เมื่อใช้ final133 เพื่อวินิจฉัยหรือ tune แล้วให้จัดเป็น development ห้ามอ้างผล rerun ว่า unseen; future independent final test ต้องใช้ reports ใหม่และ freeze ใหม่

โฟกัสรอบนี้ที่ numeric/capture ก่อน ไม่เปิด ranking sweeps, full-report OCR หรือ 500–1,000-question expansion พร้อมกัน

## กติกาและบัญชี usage

- User เคยยกเลิก project count/token/deadline caps แล้ว ให้ใช้ authorization/checkpoint ล่าสุด ไม่บังคับงบ/วันหมดอายุ historical ที่หัว goal file และไม่ reset counters เมื่อย้ายแชท
- Active ledger: `TestFile/evaluation_completion_2026-10-07/resource_ledger.json`; canonical lineage ใน `ledger_lineage.json`
- ล่าสุด recorded SDK ≥3311, known input ≥54,347,114, known output ≥1,802,576; paid OCR page keys 66 สะสม รอบ continuation นี้เพิ่ม OCR 0 หน้า ค่าที่อาจหายระหว่าง interruption ไม่ทราบ จึงเป็น lower bounds; USD cost=N/A
- Project limits removed ไม่ได้ยกเลิก provider/account limits ให้ใช้ pacing/backoff และ metering ทุก actual API attempt
- เก็บ snapshots/checkpoints และ old raw evidence ทุกชุด; cold meter อาจเริ่ม call journal ใหม่ จึง archive journal ก่อน resume
- ไม่ลบ production DB ไม่ commit/push/deploy โดยไม่อยู่ในคำสั่งผู้ใช้ และไม่ปลอม human certification

## จุดจบรอบและการย้ายหัวข้อ

ส่ง patch, tests, same-input comparison, failure/missingness breakdown และอัปเดต goal เดิม/next action ตามจริง เก็บผลที่ไม่ดีด้วย ไม่ mark quality objective complete หาก targets ยังไม่ผ่าน

ผู้ใช้ต้องการเริ่มแชทใหม่เมื่อเปลี่ยนหัวข้อหลัก ดังนั้นก่อนย้ายจาก numeric/capture ไป Retrieval หรือ Context/Table ให้ทำ checkpoint พร้อมชื่อและ prompt รับช่วง แล้วจบรอบหัวข้อนี้ ไม่เริ่มหัวข้อใหญ่ต่อในแชทเดียวกันโดยอัตโนมัติ

## ข้อความเปิดแชทใหม่

```text
Stage2: Evaluation Plan — Numeric Binding & Capture Quality

รับช่วงเป้าหมายเดิมในโปรเจกต์ Agentic_RAG_Business-Insight-Analysis อ่าน C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/docs/STAGE2_EVALUATION_PLAN_HANDOFF_2026-10-07.md แล้วลงมือแก้ numeric binding และ capture gaps ตามแผน Astra โดยรักษาเกณฑ์เข้มและ old evidence เริ่มจาก local/source diagnosis ไม่รัน final133 ซ้ำโดยไม่จำเป็น ใช้ ledger สะสมเดิม และส่ง patch/tests/ผลเปรียบเทียบจริง เมื่อจะเปลี่ยนหัวข้อหลักให้เขียน checkpoint และ prompt สำหรับแชทใหม่ก่อน
```
