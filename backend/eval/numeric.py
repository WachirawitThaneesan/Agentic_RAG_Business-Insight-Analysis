"""Strict, unit-aware numeric matching for evaluation labels.

Only an explicitly named unit permits a scale conversion. Year tokens are
treated as context, not as candidate financial values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


_NUMBER = re.compile(
    r"(?<![\dA-Za-z])(?P<open>\()?(?:(?P<sign>[-−])\s*)?"
    r"(?P<digits>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?P<close>\))?(?![\dA-Za-z])"
)
_YEAR = re.compile(r"(?<!\d)(?:25\d{2}|20\d{2})(?!\d)")
_PAGE_REFERENCE = re.compile(
    r"(?:หน้า(?:\s*(?:PDF|อ้างอิง))?|page|p\.)\s*:?\s*\d+(?:\s*(?:[-–]|และ|,)\s*\d+)*", re.IGNORECASE
)
_DATE = re.compile(r"(?<!\d)\d{1,2}[/-]\d{1,2}[/-](?:25\d{2}|20\d{2})(?!\d)")
_THAI_DAY_MONTH = re.compile(
    r"(?<!\d)\d{1,2}\s+(?:มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|"
    r"กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|[ก-ฮ]{1,3}\.[ก-ฮ]\.)(?![ก-๙])"
)
_AGE_RANGE = re.compile(r"(?<!\d)\d{1,3}\s*[-–]\s*\d{1,3}\s*ปี")
_GENERATION_LABEL = re.compile(
    r"(?:(?<![A-Za-zก-๙])(?:Gen(?:eration)?|เจน|Unit)\s*\d+|(?:หน่วยที่|ระดับที่|ตารางที่)\s*\d+)(?!\d)", re.I
)
_UNIT_AFTER = re.compile(
    r"^\s*(พันล้านดอลลาร์\s*สรอ\.?|ล้านดอลลาร์\s*สรอ\.?|ดอลลาร์\s*สรอ\.?|"
    r"พันล้านดอลลาร์สหรัฐ|ล้านดอลลาร์สหรัฐ|ดอลลาร์สหรัฐ|"
    r"พันล้านบาท|ล้านบาท|พันบาท|บาท\s*ต่อเดือน\s*ต่อคัน|บาทต่อเดือน|บาท|เปอร์เซ็นต์แรก|เปอร์เซ็นต์|ร้อยละ|%|"
    r"ล้านหมายเลข|หมายเลข|ล้านรายการ|รายการ|ล้านบัญชี|บัญชี|ล้านคน|คน|"
    r"ล้านตัน|ตัน|แห่ง|จังหวัด|รีม|เท่า|วัน|คะแนน|คัน|สาขา|ประเภท|เมกะวัตต์|MW(?![A-Za-z])|"
    r"กิโลวัตต์[- ]?ชั่วโมงต่อปี|กิโลวัตต์[- ]?ชั่วโมง|kWh/year(?![A-Za-z])|kWh(?![A-Za-z])|ปี|"
    r"USD\s+billion|USD\s+million|USD|US\$\s+billion|US\$\s+million|US\$|"
    r"billion\s+(?:US\s+)?dollars?|million\s+(?:US\s+)?dollars?|dollars?|"
    r"billion\s+people|million\s+people|people|billion|million)",
    re.IGNORECASE,
)
_UNIT_BEFORE = re.compile(r"(ร้อยละ|เปอร์เซ็นต์|ปีที่)\s*$", re.IGNORECASE)
_NEGATIVE_WORD_BEFORE = re.compile(
    r"(?:ลดลง|หดตัว|ติดลบ|ขาดทุน|ใช้ไป)\s*(?:(?:ร้อยละ|เปอร์เซ็นต์|ประมาณ)\s*)?$"
)
_UNIT_ALIASES = {
    "พันล้านดอลลาร์สรอ.": "usd_billion", "พันล้านดอลลาร์สรอ": "usd_billion",
    "ล้านดอลลาร์สรอ.": "usd_million", "ล้านดอลลาร์สรอ": "usd_million",
    "ดอลลาร์สรอ.": "usd", "ดอลลาร์สรอ": "usd",
    "mw": "เมกะวัตต์", "kwh": "กิโลวัตต์ชั่วโมง",
    "kwh/year": "กิโลวัตต์ชั่วโมงต่อปี",
    "กิโลวัตต์-ชั่วโมง": "กิโลวัตต์ชั่วโมง",
    "กิโลวัตต์-ชั่วโมงต่อปี": "กิโลวัตต์ชั่วโมงต่อปี",
    "เปอร์เซ็นต์": "%", "ร้อยละ": "%", "ปีที่": "ปี",
    "พันล้านดอลลาร์สหรัฐ": "usd_billion", "ล้านดอลลาร์สหรัฐ": "usd_million",
    "ดอลลาร์สหรัฐ": "usd", "คน": "people", "ล้านคน": "million_people",
    "us$": "usd", "dollar": "usd", "dollars": "usd",
    "usdmillion": "usd_million", "usdbillion": "usd_billion",
    "us$million": "usd_million", "milliondollar": "usd_million",
    "milliondollars": "usd_million", "millionusd": "usd_million",
    "millionusdollar": "usd_million", "millionusdollars": "usd_million",
    "us$billion": "usd_billion", "billiondollar": "usd_billion",
    "billiondollars": "usd_billion", "billionusd": "usd_billion",
    "billionusdollar": "usd_billion", "billionusdollars": "usd_billion",
    "millionpeople": "million_people", "billionpeople": "billion_people",
}
_MONEY_SCALE = {
    "บาท": Decimal(1),
    "พันบาท": Decimal(1000),
    "ล้านบาท": Decimal(1000000),
    "พันล้านบาท": Decimal(1000000000),
    "usd": Decimal(1),
    "usd_million": Decimal(1000000),
    "usd_billion": Decimal(1000000000),
}
_COUNT_SCALE = {"people": Decimal(1), "million_people": Decimal(1000000),
                "billion_people": Decimal(1000000000),
                "หมายเลข": Decimal(1), "ล้านหมายเลข": Decimal(1000000),
                "รายการ": Decimal(1), "ล้านรายการ": Decimal(1000000),
                "บัญชี": Decimal(1), "ล้านบัญชี": Decimal(1000000),
                "ตัน": Decimal(1), "ล้านตัน": Decimal(1000000)}
_COUNT_FAMILIES = ({"people", "million_people", "billion_people"},
                   {"หมายเลข", "ล้านหมายเลข"}, {"รายการ", "ล้านรายการ"},
                   {"บัญชี", "ล้านบัญชี"}, {"ตัน", "ล้านตัน"})


@dataclass(frozen=True)
class Mention:
    value: Decimal
    unit: str | None
    start: int
    end: int


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid numeric label: {value!r}") from exc


def normalize_unit(value: str | None) -> str | None:
    if not value:
        return None
    unit = re.sub(r"\s+", "", str(value)).lower()
    return _UNIT_ALIASES.get(unit, unit)


def _year_be(value: int) -> int:
    return value + 543 if 2000 <= value <= 2100 else value


def years_in(text: str) -> list[tuple[int, int, int]]:
    return [(m.start(), m.end(), _year_be(int(m.group()))) for m in _YEAR.finditer(text or "")]


def single_year(text: str) -> int | None:
    years = {year for _, _, year in years_in(text)}
    return next(iter(years)) if len(years) == 1 else None


def year_matches(target_year: int, answer: str) -> bool:
    return _year_be(int(target_year)) in {year for _, _, year in years_in(answer)}


def mentions_in(text: str) -> list[Mention]:
    mentions: list[Mention] = []
    context_spans = [m.span() for pattern in (_PAGE_REFERENCE, _DATE, _THAI_DAY_MONTH, _AGE_RANGE)
                     for m in pattern.finditer(text or "")]
    # A business segment identifier such as "Gen 2" is context, unless the
    # number itself has a unit ("Gen 2%" is a numeric claim).
    context_spans.extend(m.span() for m in _GENERATION_LABEL.finditer(text or "")
                         if not _UNIT_AFTER.match(text[m.end():m.end() + 24]))
    for match in _NUMBER.finditer(text or ""):
        if any(start <= match.start("digits") and match.end("digits") <= end
               for start, end in context_spans):
            continue
        if bool(match.group("open")) != bool(match.group("close")):
            continue
        value = decimal_value(match.group("digits"))
        preceding = text[max(0, match.start() - 40):match.start()]
        if match.group("sign") or match.group("open") or _NEGATIVE_WORD_BEFORE.search(preceding):
            value = -value
        after = _UNIT_AFTER.match(text[match.end():match.end() + 48])
        before = _UNIT_BEFORE.search(text[max(0, match.start() - 16):match.start()])
        unit = normalize_unit(after.group(1) if after else (before.group(1) if before else None))
        if unit is None:
            # Evidence cards may print value and unit on separate labeled lines.
            card = re.match(r"\s*\r?\n\s*(?:\*\*)?หน่วย(?:\*\*)?\s*:\s*(.*)", text[match.end():])
            card_unit = _UNIT_AFTER.match(card.group(1)) if card else None
            if card_unit:
                unit = normalize_unit(card_unit.group(1))
        if unit is None and re.match(r"\s*(?:/|จาก(?:เต็ม)?)\s*\d+(?:\.\d+)?\s*คะแนน",
                                         text[match.end():match.end() + 40]):
            unit = "คะแนน"
        currency_prefix = re.search(r"(?:US\$|USD|\$)\s*$", text[max(0, match.start() - 8):match.start()], re.I)
        if currency_prefix and unit in {None, "million", "billion"}:
            unit = {None: "usd", "million": "usd_million",
                    "billion": "usd_billion"}[unit]
        if unit == "บาท" and re.search(r"ต่อเดือน\s*$", text[max(0, match.start() - 32):match.start()]):
            unit = "บาทต่อเดือน"
        mentions.append(Mention(value, unit, match.start(), match.end()))
    return mentions


def infer_unit(reference: str, target: Any) -> str | None:
    """Find the unit attached to the expected number in the reference answer."""
    expected = decimal_value(target)
    for mention in mentions_in(reference):
        if mention.value == expected and mention.unit:
            return mention.unit
    return None


def question_unit(text: str) -> str | None:
    """Use only a unit explicitly supplied in parentheses in the question."""
    pattern = re.compile(
        r"\(\s*(พันล้านบาท|ล้านบาท|พันบาท|บาทต่อเดือน|บาท|เปอร์เซ็นต์|ร้อยละ|%|คน|รีม|เท่า|วัน)\s*\)",
        re.IGNORECASE,
    )
    units = {normalize_unit(m.group(1)) for m in pattern.finditer(text or "")}
    return next(iter(units)) if len(units) == 1 else None


def _same_value(expected: Decimal, actual: Decimal, tolerance: Decimal,
                rounding_decimals: int | None) -> bool:
    if rounding_decimals is not None:
        quantum = Decimal(1).scaleb(-rounding_decimals)
        return actual.quantize(quantum, rounding=ROUND_HALF_UP) == expected.quantize(
            quantum, rounding=ROUND_HALF_UP)
    return abs(actual - expected) <= tolerance


def _same_quantity(expected: Decimal, expected_unit: str | None, actual: Mention,
                   tolerance: Decimal, rounding_decimals: int | None = None) -> bool:
    if expected_unit is None:
        # A label with no known unit can only certify a bare value.
        return actual.unit is None and _same_value(expected, actual.value, tolerance,
                                                   rounding_decimals)
    if actual.unit is None:
        return False
    if expected_unit in _MONEY_SCALE and actual.unit in _MONEY_SCALE:
        expected_currency = "usd" if expected_unit.startswith("usd") else "thb"
        actual_currency = "usd" if actual.unit.startswith("usd") else "thb"
        if expected_currency != actual_currency:
            return False
        converted = actual.value * _MONEY_SCALE[actual.unit] / _MONEY_SCALE[expected_unit]
        return _same_value(expected, converted, tolerance, rounding_decimals)
    if any(expected_unit in family and actual.unit in family
           for family in _COUNT_FAMILIES):
        converted = actual.value * _COUNT_SCALE[actual.unit] / _COUNT_SCALE[expected_unit]
        return _same_value(expected, converted, tolerance, rounding_decimals)
    return expected_unit == actual.unit and _same_value(expected, actual.value, tolerance,
                                                        rounding_decimals)


def quantity_match(target: Any, value: Any, *, expected_unit: str | None,
                   actual_unit: str | None, tolerance: Any = 0,
                   rounding_decimals: int | None = None) -> bool:
    """Compare explicit bound fields without reparsing a compound unit as prose."""
    expected, actual, tol = decimal_value(target), decimal_value(value), decimal_value(tolerance)
    if not all(n.is_finite() for n in (expected, actual, tol)): return False
    if tol < 0: raise ValueError('tolerance cannot be negative')
    if rounding_decimals is not None:
        if type(rounding_decimals) is not int or not 0 <= rounding_decimals <= 12:
            raise ValueError('rounding_decimals must be an integer from 0 to 12')
        if tol: raise ValueError('Specify either tolerance or rounding_decimals')
    return _same_quantity(expected, normalize_unit(expected_unit),
        Mention(actual, normalize_unit(actual_unit), 0, 0), tol, rounding_decimals)


def _verified_equation_operands(answer: str, expected: Decimal, unit: str | None,
                                allowed: tuple[Any, ...]) -> str:
    """Ignore operand tokens only for a correct equation using independently labeled operands."""
    if not allowed:
        return answer
    number = r"[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    pattern = re.compile(rf"(?<![\dA-Za-z])(?P<a>{number})\s*(?P<op>[+−-])\s*(?P<b>{number})\s*=\s*(?P<c>{number})(?![\dA-Za-z])")
    permitted = {decimal_value(value) for value in allowed}
    characters = list(answer)
    for expression in pattern.finditer(answer):
        a, b, c = [decimal_value(expression.group(key).replace("−", "-")) for key in ("a", "b", "c")]
        actual_unit = _UNIT_AFTER.match(answer[expression.end():expression.end() + 40])
        if a not in permitted or b not in permitted or c != expected or actual_unit is None:
            continue
        if normalize_unit(actual_unit.group(1)) != unit:
            continue
        computed = a + b if expression.group("op") == "+" else a - b
        if computed != c:
            continue
        for key in ("a", "b"):
            start, end = expression.span(key)
            characters[start:end] = " " * (end - start)
    return "".join(characters)


def numeric_match(target: Any, answer: str, *, expected_unit: str | None = None,
                  expected_year: int | None = None, tolerance: Any = 0,
                  allowed_other_values: tuple[Any, ...] = (),
                  allowed_other_quantities: tuple[tuple[Any, str], ...] = (),
                  rounding_decimals: int | None = None) -> bool:
    """Match a signed value, its unit, and its year context.

    An answer with multiple values under the same year is ambiguous and fails.
    A bare value fails when the reference specifies a unit.
    """
    # Calendar-year answers (e.g. a net-zero target) are values, not report-year context.
    if expected_unit == "ปี" and re.fullmatch(r"(?:25|20)\d{2}", str(target)):
        stated = re.findall(
            r"(?:ปี\s*(?:พ\.?\s*ศ\.?|ค\.?\s*ศ\.?)?|พ\.?\s*ศ\.?|ค\.?\s*ศ\.?)"
            r"\s*((?:25|20)\d{2})(?!\d)", str(answer)
        )
        values = [year for _, _, year in years_in(str(answer))] if stated else []
        target_calendar = _year_be(int(target))
        if expected_year is not None:
            context_year = _year_be(int(expected_year))
            values = [year for year in values if year != context_year or year == target_calendar]
        return bool(values) and all(year == target_calendar for year in values)

    expected = decimal_value(target)
    unit = normalize_unit(expected_unit)
    tol = decimal_value(tolerance)
    if tol < 0:
        raise ValueError("tolerance cannot be negative")
    if rounding_decimals is not None:
        if isinstance(rounding_decimals, bool) or not isinstance(rounding_decimals, int) \
                or not 0 <= rounding_decimals <= 12:
            raise ValueError("rounding_decimals must be an integer from 0 to 12")
        if tol:
            raise ValueError("Specify either tolerance or rounding_decimals")
    answer = str(answer or "")
    answer = _verified_equation_operands(answer, expected, unit, allowed_other_values)
    years = years_in(answer)
    target_year = _year_be(int(expected_year)) if expected_year is not None else None
    if target_year is not None and years and target_year not in {y for _, _, y in years}:
        return False

    candidates: list[Mention] = []
    for mention in mentions_in(answer):
        if any(mention.start == start and mention.end == end for start, end, _ in years):
            continue
        if target_year is not None and years:
            # With several years, bind the value to the nearest stated year.
            nearest = min(years, key=lambda y: min(abs(mention.start - y[1]), abs(y[0] - mention.end)))
            if nearest[2] != target_year:
                continue
        candidates.append(mention)

    if not candidates:
        return False
    matches = [m for m in candidates if _same_quantity(expected, unit, m, tol,
                                                        rounding_decimals)]
    if not matches:
        return False
    # A competing number in the same context is not an unambiguous answer.
    # Units of a different dimension (e.g. a percentage beside a baht value)
    # do not compete with the target.
    for mention in candidates:
        if mention in matches:
            continue
        if any(_same_quantity(decimal_value(other), unit, mention, tol)
               for other in allowed_other_values):
            continue
        # Additional currencies are accepted only when independently labeled;
        # this never infers an exchange rate or certifies arbitrary extra facts.
        if any(_same_quantity(decimal_value(value), normalize_unit(other_unit), mention, Decimal(0))
               for value, other_unit in allowed_other_quantities):
            continue
        if unit is None or mention.unit is None or mention.unit == unit or (
            unit in _MONEY_SCALE and mention.unit in _MONEY_SCALE
        ):
            return False
    return True
