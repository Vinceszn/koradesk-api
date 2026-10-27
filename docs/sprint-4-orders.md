# Sprint 4: Orders and stock reservations

This sprint is implemented on the current review branch and verified locally. Production PostgreSQL contention checks remain a release-gate task for Sprint 9.

## Outcome

Sprint 4 creates the shared order engine for walk-in sales, hosted checkout and WhatsApp orders. A merchant can prepare an order, preserve what was sold and at what price, reserve all required stock atomically, find the order later and cancel it without corrupting availability.

The sprint adds three main merchant pages:

1. **Orders** — searchable directory with status and date filters.
2. **New order** — customer selection, product search, quantities, totals and review.
3. **Order details** — immutable item snapshots, three status tracks, reservation deadline and activity history.

## Functional scope

| Area | Required behaviour |
|---|---|
| Order identity | Merchant-scoped human reference and internal ID; references cannot expose another merchant's volume or records. |
| Customer | Optional existing customer link plus name, phone and email snapshots so history survives later customer edits. Anonymous/walk-in is allowed. |
| Items | Variant, SKU, product and label snapshots; positive whole-number quantity; archived variants cannot be added to a new order. |
| Pricing | Unit price stored in integer kobo when the order is placed. Later catalogue price changes do not rewrite the order. Subtotal and total are calculated by the server. Discounts, tax and delivery charges are deferred until their rules are approved. |
| Draft | A draft may be edited without reserving stock. Availability is informative until placement. Empty drafts cannot be placed. |
| Placement | Placement validates every line and reserves the entire order in one transaction. If one line is unavailable, no line is reserved. |
| Availability | `available = on_hand - reserved`. Reservations increase `reserved`; they do not reduce `on_hand`. |
| Cancellation | A placed, unfulfilled order can be cancelled once. Its active reservations are released in the same transaction. Repeated requests return the established result. |
| Expiry | Unpaid reservations receive a deadline. A retry-safe background task expires overdue orders and releases only their active reservations. Paid orders are never expired by this task. |
| Status | Order, payment and fulfilment are independent state fields. UI presents each separately instead of collapsing them into one ambiguous status. |
| History | Creation, edits, placement, cancellation, expiry and state changes record actor, time and safe metadata. History is append-only. |
| Search | Reference, customer name, phone and email; filters for date, order state, payment state and fulfilment state; newest first with pagination. |

## State model

### Order state

`draft` → `placed` → `completed`

`draft` may be deleted. `placed` may become `cancelled` or `expired`. Completion is driven by later payment and fulfilment work, not by manually changing a single combined status.

### Payment state

`unpaid`, `partially_paid`, `paid`, `partially_refunded`, `refunded`

Sprint 4 stores and displays the state but does not integrate a payment provider or permit arbitrary paid-state changes. Provider attempts, webhooks and reconciliation arrive in Sprint 6.

### Fulfilment state

`unfulfilled`, `partially_fulfilled`, `fulfilled`, `cancelled`

Sprint 4 starts orders as unfulfilled. Stock consumption and partial fulfilment arrive in Sprint 5.

### Reservation state

`active`, `released`, `consumed`, `expired`

Each transition is one-way and records when and why it occurred. This prevents a retry from releasing or consuming the same units twice.

## Data boundaries

Proposed records:

- `orders`: merchant, location, reference, optional customer, customer snapshots, three statuses, totals, reservation deadline, creator and timestamps.
- `order_items`: order, variant, product/SKU/label snapshots, quantity, unit-price snapshot and line total.
- `stock_reservations`: order item, merchant, location, variant, quantity, state and transition timestamps.
- `order_events`: order, actor, event type, timestamp and limited structured metadata.
- `order_requests`: merchant-scoped idempotency key, request fingerprint and established result for mutation retries.

All tenant-owned foreign keys include the merchant boundary. Money remains integer kobo. Historical rows are retained when products, variants or customers are archived.

## Concurrency and retry rules

- Reserve variants in a deterministic ID order to reduce database deadlocks.
- Lock or conditionally update every affected balance inside one database transaction.
- Recheck `on_hand - reserved` during that transaction; page-load availability is never treated as authoritative.
- A failure on any item rolls back the order placement and every reservation.
- Every place, cancel, expire and later fulfil request has a merchant-scoped idempotency key and request fingerprint.
- An identical retry returns the original result. Reusing the key with different input returns a conflict.
- The expiry worker claims eligible orders safely and may be run repeatedly or by competing workers without double release.

SQLite remains useful for local behaviour tests. Sprint 9 must prove contention behaviour on production PostgreSQL before pilot release.

## Permissions

During Sprint 4, owners can create, edit, place and cancel orders. Existing staff may view orders but remain unable to mutate them. Sprint 5 introduces an explicit cashier capability rather than silently turning every staff account into a seller.

Every route enforces membership, tenant-bound IDs, CSRF/origin checks and server-side totals. Unknown or foreign order IDs return the same not-found response.

## Deliberately deferred

- Payment collection and webhook processing — Sprint 6.
- Picking, dispatch, pickup and stock consumption — Sprint 5.
- Receipts, returns and refunds — Sprint 7.
- Discounts, tax rules, delivery pricing, credit sales and quotations — later approval.
- Multi-location allocation, bundles, fractional units, batches and serial numbers — later scope.

## Acceptance criteria

Sprint 4 is complete when automated and browser checks prove:

1. Two concurrent attempts for the final unit cannot both reserve it.
2. A multi-item order with one unavailable line creates no partial reservation.
3. Retrying placement, cancellation or expiry cannot change stock twice.
4. Cancelling or expiring an order restores availability exactly once.
5. Catalogue or customer edits do not alter historical order snapshots.
6. Order, payment and fulfilment states reject invalid transitions.
7. Merchant and role boundaries hold for list, search, details and every mutation.
8. The three pages work on desktop and mobile and are keyboard operable.

## Local validation

- The complete automated suite passes with 101 tests, including tenant and role boundaries, immutable snapshots, stale-price review, whole-order rollback, final-unit protection, retry-safe placement/cancellation/expiry and migration checks.
- A real-browser owner flow created a draft, placed it, reserved stock, displayed the reduced availability and rendered the order detail at desktop and 360 px mobile widths without horizontal overflow.
- The browser console completed the flow without errors or warnings. The expiry runner is available at `scripts/expire_orders.py` for scheduled execution.
- Production PostgreSQL contention, scheduler deployment and operational monitoring remain in Sprint 9.

## Barcode POS handoff for Sprint 5

The barcode scanner belongs to the walk-in sales sprint because scanning is a fast way to construct and complete an order. Sprint 4 supplies the order, price-snapshot, idempotency and stock-reservation services that it will call.

### MVP interface

Sprint 5 adds one main **Point of sale** page. It uses a two-pane desktop layout and a single-column mobile layout:

- A persistent **Scan barcode or search** field accepts scanner input, SKU, product name or variant label.
- A successful scan adds the matched variant. Scanning it again increments quantity.
- The basket shows item, variant, unit price, quantity, available units and line total.
- The checkout panel shows customer (optional), total, payment method available in that sprint, amount tendered/change for cash, and a clear complete-sale action.
- Success gives a strong visual confirmation and optional short sound, clears the basket only after the server confirms, and keeps the scan field ready for the next sale.
- Unknown, archived and unavailable codes produce distinct messages and preserve the current basket.
- Every action has a keyboard and touch alternative; scanner hardware is never the only path.

### Scanner support

The first release supports USB and Bluetooth scanners operating as a **keyboard wedge**: the device types the barcode and sends Enter. This requires no manufacturer SDK and works with common desktop and Android setups.

Camera scanning is an optional enhancement on supported secure browsers. It requires an explicit user action and permission, displays a visible camera state, and falls back to the manual field. A camera failure must never block keyboard-wedge or typed sales.

### Barcode records

Use a separate `variant_barcodes` record rather than one barcode column on a product:

| Field | Rule |
|---|---|
| Merchant and variant | Tenant-bound foreign keys; barcodes identify sellable variants, not only products. |
| Code | Trimmed and normalized without converting to a number, so leading zeroes survive. Unique per merchant among active records. |
| Symbology | EAN-8, EAN-13, UPC-A, GTIN-14, Code 128 or `unknown`; validate check digits when the declared format has one. |
| Primary | One preferred code for display; a variant may have alternate supplier or packaging codes. |
| Status | Active/archived with timestamps and actor history. Historical sales retain item snapshots. |

Barcode assignment is added to the existing variant form and CSV catalogue format, so it does not require another main page. Duplicate codes are rejected with the already-matched item identified. Owners may link an unknown scanned code to a variant; cashiers may search and continue but cannot silently remap catalogue identifiers.

### POS transaction rules

- A scan only edits the local basket; it does not mutate stock.
- Completing a walk-in sale sends one idempotent order request. The server rechecks current prices and availability and reports any changed lines before completion.
- The final transaction creates/places the order, records the accepted payment declaration, consumes stock exactly once and records activity. Any failure rolls back the whole sale.
- Browser refresh or a double click must not create a second sale. An unfinished local basket may be restored on the same device but cannot be mistaken for a completed sale.
- Barcode values are treated as untrusted text: length limits, allowed characters, tenant scoping and server-side lookup apply.

### POS acceptance criteria

1. A keyboard-wedge scan ending in Enter adds one item without a mouse.
2. Repeated scans increment quantity and never exceed confirmed availability at completion.
3. Unknown, duplicate, archived and unavailable barcodes follow their specified recovery paths.
4. Typed SKU/product search completes the same sale when no scanner is connected.
5. Double submission, refresh and network retry result in one order, one stock deduction and one payment declaration.
6. A 40-line basket remains responsive, totals correctly and can be completed using only the keyboard.

### Deferred scanner features

Weighted/price-embedded barcodes, barcode label printing, GS1 application identifiers, case-to-unit conversion, offline selling, scanner fleet management and native manufacturer SDKs are outside the MVP.
