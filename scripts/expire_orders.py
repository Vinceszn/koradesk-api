"""Release expired unpaid order reservations. Run from the commerce scheduler."""
from app.db import SessionLocal
from app.commerce_orders import expire_due


def main():
    with SessionLocal() as db:
        print(f"Expired {expire_due(db)} order reservations.")


if __name__ == "__main__":
    main()
