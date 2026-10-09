# Existing listing refresh / enhancement mode

This is a separate mode from NEW_LISTING. This document is a specification, not a deployed implementation.

## Input and baseline
- Require marketplace, seller account/store, existing listing identifier (Amazon ASIN/SKU or eBay item/offer identifier as applicable), seller authorisation and current listing snapshot.
- Capture existing title, bullets/description, images, item specifics, variants, SKU, GTIN, category, pricing, fulfilment, policy settings and listing status.
- Capture available performance baseline (impressions, clicks, conversion, sales, returns) with date range; never promise improvement without measured evidence.

## Refresh pipeline
1. Snapshot existing listing and record its version/time for rollback and conflict detection.
2. Identify and preserve verified product facts; flag missing or conflicting details for seller confirmation.
3. Research exact/comparable current Amazon/eBay market listings and keywords with dated evidence, including relevant category requirements.
4. Draft marketplace-specific enhancements for title, opening mobile copy, desktop detail, attributes and discoverability; preserve true product identity and avoid keyword stuffing.
5. Plan 3–5 refreshed owned/licensed images including marketplace-compliant hero, real-use examples and verified dimension/sizing image when needed. Never invent dimensions, product capabilities, or included accessories.
6. Show field-level before/after diff, proposed images, rationale, and evidence. Preserve identifiers, variations, reviews and sales history where supported; warn of any changes that could affect them.
7. Immediately before approval/publish, refresh market research, validate live category requirements, eligibility, fees/price assumptions, image policies, variation constraints and listing version.
8. Require explicit seller approval for each channel and listing; update only approved fields via authorised marketplace adapters, and record response/audit log. No automatic publication.

## Safety and data authority
- Do not overwrite unapproved fields or inventory/warehouse truth.
- Fail closed if listing has changed since snapshot, seller permissions are missing, measurements unverified, or rules cannot be validated.
- Store original snapshot and proposed changes for recovery; rollback only if API permits and seller approves.
- Separate enhancement of content from repricing, fulfilment, and stock changes.
- No modifications to existing BT38 deployment, FBM/MCF or OAuth flows.

## States
REFRESH_INTAKE -> SNAPSHOT -> MARKET_RESEARCH -> ENHANCEMENT_DRAFT -> IMAGE_REVIEW -> BEFORE_AFTER_REVIEW -> PRE_UPDATE_CHECK -> APPROVAL_REQUIRED -> UPDATED or BLOCKED.
