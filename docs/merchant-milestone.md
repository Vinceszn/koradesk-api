# Merchant workspace — milestone one

Branch: `codex/merchant-onboarding-mvp`. This is a reviewable first slice of
the commerce proposal, not the entire commerce MVP.

## What works

- Email/password accounts with scrypt password hashing, expiring server-side
  sessions, CSRF checks and persisted login throttling.
- Business creation, owner/staff memberships and one default stock location.
- A merchant may belong to several businesses. Tenant access is checked on
  every merchant route, including mutations. Composite foreign keys prevent
  inventory records referencing another merchant's products or location.
- Products and variants, per-business unique SKU, integer-kobo prices.
- Atomic CSV import of up to 500 variants. Invalid rows or duplicate SKUs
  roll back the entire import.
- One-time opening physical counts. Conditional updates and unique movement
  keys prevent duplicate counts. Balance and append-only movement are committed
  together; zero is a valid counted quantity.
- Expiring staff invitations shared manually using a private link. Acceptance
  requires the invited email account; links can be revoked, and staff removed.
- Staff can read catalogue, stock, team and movements. Owners manage changes.
- Responsive overview, setup checklist, products, inventory and team screens.

## Architecture and compatibility

The merchant app runs as `app.commerce:app`, separately from `app.main:app`.
This avoids exposing the legacy internal admin or starting WhatsApp scheduler
jobs in the merchant process. It reuses Python, SQLAlchemy and PostgreSQL.
There is no new Node application or dependency on Supabase.

New tables use `commerce_` names. Existing shops, pricing, approvals, and message
tables are untouched. New merchants are **not** automatically connected to
legacy WhatsApp shops. That mapping belongs to the later channel integration.
The legacy internal admin continues managing its existing shops; it is not yet
an operations console for the new commerce records.

Database access is server-only. Authorization is enforced in the API and tenant
relationships in PostgreSQL; this milestone does **not** claim PostgreSQL RLS.
Do not expose these tables through a client-accessible database API. RLS and a
restricted runtime database role are additional release hardening if that access
model changes.

## Local preview (no external services)

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts/preview.py --seed
```

Open http://127.0.0.1:8010. Demo account: `ada@example.com`, password
`Kora-preview-2026!`. These are local demo credentials only. You can also
register a fresh account to follow the empty-state onboarding journey.

SQLite data lives in ignored `work/merchant-preview.db`. The preview explicitly
overrides database/environment settings and binds to loopback. It does not run
the legacy scheduler or send WhatsApp, payment or email requests. Invitation
links remain local unless the application is separately deployed.

## PostgreSQL migration and run

Set `DATABASE_URL` to your PostgreSQL database and back it up before deployment.
The migration adds only commerce tables; existing tables need no baseline stamp.

```powershell
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.commerce:app --host 127.0.0.1 --port 8010
```

Use `ENV=production` behind HTTPS for Secure cookies. Configure the proxy to
preserve the public host and scheme, trust forwarded headers only from that
proxy, restrict accepted hosts there, and cap request bodies at 2 MB. Keep the
legacy `/admin` behind its separate access controls. The merchant app itself
does not mount `/admin` or webhook routes.

## Review checklist

1. Sign in to the seeded shop; review desktop and mobile screens.
2. Register a fresh account, create a business and add a product.
3. Download the CSV sample, import it, and record opening quantities.
4. Retry a recorded quantity; confirm it cannot be overwritten.
5. Invite another email, register it in a separate browser, reopen the invitation
   and accept. Check read-only staff access and owner revocation.
6. Run `python -m pytest -q`. The commerce tests use isolated databases and no
   provider calls. Production PostgreSQL concurrency must also be rehearsed.

## Before a public pilot

Review verification (18 October 2026): all 43 automated tests passed. A real
Chrome walkthrough passed login, mobile sign-out, registration, business setup,
product creation, opening count, invitation acceptance, read-only staff access,
and revocation. Desktop and 390px mobile layouts were checked for horizontal
page overflow. Migration upgrade/repeat/downgrade was exercised against SQLite
with an existing legacy table; PostgreSQL SQL generation also passed. A running
PostgreSQL deployment and its concurrent transaction behavior remain unverified.

This local review does not establish production readiness. Add verified-email
and password-recovery delivery, broader abuse controls, deployment monitoring,
backup/restore rehearsal and a tested PostgreSQL deployment. Email delivery is
deliberately absent in this slice; invitations are manually shared.

Next functional increments are receiving/adjusting stock with compensating
movements, orders/reservations/expiry, provider-verified payments and receipts.
There are no sales, reservations, payment processing or refunds in this milestone.
The reserved column is prepared for the next increment and remains zero.
Stock selling value is explicitly labelled as such; it is not cost or profit.
