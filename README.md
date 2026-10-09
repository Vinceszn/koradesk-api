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
- `app/scheduler.py` — reminders, 6pm summaries, retention purge, SLA pages,
  margin alerts (APScheduler)
- `app/admin.py` — internal ops dashboard: shops, approvals inbox, leads,
  costs, prices (`/admin`, Jinja templates in `app/templates/`)
- `app/caps.py` — plan caps, conversation windows, margin + SLA math
- `app/approvals.py` — one decision writer for WhatsApp taps + admin inbox
- `app/ops_mail.py` — ops mail (SMTP; console-logged when SMTP_HOST empty)

## Tests (no DB needed)

```bash
pip install -r requirements.txt
pytest -q
```

## Admin dashboard (internal only)

```bash
docker compose up --build
# open http://localhost:8000/admin/shops
```

- Internal-only v1: no shop logins. In production, put Cloudflare Access
  (email OTP) in front of `/admin` at the tunnel — zero auth code in the app.
- Money copy (reminders, 6pm summary) is hardcoded strings (v1 decision);
  DB templating is v1.1.
- Audit actors are real addresses: WhatsApp taps log the sender number,
  dashboard decisions log `admin:<email>`.

## Ops mail (to founder, extendable)

Stuck approvals (>2h amber, >24h red, hourly check), sub-40% margin alerts
(daily, once per shop per month), and new-lead notices go to `ADMIN_EMAILS`:

```bash
ADMIN_EMAILS=hello@koradesk.com
# later: ADMIN_EMAILS=hello@koradesk.com,ops@koradesk.com
```

SMTP via `SMTP_HOST/PORT/USER/PASS/FROM/TLS` env. With `SMTP_HOST` empty
(local dev) mail is logged to console instead of sent — nothing disappears
silently. Each approval mails once per SLA level; margin alerts dedupe per
shop per month (`ops_alerts`).

## Production notes (before real shops)

1. Replace `init_db()` with Alembic migrations.
2. One VPS (4vCPU/8GB) + Postgres + nightly off-box backups; disclose the
   hosting region honestly (/trust must not claim Lagos until true).
3. Meta production: verify the Business Account, approve message templates,
   connect a fresh SMS-capable number (never one already on WhatsApp).
4. Watch the daily cost dashboard from the first automated message.
