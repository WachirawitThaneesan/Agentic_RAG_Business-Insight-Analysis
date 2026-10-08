# Goal: <ชื่อเป้าหมาย>

- ID / วันที่ / timezone:
- สถานะ: planned | active | partial | blocked | transferred | completed
- แชทเจ้าของ / model:
- อัปเดตล่าสุด:
- เป้าหมายที่เกี่ยวข้อง / handoff:

## 1. ผลลัพธ์ที่ผู้ใช้ต้องการ
<อธิบายให้จบในหนึ่งย่อหน้า>

## 2. ขอบเขตและอำนาจตัดสินใจ
- ทำ:
- ไม่รวม:
- ข้อจำกัด/การอนุญาตที่มีแล้ว:

## 3. จุดเริ่มและหลักฐาน
- Repository absolute path / branch / HEAD / dirty changes:
- ข้อมูลและ hash / scorer version / model:
- Baseline พร้อม numerator, denominator, missing และข้อจำกัด:
- Source of truth / raw artifacts:

## 4. เกณฑ์จบที่ตรวจได้
| เกณฑ์ | หลักฐานที่ต้องมี | สถานะ |
|---|---|---|
| <เกณฑ์> | <ไฟล์/ผลจริง> | pending |

## 5. แผนตามลำดับ
1. <งานและ dependency>
2. <งานและ gate>

## 6. งบและเวลา
- Start / deadline (absolute timezone):
- Limits / consumed / remaining / unknown usage:
- เมื่อถึงขีดจำกัดให้ทำอะไร:

## 7. ผลจริงและ decision log
| เวลา | ทดลอง/เปลี่ยนอะไร | ผลและ artifact | รับ/ปฏิเสธ/เหตุผล |
|---|---|---|---|

## 8. คำสั่งและ checkpoint
- Working directory / Python:
- คำสั่งล่าสุด / exit code:
- Process/session ที่ยังรัน:
- งานที่แก้ไปแล้วแต่ยังไม่ตรวจ:
- Secrets: เก็บเฉพาะชื่อ config ห้ามเก็บค่าลับ

## 9. ทำต่อทันที
1. <ขั้นแรกที่ไม่คลุมเครือ>
2. <ขั้นถัดไป>

## 10. ส่งมอบ
- Report / next action / results / code hash:
- สิ่งที่ยังไม่ผ่านและข้อจำกัด:
- ห้ามรายงานว่าเสร็จจนเกณฑ์ในข้อ 4 มีหลักฐานครบ
