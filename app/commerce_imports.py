"""Reviewable catalogue imports. Confirmation revalidates against current records."""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import commerce as c, commerce_models as m
from app.commerce_barcodes import normalize_barcode
from app.commerce_csv import catalogue_rows
from app.db import get_session

router = APIRouter()


async def source(data):
    upload = data.get("file")
    if hasattr(upload, "read"):
        raw = await upload.read(1_000_001)
        name = str(getattr(upload, "filename", "catalogue.csv"))[:150]
    else:
        try:
            encoded = str(data.get("payload", ""))
            if not encoded or len(encoded) > 1_333_336:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            name = str(data.get("filename", "catalogue.csv"))[:150]
        except (ValueError, binascii.Error):
            raise HTTPException(400, "Choose a CSV file and review it before importing.")
    if len(raw) > 1_000_000:
        raise HTTPException(400, "CSV must be smaller than 1 MB.")
    return raw, name


def plan_import(db, merchant_id, raw):
    planned, seen, barcodes = [], set(), set()
    existing = {v.sku: (p, v) for p, v in db.execute(select(m.Product, m.Variant)
        .join(m.Variant, m.Variant.product_id == m.Product.id)
        .where(m.Product.merchant_id == merchant_id)).all()}
    assigned = set(db.scalars(select(m.VariantBarcode.code).where(
        m.VariantBarcode.merchant_id == merchant_id, m.VariantBarcode.archived.is_(False))).all())
    for index, row in catalogue_rows(raw):
        item = dict(line=index, row=row.copy(), status="new", problem="")
        try:
            row["sku"] = c.clean(row["sku"], "SKU", 64).upper()
            row["name"] = c.clean(row["name"], "Product name", 160)
            row["variant"] = c.clean(row["variant"] or "Standard", "Variant")
            price = c.price_value(row["price"])
            if row["sku"] in seen:
                raise HTTPException(400, f"SKU {row['sku']} appears more than once in this file.")
            seen.add(row["sku"])
            matched = existing.get(row["sku"])
            if matched:
                product, variant = matched
                if (product.name, variant.label, variant.price_kobo, variant.archived) != (row["name"], row["variant"], price, row["archived"]):
                    raise HTTPException(400, f"SKU {row['sku']} already exists with different details. Edit that variant in Products or use a new SKU.")
                item["status"] = "skipped"
            elif row.get("barcode"):
                code = normalize_barcode(row["barcode"])
                if code in assigned or code in barcodes:
                    raise HTTPException(400, "This barcode is already assigned or repeated in the file.")
                barcodes.add(code)
                row["barcode"] = code
            item.update(row=row, price=price)
        except HTTPException as exc:
            item.update(status="invalid", problem=str(exc.detail))
        planned.append(item)
    return planned


def review_page(request, db, merchant_id, raw=b"", filename="", planned=None, error="", status=200):
    ctx = c.context(request, db, merchant_id, "products")
    planned = planned or []
    ctx.update(import_plan=planned, filename=filename, payload=base64.b64encode(raw).decode(),
               import_error=error, new_count=sum(p["status"] == "new" for p in planned),
               skip_count=sum(p["status"] == "skipped" for p in planned),
               invalid_count=sum(p["status"] == "invalid" for p in planned))
    return c.templates.TemplateResponse(request, "import_review.html", ctx, status_code=status)


@router.post("/app/{merchant_id}/import/preview")
async def preview(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    _, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    raw, filename = b"", ""
    try:
        raw, filename = await source(data)
        planned = plan_import(db, merchant_id, raw)
    except HTTPException as exc:
        return review_page(request, db, merchant_id, raw, filename, error=exc.detail, status=400)
    invalid = any(item["problem"] for item in planned)
    return review_page(request, db, merchant_id, raw, filename, planned,
                       status=400 if invalid else 200)


async def commit(request, merchant_id, db):
    _, login, _, _ = c.workspace(request, db, merchant_id, owner=True)
    data = await c.form_data(request, login.csrf)
    raw, filename = b"", ""
    try:
        raw, filename = await source(data)
        planned = plan_import(db, merchant_id, raw)
        invalid = next((p for p in planned if p["problem"]), None)
        if invalid:
            raise HTTPException(400, f"CSV row {invalid['line']}: {invalid['problem']} Nothing was imported.")
        added, skipped = 0, 0
        for item in planned:
            if item["status"] == "skipped":
                skipped += 1
                continue
            row = item["row"]
            variant = c.add_variant(db, merchant_id, row)
            variant.archived = row["archived"]
            if row.get("barcode"):
                db.add(m.VariantBarcode(merchant_id=merchant_id, variant_id=variant.id,
                    code=row["barcode"], is_primary=True))
                db.flush()
            added += 1
        db.commit()
    except (HTTPException, IntegrityError) as exc:
        db.rollback()
        message = exc.detail if isinstance(exc, HTTPException) else "A product changed while importing. Nothing was imported. Review the file again."
        # Keep the established error page contract for existing direct upload clients.
        if hasattr(data.get("file"), "read"):
            ctx = c.context(request, db, merchant_id, "products")
            ctx["rows"] = [row for row in ctx["rows"] if not row[1].archived]
            ctx["import_error"] = message
            return c.templates.TemplateResponse(request, "workspace.html", ctx, status_code=400)
        return review_page(request, db, merchant_id, raw, filename, error=message, status=400)
    return c.redirect(f"/app/{merchant_id}/products?notice=Imported+{added}+variants.+Skipped+{skipped}+unchanged+variants.+Stock+quantities+were+not+changed.")


@router.post("/app/{merchant_id}/import/confirm")
async def confirm(request: Request, merchant_id: int, db: Session = Depends(get_session)):
    return await commit(request, merchant_id, db)
