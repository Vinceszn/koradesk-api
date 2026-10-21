# Sprint 1 — account and catalogue completion

Implemented on the review branch, without merging or deploying.

## User flows
- My account: request email verification, confirm the emailed link, change password using the current password.
- Forgot password: generic account response, single-use 30-minute reset links, server-side CSRF and request throttling. Password changes/recovery invalidate all login sessions and outstanding reset links.
- Settings: business name/category, location name, contact email, phone, address, and future receipt note.
- Switch business: explicit membership-scoped chooser; account access is also available from the avatar on phones.
- Products: edit name/variant/SKU/price; stale variant edits return a conflict; renaming affects sibling variants. Archive one variant or the entire product's variants, include archived entries, restore variants.
- Export: owner-only catalogue CSV, including archived status, exact two-decimal prices and spreadsheet-formula escaping. Following the feature audit, this export can be re-imported: matching existing products are skipped and conflicting details are reported without overwriting stock.
- Customers: owner-only create, search, edit, archive and restore; tenant-bound routes. Email and phone are optional. Operational staff permissions arrive in Sprint 4.

Archived inventory remains visible in inventory and is retained in overview totals; archiving does not destroy quantities or movements. Email verification is recorded but does not yet gate commerce access. Business logos and receipt generation belong to the receipt increment; this sprint stores receipt text.

## Database and preview
Back up first, then run the existing Alembic upgrade command to apply revision 0002_account_catalogue. It adds account tokens, customers, merchant contact fields, verified-email state, variant archive state and edit versions.

The preview runner upgrades its isolated SQLite database. It adopts the known unversioned milestone-one local preview before upgrading; production databases must use the normal reviewed migration process.

Preview emails are private .eml files in ignored work/mailbox. Open the matching file locally and follow its account link. They are not served through the application. Do not commit, publish or share the mailbox: messages contain bearer reset/verification links. The preview forces file delivery and a loopback public URL.

## Production email configuration
Set these process environment variables through the deployment's secret/configuration system:

| Variable | Value |
|---|---|
| COMMERCE_MAIL_MODE | smtp |
| COMMERCE_PUBLIC_URL | Exact HTTPS origin of the merchant app, with no path |
| COMMERCE_MAIL_FROM | Approved sender address |
| COMMERCE_SMTP_HOST | SMTP server |
| COMMERCE_SMTP_PORT | STARTTLS port, default 587 |
| COMMERCE_SMTP_USER | SMTP username, when required |
| COMMERCE_SMTP_PASSWORD | Secret password |

SMTP uses certificate-verified STARTTLS and bounded timeouts. File delivery is rejected outside dev mode. Provider credentials and reset links are not written to app logs; Uvicorn account-link paths are redacted. Configure reverse-proxy access logs to redact account tokens too. Live sender configuration and real inbox delivery have not been verified.

## Validation
53 automated tests passed, including preservation of an existing account during migration and private recovery responses when email delivery fails. Includes tenant/staff restrictions, edit conflicts, archive/history preservation, safe CSV export, customers, current-password checks, revoked sessions, reset expiry/replay, verification, throttling and local mail restrictions.

A real Chrome walkthrough passed settings, edit/archive/restore/download, customers, membership chooser, local verification email, password change/recovery and login with the recovered password. Settings and customers were checked at 1440, 768, 390 and 360 pixels. Migration upgrade/repeat/downgrade and PostgreSQL SQL compilation passed; live PostgreSQL and live SMTP remain deployment checks.
