import re

_DIGITS = re.compile(r"\D+")


def normalize_indian_mobile(raw: str | None) -> str | None:
    """Return +91XXXXXXXXXX for a valid Indian mobile number, else None."""
    if raw is None:
        return None
    digits = _DIGITS.sub("", str(raw))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    return None
