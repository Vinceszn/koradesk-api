# Kora Desk — Admin & Onboarding Dashboard (v1 built)

Status: BUILT — all screens, deltas, and API from this spec implemented in
`app/admin.py`, `app/caps.py`, `app/approvals.py`, `app/ops_mail.py` plus
`app/templates/`. Open questions below are answered and applied.

## Why this exists (jobs, not screens)

1. **Onboard a shop in <30 minutes** without touching the database by hand:
   lead → shop → plan + limits → price list → number connected → test order.
2. **Never miss a money decision:** every pending approval visible in one
   inbox, decidable here when WhatsApp is inconvenient (stuck approvals page
   the founder, per the trust promise).
3. **Enforce the pricing model:** live conversation counts vs plan caps
   (Starter 300 / Growth 1,200 / Partner 150-per-client / pilot ≤100),
   overage packs, and margin alerts (<40% gross margin two months running →
   pricing review, per `pricing-model.md`).
4. **Debug like an engineer:** per-shop message tail, extraction payloads,
   match scores, and cost rows — the same data support would ask for.

## Users (v1: internal only)

- **Founder/ops (sole v1 user).** No shop logins, no accountant logins in v1.
  Auth = Cloudflare Access (email OTP) in front of `/admin`, zero auth code.
- Explicit non-users: shop owners (they live on WhatsApp), accountants
  (Phase 3 partner dashboard is a separate build).

## Screens (v1)

### 1. Shops list — `/admin/shops`
Table: name · plan · onboarding stage · conversations MTD vs cap (bar) ·
spend MTD (Meta + AI) · margin signal (green/amber/red) · pending approvals
count. Search by name/number. Row click → shop detail. Amber/red defined by
pricing-model thresholds, not vibes.

### 2. Shop detail — `/admin/shops/{id}`
- **Profile:** plan (change = new approval-gated event, logged), approval
  limit ₦ (editable, logged), WhatsApp number + connection status, monthly
  conversation cap (auto from plan; overridable with reason, logged).
- **Onboarding checklist** (the guided pilot, tracked): number connected →
  price list confirmed (≥10 items matched in a test) → limits set → test
  order approved → day-7 review done → live. Each step shows who/when.
- **Price list editor:** table add/edit/deactivate + bulk paste
  (`name | unit | price` per line). Every change versioned (old rows kept,
  never hard-deleted — matching disputes need history).
- **Approval queue (per shop):** pending first, each with kind, payload
  summary, age, Approve/Reject buttons = same effect as WhatsApp taps
  (writes the same `approvals` row + actor `admin:<email>`).
- **Money tabs:** orders, invoices (open/paid), payments (matched/unmatched)
  — read-only lists with status filters, newest first, 50/page.
- **Message tail:** last 50 inbound/outbound with kind + timestamp; click to
  expand the stored payload (for debugging extractions).
- **Cost panel:** MTD Meta ₦ / AI ₦ / conversations / blended ₦-per-convo /
  plan price / margin % — the exact inputs pricing-model review needs.

### 3. Approvals inbox — `/admin/approvals` (global)
All pending across shops, oldest first, each showing shop, kind, amount,
age, payload summary, Approve/Reject inline. SLA display: >2h pending =
amber, >24h = red. (Money waiting is the product failing.)

### 4. Leads — `/admin/leads`
Pilot/partner/demo requests arrive as WhatsApp messages and emails — no
backend capture exists. So: manual lead entry (name, business, contact,
source, plan interest) → **Convert to shop** button pre-fills the onboarding
checklist. Lead list shows stage (new → contacted → pilot → converted/lost).

### 5. Costs — `/admin/costs`
Global MTD table per shop (same columns as shop cost panel) + totals row +
margin alerts. This page IS the pricing-model enforcement surface — if it
doesn't exist, margins are fiction (per architecture constraint 4).

## Data deltas (new migrations, all additive)

1. `shops.stage` (lead|onboarding|pilot|live|churned) + `stage_changed_at`.
2. `shops.monthly_cap` (int, seeded from plan: pilot 100 / starter 300 /
   growth 1200 / partner 150) + `shops.cap_override_reason` (nullable text).
3. `price_list_items.is_active` + `superseded_by_id` (versioning, no deletes).
4. `conversations` table (id, shop_id, customer_key, window_start, messages
   count) — 24h windows per customer per number; THE cap counter. Backfilled
   from `message_log`, then maintained on ingest.
5. `leads` table (name, business, contact, source, plan_interest, stage,
   shop_id nullable on convert).
6. `overage_packs` table (shop_id, conversations, amount_ngn, month) —
   ₦5,000/100 per pricing rules; packs raise the effective cap.
7. `plan_changes` audit (shop_id, from_plan, to_plan, actor, reason, at).

## API additions (all `/admin/*`, same FastAPI app, Jinja-rendered)

- `GET/POST /admin/shops`, `GET/PATCH /admin/shops/{id}` (plan/limit/cap
  changes validated: cap ≥ 0, limit ≥ 0, plan in enum)
- `GET/POST /admin/shops/{id}/prices`, `PATCH /admin/shops/{id}/prices/{item}`
  (deactivate, never delete), `POST .../prices/bulk`
- `GET /admin/approvals?status=pending`, `POST /admin/approvals/{id}/decide`
  (shared decision writer with the WhatsApp button handler — one function,
  two triggers; actor differs)
- `GET /admin/shops/{id}/{orders,invoices,payments,messages}` (list+filter)
- `GET /admin/costs?month=YYYY-MM` (per-shop + totals + margin flags)
- `GET/POST /admin/leads`, `POST /admin/leads/{id}/convert`
- `POST /admin/shops/{id}/overage` (sell a pack: writes row, bumps cap)

## Tech + hosting (keep it boring)

- Jinja2 templates in the same FastAPI app (`app/admin/` routes +
  `app/templates/`), no JS build step, no SPA. Server-rendered tables,
  plain HTML forms + minimal inline JS (confirm dialogs only).
- Same Docker Compose service (no new infra); `/admin` protected by
  Cloudflare Access at the tunnel when exposed. Locally: open, documented.
- No new dependencies beyond `jinja2` (add to requirements).

## Phased scope

- **v1 (this spec):** screens 1–5, data deltas 1–7, API list above. No charts
  (tables first), no bulk messaging, no exports (CSV export is v1.1).
- **Explicitly later:** shop-visible views, accountant multi-client,
  self-serve signup, analytics charts, broadcast composer.

## Acceptance criteria (build is done when…)

1. A new lead converts to a live shop using only the dashboard + WhatsApp
   (no `psql`, no code), price list pasted in bulk, test order approved.
2. A stuck approval is decidable from the inbox with identical effect to the
   WhatsApp tap (same row, same audit fields, actor differs).
3. Costs page numbers reconcile with Meta + OpenAI invoices within 5%.
4. A shop at 100% cap shows red and blocks new billable sends until a pack
   is sold (cap gate in the send path, not just displayed).

## Open questions for the founder — ANSWERED + APPLIED

1. Internal-only v1, or should pilot shops see a read-only status page?
   (Recommendation: internal-only; shops live on WhatsApp per constraint 1.)
   → ACCEPTED. No shop-visible views built. Prod note: Cloudflare Access
   (email OTP) in front of `/admin`; see README.
2. Reminder copy + 6pm summary format: founder-written templates in DB, or
   hardcoded v1? (Recommendation: hardcoded v1, templating is v1.1.)
   → ACCEPTED. Copy stays hardcoded (`payments.send_reminders`,
   `scheduler._summary_job`).
3. Who besides you gets Access emails? (Determines nothing in code, but the
   audit actor strings should be real addresses from day one.)
   → ACCEPTED. WhatsApp decisions log the sender number; dashboard decisions
   log `admin:<first ADMIN_EMAILS address>`. `decided_by` widened 64→128.

## Ops mail (founder-only for now, extendable)

Stuck-approval pages (>2h amber / >24h red, hourly, once per level via
`approvals.escalated/escalated_red`), sub-40% margin alerts (daily, once per
shop per month via `ops_alerts`), and new-lead notices go to `ADMIN_EMAILS`
(currently just `hello@koradesk.com`). Add recipients any time:
`ADMIN_EMAILS=a@x,b@x` — no code change. SMTP from env; empty `SMTP_HOST`
dev-logs instead of sending.

## Build notes (deviations from spec)

- Added `python-multipart` alongside `jinja2`: FastAPI HTML forms require it.
- Fixed `order_draft` confirm-on-approve: the old WhatsApp handler matched
  `kind == "order"` but pipelines write `"order_draft"`, so approvals never
  confirmed orders. The shared writer (`app/approvals.py`) matches
  `"order_draft"` — WhatsApp and inbox now behave identically.
- Fixed `costs._row` first-of-day crash (`None + 1` on fresh ledger rows).
