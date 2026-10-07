# Kora Desk API — backend service (Phase 1 scaffold)

WhatsApp is the entire UI. This service receives Cloud API webhooks, runs the
agent pipelines (Orders first), enforces human approval on money moves, and
logs every naira of cost. See `../kora-desk/docs/architecture.md` (locked v1)
and `../kora-desk/docs/pricing-model.md` (no-loss edition) — both are binding.

## Run locally (needs Docker)

```bash
cp .env.example .env   # fill WHATSAPP_TOKEN, APP_SECRET, VERIFY_TOKEN
docker compose up --build
```

- API: http://localhost:8000, health at `/health`
- Postgres: localhost:5432 (user `kora`, db `koradesk`, see `.env`)

Expose the webhook to Meta with Cloudflare Tunnel (or ngrok):

```bash
cloudflared tunnel --url http://localhost:8000
```

Then set the Callback URL to `https://<tunnel>/webhook/receive` in the
Meta App Dashboard (WhatsApp → Configuration), using your `VERIFY_TOKEN`.

## Layout

- `app/main.py` — FastAPI app: webhook verify (GET) + ingest (POST), `/health`
- `app/config.py` — settings from environment (pydantic-settings)
- `app/db.py` — engine, session factory, `init_db()` (dev only)
- `app/models.py` — shops, price lists, orders, invoices, payments, stock
  ledger, approvals, message log, cost ledger
- `app/security.py` — webhook signature verification + idempotency helpers
- `app/whatsapp.py` — Cloud API client (send text/buttons, mark read, media)
- `app/matching.py` — pure functions: price lookup, payment fuzzy match
- `app/pipelines/orders.py` — voice/text/photo → draft → approval request
- `app/pipelines/payments.py` — reminder + alert/screenshot matching
- `app/costs.py` — per-shop Meta + AI spend ledger (feeds pricing review)
- `app/scheduler.py` — reminders, 6pm summaries, retention purge (APScheduler)

## Tests (no DB needed)

```bash
pip install -r requirements.txt
pytest -q
```

## Production notes (before real shops)

1. Replace `init_db()` with Alembic migrations.
2. One VPS (4vCPU/8GB) + Postgres + nightly off-box backups; disclose the
   hosting region honestly (/trust must not claim Lagos until true).
3. Meta production: verify the Business Account, approve message templates,
   connect a fresh SMS-capable number (never one already on WhatsApp).
4. Watch the daily cost dashboard from the first automated message.
