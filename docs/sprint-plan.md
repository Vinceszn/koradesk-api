# Kora commerce delivery plan

Approved for implementation by the user. Work stays on the review branch until merge approval.
Each sprint is an estimated two weeks, not a calendar commitment. External provider approval and pilot feedback may change timing.

| Sprint | Scope | Exit criterion | Status |
|---|---|---|---|
| 1: Account and catalogue completion | Email verification, password reset/change, business settings and switching, product/variant editing and archiving, catalogue export, basic customer records | Merchant can recover an account and maintain business/catalogue/customer records without developer assistance | In progress |
| 2: Inventory operations | Suppliers, receiving, purchase costs, reasoned adjustments, recounts, compensating corrections, reconciliation, low-stock thresholds | Auditable stock changes reconcile with balances | Planned |
| 3: Orders and reservations | Orders/items, price snapshots, customers, atomic reservations, cancellation, unpaid expiry, independent order/payment/fulfilment states | Last-unit contention, whole-order rollback and idempotent retry tests pass | Planned |
| 4: Walk-in sales and fulfilment | Cashier permissions, fast sales, audited cash declaration, pickup/dispatch, partial fulfilment/cancellation, order search/details | Sale completes and deducts stock once; partial actions retain correct balances | Planned |
| 5: Provider payments | Paystack sandbox, account binding, attempts, webhook verification/deduplication, reconciliation, late/partial/mismatch exception review | Duplicate and racing payment events are safe; exceptions visible | Planned |
| 6: Receipts, returns and refunds | Branded immutable PDF receipts, download/manual WhatsApp sharing, durable jobs/retries, resellable/damaged returns, refund tracking/provider refunds | Receipt failures retry; refunds and physical restock are separate | Planned |
| 7: Reporting and operations | Sales charts/date filters, best sellers, stock trends, exports, merchant directory/onboarding status, suspension, support queue, admin audit, manual pilot subscription tracking | Reports reconcile; operators resolve issues with an audit trail | Planned |
| 8: Production and pilot | PostgreSQL concurrency, deployment controls, access review, backup/restore, monitoring, abuse controls, guidance, live-payment approval, 3–5 pilots | Release gates and restore rehearsal pass; supervised real transactions succeed | Planned |
| 9: Hosted storefront | Images/descriptions, published catalogue, cart, checkout, availability and confirmation | Uses shared tested order/reservation/payment API | After pilot |
| 10: WhatsApp commerce | Explicit legacy shop mapping, official integration, enquiries/orders/payment links/receipts, retries and human handoff | Uses shared API with tenant and stock rules | After pilot |

## Continuous requirements
Maintain the approved dark UI; mobile/desktop/keyboard verification; tenant isolation and role checks; transactional data changes and duplicate protection; meaningful failure/retry tests; preview before merge; documentation and operating instructions.

## Milestones and deferred scope
Sprint 4: operational walk-in selling. Sprint 8: controlled pilot release.
Later: multiple locations/transfers, supplier purchase orders, bundles, batches/expiry, serial numbers, fractional stock, external store integrations, agreed costing/gross margin, automated subscriptions, voice. Accounting and tax reporting are separate scope.

## Starting point
Accounts, owner/read-only staff, businesses, one location, catalogue/CSV import, opening counts, manual invitations, stock charts, and collapsible navigation exist. Legacy admin/WhatsApp services are separate from the commerce application. Current local SQLite tests do not establish production PostgreSQL concurrency readiness.
