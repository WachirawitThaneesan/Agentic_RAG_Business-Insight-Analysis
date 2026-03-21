"""Quick verification: unit column shift repair with real data from the user's table."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.services.self_correction import _repair_unit_column_shift, validate_table


def test():
    headers = ["รายการ", "2567", "2566", "2565", "2564", "2563"]

    # Broken rows as OCR produces them:
    broken_rows = [
        # Normal rows (no unit) — should NOT be altered
        ["สินทรัพย์รวม", "2,620,074", "2,708,295", "2,636,951", "2,499,109", "2,609,374"],
        ["รายได้ดอกเบี้ย", "156,538", "139,251", "105,428", "99,804", "108,062"],
        ["กำไรสุทธิ (ส่วนที่เป็นของธนาคาร)", "29,700", "32,929", "30,713", "33,794", "23,040"],
        # Unit rows — (%) or (บาท) displaces the first year value
        ["ผลตอบแทนต่อสินทรัพย์ (ROA)", "(%)", "1.10", "1.22", "1.20", "1.32"],
        ["ผลตอบแทนต่อส่วนของเจ้าของ (ROE)", "(%)", "7.81", "9.28", "9.33", "11.17"],
        ["กำไรสุทธิต่อหุ้น", "(บาท)", "4.04", "4.48", "4.18", "4.59"],
        ["ค่าใช้จ่ายต่อรายได้", "(%)", "44.45", "44.50", "43.84", "39.83"],
        ["มูลค่าตามบัญชีต่อหุ้น", "(บาท)", "53.81", "50.50", "46.48", "43.26"],
    ]

    print("=" * 100)
    print("BEFORE repair:")
    print(f"  Headers ({len(headers)} cols): {headers}")
    for r in broken_rows:
        print(f"  {r[0][:42]:<44} {' | '.join(r[1:])}")

    new_h, fixed = _repair_unit_column_shift(headers, broken_rows)

    print()
    print("=" * 100)
    print("AFTER repair:")
    print(f"  Headers ({len(new_h)} cols): {new_h}")
    print("-" * 100)
    for r in fixed:
        print(f"  {r[0][:42]:<44} {' | '.join(r[1:])}")

    # Assertions
    print()
    assert "หน่วย" in new_h, f"FAIL: หน่วย not in headers: {new_h}"
    print("OK  หน่วย column added to headers")

    assert len(new_h) == 7, f"FAIL: expected 7 headers, got {len(new_h)}"
    print(f"OK  Header count = {len(new_h)} (was 6)")

    # Normal row: สินทรัพย์รวม — unit col should be empty, values unchanged
    assert fixed[0][1] == "", f"FAIL: normal row unit col should be empty, got '{fixed[0][1]}'"
    assert fixed[0][2] == "2,620,074", f"FAIL: normal row 2567 wrong: '{fixed[0][2]}'"
    print("OK  Normal row: หน่วย='' , 2567=2,620,074")

    # Unit row: ROA — unit col = (%), 2567 = 1.10
    assert fixed[3][1] == "(%)", f"FAIL: ROA unit col: '{fixed[3][1]}'"
    assert fixed[3][2] == "1.10", f"FAIL: ROA 2567: '{fixed[3][2]}'"
    print("OK  ROA row: หน่วย=(%), 2567=1.10")

    # Unit row: กำไรสุทธิต่อหุ้น — unit = (บาท), 2567 = 4.04
    assert fixed[5][1] == "(บาท)", f"FAIL: EPS unit: '{fixed[5][1]}'"
    assert fixed[5][2] == "4.04", f"FAIL: EPS 2567: '{fixed[5][2]}'"
    print("OK  EPS row: หน่วย=(บาท), 2567=4.04")

    report = validate_table(new_h, fixed)
    print(f"\nOK  Validation confidence: {report.confidence_score:.2f}")
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    test()
