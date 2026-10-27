# Sprint 3: Personal account and customization

The expanded account sprint precedes orders/reservations, which now move to Sprint 4. Implementation stays on `codex/account-customization` for preview and review.

## Scope

| Area | Behavior |
|---|---|
| Profile | Full name, separate display name, optional phone, photo upload/replacement/removal, verification status, join date for new accounts |
| Email | Password-confirmed request, new-address verification, notices to the previous address, cancellation/expiry, uniqueness, session and old-link revocation |
| Security | Password change, recorded browser/device and activity, individual/all-other session revocation, latest 30 security events with read status |
| Two-factor | Authenticator QR/manual setup, encrypted secrets, activation confirmation, one-use recovery codes, replacement/disable, factor enforcement at login, password recovery and sensitive changes |
| Business access | Membership roles, switching/settings links, email-bound invitations, accept/decline, leaving a business and ownership transfer to a verified existing teammate |
| Data controls | Immediate authenticated JSON export; closure removes personal data and access while preserving anonymous actor IDs in stock history; owners must transfer first |
| Appearance | Dark/light/device theme, live appearance preview, reduced motion, compact/comfortable tables, chart patterns |
| Navigation | Account-persisted sidebar state, default business, allowed landing page |
| Region | Validated IANA time zone, date format, 12/24-hour clock |
| Language | English/French account and navigation labels; working pages and service messages remain English and the limitation is disclosed |
| Notifications | Per-business overview low-stock notices, unread security activity, optional announcement opt-in; essential security notices cannot be muted |
| Overview | Choose visible summary cards and their order, at least one visible; restore defaults |
| Form behavior | Responsive layout, password visibility, save/error feedback, cancel/reset, unsaved-change warning and confirmations for consequential actions |

## Operating details

Migration `0004_account_workspace` adds account tables and session metadata without resetting stock, catalogue, existing passwords or memberships. Older accounts have an unknown join date; the UI does not invent one. Earlier sessions appear as unknown devices until a new sign-in.

`COMMERCE_ACCOUNT_KEY` is a Fernet key supplied through the process environment. Production must provide a stable protected key and back it up separately from the database. Do not lose or casually rotate it: existing two-factor secrets depend on it. The local preview generates and reuses `work/account-encryption.key` and keeps account emails in the private mailbox. No external account mail is sent in preview.

Two-factor codes use the [RFC 6238 algorithm](https://www.rfc-editor.org/rfc/rfc6238). Secrets use [Fernet authenticated encryption](https://cryptography.io/en/latest/fernet/). A used TOTP time step cannot be replayed, and recovery codes are stored as hashes. A freshly used authenticator code must roll over before reuse for another sensitive action.

Security activity is visible inside the account. Email-change notices use the configured account mail transport. Live SMTP delivery, production PostgreSQL concurrency, backup/restore, and a supervised pilot remain release gates. The optional announcement preference is saved; no marketing sender is connected. Personal exports are generated immediately, so there is no background job or download-expiry queue to manage.

## Validation

The full automated suite passes: **94 tests**, including 11 account-specific tests. Coverage includes profile and image validation, preference persistence and tenant boundaries, session revocation, email confirmation/cancellation/delivery failures, RFC TOTP vectors, one-use recovery codes, two-factor password recovery, ownership transfer, leaving/closure with stock history preserved, personal export exclusions, and CSRF/origin enforcement. Existing migration upgrade/repeat/downgrade and PostgreSQL SQL-compilation checks also pass.

Real Chrome checks covered profile saving; saved theme, table density, sidebar, region and card choices across reloads; French labels; and device light/dark switching. All four tabs were checked at 1440, 768, 390 and 360 pixels with no document overflow or JavaScript errors. Screenshots were visually reviewed in dark and light themes. Working-workspace checks confirmed the saved sidebar and summary-card choices. Test data used a separate local review account; the existing merchant account and stock were preserved.

One upstream Starlette/AnyIO deprecation warning remains in the test runner; it does not fail the tests.

## Follow-up: navigation and usability

The user's saved browser autofill exposed a false unsaved-change warning in a hidden email form. The warning and account layout were corrected and checked in the actual in-app browser. See [the account UX fix](account-ux-fix.md) for the cause, design decisions and regression evidence.
