"""Validation shared by the catalogue and the future POS scanner."""
import re

from fastapi import HTTPException

_LENGTHS = {"ean8": 8, "ean13": 13, "upca": 12, "gtin14": 14}
_SYMBOLS = frozenset((*_LENGTHS, "code128", "unknown"))


def normalize_barcode(value, symbology="unknown"):
    """Keep codes as strings, including zeroes; validate declared GTIN formats."""
    code = str(value or "").strip()
    if symbology not in _SYMBOLS:
        raise HTTPException(400, "Choose a supported barcode format.")
    if not 1 <= len(code) <= 128 or not re.fullmatch(r"[\x21-\x7e]+", code):
        raise HTTPException(400, "Barcode must contain 1–128 printable characters without spaces.")
    if symbology in _LENGTHS:
        if not code.isascii() or not code.isdigit() or len(code) != _LENGTHS[symbology]:
            raise HTTPException(400, "Barcode length or characters do not match the selected format.")
        weighted = sum(int(digit) * (3 if i % 2 == 0 else 1)
                       for i, digit in enumerate(reversed(code[:-1])))
        if (10 - weighted % 10) % 10 != int(code[-1]):
            raise HTTPException(400, "Barcode check digit is invalid.")
    return code
