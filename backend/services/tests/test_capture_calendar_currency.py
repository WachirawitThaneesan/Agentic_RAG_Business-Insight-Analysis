from decimal import Decimal

from backend.services import answer_capture as c


def test_calendar_date_and_base_year_leave_real_amounts_visible():
    assert c._quantity_values('12000 บาท ปรับเพิ่มตั้งแต่วันที่ 1 กุมภาพันธ์ 2567') == [Decimal('12000')]
    assert c._quantity_values('อย่างน้อย 30 ร้อยละ จากปีฐาน 2563') == [Decimal('30')]
    assert c._quantity_values('วันที่ 1 กุมภาพันธ์ 2567 จัดประชุม 2 ครั้ง') == [Decimal('2')]
    assert c._quantity_values('มีพนักงาน 2563 คน') == [Decimal('2563')]


def test_foreign_dollar_unit_keeps_its_currency_identity():
    q = 'ชำระ 192.5 ล้านดอลลาร์ออสเตรเลีย'
    assert c._value_unit_in_quote(Decimal('192.5'), 'ล้านดอลลาร์ออสเตรเลีย', q)
    assert not c._value_unit_in_quote(Decimal('192.5'), 'ล้านดอลลาร์', q)
    assert not c._value_unit_in_quote(Decimal('192.5'), 'ล้านดอลลาร์สหรัฐ', q)
    assert not c._value_unit_in_quote(Decimal('192.5'), 'ดอลลาร์ออสเตรเลีย', q)
