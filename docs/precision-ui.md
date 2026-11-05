# Kora Precision UI

Implemented locally on `codex/sprint-5-pos`, 1 November 2026. This is the merchant application, account and onboarding design; the separate legacy admin and paused WhatsApp service are unchanged.

## Direction and brand provenance

The user selected Precision Dark and approved an app-wide redesign grounded in the landing page. The source of truth is the newer marketing snapshot in `../koradesk/references/kora-ui-preview`, together with its `docs/CODEX_HANDOFF.md` and `docs/BRAND_ASSETS.md`. The editable marketing Astro source still contains older messaging and was not changed in this task.

The shared visual system uses the approved green-charcoal canvas, emerald primary action, Nunito headings, Inter controls/body, 8 px controls, 16 px panels and restrained glass on the utility bar. Orders use emerald accents; catalogue/inventory use rose; overview reporting uses violet. Gold remains the payment/warning family. Section colours do not substitute for labelled statuses. The four approved enamel assets are copied locally for onboarding and empty states; controls and product data remain live HTML.

`precision.css` is the shared token and component layer, loaded after the existing page styles. Existing light/dark/system, density, chart-pattern, sidebar, language and reduced-motion preferences retain their behaviour. No new framework, external font request or animation runtime was added.

## Delivered workflows

- Navigation groups Sell, Stock and Business. The utility-bar business switcher stays available when navigation is collapsed and on mobile. The avatar opens personal account settings.
- Overview puts open orders, low-stock variants and incomplete counts first. It honours personal low-stock notice preferences and summary-card visibility/order. Stock charts show the top eight counted active variants by available units; labels explicitly state that scope. Inventory health distinguishes free stock, no free stock and uncounted variants. Stock value remains selling-price value, not profit. Sales-trend reporting remains its planned sprint.
- Product, customer, supplier and invitation creation uses focused native-dialog panels with keyboard focus, Escape, dirty-state protection and explicit discard/keep actions. Plain server forms remain available without enhancement.
- Catalogue and inventory retain search/filter state when returning from a record. Return links preserve the originating directory query. Inventory adds a Reserved column and searchable stock statuses. Supplier records have client-side search.
- Stock detail separates delivery, adjustment and physical recount. Each previews resulting on-hand, reserved and available stock. Switching between adjustment and recount retains separate entries. Thresholds and compensating corrections are disclosures. The selected variant now has its own tenant-scoped, paginated movement history.
- Orders use compact status shortcuts and a search toolbar with advanced filters. Result counts describe the actual filtered set. Existing independent order/payment/fulfilment states and server authorisation are preserved.
- Rejected catalogue, business, contact and stock edits stay in their form with an announced error. Successful changes follow the normal server redirect. Stock/sale rules and request keys remain enforced by the backend.
- CSV UI now follows choose → validate/review → confirm. Review performs no writes, lists new/unchanged/invalid rows and blocks confirmation on invalid rows. Confirmation reparses and revalidates the payload against current merchant records, then commits atomically. It preserves leading-zero barcodes and the conservative skip policy for matching SKUs. Direct upload clients retain their existing endpoint. Import does not change stock quantities.
- Account sections, authentication, business selection/setup and the register share the visual system. Returning from Account preserves the current business and page. POS scanning, cash change, basket recovery and payment retry behaviour remain available.
- A duplicate-SKU database conflict now returns a usable 409 page rather than trying to read detached account data during error rendering.

## Component research and implementation choices

Official documentation reviewed in this chat on 1 November 2026; this was documentation review, not interactive demo testing.

| Candidate | Use / decision |
| --- | --- |
| [Shopify POS smart grid](https://help.shopify.com/en/manual/sell-in-person/getting-started/smart-grid) | Product access and register flow reference. No competitor source or assets copied. |
| [Adobe Spectrum colour](https://spectrum.adobe.com/page/using-color) | Purposeful colour and hierarchy reference. Kora's own approved tokens and fonts are retained. |
| [Carbon data tables](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/specifications) | Density, row hierarchy and toolbar reference. No component package copied. |
| [Web Awesome dialog](https://webawesome.com/docs/components/dialog/) | Dialog behaviour candidate; [Core licensing](https://webawesome.com/support) was reviewed. Not installed because native dialogs fit the existing HTML application. |

Native HTML, CSS, SVG and small JavaScript enhancements were selected to fit the Jinja application and avoid another rendering system. No third-party component source or paid block was integrated. Approved brand artwork is reused, with live text and accessible controls separate from the images. Motion is limited to existing brief transitions and reduced-motion preferences are honoured.

## Verification

- 128 Python tests pass, including six new cases covering no-write import review, confirmation/retry, invalid rows and rollback, stale catalogue conflicts, permissions/CSRF/payload boundaries, variant/merchant history scope and duplicate-product error rendering.
- All five account unsaved-change JavaScript tests pass. JavaScript syntax checks and `git diff --check` pass.
- Local Chrome checked 17 routes at 1440 × 960 and 390 × 844, plus tablet order filters, mobile navigation, creation panel and light theme. No page-level horizontal overflow or uncaught JavaScript errors was found in that layout pass.
- The isolated review shop exercised create product, retained duplicate submission, keep/discard, working-view restoration, opening stock, delivery, adjustment, recount, variant history, reviewed CSV confirmation, team/customer/supplier panels, all account sections, current-business return, POS scan/change and mobile payment. Test data is confined to that shop; no outbound invitations or emails were sent.
- Visual screenshots were inspected and refined for stock-summary spacing and the mobile register heading. Physical scanner, Safari/Firefox, assistive-technology and production PostgreSQL contention checks remain release gates.

Self-review: 84/100 against Creative UI v3 (product clarity 14/15, originality 11/15, typography/composition 13/15, brand cohesion 14/15, interaction 8/10, functional/accessibility 12/15, engineering 8/10, craft 4/5). This is an internal design assessment, not independent user testing. Wider browser/device and assisted-use validation remain necessary before production.

Local preview: `http://127.0.0.1:8017/app/1`. Changes are available for review and have not been merged by this task.
