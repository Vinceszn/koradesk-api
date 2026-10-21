"""Conservative catalogue imports: tolerate spreadsheet formatting, never guess stock."""
import csv
import io
from fastapi import HTTPException


def catalogue_rows(raw):
    try:
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeError:
        raise HTTPException(400, "Save the file as CSV UTF-8 in your spreadsheet app, then upload it again.")
    text = text.lstrip("\r\n")
    if text.lower().startswith("sep="):
        text = text.split("\n", 1)[-1]
    header = text.splitlines()[0] if text.splitlines() else ""
    delimiter = ";" if ";" in header and "," not in header else ("\t" if "\t" in header and "," not in header else ",")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
    try:
        fields = [field.strip().lower() for field in (reader.fieldnames or [])]
        required = {"name", "variant", "sku", "price"}
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise HTTPException(400, "Include name, variant, sku and price columns. Column order does not matter. Download the sample below.")
        extra = set(fields) - required - {"archived"}
        if extra:
            raise HTTPException(400, "Unsupported columns: " + ", ".join(sorted(extra))[:200] + ". This imports product details only. Record quantities in Inventory.")
        reader.fieldnames = fields
        result = []
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise HTTPException(400, f"CSV row {line} has missing or extra cells. Nothing was imported.")
            row = {key: value.strip() for key, value in row.items()}
            if not any(row.values()):
                continue
            if row.get("archived", "").lower() not in ("", "true", "false"):
                raise HTTPException(400, f"CSV row {line}: archived must be true or false.")
            # Undo the formula-safe prefix emitted by Kora's own export.
            for key in ("name", "variant", "sku"):
                if row[key].startswith("'") and row[key][1:].lstrip().startswith(("=", "+", "-", "@")):
                    row[key] = row[key][1:]
            row["archived"] = row.get("archived", "").lower() == "true"
            result.append((line, row))
            if len(result) > 500:
                raise HTTPException(400, "Import up to 500 variants at a time.")
        if not result:
            raise HTTPException(400, "This CSV has no product rows. Add at least one product below the headings.")
        return result
    except csv.Error:
        raise HTTPException(400, "This CSV has malformed quotes or cells. Export it again as CSV UTF-8.")
