# Independent second review of the Thai final labels

**Status: pending human review.** The authoring assistant's PDF inspection is
not an independent second reader. A separate reader should open the original
PDF pages and fill in the observed values **before** consulting
`heldout_thai_final_reference_v1.json` or the model predictions. The page links
use 1-based *physical PDF pages*. Thai Union places two printed pages on each
physical page.

Reviewer name/role: ____________________  Date: __________

PDF SHA-256: SCBX `c9f3b1fd6951f696023ae87111797bfefd2dfb49cbdf36e164260d673903a10d`;
Thai Union `61eba982038eb8382a2c78412738fc2562ff2f3ee83d0ffb29d6afc585a3dbd1`.
If a different file version is used, record its hash and page numbering.

For each row, write the value, sign, unit, year, row/column or nearby label,
and any ambiguity in the last column. Do not infer a value from the saved
prediction. After filling all rows, compare against the frozen reference and
mark each as **agree / correction needed / ambiguous**.

| ID | Original PDF page | Thai question | Observed value, unit, year, label, and decision |
| --- | --- | --- | --- |
| TF01 | [SCBX p. 9](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=9) | ในปี 2567 SCBX มีรายได้จากการดำเนินงานเท่าไร หน่วยพันล้านบาท? | |
| TF02 | [SCBX p. 9](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=9) | ข้อมูลสำคัญปี 2567 ของ SCBX ระบุสัดส่วนสินเชื่อด้อยคุณภาพต่อเงินให้สินเชื่อรวมเท่าไร? | |
| TF03 | [SCBX p. 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | ณ สิ้นปี 2567 SCBX มีสินทรัพย์รวมตามงบการเงินรวมเท่าไร หน่วยพันล้านบาท? | |
| TF04 | [SCBX p. 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | ณ สิ้นปี 2567 เงินรับฝากของ SCBX ในตารางฐานะการเงินรวมเท่าไร หน่วยพันล้านบาท? | |
| TF05 | [SCBX p. 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | ปี 2566 ไม่ใช่ปี 2567 SCBX มีรวมรายได้จากการดำเนินงานตามงบรวมเท่าไร หน่วยพันล้านบาท? | |
| TF06 | [SCBX p. 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | กำไรสุทธิส่วนที่เป็นของบริษัท SCBX ในปี 2567 ตามตารางผลประกอบการรวมคือเท่าไร หน่วยพันล้านบาท? | |
| TF07 | [SCBX p. 19](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=19) | ส่วนต่างอัตราดอกเบี้ยสุทธิ NIM ของ SCBX ปี 2567 ในตารางอัตราส่วนทางการเงินเป็นกี่เปอร์เซ็นต์? | |
| TF08 | [SCBX p. 20](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=20) | กำไรสุทธิต่อหุ้นของ SCBX ปี 2567 เท่ากับกี่บาท? | |
| TF09 | [SCBX p. 20](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=20) | เงินปันผลต่อหุ้นของ SCBX สำหรับผลประกอบการปี 2567 ตามตารางข้อมูลหลักทรัพย์เท่าไร? | |
| TF10 | [SCBX p. 33](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=33) | ในปี 2567 ธุรกิจ Gen 2 ของ SCBX คิดเป็นสัดส่วนรายได้รวมกี่เปอร์เซ็นต์? | |
| TF11 | [TU p. 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | ไทยยูเนี่ยนมีรายได้จากการขายปี 2567 เท่าไร หน่วยพันล้านบาท? | |
| TF12 | [TU p. 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | กำไรก่อนหักดอกเบี้ย ภาษี ค่าเสื่อมราคา และค่าตัดจำหน่ายของไทยยูเนี่ยนในปี 2567 เท่าไร หน่วยพันล้านบาท? | |
| TF13 | [TU p. 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | หนี้สินรวมของไทยยูเนี่ยนปี 2567 มีมูลค่าเท่าไร หน่วยพันล้านบาท? | |
| TF14 | [TU p. 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | กำไรสุทธิส่วนที่เป็นของผู้เป็นเจ้าของบริษัทใหญ่ของไทยยูเนี่ยนปี 2567 เท่าไร หน่วยพันล้านบาท? | |
| TF15 | [TU p. 18](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=18) | เงินปันผลต่อหุ้นของไทยยูเนี่ยนในปี 2567 เท่ากับกี่บาท? | |
| TF16 | [TU p. 21](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=21) | ในรายงานปี 2567 ไทยยูเนี่ยนระบุคะแนนรวมจากดัชนีความยั่งยืนดาวโจนส์ DJSI กี่คะแนน? | |
| TF17 | [TU p. 21](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=21) | ปี 2567 ไทยยูเนี่ยนระบุว่าได้รับคัดเลือกเข้า FTSE4Good Emerging Index ติดต่อกันเป็นปีที่เท่าไร? | |
| TF18 | [TU p. 40](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=40) | ตามส่วนภาพรวมการแข่งขันในรายงานไทยยูเนี่ยน ปี 2567 ตลาดซื้อขายปลาทูน่าช่วงครึ่งแรกเติบโตร้อยละเท่าไรเทียบกับปีก่อน? | |
| TF19 | [TU p. 65](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=65) | ระยะเวลาเก็บหนี้เฉลี่ยของไทยยูเนี่ยนในปี 2567 เท่ากับกี่วัน? | |
| TF20 | [TU p. 65](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=65) | ระยะเวลาขายสินค้าเฉลี่ยของไทยยูเนี่ยนในปี 2567 เท่ากับกี่วัน? | |

## Candidate alternate pages and rounding rule

The items below were proposed **after** model outputs were seen. Check each
page independently. Mark **accept / reject / uncertain** and explain why.

| ID | Candidate page | Question for reviewer | Decision and explanation |
| --- | --- | --- | --- |
| TF06 | [SCBX p. 111](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=111) | Does this page independently support the same 2567 SCBX parent net profit asked on p. 19? | |
| TF08 | [SCBX p. 252](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=252) | Does note 41 give the same 2567 consolidated basic earnings per share as p. 20? | |
| TF09 | [SCBX p. 252](https://hub.optiwise.io/storage/151/annual-report/2024/scbx-annual-report-2024-th.pdf#page=252) | Does note 42 state the dividend for 2567 operations, matching p. 20? | |
| TF14 | [TU p. 194](https://tu.listedcompany.com/misc/ar/20250306-tu-or2024-th.pdf#page=194) | Is the 2567 consolidated profit attributable to parent shareholders equivalent to the p. 18 infographic after excluding any discontinued-operation amount? | |

Proposed TF14 rule for this **one label only**: express a supported answer in
**billion baht**, then round to **one decimal place, half up**. Thus an exact
table value can match the infographic's displayed precision. Check whether
the question's wording permits that equivalent value and whether the rule
would accept an incorrect adjacent row, company-only value, year, sign, or
unit. Decision and reason: _______________________________________________

## Sign-off

Frozen-reference disagreements (ID, original label, corrected label, PDF
page, reason): ___________________________________________________________

Candidate alternate-page or rounding disagreements: _____________________

Reviewer signature/name: ____________________  Date: __________
