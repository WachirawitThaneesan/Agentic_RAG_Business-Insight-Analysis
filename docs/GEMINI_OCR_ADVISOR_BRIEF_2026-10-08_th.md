# ผลเบื้องต้น: Gemini OCR สำหรับตารางรายงานธุรกิจภาษาไทย

> **ยังไม่ผ่าน >80% ทุกเกณฑ์:** สร้างและตรวจคำตอบจริงครบ 498/498 ข้อแล้ว ไม่มีงานตรวจที่ล้มเหลวค้าง คะแนนด้านคำตอบ/หลักฐานทั้ง 8 ตัวเกิน 80% แม้คำนวณขอบล่างโดยหาร 498 และให้ข้อไม่มีคะแนนเป็นศูนย์ แต่ strict numeric อยู่ที่ 18/102 และตอบครบทุกเงื่อนไขอยู่ที่ 302/498 (60.64%) ดูรายงานครบ 498 ที่ `TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/focus498_report_final_v3/REPORT_th.md` ผล OCR ด้านล่างยังเป็นชุดหน้าที่คัดเลือก และการประเมินความพร้อม 85–90% เดิมถูกถอนแล้ว

ระบบอ่านตารางด้วย Gemini ร่วมกับการปรับหัวตารางแบบ deterministic และตรวจการเก็บข้อมูลผ่าน ingestion จริง ผลนี้เหมาะสำหรับนำเสนอความคืบหน้า ยังเป็น development evaluation บนหน้าที่คัดเลือกไว้

| การตรวจ | ผลที่วัดได้ |
|---|---:|
| Baseline: เซลล์ที่ถูกต้อง | 123/169 — 72.78% |
| Gemini tables + header normalization | 166/169 — 98.22% |
| เซลล์ที่กู้ได้ / เซลล์ที่ถดถอย | 43 / 0 |
| ความแม่นยำเพิ่มขึ้น | 25.44 percentage points |
| เซลล์ที่ยังผิด | 3/169 |
| Fresh ingestion สำหรับ 32 หน้าที่ตรวจ | 32 indexed pages, 341 chunks, 80 structured rows |
| ความตรงกันของ raw/stored cells | 166/169 ทั้งสองส่วน |
| Chunk/row provenance hashes | 341/341 chunks และ 80/80 rows |
| Restart, idempotency และ rollback | ตรวจผ่านบนฐานข้อมูลแยก |

## ข้อความสำหรับนำเสนอ

“การใช้ Gemini อ่านตารางร่วมกับการแก้หัวตารางแบบ deterministic เพิ่มความถูกต้องของเซลล์ที่ตรวจจาก 72.78% เป็น 98.22% บน reference และ scorer เดียวกัน กู้ได้ 43 เซลล์โดยไม่มี regression ในชุดนี้ จากนั้นตรวจ fresh ingestion 32 หน้า พบว่าค่าที่เก็บในฐานข้อมูลรักษาผล raw/stored cells เดิม และตรวจ provenance/restart/idempotency/rollback ผ่านบนฐานข้อมูลแยก”

## วิธีประเมินและขอบเขต

- ชุด OCR เริ่มต้นมี 8 physical development pages จาก 4 รายงาน เป็น 10 regions; denominator ตัวเลข169เซลล์อยู่บน5หน้าตารางจาก3issuers. หน้าควบคุมอื่นไม่ถูกนับเพิ่มเป็น169เซลล์
- Baseline และ candidate เปรียบเทียบบน reference v3 และ scorer เดียวกัน. ผล98.22%เป็น Gemini output ร่วมกับ header normalization ไม่ใช่คะแนนของโมเดล Gemini ล้วน
- ระบบ online ปัจจุบันใช้ Typhoon อ่าน prose และ Gemini อ่านตาราง จึงไม่เรียกว่า Gemini-only OCR ทั้งหน้า
- เป็นหน้าที่ใช้พัฒนา ยังไม่ใช่ผล unseen ทั้งรายงาน; reference เป็น AI/source-reviewed ไม่ใช่ independent human certification
- Text CER/WER และ chart accuracy ยังไม่ได้วัด. การผูกปี/ความสัมพันธ์บางกรณียังไม่ยืนยันทั้งหมด
- คุณภาพคำตอบ RAG เป็นอีกชั้น: strict numeric และ complete-answer ยังต่ำกว่าเป้าหมาย. คะแนนเซลล์98.22%ไม่ใช่ความแม่นยำคำตอบของทั้งระบบ

## งานต่อหลังนำเสนอความคืบหน้า

ตรวจข้อผิดพลาดที่เหลือและ source relationships จากนั้นล็อก configuration และประเมินรายงานใหม่ตาม Stage C. Docling เป็นงานรอบหลังและยังไม่เริ่ม. แผน A/B/C เต็มยังไม่ถูกประกาศว่าเสร็จ

## หลักฐาน

- docs/evaluation-A-2026-10-08/REPORT_th.md — baseline/candidate และวิธีให้คะแนนเดียวกัน
- docs/evaluation-B-2026-10-08/STAGE5_RECOVERY_REPORT_th.md — fresh ingestion และ provenance
- docs/GEMINI_EVALUATION_CHECKPOINT_2026-10-08_th.md — ผลล่าสุดรวม failures/unknowns และ ledger

สรุปนี้ใช้ artifacts เดิม ไม่มี model calls ใหม่ และไม่ได้เปลี่ยน gold/scorer
