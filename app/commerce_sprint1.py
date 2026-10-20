"""Account and catalogue maintenance, using the merchant application's guards."""
import csv
import io
import logging
import os
import re
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app import commerce as c, commerce_models as m, commerce_mail
from app.db import get_session

router = APIRouter()

class AccountLinkRedaction(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = re.sub(r"(/account/(?:reset|verify)/)[^/?\s]+", r"\1[redacted]", str(args[2]))
            record.args = tuple(args)
        return True

logging.getLogger("uvicorn.access").addFilter(AccountLinkRedaction())

def optional(value, label, limit):
    value = str(value or "").strip()
    if len(value) > limit:
        raise HTTPException(400, f"{label} must be at most {limit} characters.")
    return value

def password(value):
    value = str(value)
    if not 12 <= len(value) <= 128:
        raise HTTPException(400,"Use a password between 12 and 128 characters.")
    return value

def account_page(request, mode, **values):
    csrf = secrets.token_hex(32)
    response = c.templates.TemplateResponse(request,"account.html",dict(mode=mode,csrf=csrf,preview_mail=c.settings.env=="dev" and os.getenv("COMMERCE_MAIL_MODE")=="file",**values))
    response.set_cookie("kora_form",csrf,httponly=True,secure=c.settings.env != "dev",samesite="strict",max_age=1800)
    return response

def throttle(request, db, email):
    now = int(time.time())
    host = request.client.host if request.client else "local"
    keys = [c.digest("mail-ip:" + host), c.digest("mail-address:" + email)]
    for key, limit in zip(keys,[15,3]):
        count = db.scalar(select(func.count()).select_from(m.LoginAttempt).where(m.LoginAttempt.key==key,m.LoginAttempt.at>now-900))
        if count >= limit:
            raise HTTPException(429,"Please wait before requesting another account email.")
    for key in keys:
        db.add(m.LoginAttempt(key=key,at=now))
    db.commit()

@router.get("/businesses")
def businesses(request: Request, db: Session=Depends(get_session)):
    user,login=c.identity(request,db)
    merchants=db.execute(select(m.Merchant,m.Membership.role).join(m.Membership).where(m.Membership.user_id==user.id)).all()
    return c.templates.TemplateResponse(request,"businesses.html",dict(user=user,csrf=login.csrf,merchants=merchants))

@router.get("/account")
def account(request: Request, db: Session=Depends(get_session)):
    user,login=c.identity(request,db)
    return c.templates.TemplateResponse(request,"account.html",dict(mode="account",user=user,csrf=login.csrf))

@router.get("/forgot-password")
def forgot(request: Request):
    return account_page(request,"forgot")

@router.post("/forgot-password")
async def request_reset(request: Request, db: Session=Depends(get_session)):
    data=await c.form_data(request,request.cookies.get("kora_form",""))
    email=c.email_value(data.get("email",""))
    throttle(request,db,email)
    try:
        commerce_mail.configuration()
    except RuntimeError:
        raise HTTPException(503,"Account email is unavailable. Please try again later.")
    user=db.scalar(select(m.User).where(m.User.email==email))
    if user:
        try:
            await issue_mail(db,user,"reset")
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            logging.getLogger(__name__).warning("Password recovery delivery failed; request result remains private.")
    return account_page(request,"sent")

async def issue_mail(db,user,purpose):
    raw=secrets.token_urlsafe(32)
    token=m.AccountToken(token_hash=c.digest(raw),user_id=user.id,purpose=purpose,expires=int(time.time())+1800,used=False)
    db.add(token)
    db.commit()
    try:
        await run_in_threadpool(commerce_mail.send_account_mail,user.email,purpose,raw)
    except Exception:
        # Do not log bearer links or provider credentials.
        db.execute(update(m.AccountToken).where(m.AccountToken.token_hash==token.token_hash).values(used=True))
        db.commit()
        raise HTTPException(503,"Account email is unavailable. Please try again later.")

@router.post("/account/verify")
async def request_verify(request: Request, db: Session=Depends(get_session)):
    user,login=c.identity(request,db)
    await c.form_data(request,login.csrf)
    if user.email_verified:
        return c.redirect("/account")
    throttle(request,db,user.email)
    await issue_mail(db,user,"verify")
    return account_page(request,"sent")

def valid_token(db,purpose,raw):
    token=db.get(m.AccountToken,c.digest(raw))
    if purpose not in ("reset","verify") or not token or token.purpose != purpose or token.used or token.expires <= int(time.time()):
        raise HTTPException(400,"This account link has expired or has already been used. Request another link.")
    return token

@router.get("/account/{purpose}/{raw}")
def token_page(request: Request,purpose: str,raw: str,db: Session=Depends(get_session)):
    valid_token(db,purpose,raw)
    return account_page(request,purpose)

@router.post("/account/{purpose}/{raw}")
async def consume_token(request: Request,purpose: str,raw: str,db: Session=Depends(get_session)):
    data=await c.form_data(request,request.cookies.get("kora_form",""))
    token=valid_token(db,purpose,raw)
    new_hash=c.hash_password(password(data.get("password",""))) if purpose=="reset" else None
    user=db.scalar(select(m.User).where(m.User.id==token.user_id).with_for_update())
    consumed=db.execute(update(m.AccountToken).where(m.AccountToken.token_hash==token.token_hash,m.AccountToken.used.is_(False),m.AccountToken.expires>int(time.time())).values(used=True))
    if consumed.rowcount != 1:
        raise HTTPException(409,"This account link was already used.")
    if purpose=="verify":
        user.email_verified=True
    else:
        user.password_hash=new_hash
        db.execute(delete(m.LoginSession).where(m.LoginSession.user_id==user.id))
    db.execute(update(m.AccountToken).where(m.AccountToken.user_id==user.id,m.AccountToken.purpose==purpose).values(used=True))
    db.commit()
    return account_page(request,"verified" if purpose=="verify" else "reset-done")

@router.post("/account/password")
async def change_password(request: Request, db: Session=Depends(get_session)):
    user,login=c.identity(request,db)
    data=await c.form_data(request,login.csrf)
    # Refresh under lock so simultaneous changes cannot authenticate with a stale hash.
    user=db.scalar(select(m.User).where(m.User.id==user.id).with_for_update().execution_options(populate_existing=True))
    if not c.verify_password(str(data.get("current_password","")),user.password_hash):
        raise HTTPException(400,"Your current password was not recognised.")
    user.password_hash=c.hash_password(password(data.get("password","")))
    db.execute(delete(m.LoginSession).where(m.LoginSession.user_id==user.id))
    db.execute(update(m.AccountToken).where(m.AccountToken.user_id==user.id,m.AccountToken.purpose=="reset").values(used=True))
    db.commit()
    return account_page(request,"reset-done")

@router.post("/app/{merchant_id}/settings")
async def business_settings(request: Request,merchant_id: int,db: Session=Depends(get_session)):
    _,login,_,merchant=c.workspace(request,db,merchant_id,owner=True)
    data=await c.form_data(request,login.csrf)
    merchant.name=c.clean(data.get("name",""),"Business name")
    merchant.category=c.clean(data.get("category",""),"Category",80)
    merchant.contact_email=c.email_value(data["contact_email"]) if data.get("contact_email") else ""
    for field,limit in [("phone",40),("address",300),("receipt_note",300)]:
        setattr(merchant,field,optional(data.get(field),field.replace("_"," ").capitalize(),limit))
    location=db.scalar(select(m.Location).where(m.Location.merchant_id==merchant_id))
    location.name=c.clean(data.get("location",""),"Location")
    db.commit()
    return c.redirect(f"/app/{merchant_id}/settings?notice=Business+settings+saved.")

def variant_for(db,merchant_id,variant_id):
    variant=db.scalar(select(m.Variant).where(m.Variant.id==variant_id,m.Variant.merchant_id==merchant_id))
    if not variant:
        raise HTTPException(404,"Variant not found.")
    return variant

@router.get("/app/{merchant_id}/variants/{variant_id}/edit")
def edit_variant(request: Request,merchant_id: int,variant_id: int,db: Session=Depends(get_session)):
    c.workspace(request,db,merchant_id,owner=True)
    ctx=c.context(request,db,merchant_id,"products")
    variant=variant_for(db,merchant_id,variant_id)
    ctx.update(mode="variant",variant=variant,product=db.get(m.Product,variant.product_id))
    return c.templates.TemplateResponse(request,"manage.html",ctx)

@router.post("/app/{merchant_id}/variants/{variant_id}/edit")
async def save_variant(request: Request,merchant_id: int,variant_id: int,db: Session=Depends(get_session)):
    _,login,_,_=c.workspace(request,db,merchant_id,owner=True)
    data=await c.form_data(request,login.csrf)
    variant=variant_for(db,merchant_id,variant_id)
    product=db.scalar(select(m.Product).where(m.Product.id==variant.product_id).with_for_update())
    name=c.clean(data.get("name",""),"Product name",160)
    # Product names are shared by sibling variants. Compare the original name too.
    if data.get("original_name") != product.name:
        raise HTTPException(409,"This product changed. Reload before saving.")
    try:
        version=int(data.get("version",""))
    except ValueError:
        raise HTTPException(400,"Reload the product before saving.")
    result=db.execute(update(m.Variant).where(m.Variant.id==variant.id,m.Variant.version==version).values(
        sku=c.clean(data.get("sku",""),"SKU",64).upper(),label=c.clean(data.get("variant",""),"Variant"),
        price_kobo=c.price_value(data.get("price","")),version=version+1))
    if result.rowcount != 1:
        raise HTTPException(409,"This variant changed. Reload before saving.")
    product.name=name
    db.commit()
    return c.redirect(f"/app/{merchant_id}/products?notice=Product+updated.")

@router.post("/app/{merchant_id}/variants/{variant_id}/archive")
async def archive_variant(request: Request,merchant_id: int,variant_id: int,db: Session=Depends(get_session)):
    _,login,_,_=c.workspace(request,db,merchant_id,owner=True)
    data=await c.form_data(request,login.csrf)
    variant=variant_for(db,merchant_id,variant_id)
    action=data.get("action")
    if action not in ("archive","restore"):
        raise HTTPException(400,"Choose archive or restore.")
    condition = (m.Variant.product_id==variant.product_id) if data.get("scope")=="product" else (m.Variant.id==variant.id)
    db.execute(update(m.Variant).where(condition,m.Variant.merchant_id==merchant_id).values(archived=action=="archive",version=m.Variant.version+1))
    db.commit()
    return c.redirect(f"/app/{merchant_id}/products?archived=1&notice=Catalogue+updated.+Stock+history+is+preserved.")

@router.get("/app/{merchant_id}/catalogue/export")
def export_catalogue(request: Request,merchant_id: int,db: Session=Depends(get_session)):
    c.workspace(request,db,merchant_id,owner=True)
    rows=db.execute(select(m.Product,m.Variant).join(m.Variant).where(m.Product.merchant_id==merchant_id).order_by(m.Product.name,m.Variant.sku)).all()
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["name","variant","sku","price","archived"])
    def safe(value):
        return "'" + value if value.lstrip().startswith(("=","+","-","@")) or value.startswith(("\t","\r","\n")) else value
    for product,variant in rows:
        writer.writerow([safe(product.name),safe(variant.label),safe(variant.sku),f"{variant.price_kobo//100}.{variant.price_kobo%100:02d}",str(variant.archived).lower()])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":'attachment; filename="kora-catalogue-export.csv"'})

@router.get("/app/{merchant_id}/customers/{customer_id}/edit")
def edit_customer(request: Request,merchant_id: int,customer_id: int,db: Session=Depends(get_session)):
    c.workspace(request,db,merchant_id,owner=True)
    customer=db.scalar(select(m.Customer).where(m.Customer.id==customer_id,m.Customer.merchant_id==merchant_id))
    if not customer:
        raise HTTPException(404,"Customer not found.")
    ctx=c.context(request,db,merchant_id,"customers")
    ctx.update(mode="customer",customer=customer)
    return c.templates.TemplateResponse(request,"manage.html",ctx)

@router.post("/app/{merchant_id}/customers")
@router.post("/app/{merchant_id}/customers/{customer_id}/edit")
async def save_customer(request: Request,merchant_id: int,customer_id: int=0,db: Session=Depends(get_session)):
    _,login,_,_=c.workspace(request,db,merchant_id,owner=True)
    data=await c.form_data(request,login.csrf)
    customer=db.scalar(select(m.Customer).where(m.Customer.id==customer_id,m.Customer.merchant_id==merchant_id)) if customer_id else m.Customer(merchant_id=merchant_id)
    if not customer:
        raise HTTPException(404,"Customer not found.")
    customer.name=c.clean(data.get("name",""),"Customer name")
    customer.email=c.email_value(data["email"]) if data.get("email") else ""
    customer.phone=optional(data.get("phone"),"Phone",40)
    customer.notes=optional(data.get("notes"),"Notes",500)
    customer.archived=data.get("archived")=="yes"
    db.add(customer)
    db.commit()
    return c.redirect(f"/app/{merchant_id}/customers?notice=Customer+saved.")
