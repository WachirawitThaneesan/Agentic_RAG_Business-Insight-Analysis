# ผลทดสอบหลังรวมโค้ด และนำเข้าข้อมูลเก่าใหม่ — 1 ตุลาคม 2026

## ผลที่ใช้รายงาน: strict scorer v3

ผ่านเมื่อค่าถูก เครื่องหมายถูก หน่วย/สเกลมีเหตุผล ปีตรงบริบท และอ้างหน้าของ PDF ต้นฉบับที่รองรับครบตาม label
นี่เป็นชุดวินิจฉัยที่ใช้พัฒนาแล้ว ไม่ใช่ความแม่นยำบนเอกสารใหม่ และไม่ใช่การรันทวนชุด 499/500 ข้อของอีก branch

| ชุดทดสอบ | ถูกพร้อมหน้ารองรับ | อ้างหน้าถูก | Gemini attempts / สำเร็จ | เวลาคำถามรวม |
|---|---:|---:|---:|---:|
| CP Axtra/EGCO: BM25 + Gemini | 13/20 (65%) | 13/20 | 20 / 20 | 75.7 วินาที |
| CP Axtra/EGCO: agent ปัจจุบัน | 15/20 (75%) | 19/20 | 91 / 74 | 558.2 วินาที |
| ฐานข้อมูลจริง ก่อนนำเข้าใหม่ | 0/15 | 0/15 | 35 / 30 | 218.5 วินาที |
| ฐานข้อมูลจริง หลังนำเข้าใหม่ | 9/15 (60%) | 15/15 | 53 / 45 | 296.9 วินาที |

CP Axtra/EGCO ใช้ PDF ไทย 832 หน้า แต่เฉพาะ selectable text และ embeddings ที่ล็อกด้วย hash; ไม่มี OCR ในรอบนี้
ฐานข้อมูลจริงเป็น PDF สแกน 5 หน้า ชื่อ 1testfile.pdf ที่เคยนำเข้าซ้ำเป็น document 1 และ 4 ใช้ label 15 ข้อที่อ่านจากภาพต้นฉบับ

## ทำอะไรแล้ว

1. ล็อก commit เริ่มต้น 5396857 และ source/reference hashes; เก็บคำตอบเต็ม แหล่งอ้างอิง trace เวลา calls/tokens และ resource samples
2. พบ scorer ไม่รู้จักหน่วย คัน/สาขา/ประเภท/MW/kWh ต่อปี, ปีเป้าหมาย, หมายเลขตาราง/ระดับเครดิต และการ์ดแยกค่า–หน่วย จึงแก้พร้อม regression cases ที่ยังปฏิเสธหน่วย/เครื่องหมาย/สเกล/ปีผิด
3. เพิ่ม label operands ของ L03 จาก PDF หน้า 1: รายได้ดอกเบี้ยสุทธิ 137,152 ล้านบาท (2568), 148,004 ล้านบาท (2567); ตรวจสมการ −10,852 โดยใช้ค่าต้นฉบับ ไม่ได้ยอมรับตัวเลขประกอบที่โมเดลคิดเอง
4. สำรอง PostgreSQL และ DuckDB ก่อนเปลี่ยนข้อมูล เก็บไว้ใน workspace ไม่รวม backup DB/embeddings หรือ credentials ในแพ็กเกจนี้
5. นำเข้าใหม่ผ่าน pipeline ปกติ: Typhoon อ่านข้อความ, Gemini อ่านตาราง รวม Typhoon 6 ครั้ง + Gemini ตาราง 6 ครั้ง เนื่องจากมี retry คุณภาพหน้า 2 หนึ่งรอบ ใช้เวลา 147.0 วินาที
6. ตรวจตารางจากภาพ พบหน่วยรวม ล้านบาท ทับ บาทต่อหุ้น/ร้อยละ, ปี OCR 25688 และปีที่หายจากคอลัมน์เปอร์เซ็นต์ จึงแก้หน่วยรายช่องและเก็บบริบทปี/กลุ่มคอลัมน์ให้ครบ
7. ปี 25688 หนึ่งหัวคอลัมน์ได้รับการแก้เป็น 2568 หลังดู PDF หน้า 5 โดยตรง มี ledger ระบุภาพและ SHA-256; OCR ดิบเดิมถูกเก็บไว้ ปีเสียในเอกสารอื่นจะถูกกัก ไม่ตัดเลขทิ้งโดยเดา
8. สร้าง staging v2/v3 จาก OCR cache ไม่เรียก cloud OCR เพิ่ม ตรวจ 14 facts แบบรายการ+คอลัมน์/ปี+หน่วย+หน้า จาก 11/14 เป็น 14/14 ก่อนนำเข้าแทนข้อมูลจริง IDs 1 และ 4
9. ตรวจหลังนำเข้าจริง: chunks ไม่มีหน้าจาก 34/52 เป็น 0/78; structured rows ขาดหน้า/หน่วย/provider/quality จากทั้งหมด 73 แถว เป็น 0/88; อีก 1 แถวต่อเอกสารที่ OCR ขัดกันยังถูกกัก มี 24 แถวต่อเอกสารที่สถานะ unverified
10. Regression รอบสุดท้าย: **189 passed, 5 skipped** มี Pydantic deprecation warning เดิม 1 รายการ; git diff --check ผ่าน

## ทรัพยากร

| รอบ | Python peak RSS | Ollama peak RSS | GPU peak ที่เก็บได้ | CPU ของ Python |
|---|---:|---:|---:|---:|
| เปรียบเทียบ CP Axtra/EGCO ทั้งรอบ | 371.0 MiB | 3182.9 MiB | ไม่ได้เก็บ peak ในรอบแรก | 43.6 CPU-seconds |
| ก่อนนำเข้าใหม่ | 224.0 MiB | 79.8 MiB | 725 MiB | 12.0 CPU-seconds |
| หลังนำเข้าใหม่ | 221.9 MiB | 80.8 MiB | 729 MiB | 12.5 CPU-seconds |

RSS เก็บประมาณทุกวินาที GPU ทุก 5 samples เป็นค่าที่สังเกตได้ อาจพลาดช่วงพุ่งสั้น ๆ; ไม่รวม compute ของ Gemini/Typhoon หรือหน่วยความจำ Docker VM
hardware_snapshot.json มี snapshot PostgreSQL/Redis แยกไว้ จำนวน calls เป็น SDK invocations รวม application retries; ไม่แอบนับ retries ที่ SDK อาจทำภายใน
local embedding HTTP responses ถูกนับแยกใน summary.json จาก runtime log; OCR กับการตอบคำถามไม่รวมเป็นเปอร์เซ็นต์เดียว

## สิ่งที่ยังไม่ผ่านและควรทำต่อ

| ข้อ | ปัญหาที่พบ |
|---|---|
| L02 | Gemini ตารางถูก 49,565 แต่ Typhoon prose เป็น 49,585 และ agent เลือก prose; ต้องตรวจความขัดกันข้าม prose/table |
| L04 | EPS 20.63 บาทมีในตารางและหน่วยรายช่องถูก แต่ final evidence guard ยังไม่ผูกหน่วยกับแถวที่ตอบ จึงงดตอบ |
| L07, L11, L12, L13 | Agent งดตอบทั้งที่มีหน้ารองรับ; trace มี SQL เอาชื่อไฟล์ไปกรอง document_id และเลือกข้อมูล/บริบทไม่ตรง ต้องกรองด้วย dim_documents และใช้ค่าที่มี schema ตรวจแล้ว |
| อีก 5 ข้อของ CP Axtra/EGCO | อ่านหน้าเจอไม่ได้รับประกันว่าจะเลือกค่าหรือสรุปถูก ดูรายละเอียดใน strict_rescore_v3.json และ saved answers |

SQL schema หลังนำเข้าเก็บหัวปีแบบมีข้อความ/หลายกลุ่มเป็น dim_table_rows เพื่อรักษาความสัมพันธ์ทั้งหมด; fact_financial_metrics ไม่มีแถวในตัวอย่างนี้
ขั้นต่อไปควรทำให้ agent เลือก query จาก schema และ column context ที่มีจริง ไม่ใช้ตัวอย่าง SQL เก่าโดยสมมติว่าทุกตารางเป็น year-only facts
ผล 14/14 เป็นเฉพาะ cells ที่มี label ไม่ยืนยันทุก cell/ทุก chart หรือ PDF ทั้งฉบับ หัวปีที่แก้และ labels ยังเป็น AI review ไม่มี second human certification

## คะแนนแต่ละรุ่นและทำซ้ำ

- main_metrics_frozen_v1.json / legacy_*_metrics_frozen_*.json เก็บผลที่ออกจาก runner เดิม ไม่แก้ทับ
- strict_rescore_v2*.json และ strict_rescore_v3.json เป็นผลตรวจคำตอบเดิมใหม่ที่มีชื่อรุ่นแยก รุ่นที่ใช้สรุปคือ v3 ไม่เรียกโมเดลเพิ่ม
- reference_reviewed_v3 ระบุ operands ที่เพิ่มจากต้นฉบับและยังใช้คำถาม/ค่าหลัก/หน้าเดิม
- hashes, config, package versions, timings, token/call totals และ source ledger อยู่ใน JSON ของแพ็กเกจนี้
- Instrumented runners และ OCR/resource/trace ดิบอยู่ที่ C:\Users\nonga\Documents\Codex\2026-09-25\i-would-currently-rate-the-project\work และ C:\Users\nonga\Documents\Codex\2026-09-25\i-would-currently-rate-the-project\outputs\postmerge_2026-10-01_v1; บนเครื่องนี้ใช้ .venv ของ repo รัน scripts เหล่านั้นได้ แต่ต้องเลือก output version ใหม่เพื่อไม่ทับผล
- ย้ายไปเครื่องอื่นต้องตั้ง repo/workspace paths และมี PDFs ตาม SHA-256, local bge-m3, PostgreSQL และ Vertex/Typhoon credentials ของผู้ทดสอบเอง; ไม่ใช่ automated one-command reproduction package
- ยังไม่ได้รันทดสอบ browser/API demo ในรอบนี้ ใช้ agent entrypoint และ ingestion function เดียวกับ backend โดยตรง

โค้ดและแพ็กเกจผลนี้ยังเป็น working-tree changes ไม่ได้ commit/push เพิ่มในรอบนี้
