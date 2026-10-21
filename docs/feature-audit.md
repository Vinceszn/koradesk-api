# Built-feature audit — 21 October 2026

Scope: the merchant workspace implemented through Sprint 2. Sales, orders, payments, receipts and legacy WhatsApp/admin integrations are not part of this audit.

## Fixes

- Catalogue CSV imports accept reordered, trimmed, case-insensitive headers, comma/semicolon/tab delimiters, UTF-8 BOM and UTF-16 spreadsheet exports.
- The optional `archived` column allows Kora catalogue exports to be imported. Identical existing SKUs are skipped; conflicting details require an explicit product edit. Stock is never overwritten by catalogue import.
- Validation failures show a specific error on the Products page with the upload form available. A failed import rolls back all rows. The old `/import` page address now redirects to the upload section.
- Product stock-status labels account for reserved units. Setup progress uses the complete catalogue even when archived products are hidden.
- Reissuing an invitation expires earlier unused invitations for the same business/email.
- Team page uses a compact member directory, invitation form, pending list and expandable role explanation. Owner/staff restrictions remain enforced on the server.

## Validation coverage

The full automated suite passed: **83 tests**.

| Built area | Covered behaviour |
|---|---|
| Account and access | Registration, login/logout, expired sessions, password change/reset, verification, token expiry/replay, CSRF and throttling |
| Business | Creation, membership boundaries, chooser, settings, owner/staff restrictions |
| Catalogue | Creation, price validation, edits/conflicts, archive/restore, search, export and transactional CSV import |
| Customers | Create, edit, search, archive, tenant isolation |
| Team | Invite, replacement, email-bound acceptance, removal, revocation and read-only staff |
| Inventory | Opening counts, receiving/cost snapshots, adjustments, recounts, stale-write rejection, reversals, replay protection, reserved stock, rollback, low-stock indicators and reconciliation |
| Suppliers | Create/edit/archive, tenant restrictions and historical name preservation |
| Database | Upgrade/repeat/downgrade, existing data preservation and PostgreSQL SQL compilation |

Three real Chrome walkthroughs passed: account/catalogue/customer maintenance; supplier/inventory operations; and CSV/team flows. Checks included actual file upload, export roundtrip, conflicting-row recovery, product search, invitation copy/acceptance/removal/revocation, account verification/password recovery through the private mailbox, and desktop/mobile layouts. The redesigned team page was checked at 1440, 768, 390 and 360 pixels and screenshots were visually reviewed.

## Remaining limits

CSV import creates catalogue entries; bulk stock quantity import and bulk updates remain unbuilt. Existing conflicting SKUs are not silently updated. Excel `.xlsx` is not a supported upload format. Invitations require manually sharing a link. Account emails use the local private test mailbox; live SMTP delivery is not verified. Live PostgreSQL concurrency, deployment, recovery and pilot checks remain release work. Local test results do not establish production readiness.
