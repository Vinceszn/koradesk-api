"""Local-only preview with isolated SQLite data and no outbound integrations."""
import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8010)
parser.add_argument("--seed", action="store_true")
args = parser.parse_args()
(ROOT / "work").mkdir(exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + (ROOT / "work" / "merchant-preview.db").as_posix()
os.environ["ENV"] = "dev"
os.environ["COMMERCE_MAIL_MODE"] = "file"
os.environ["COMMERCE_PUBLIC_URL"] = f"http://127.0.0.1:{args.port}"
os.environ["COMMERCE_MAIL_DIRECTORY"] = str(ROOT / "work" / "mailbox")
if not os.getenv("COMMERCE_ACCOUNT_KEY"):
    from cryptography.fernet import Fernet
    key_file = ROOT / "work" / "account-encryption.key"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
    os.environ["COMMERCE_ACCOUNT_KEY"] = key_file.read_text(encoding="ascii").strip()

from sqlalchemy import select
from app.db import Base, engine, SessionLocal
from app import commerce_models as m
from app.commerce import add_variant, hash_password

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
cfg = Config(str(ROOT / "alembic.ini"))
tables = inspect(engine).get_table_names()
# Earlier isolated previews predate Alembic; adopt only that known local schema.
if "commerce_users" in tables and "alembic_version" not in tables:
    command.stamp(cfg, "0001_commerce")
command.upgrade(cfg, "head")
if args.seed:
    with SessionLocal() as db:
        user = db.scalar(select(m.User).where(m.User.email == "ada@example.com"))
        if not user:
            user = m.User(name="Ada Okafor", email="ada@example.com", password_hash=hash_password("Kora-preview-2026!"))
            db.add(user)
            db.flush()
            merchant = m.Merchant(name="Ada’s Everyday", category="Fashion & accessories")
            db.add(merchant)
            db.flush()
            db.add(m.Membership(merchant_id=merchant.id, user_id=user.id, role="owner"))
            location = m.Location(merchant_id=merchant.id, name="Lekki shop")
            db.add(location)
            db.flush()
            for name, label, sku, price, count in [
                ("Everyday T-shirt", "Olive / Medium", "TEE-OLV-M", "8500", 24),
                ("Everyday T-shirt", "Olive / Large", "TEE-OLV-L", "8500", 18),
                ("Canvas tote", "Natural / One size", "TOTE-NAT", "6500", 32),
                ("Ribbed tank", "Cream / Medium", "TANK-CRM-M", "7200", 15),
                ("Linen shirt", "Sand / Large", "LIN-SND-L", "18000", None),
            ]:
                variant = add_variant(db, merchant.id, dict(name=name, variant=label, sku=sku, price=price))
                balance = db.scalar(select(m.Balance).where(m.Balance.variant_id == variant.id))
                if count is not None:
                    balance.counted = True
                    balance.on_hand = count
                    db.add(m.Movement(merchant_id=merchant.id, location_id=location.id, variant_id=variant.id, actor_id=user.id, quantity=count, reason="Opening physical count", idempotency_key=f"opening:{location.id}:{variant.id}", at=int(time.time())))
            db.commit()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.commerce:app", host="127.0.0.1", port=args.port)
