# Sprint checkpoint — 22 October 2026

Current position: Sprint 2 implementation and local verification are complete. Sprint 3 has not started. This is a review checkpoint, not a production release.

Branch: `codex/sprint-2-checkpoint`, created from `codex/merchant-onboarding-mvp` at `24d2e02`. It includes all existing implementation commits. Main has not been merged or changed by this checkpoint.

| Stage | Status | Delivered or next scope |
|---|---|---|
| Foundation | Implemented | Merchant accounts, businesses, owner/read-only staff access, catalogue, opening counts, dark overview charts and collapsible navigation |
| Sprint 1 | Implemented and locally verified | Account recovery/verification, business settings/switching, catalogue editing/archive/export, customer records |
| Sprint 2 | Implemented and locally verified | Suppliers, receiving/purchase costs, adjustments, recounts, reversals, reconciliation and low-stock indicators |
| Post-Sprint 2 audit | Implemented and locally verified | CSV compatibility and export roundtrip, row-specific import errors, invitation replacement, availability labels and simpler team page |
| Sprint 3 | Not started; next planned sprint | Orders, price snapshots, stock reservations, cancellation, expiry and separate payment/fulfilment states |
| Sprints 4–8 | Planned | Walk-in sales/fulfilment, payments, receipts/returns/refunds, reporting/admin, production/pilot |
| Sprints 9–10 | After pilot | Hosted storefront and WhatsApp commerce |

## Open work and release limits

- Bulk stock-quantity CSV import and bulk catalogue updates remain unbuilt. Current CSV import handles product details only; stock changes are recorded separately.
- Live email delivery is not configured/verified; local preview emails go to a private test mailbox. Team invitations are manually shared links.
- PostgreSQL concurrency, deployment controls, backup/restore and pilot verification remain production-release work.
- Orders, sales, payment collection and receipts are not yet implemented in the merchant workspace.

## Recorded validation

The latest feature audit recorded 83 passing automated tests and three successful Chrome walkthroughs covering account/catalogue/customer maintenance, supplier/inventory operations and CSV/team flows. Desktop/mobile layouts were checked. These are the previous implementation validation results; this documentation-only checkpoint does not claim a fresh test run.

## Implementation commits

- `fdd9348`: approved sprint plan
- `aa732ed`: Sprint 1
- `9782337`: Sprint 2
- `24d2e02`: CSV fixes, team redesign and feature audit

The converted 100-product upload file and local preview database remain local artifacts, not application source or production data in this checkpoint.
