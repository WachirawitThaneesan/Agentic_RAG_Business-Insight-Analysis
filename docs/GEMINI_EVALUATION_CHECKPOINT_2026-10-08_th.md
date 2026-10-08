> **Current update — 8 October 2026:** See [Evaluation Progress and Next Steps](EVALUATION_NEXT_STEPS_2026-10-08.md) and the [full498 English report](GEMINI_RAG_FULL498_REPORT_2026-10-08.md). All498 original outputs now have valid AI judgments; eight conservative RAG scores exceed80%. Numerical and complete-answer targets remain future work. Historical estimates, active-worker statements, and earlier no-push restrictions below are superseded where applicable; the user explicitly authorized publication to `auto1`. Docling remains deferred.

# Gemini evaluation checkpoint — 8 ตุลาคม 2026

ปิดรอบตรวจและทดลองนี้แล้ว แต่ยังไม่ยืนยันว่าทุกเกณฑ์ >80% และยังไม่เริ่ม local Docling. ใช้นโยบาย v2: ประหยัด Codex; Gemini ใช้ได้ตามจำเป็น. ไม่มี subagent, production DB write, push/deploy หรือการรับรองโดยมนุษย์.

ตรวจคำตอบเดิมครบ 100/100 และ candidate สองเวอร์ชันครบเวอร์ชันละ 42/42. Reuse เฉพาะ inputs ตรงและ verdict ที่ตรวจซ้ำได้; กู้ schema/quote/index errors แยกชุดและเก็บ raw attempts เดิมทั้งหมด. ไม่แก้ gold/scorer หรือ resume generation50 v1.10 ด้วยโค้ดใหม่.

## ผลคำตอบเดิม 50 คำถามต่อวิธี

| Metric | hybrid | lexical |
|---|---:|---:|
| Factual precision | 96.47% (n=46/50) | 96.58% (n=45/50) |
| Factual recall | 90.00% (n=50/50) | 88.00% (n=50/50) |
| Faithfulness | 100.00% (n=46/50) | 100.00% (n=45/50) |
| Context recall | 98.00% (n=50/50) | 98.00% (n=50/50) |
| Context precision AP | 77.93% (n=50/50) | 83.06% (n=50/50) |
| Answer relevance | 95.00% (n=50/50) | 97.00% (n=50/50) |
| Actual citation precision | 100.00% (n=46/50) | 98.89% (n=45/50) |
| Actual citation recall | 100.00% (n=46/50) | 98.89% (n=45/50) |
| Strict numeric correct / required | 7/20 (35%; measured 7/19) | 5/20 (25%; measured 5/20) |
| Capture coverage | 48/50 (96%) | 47/50 (94%) |
| Complete-answer lower bound | 31/50 (62%) | 30/50 (60%) |

Complete-answer มี unresolved 3 คำตอบต่อวิธี แม้ judge valid ครบ: การตรวจรูปแบบผ่านไม่ทำให้มิติที่หลักฐานไม่พอกลายเป็น pass. คะแนนเนื้อหาเป็น provisional AI + quote binding; citation ใช้ลิงก์ที่แอปส่งจริง. Context precision AP ต่างจากสัดส่วน context ที่ useful (hybrid21.04%, lexical23.79%).

## Controlled candidate comparison: 21 คำถามชุดเดียวกัน

ใช้ทุก 18 คำถามตัวเลข/20 tuple ใน baseline50 พร้อม narrative1และ former-pass qualitative2. Corpus/model/labels/scorer เหมือนเดิม; ไม่มี unanswerable controls ใน baseline50 และเป็น development ที่มีการใช้ซ้ำ ไม่ใช่ unseen. Baseline เป็น historical saved output จึงยังมี time/randomness confound.

| Version | Numeric hybrid /20 | Numeric lexical /20 | Former-pass retained hybrid /7 | lexical /5 | Complete lower bound hybrid /21 | lexical /21 |
|---|---:|---:|---:|---:|---:|---:|
| candidate1 | 6 | 6 | 4 | 3 | 5 | 6 |
| candidate2 | 8 | 7 | 5 | 4 | 8 | 7 |

Matched baseline21: numeric7/20และ5/20; complete lower bound7/21และ6/21. Candidate2 เพิ่มสุทธิ แต่เสีย strict former-pass3tuple ในชื่อ measure; ไม่รับ experimental prompt/schema เป็น overall upgrade. โค้ดทุก candidate และทุกผลยังอยู่.

## การเปลี่ยนที่เก็บไว้

เก็บ unit-anchored whitespace-decimal reader ใน grounding และป้องกัน numbered-price-list/การรวมข้ามแหล่ง. Source จริงมี99.31/80.07 แต่ข้อความเป็น `99.\n\n31`/`80. 07`; ไม่แก้ข้อความอ้างอิง. Offline causal replay ของ draft เดิม99คำตอบ เปลี่ยนเฉพาะ4คำตอบจากB0263/B0133ทั้งสองวิธี; former-pass12คำตอบไม่เปลี่ยน. Live candidate ทั้งสองตอบ99.31ได้ แต่ replay นี้ไม่ใช่ headline accuracy ของ configuration สุดท้าย.

คืน capture prompt/schema field descriptions เป็น configuration ก่อนทดลอง โดยคง native NUMBER เดิมจาก handoff; VERSION v1.14 เก็บ compatibility กับ v1.10–v1.13. Complete captured outputs174/174ยัง binding-valid; focused tests85ผ่าน. ยังไม่ได้วัด live full50 ของ configuration สุดท้าย.

Judge: กู้ parent input ผ่าน hash-verified lineage; เก็บ input เมื่อ reuse; คง raw protocol ของ parent; บันทึก dispatch errors; ลดข้อจำกัด array-countฝั่งSDKแต่ตรวจ exact identities/counts/quotes/citations ในแอปเหมือนเดิม. Portable schema กู้B0062/API400ได้ ซึ่งสอดคล้องกับ [ข้อจำกัด structured output ของ Google](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/control-generated-output).

## ข้อจำกัดที่ยังต้องแก้

Numeric inventoryแยก omissions/false refusal, company/measure identity, year/unit/bound/page failures. B0184มีwithin30daysแต่ baselineใช้eq; B0113ขาดper-year; B0004ขาดratio denominator. B0078มี2030บนPDF90แต่OCR90ขาดปี; suppliedPDF65มีtarget2573แต่ frozen page qrelsไม่รับ65. B0132มีyear-scopeจากtableที่ต้องทบทวน. ค่าตรงหรือคำต่างที่ sourceรองรับยังไม่ถูกเปลี่ยนเป็น strict pass.

OCRเป็นTyphoon prose + Gemini tables: selected cells166/169=98.22%; year-relationship audit118/185=63.78% strict lower bound,61unknown. Measured118/124=95.16%ไม่ใช่overallOCRaccuracy. CER/WER/chart accuracyยังไม่วัด. Full corpus3617chunksใช้actual32-page substitutionเท่านั้น; outside3339chunksไม่เปลี่ยน. Retrieval498development: lexical465/498=93.37%, hybrid421/498=84.54%; ไม่อ้างว่าOCRหรือการแก้ครั้งนี้เพิ่มretrieval.

## Resource ledger

รอบนี้เพิ่ม274SDK attempts, known input5,797,076/output138,581tokens, failed callsที่usageไม่ครบเพิ่ม35; paid OCRใหม่0หน้า. สะสม4,146attempts, known input66,945,422/output2,176,847tokens, failed callsusageไม่ครบ431. Pendingจากการหยุดworker1attemptยังคงunknown; ledgerเป็นlower boundsและไม่reset. Cloud costไม่ทราบ.

## หลักฐานและงานต่อ

- [Full50 valid audit](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/current50_judge_portable_v5/contract_summary.json)
- [Candidate1 comparison](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/candidate_comparison21_v1_completed/comparison.json)
- [Candidate2 comparison](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/candidate_comparison21_v2_completed/comparison.json)
- [Numeric/source diagnosis](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/numeric_inventory_v1/summary.json)
- [Causal guard replay](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/decimal_guard_causal_replay_v1/summary.json)
- [Selected configuration / checks](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/SELECTED_CONFIGURATION_OFFLINE_CHECKPOINT.json)
- [Integrity / usage](C:/Users/nonga/OneDrive/Desktop/Project_2/Agentic_RAG_Business-Insight-Analysis/TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/FINAL_INTEGRITY_CHECKPOINT.json)

ก่อน quality sign-off: แก้ identity/page/year/period gapsจากsource โดยเก็บ frozen scoreเดิม; ทำ controlled validation ของconfigurationสุดท้ายและ full/new-report evaluationอย่างมีdenominator. หากแก้ measurement contract ให้ versionและวัดbaseline/candidateเหมือนกัน ห้ามเพิ่มaliasesตามคำตอบเพื่อให้ผ่าน. Docling Cยังไม่เริ่ม; whole quality goalยังไม่complete.
