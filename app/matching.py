"""Pure matching logic (no DB, no network) — everything here is unit-tested."""

import difflib
import re


def normalize_item_name(name: str) -> str:
    """Lowercase, strip quantities/units/punctuation for fuzzy price lookup."""
    text = name.lower()
    text = re.sub(r"\d+(\.\d+)?\s*(kg|g|l|ml|pcs|packs|bags|cartons|gallons?|×|x)\b", " ", text)
    text = re.sub(r"[^a-z ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def price_lookup(query: str, catalog: list[tuple[str, int]]) -> tuple[str, int] | None:
    """Best price-list match for an extracted item name. None below threshold."""
    needle = normalize_item_name(query)
    if not needle:
        return None
    names = [normalize_item_name(name) for name, _ in catalog]
    matches = difflib.get_close_matches(needle, names, n=1, cutoff=0.55)
    if not matches:
        return None
    index = names.index(matches[0])
    return catalog[index]


def parse_amount_naira(text: str) -> int | None:
    """First plausible naira amount in a bank alert or message."""
    cleaned = text.replace(",", "").replace("₦", " ").replace("NGN", " ")
    for chunk in re.findall(r"\d+(?:\.\d{1,2})?", cleaned):
        try:
            value = float(chunk)
        except ValueError:
            continue
        if 100 <= value <= 100_000_000:
            return int(value)
    return None


def payment_match_score(
    amount: int,
    sender_hint: str,
    invoice_amount: int,
    invoice_customer: str,
    same_day: bool,
) -> float:
    """0–1 confidence that a payment belongs to an invoice. Amount dominates."""
    if amount != invoice_amount:
        if abs(amount - invoice_amount) > max(500, invoice_amount * 0.02):
            return 0.0
        score = 0.4
    else:
        score = 0.6
    if sender_hint and invoice_customer:
        similarity = difflib.SequenceMatcher(
            None, sender_hint.lower(), invoice_customer.lower()
        ).ratio()
        score += 0.3 * similarity
    if same_day:
        score += 0.1
    return round(min(score, 1.0), 3)


AUTO_CLEAR_THRESHOLD = 0.85


def should_auto_clear(score: float, source: str) -> bool:
    """Screenshot-only claims NEVER auto-clear — fraud vector. Alerts may."""
    if source == "screenshot":
        return False
    return score >= AUTO_CLEAR_THRESHOLD
