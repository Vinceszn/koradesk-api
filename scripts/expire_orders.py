"""Release all overdue unpaid reservations in bounded transactions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import SessionLocal
from app.commerce_orders import expire_due


def main():
    with SessionLocal() as db:
        total = 0
        while True:
            count = expire_due(db)
            total += count
            if count < 100:
                break
        print(f"Expired {total} order reservations.")


if __name__ == "__main__":
    main()
