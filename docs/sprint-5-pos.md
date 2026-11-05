# Sprint 5: cash POS and fulfilment

Implemented locally on codex/sprint-5-pos.

- Point of sale supports product/variant/SKU search and barcode input ending in Enter. Repeated input increases quantity. The basket supports up to 40 unique variants and remains in session storage until the server confirms a sale.
- Owners enable or revoke cashier capability from Your team. Staff remain read only unless explicitly enabled; cashiers can sell but cannot edit stock or assign barcodes.
- Owners assign primary and alternate barcodes and retire codes from the variant editor. Barcode setup is separate from the selling screen. Declared GTIN formats validate check digits. Optional barcode CSV column applies to newly imported variants; existing matching SKUs retain the conservative skip behavior.
- Cash sales recheck prices and available stock, record immutable item snapshots, a cash declaration, change and stock ledger entries in one transaction. Request keys protect retries. Cash is an operator declaration, not provider-verified settlement.
- Placed orders support partial unpaid cancellation, pickup and dispatch. First fulfilment collects the full remaining order amount in cash. Paid cancellations require the returns/refunds sprint. Remaining reservations are retained until fulfilled; paid orders do not expire.
- Order details show fulfilled/cancelled line quantities and activity. Completed POS sales link to the existing order detail confirmation.

Validation includes rollback, reservation safety, sequential final-unit protection, cash declaration uniqueness, retries, staff permissions, barcode assignment/retirement and migration checks. Browser testing used the isolated review shop and simulated scanner keystrokes; a real cash sale declaration reduced available test stock from 12 to 10 and reset the basket. Mobile checks used 390 px.

Production PostgreSQL concurrent-worker tests and physical scanner validation remain release gates. Camera scanning is optional and deferred; USB/Bluetooth keyboard-wedge input and typed lookup are available. Branded PDF receipts and returns/refunds remain Sprint 7.

## Register redesign (1 November 2026)

The register now keeps the product catalogue and current sale side by side with independent scrolling and an always-visible Charge button. Available products sort first; the full catalogue has no 60-item cutoff. Search includes product name, variant, SKU and assigned barcode. Cashiers can switch between tiles and a compact list, filter in-stock items, and star regular items (favourites are local to the browser).

The basket has quantity steppers, direct quantity entry, per-line totals, removal, optional customer selection and confirmed clearing. A separate cash dialog defaults to exact payment, offers suggested amounts, calculates change and blocks insufficient cash. F2 focuses search; F4 opens payment. Narrow screens separate Products and Basket, with a fixed basket shortcut rather than stacking the cart below the entire catalogue. Dialogs support keyboard navigation and Escape.

Basket, customer, cash amount and request key survive refresh within the tab. Changed prices, unavailable items and reduced stock require review. Server rejection stays in the checkout. An ambiguous network failure preserves and locks the original payment details for an idempotent retry, including after refresh. Offline checkout is blocked. A completed-sale URL is consumed so refreshing cannot discard the next basket.

Research: [Square item grid](https://squareup.com/help/us/en/article/8334-set-up-item-grid) supports quick product access; [Shopify cash checkout](https://help.shopify.com/en/manual/sell-in-person/shopify-pos/payment-management/cash-payments) separates basket building from exact/suggested cash amounts and completion. These informed the interaction choices; this is an adaptation to Kora Desk's existing cash-only capabilities.

Browser validation covered repeated SKU input, unknown codes, favourites, list view, insufficient cash, change, rejected checkout, offline state, ambiguous network retry across refresh, one confirmed test sale (10 to 8 units), next-sale refresh, and clear confirmation in the isolated review shop. Test traffic errors were deliberately injected for the recovery checks.

The full 122-test suite passes. Visual checks used the 105-variant demo catalogue at 1440 px, 1024 px and 390 px, including light/dark themes and the mobile product, basket and payment views. Demo catalogue checks did not submit a sale.
