import re


def parse_quantity(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    normalized = text.replace("＋", "+").replace("，", "+").replace(",", "+").replace(" ", "")
    if not re.fullmatch(r"\d+(\+\d+)*", normalized):
        return 0
    return sum(int(part) for part in normalized.split("+") if part)
