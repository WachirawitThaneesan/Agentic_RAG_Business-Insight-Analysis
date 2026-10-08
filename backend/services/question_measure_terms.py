"""Requested quantity labels from question text only; no reference/answer access.

This module is not enabled in the frozen498 run. It prepares an independently
testable query-label constraint for the next candidate, preserving free output
when a concise quantity label cannot be derived confidently.
"""
import re


def measure_terms(question):
    if not re.search(r'กี่|เท่าใด|เท่าไร|เท่าไหร่|ระดับใด|จำนวน|สัดส่วน|เป้าหมาย|มูลค่า|อายุ|มีค่า', question):
        return []
    terms = []

    def add(text):
        text = re.sub(r'\s+', ' ', text).strip(' ?？,.;:')
        text = text.replace('ที่เป็นเพศ', 'เพศ')
        if 4 <= len(text) <= 180 and not re.search(r'\d|กี่|เท่าใด|เท่าไร|ตามรายงาน|ประจำปี', text):
            if text not in terms:
                terms.append(text)

    patterns = [
        r'ต้อง(?:จัดทำ|ส่ง|ยื่น|เปิดเผย)(.+?)ภายในกี่',
        r'(?:คาดว่าจะ|ตั้งเป้า)(?:สามารถ)?(.+?)ได้ประมาณ(?:เท่าใด|เท่าไร)',
        r'ตั้งเป้า(.+?)(?:เท่าใด|เท่าไร)',
        r'ตั้งเป้าหมายให้มี(.+?)อยู่ในระดับใด',
        r'มี(สัดส่วน.+?)(?:คิดเป็น|เท่าใด|เท่าไร)',
        r'มี(จำนวน.+?)(?:กี่|เท่าใด|เท่าไร)',
        r'มี(.+?)(?:รวม)?กี่(?:คน|แห่ง|สาขา)',
        r'มี(กรรมการ.+?)กี่คน',
        r'มี((?:รายได้|กำไร|สินทรัพย์|ต้นทุน|ค่าใช้จ่าย|มูลค่า|ปริมาณ|เงินปันผล).+?)(?:กี่|เท่าใด|เท่าไร|มีค่า)',
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            add(match.group(1))
    # Relative clauses describing exclusions remain in qualifiers; the core
    # abbreviation and averaging scope still identify the requested quantity.
    match = re.search(r'\(([A-Z]{2,8})\)\s*(เฉลี่ย[^?]+?)(?:ที่ไม่รวม|มีค่า|เท่าใด|เท่าไร)', question)
    if match:
        add(match.group(1)+' '+match.group(2))
    if re.search(r'กี่คนจากกรรมการทั้งหมด', question):
        add('กรรมการทั้งหมด')
    # Declarative quantity questions do not necessarily contain มี: e.g.
    # "ยอดขายรวมมีค่าเท่าไหร่". Keep the visible noun phrase, not the company
    # or the introductory report date. This is a linguistic span, not a label
    # or value obtained from evaluation data.
    noun = (r'(?:ค่าเฉลี่ย|กระแสเงินสด|เงินปันผล|งบประมาณ|สัดส่วน|สินทรัพย์|'
            r'ค่าใช้จ่าย|รายได้|กำไร|ต้นทุน|มูลค่า|ปริมาณ|ยอดขาย|จำนวน|อัตรา|'
            r'เงินลงทุน|หนี้สิน|คะแนน|อายุ)')
    match = re.search('('+noun+r'.+?)(?:มีค่า|คิดเป็น|เท่าใด|เท่าไร|เท่าไหร่|กี่)', question)
    if match:
        add(match.group(1))
    # Requested property can precede its owner instead of following มี.
    # Copy source-independent query words; a ticker is a delimiter, not a
    # dictionary of company or metric aliases.
    property_noun = r'(?:ศูนย์|อสังหาริมทรัพย์|ที่ดิน|สินทรัพย์|ยอดขาย|รายได้|กำไร|เงินปันผล|อัตรา|จำนวน|สัดส่วน)'
    match = re.search('('+property_noun+r'.+?)ของ\s*[A-Za-z][A-Za-z0-9’\x27.]*\s*มี(?:จำนวน)?(?:เท่าใด|เท่าไร|เท่าไหร่|กี่)', question)
    if match:
        add(match.group(1))
        location = re.search(r'กี่(?:คน|แห่ง|สาขา)(ใน[^?？]+)', question)
        if location:
            add(match.group(1)+location.group(1))
    return terms[:8]
