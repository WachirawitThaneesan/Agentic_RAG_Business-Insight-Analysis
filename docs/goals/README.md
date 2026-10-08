# Goal files — สมุดบันทึกงานข้ามแชท

หนึ่งเป้าหมายใหม่ = หนึ่งไฟล์ Markdown; การย้ายแชทเพื่อทำเป้าหมายเดิมใช้ไฟล์เดิมต่อ ไม่เริ่มงานหรือ deadline ใหม่

| ID | Goal | สถานะ | File |
|---|---|---|---|
| 2026-10-05-01 | Thai RAG evaluation: รับช่วงคืนแรก | partial / bounded continuation delivered | [Goal](2026-10-05-01-rag-evaluation-continuation.md) |

## วิธีใช้

1. คัดลอก [GOAL_TEMPLATE.md](GOAL_TEMPLATE.md) เป็น `YYYY-MM-DD-NN-short-name.md` เมื่อผู้ใช้มีเป้าหมายใหม่
2. เขียนผลที่ต้องส่ง ขอบเขต เกณฑ์จบ และงบก่อนแก้โค้ด; เพิ่มรายการในตารางนี้
3. อ่าน goal ล่าสุด + handoff + raw evidence ก่อนรับช่วง; แยกข้อเท็จจริงจากสมมติฐาน
4. อัปเดต results/decision log/next action หลังแต่ละการทดลอง รวมผลที่แย่ลงและสิ่งที่ revert
5. บันทึก absolute path, branch, dirty code hashes, dataset/scorer version, command, exit code, calls/tokens/runtime และ denominator
6. ก่อนย้ายแชท ระบุ process ที่ยังรัน เจ้าของงาน งบ/เวลาเหลือ และสิ่งที่ห้ามรันซ้ำ
7. ให้ completed เมื่อมีหลักฐานผ่านเกณฑ์ครบ; ใช้ partial/blocked/transferred ตามจริง ไม่บอกว่าจบเพราะหยุดทำ

ไฟล์ .md เป็นบันทึกงาน ไม่ได้สร้างหรือย้าย Codex /goal อัตโนมัติ และไม่ทำให้แอปทำงานขณะเครื่องหลับ


## Latest chat roadmap — 2026-10-08

User-approved grouping A(Stage2+4) → B(Stage3+5) → C(Stage6+7): [Roadmap](../EVALUATION_CHAT_ROADMAP_2026-10-08.md). Continue goal2026-10-05-01; chat transfer does not reset resource counters.
