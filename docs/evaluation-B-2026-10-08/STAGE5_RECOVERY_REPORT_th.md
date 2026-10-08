Latest quota clarification (2026-10-08): conserve Codex quota, not Gemini quota. Gemini calls necessary for evaluation and controlled improvements are allowed. Earlier statements restricting broad Gemini judgments for quota conservation reflect a superseded interpretation. Working targets remain >80%; preserve failed/unknown evidence and cumulative metering. See docs/EVALUATION_WORKING_POLICY_2026-10-08.json.

# Stage5 recovery — 8 ตุลาคม 2026

**นโยบายล่าสุด:** ผู้ใช้ให้ทำทุกเกณฑ์ดีที่สุดอย่างคุ้มโควต้าก่อน; >80%ยอมรับได้ และปรับถึงเกณฑ์เดิมอย่างละเอียดภายหลัง. ดู `docs/EVALUATION_WORKING_POLICY_2026-10-08.json`. ข้อความเดิมด้านล่างที่คงold targetsเป็นhard gateเป็นhistorical checkpointแล้ว.

Current50 generation100outputsครบ: hybridcapture48/50=96%, numeric7/19measured(coverage19/20); lexicalcapture47/50=94%, numeric5/20. คะแนนnumericยังไม่ถึง80%;capture94%ต่ำกว่าold95%แต่สูงกว่าworking80%. Broadjudgeหยุดตามคำสั่งใหม่ที่67/100records(64measured,3failed),ไม่ได้เติม33recordsที่ยังไม่ตรวจ; aggregatepartialยังเก็บplanned denominator50ต่อarm. ห้ามนำlexicalpartialjudgeมาเรียกคะแนนครบ50. C/Doclingยังไม่เริ่ม.

หลังหยุด SDK: capturev1.11เปลี่ยนnative numeric value schemaเป็นNUMBERแทนSTRINGเพื่อแยกAAA/AA/Aออกจากช่องจำนวน. ParserรักษาdecimalจากJSONโดยไม่roundผ่านbinaryfloat. Local68testsผ่าน;95oldcompletecapturedoutputsยังbindingvalidทั้งหมด;คำตอบเดิมไม่ถูกเขียนใหม่. NewSDKหลังเปลี่ยนแผน0;cloudaccuracygainยังไม่วัด. Source/scoresเดิมยังอยู่;proof `NATIVE_SCHEMA_OFFLINE_CHECKPOINT.json`. Ledger3872attempts/input61,148,346/output2,038,266;396failedusageincompleteยังเก็บ. ไม่มีresetหรือtoken/countcapที่เดาขึ้นใหม่.

สถานะ **ยัง partial**: Gemini คงเป้าหมายคุณภาพเดิม; C/final และ local Docling ยังไม่เริ่ม ผล integration16 และ cells169 ไม่ใช้แทน gate50.

รับช่วงหลังแชท B สิ้นสุดด้วย usage limit และไม่มี evaluation worker เดิมทำงานแล้ว เก็บผลเดิมทั้งหมดและใช้ cumulative resource ledger เดิมต่อ ไม่ reset. Evidence root: `TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/`.

## ผลที่ตรวจเสร็จ

| การตรวจ | ผล | ขอบเขต |
|---|---|---|
| Actual upload/scraped 32 หน้า | indexed32, chunks341, structured rows80 | Typhoon prose + Gemini tables; PDF ต้นฉบับ 4 รายงาน; DB แยก |
| Raw/stored Gemini cells | 166/169 ทั้งสองชั้น | Source v3/scorer เดิม; ไม่ใช่ความถูกต้องของทั้งรายงาน |
| Provenance | hashes341/341 chunks,80/80 rows; mapped searchable278/278 | ไม่เกิด duplicate indices; unit54/80 ต้องพิจารณาว่าแต่ละแถวต้องมีหน่วยหรือไม่ |
| Fresh CPAXT38 | N/A4ค่าอยู่ใน raw/stored Gemini table | ไม่ตีความเป็นศูนย์; fresh run ไม่ได้ใช้ prose fallback |
| N/A fallback replay | 4ค่า จาก actual provider HTML | Local replay; ไม่อ้างว่าเป็น fresh empty-Gemini integration |
| Repaired answers16 | capture/binding16/16; recovered6; regressed0 | รุ่น capture1.10; โครงสร้างอย่างเดียวไม่รับรองข้อเท็จจริง |
| Factual/citation audit | saved judgments31/32; repaired complete lower bound12/16=75% | repaired numeric2/5=40%, coverage5/5; B0031 judge invalid fragment ยัง unresolved |
| Native route control16 | capture16/16; numeric2/5=40%; 1คำถามมี provider error trace | Same selected32 original pages/questions/current application; route comparisonมีchunking/SQL/summaryแตกต่าง |
| Restart/idempotency/rollback | ผ่าน; duplicate0; restored DB/warehouseตรง snapshot | Cached actual OCR บนสำเนา DB; new SDK0; ต้นทางเดิมไม่เปลี่ยน |
| Real UI | คำตอบ/citationแสดงจริง; observed image URL เปิดภาพถูกหน้า | Replay actual API answer; new SDK0; กดลิงก์แล้ว popup ใหม่ยังยืนยันไม่ได้ใน IAB |

คำตอบเดิมก่อน repair complete lower bound10/16=62.5%; numeric2/3 measured, coverage3/5. จึงห้ามเปรียบเทียบ accuracy2/3กับ2/5เป็น factual improvement. คำตอบใหม่เพิ่มการวัดและ capture; ความผิดเรื่อง tuple ยังคงอยู่.

Audit address รุ่นแรกใช้ page ต้นฉบับเทียบกับ citation ของ subset จึงผิด coordinate space. `answer16_address_audit_v2/` แก้เฉพาะ derived address checks ด้วย original/subset map ที่ source hash ผ่านแล้ว โดย reverse-project emitted bound citations; เก็บ evidence options ทั้งหมด รวม alternatives ที่ไม่ได้ upload. คำตอบ/claims/links/context, independent reference text และ AI judgments เดิมไม่เปลี่ยน. Numeric label view เปลี่ยนเพียง citation address; factual tuple/aliases/scorer เดิม. รุ่นผิดและข้อผิดพลาดของ script ยังเก็บไว้.

## Source relationships และข้อผิดพลาดที่ยังอยู่

Independent original-image probesเดิม32หน้า reuse เฉพาะเมื่อ payload/image hash ตรง; ไม่ reuse extraction verdict เดิม. ตรวจ current extractionใหม่ครบ32หน้า: 31 valid page audits, 1 invalid source-probe page EGCO59 เก็บ unresolved. รุ่นแรกมี quote_unverifiable59และ AI reviewer รับบาง relation ที่ไม่มีปีอยู่ใน extraction.

`relationship32_year_guard_v2/` เพิ่ม necessary year-presence check แบบ offline: ไม่ยอมรับปีจากภาพต้นฉบับแทนปีที่ extractionไม่มี และปีที่ปรากฏก็ยังไม่รับรองว่าผูกกับ relation ถูกต้อง. Demote5กรณี; final118/124 measured, strict lower bound118/185=63.78%, unknown61. ผล measured95.16% **ไม่ใช่ OCR accuracyทั้งชุด**. 1invented/transformed-table verdictและข้อผิดพลาดอื่นยังอยู่.

- EGCO90: source targetปี2573/2030 แต่ actual extracted proseขาด2030. คำตอบทั้ง native/controlและproductionผูกปีรายงาน2567กับค่า10%. ไม่มีการเติมปีจาก goldลง corpusหรือคำตอบ.
- CPAXT132: row typoบริษัทรวม/บริษัทร่วมยังไม่แทนด้วย gold.
- B0004/B0113: strict company/measure identityยังไม่ตรง frozen labels; ไม่เพิ่ม aliases เพื่อทำให้คะแนนผ่าน. Source-grounded semantic reviewแยกจาก headline strict score.
- B0031: fragment identifier นอก bound evidence; เตรียม retryเฉพาะ schema/quote recovery โดยไม่ generateคำตอบใหม่หรือ retry known-wrong verdict.
- PTT39: numbered listถูกแปลงเป็น table; table-structure precisionยังไม่รับรอง.
- 18literal identity cases/36historical unresolved judgesยังไม่ถือว่าผ่านอัตโนมัติ.

## งานที่กำลังทำ

Freeze full development corpus3617chunks: แทนเฉพาะ32original pagesด้วย current actual stored OCR; corpusนอกหน้าเลือก3339chunksผ่าน exact text/metadata equalityใน `OUTSIDE_PAGE_EQUIVALENCE.json`; embeddings reuse, new SDK0. ส่วนอื่นยังเป็น explicitly frozen historical OCR/native ไม่ใช่ full-report fresh production ingestion.

Current smoke20 paired hybrid_current/lexical_first ใช้ original50 selection prefix, labels/scorer/generator/corpusเดียวกันและ counterbalanced order. Freeze code/source hashesก่อน generation. ยังไม่รับรอง gate50 และไม่เริ่ม C. หลังครบต้อง audit capture/citation/numeric coverage และข้อผิดพลาดจริงก่อนขยาย.

Screenshots: `ui_repaired16_v1/chat_answer.jpg`, `citation_image.jpg`. `UI_VERIFICATION.json` เปิดเผย replay mode และ popup limitation. Human_confirmed=false; AI review provisional; production DB/push/deployไม่ถูกดำเนินการ.
