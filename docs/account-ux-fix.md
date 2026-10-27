# Account navigation and UX refinement

## Defect and correction

The original profile's closed email-change form was automatically populated by the real browser's password manager. The unsaved-change handler compared every form value and treated that autofill as a draft, which cancelled navigation through `beforeunload`. This was reproduced in the user's in-app browser: Security stayed on Profile and direct navigation was aborted. A fresh Chrome review profile had not exposed the saved-autofill case.

The tracker now requires an intentional, trusted edit, ignores native autofill and credential helpers, and only installs `beforeunload` while real draft changes exist. Internal navigation uses a visible native HTML dialog with Keep editing and Discard changes actions. Both choices were exercised with a temporary, unsaved display-name draft; no user profile changes were submitted. Ordinary links remain server-rendered and functional without JavaScript.

## Design choices

Two options were considered: tightening the horizontal tabs, or using a compact settings rail. The rail was chosen because it keeps four destinations visible and leaves a focused, wider form area. Phones use a two-column section menu. The oversized profile banner and repeated explanatory side panel were removed. Form labels, card spacing, primary actions, selected states, heading hierarchy and native upload-button contrast were refined. Preferences use a two-column grouping on wide screens and a single column on narrower screens.

References reviewed:

- [W3C consistent navigation](https://www.w3.org/WAI/WCAG22/Understanding/consistent-navigation.html): stable destination order and selected-page indication.
- [W3C modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/): meaningful labels, initial focus on the safe action, Escape support and focus return.
- [GOV.UK text input guidance](https://design-system.service.gov.uk/components/text-input/): visible, concise labels and useful field hints.
- [MDN beforeunload guidance](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeunload_event): attach the warning only while unsaved changes exist.

The existing Jinja/HTML/CSS foundation was retained. No React component system, animation library, copied component code, new artwork, or external runtime was needed. All visual changes are original CSS using the existing Kora colours, fonts and icons. No third-party component assets or licences were introduced.

## Verification

All 94 Python tests and five focused JavaScript regression tests pass. The JavaScript checks cover hidden autofill, credential helpers, untrusted programmatic changes, actual edits, reversion/reset, and checkbox/select preferences. Security, Business access and Preferences were opened by clicking their links in the actual in-app browser. Genuine draft protection was tested in that browser with both Keep editing and Discard changes. Keyboard activation, Escape, focus return, and Cancel/reset were also exercised. All four sections were checked at a 360px viewport with no document overflow and 48px navigation targets; the normal viewport was restored afterward. The stale preview tab was replaced only after confirming it had no user-entered draft. No profile edits were saved during the browser checks.

Run the JavaScript checks with `node --test tests/account_unsaved.test.mjs`; they use Node's built-in test runner and need no npm dependencies.

This is a targeted usability and regression review, not a formal accessibility certification.
