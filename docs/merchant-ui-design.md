# Merchant workspace design

Kora Desk helps independent merchants organise products, opening stock, and staff access in one private business workspace.

Applied the user-provided creative-ui v2 instructions. Considered playful, colourful commerce panels and a quieter editorial workspace. Chose the latter for daily stock tasks, using Kora's existing four-colour symbol, dark navigation, green actions, Nunito headings, and Inter body text. The marketing repository supplied the logo and palette. Fonts are self-hosted with their licences.

The redesign covers sign-in, registration, business setup, overview, products, inventory, team management, invitations, and errors. Catalogue search and stock filters work on the loaded catalogue. Team tabs support arrow, Home, and End keys. Removing a member asks for confirmation. Without JavaScript, both team lists and ordinary server forms remain available. Phone tables become labelled records.

Validation on 18 October 2026: all 43 existing tests passed. Chrome browser checks passed registration, business creation, product entry, opening stock, invitation acceptance, staff read access, and access removal. Desktop and mobile screenshots were inspected. This is a local review build; Safari, Firefox, assistive-technology review, and production PostgreSQL concurrency remain unverified.

The preview uses isolated sample data. No merge or deployment is part of this design change.
