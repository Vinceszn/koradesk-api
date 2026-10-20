# Sprint 2 — inventory operations

Implemented on `codex/merchant-onboarding-mvp` for local review.

## Working flows

| Function | Behaviour |
|---|---|
| Suppliers | Owner creates, edits, archives and restores supplier contact records. Archived suppliers cannot be selected for a new receipt. |
| Receiving | Record one variant per entry, with supplier, whole-unit quantity, unit purchase cost in naira, optional delivery reference and required reason. Group entries from one delivery using the same reference. |
| Purchase history | Stores cost in integer kobo, delivery reference and supplier name at receipt time. Later supplier renames preserve the historical name. Costs are visible to owners only. |
| Adjustments | Add or remove units with a required reason. Balance and movement commit together. |
| Recounts | Record a physical total, including zero or an unchanged count. A stock version prevents a stale recount overwriting a newer movement. |
| Corrections | Reverse a receipt, adjustment or recount once, then enter the corrected details. Original entries remain. Opening counts are corrected through a recount. Reversals cannot themselves be reversed. |
| Reconciliation | Compares the full ledger to on-hand balances, including archived variants. Flags differences and blocks further changes to the affected variant for investigation. |
| Low-stock alerts | Configurable threshold per variant. Flags active, counted variants when available stock is at or below the threshold. Zero flags out-of-stock items. Inventory and overview display alerts. |
| History | Records actor, time, reason and signed change. History and correction forms provide older/newer paging, 100 entries at a time. |

Stock management is owner-only; staff retain read-only inventory access. Supplier management and receiving costs are restricted to owners. All routes enforce business membership, tenant-bound IDs and CSRF.

## Stock rules

- Record opening stock before receiving, adjusting or recounting.
- Restore an archived variant before receiving. Adjustments, recounts and corrections remain available for archived stock.
- Quantities are whole units. A change cannot leave on-hand below reserved stock, below zero, or above 1,000,000.
- Stock writes use row locks and a conditional version update. Each submission has an idempotency key and fingerprint: identical retries return success without another movement; changed input with the same key returns a conflict.
- A reversal creates an opposite stock movement with a link to the original. A unique constraint prevents reversing the same movement twice.
- Receiving records purchase prices; it does not establish FIFO/weighted-average costing, profit, tax, accounts payable, or supplier purchase orders.
- Low-stock alerts are in-app indicators, not outbound notifications.
- Reconciliation does not silently rewrite stock or history. A difference requires investigation and a reviewed repair based on the original evidence.

## Migration and preview

Back up the database before applying Alembic revision `0003_inventory_operations`. It adds supplier and operation tables, a balance version and a default zero threshold. Existing quantities, reservations and movements are preserved. The local preview runner applies migrations automatically to its isolated database.

Downgrade removes Sprint 2 metadata and thresholds but retains stock quantities and movement history. It loses supplier, cost and reversal metadata; use backups for a complete rollback.

## Validation

The full 72-test suite passed, including all prior sprints. A final 20-test inventory run also passed after adding two regressions for older history pages and atomic rollback on metadata-write failure (74 distinct passing tests across these runs). Coverage includes receiving/replay, stale recounts, zero-change recounts, reversals, reserved/negative/maximum stock protection, invalid costs, supplier snapshots, archived records, tenant and staff restrictions, CSRF, reconciliation differences and migration preservation.

SQLite upgrade/repeat/downgrade and PostgreSQL migration SQL compilation passed. Live PostgreSQL contention testing remains a production-release check. SQLite is the local preview database.

A real Chrome walkthrough passed supplier creation/editing, opening count, receiving with purchase costs, adjustment, recount, reversal, thresholds, reconciliation, overview alerts and sidebar collapse/expand. Inventory, stock forms and suppliers were checked at 1440, 768, 390 and 360 pixels with no horizontal overflow. Desktop and mobile screenshots were visually reviewed. Supplier and method controls have explicit accessible labels.
