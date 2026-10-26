# Kora Desk API

Kora Desk is a merchant workspace for managing a business, product catalogue, customers, suppliers, and inventory. This repository contains the merchant web application and a separate legacy WhatsApp/internal-admin service.

**Current stage:** Sprints 1 and 2 are implemented and locally verified. Sprint 3 (orders and reservations) is next. Sales, payments, receipts, and a production pilot are still planned.

## What is available

| Area | Built functionality |
|---|---|
| Accounts | Registration, sign-in/out, email verification, password recovery and password changes |
| Businesses | Business setup, settings, and switching between businesses |
| Team | Owner and read-only staff access, invitations and replacement invitations |
| Catalogue | Products and variants, SKU/pricing edits, archive/restore, CSV import and export |
| Customers | Basic customer records |
| Suppliers | Supplier records and supplier details captured on stock receipts |
| Inventory | Opening counts, receiving, purchase costs, adjustments, recounts, reversals, reconciliation, low-stock indicators, and paginated movement history |
| Overview | Stock summaries and charts, with collapsible navigation |

The [latest feature audit](docs/feature-audit.md) records 83 passing automated tests and three browser walkthroughs. These are local verification results, not evidence of production readiness. Live email delivery and production PostgreSQL checks remain outstanding.

## Run the merchant preview

Use Python 3.13 (matching the Docker runtime). Run these commands from the repository root.

**Windows / PowerShell**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.txt
.venv\Scripts\python scripts/preview.py --seed
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python scripts/preview.py --seed
```

Open [the merchant preview](http://127.0.0.1:8010).

For a newly seeded database, sign in with `ada@example.com` and `Kora-preview-2026!`. Seeding does not reset an existing account's password. You can also register a new account.

The preview script applies migrations, uses a local SQLite database, and writes account emails to private local files. It does not start the legacy WhatsApp scheduler or send account emails externally.

| Local resource | Location |
|---|---|
| Preview database | `work/merchant-preview.db` |
| Verification/password-reset emails | `work/mailbox/*.eml` |

Open the latest email file to use its account link. Team invitations are shared manually. Keep these files private; `work/` is ignored by Git.

Use `--port 8011` to choose another port. Stop the preview with Ctrl+C. Existing preview data is retained between runs.

## Product CSV import

Open **Products** in the merchant workspace and use the CSV upload section to download the sample. The old `/import` address redirects there. The required headers are:

```csv
name,variant,sku,price
Classic T-shirt,Small,TSHIRT-S,7500.00
Classic T-shirt,Medium,TSHIRT-M,7500.00
```

- `price` is in naira, with up to two decimal places. An empty variant becomes `Standard`.
- Headers can be reordered; surrounding whitespace and letter case are normalized. `archived` is optional and accepts `true` or `false`.
- Comma, semicolon, and tab delimiters are supported, including a spreadsheet `sep=` line. Use UTF-8 or BOM-marked UTF-16 text, not an `.xlsx` workbook.
- Each upload supports up to 500 product rows and 1 MB.
- Identical existing SKUs are skipped. Conflicting existing SKUs and duplicate SKUs within the file are reported; imports do not silently overwrite products.
- Invalid imports are rejected without partially applying the file.

**CSV import creates catalogue entries; it does not import stock quantities.** Record opening stock in Inventory, then use receiving for additional stock. Bulk stock import and bulk catalogue updates are not implemented.

## Inventory workflow

1. Create or import a product variant.
2. Record its opening stock count.
3. Receive additional stock, optionally recording the supplier, reference, and purchase cost.
4. Use adjustments or recounts to correct stock, with a reason. Reverse eligible entries through compensating movements to preserve the audit history.
5. Review movement history, reconciliation, and low-stock indicators.

Receiving currently handles one variant at a time; multi-item receiving is pending. Low-stock indicators appear inside the app. Stock value based on selling prices is not a profit or accounting report.

## Two separate applications

| Application | Entry point | Purpose | Default local port |
|---|---|---|---|
| Merchant workspace | `app.commerce:app` | Merchant accounts, catalogue, customers, suppliers, and stock | 8010 via the preview script |
| Legacy service | `app.main:app` | WhatsApp webhooks, legacy pipelines, scheduled jobs, and internal admin | 8000 via Docker Compose |

Merchant businesses are not automatically connected to legacy shops, orders, payments, or WhatsApp conversations. That integration is planned for a later sprint.

## Merchant database and account email configuration

For a non-preview environment, configure `DATABASE_URL`, back up existing data, and apply migrations before starting the application:

```bash
python -m alembic upgrade head
python -m uvicorn app.commerce:app --host 127.0.0.1 --port 8010
```

Run these commands with the repository virtual environment's Python. The preview script deliberately selects its own SQLite database and development mail settings; it is not a production launcher.

Account email settings are read directly from the **process environment**. Adding only these `COMMERCE_*` variables to `.env` is not sufficient; export them in the shell or configure them in the service environment.

| Variable | Purpose |
|---|---|
| `COMMERCE_MAIL_MODE` | `smtp` for delivery, `file` for local development; defaults to disabled |
| `COMMERCE_PUBLIC_URL` | Public HTTPS origin used for account links, without a path, query, or fragment |
| `COMMERCE_MAIL_FROM` | Sender email address; required for SMTP |
| `COMMERCE_SMTP_HOST` | SMTP server; required for SMTP |
| `COMMERCE_SMTP_PORT` | SMTP port, default `587` |
| `COMMERCE_SMTP_USER` / `COMMERCE_SMTP_PASSWORD` | Authentication credentials when required by the mail server |
| `COMMERCE_MAIL_DIRECTORY` | Private output directory for local file-mode emails |

SMTP uses certificate-verified STARTTLS. File mode is restricted to development with a loopback HTTP origin. Before deployment, configure `ENV=prod`, HTTPS and trusted proxy handling, protect logs containing account links, and complete the production gates in the sprint plan.

## Tests

Install the development lockfile (which includes runtime dependencies), then run with the virtual environment's Python:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

The fast suite uses isolated SQLite databases and does not need live WhatsApp or payment credentials. Live PostgreSQL tests skip unless `TEST_DATABASE_URL` is set. CI requires these tests on PostgreSQL 16 and 17; they execute migrations, tenant constraints, row locking, and HTTP inventory transactions against migrated tables. See [engineering checks](docs/engineering-foundation.md) for local PostgreSQL setup, dependency locking/auditing, configuration validation, and coverage limits.

## Run the legacy WhatsApp/admin service

The existing Dockerfile and Compose configuration launch **`app.main:app`**, not the merchant workspace. The Docker image does not currently package the merchant migration and preview tooling.

Copy `.env.example` to `.env` and configure the required values, including WhatsApp credentials if testing that integration:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

On macOS/Linux, use `cp .env.example .env` for the copy step.

- Legacy API: [http://localhost:8000](http://localhost:8000), with health at `/health`.
- Internal admin: [http://localhost:8000/admin/shops](http://localhost:8000/admin/shops).
- PostgreSQL runs inside Compose on service `db`, port `5432`. Compose does not publish that port to the host.
- Meta callback: `/webhook/receive` (GET verification and POST ingestion). For local integration testing, expose port 8000 with an HTTPS tunnel and configure the callback and `VERIFY_TOKEN` in Meta.

The legacy admin requires an external access control layer, such as Cloudflare Access, before public exposure. Merchant sign-in does not protect it.

Legacy operational emails use `ADMIN_EMAILS` and `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, and `SMTP_TLS`. These are separate from merchant account-email settings. Without an SMTP host, legacy operational mail is logged locally.

## Repository layout

| Path | Purpose |
|---|---|
| `app/commerce.py` | Merchant application and routes |
| `app/commerce_mail.py` | Merchant account email delivery |
| `app/main.py` | Legacy WhatsApp/admin application |
| `app/config.py` | Shared application settings |
| `app/admin.py` | Legacy internal operations dashboard |
| `app/pipelines/` | Legacy order/payment workflows |
| `app/templates/` | Server-rendered pages |
| `alembic.ini` | Database migration configuration |
| `scripts/preview.py` | Isolated merchant preview launcher |
| `tests/` | Automated checks |
| `docs/` | Delivery plan, sprint notes, UI notes, and audit records |

## Delivery roadmap

| Sprint | Scope | Status |
|---|---|---|
| 1 | Accounts, business settings, catalogue maintenance, customers | Implemented; live email setup pending |
| 2 | Suppliers, receiving, stock corrections, reconciliation, low-stock indicators | Implemented; production PostgreSQL checks pending |
| 3 | Orders and stock reservations | Next |
| 4 | Walk-in sales and fulfilment | Planned |
| 5 | Provider payments | Planned |
| 6 | Receipts, returns, and refunds | Planned |
| 7 | Reporting and operator tools | Planned |
| 8 | Production hardening and controlled pilot | Planned |
| 9 | Hosted storefront | After pilot |
| 10 | WhatsApp commerce integration | After pilot |

See the [full sprint plan](docs/sprint-plan.md), [Sprint 1 notes](docs/sprint-1.md), [Sprint 2 notes](docs/sprint-2.md), [feature audit](docs/feature-audit.md), and [sprint checkpoint](docs/sprint-checkpoint.md) for scope and evidence. Earlier milestone and design documents are historical snapshots; their feature counts and pending-work lists may describe an older stage.
