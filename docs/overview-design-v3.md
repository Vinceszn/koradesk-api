# Kora overview — creative-ui v3

## Direction
Kora helps independent merchants build a reliable shared stock picture from their products, opening counts, and staff permissions.

Compared a dense operational dashboard against a guided shop desk. Chose the shop desk: a green introductory panel with a real count-completion graphic, compact metrics, a three-step setup path, the live catalogue, contextual stock guidance, and a team shortcut. Existing Kora branding and fonts remain the source of truth. Empty, partial, and complete inventory states have their own truthful copy.

## Component sourcing
Official documentation reviewed on 18 October 2026; documentation inspection, not live-demo testing.

| Candidate | Fit and decision |
| --- | --- |
| [Tremor](https://www.tremor.so/) | Useful dashboard hierarchy and compact-data inspiration. Its React/Tailwind foundation would add a second rendering stack to this Jinja application; no code or paid blocks copied. |
| [Motion](https://motion.dev/docs/quick-start) | Suitable JS animation API, but this page needs only brief hover feedback. No runtime added, no source copied. |
| [Shoelace](https://shoelace.style/) | Framework-independent components and MIT licensing, but its official site reports sunset status. Not adopted. |
| [Native details](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/details) | Selected for stock explanations: keyboard-operable disclosures with no JavaScript or extra package. Original markup and styles; no third-party code copied. |

Native SVG represents counted variants, backed by the same visible counts. HTML remains the accessible information layer. No generated artwork is needed for this data-focused screen. This keeps the diagram sharp and accurate, and avoids decorative downloads.

## Implementation and limits
The stylesheet is loaded only on the overview. No new dependency, external request, or backend mutation was introduced. Explanations clarify that stock value is at selling price and that uncounted variants are excluded from totals. Owner and staff links respect their actual workflows. Motion is limited to pointer feedback and honours reduced motion.

Existing backend checks and browser workflow are rerun for this change. Local Chrome verification is not a claim of Safari, Firefox, screen-reader, low-powered-device, or production PostgreSQL validation.
