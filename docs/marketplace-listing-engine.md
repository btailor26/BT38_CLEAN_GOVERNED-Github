# Marketplace Listing Engine — governed workflow

Status: specification and intake validation only. No marketplace publication or image generation is implemented by this GitHub Action.

## Sequence
1. Receive original product photographs and seller-supplied facts, including SKU, brand, rights, variants, materials, actual dimensions, weight, packaging and applicable safety/compliance information.
2. Identify visible product characteristics; record confidence and questions. Never invent specifications or branding. Treat seller corrections and original product photos as authority; explicitly distinguish verified, contradicted, and unknown facts. Never turn an unverified fact into persuasive copy.
3. Search Amazon UK and eBay UK using authorised sources/APIs for exact GTIN/model matches first, then comparable products. Record URLs, observation time, price, delivery, competing features and keyword evidence. Do not copy competitors' text or images.
4. Plan and generate 3–5 images from owned/licensed source imagery: compliant marketplace-specific hero, product angles/features, in-use illustration, and accurate dimension/sizing chart where relevant. Clothing requires verified garment measurements and a professional size chart only when sizing information is available; do not invent size conversions. Product images must preserve original front/back, strap paths, cutouts and fastening construction. A confirmed pull-on bodysuit must never be rendered or described with crotch snaps/buttons/poppers. Label illustrative scenes; do not imply accessories are included.
5. Produce separate Amazon and eBay listing drafts: category, title, bullets/item specifics, description, variations, relevant keywords, attributes, shipping, price and policy fields. Optimise concise mobile-first opening text and desktop detail; no keyword stuffing or unsupported claims. Verify every feature, material, stretch/breathability, closure, colour and variation against seller evidence; do not add stock colours or fast dispatch/returns policies without confirmation.
6. Immediately before listing, refresh market observations and check category-specific rules, image restrictions, required attributes, product compliance, duplicate ASIN/GTIN and seller eligibility. Fail closed on missing evidence.
7. Produce review package: original facts, match confidence, source links/timestamps, price/fee assumptions, 3–5 images, channel-specific copy, compliance checklist and unresolved questions.
8. Require explicit seller approval per marketplace and SKU. Only an authorised marketplace adapter may publish; retain audit trail and marketplace response. Never auto-publish on GitHub workflow execution.

## State transitions
INTAKE -> FACTS_REVIEW -> MARKET_RESEARCH -> IMAGE_REVIEW -> LISTING_DRAFT -> PRE_PUBLISH_CHECK -> APPROVAL_REQUIRED -> PUBLISHED (or BLOCKED).

## Separation
This feature must not modify existing BT38 FBM/MCF, warehouse stock authority, OAuth, shipping, deployment readiness, or production deploy gates. Research and image-generation providers must be integrated separately; a GitHub Actions workflow alone cannot perform live market searches or create images without those integrations.

## Input manifest
A JSON file supplied to the validator must contain product_id, seller_sku, source_images (nonempty array), marketplaces (amazon_uk and/or ebay_uk), product_facts (object), and approval_status set to pending. No credentials, secrets, personal addresses, or buyer information in the manifest.

## Mandatory contradiction gate: garment fastening and variations
- Cross-check each proposed listing line against original photos and explicit seller statements. A single contradiction blocks the listing draft from APPROVAL_REQUIRED/PUBLISHED until corrected.
- For the black open-back bodysuit, seller confirms **pull-on construction, no bottom buttons, snaps or poppers**. The cross-strap open back must match the source photo exactly. Never infer a neck strap, fastening, fabric composition, breathability, or care label from a generated image.
- Colours are inventory-specific. Black is pictured; burgundy/green may only be offered if separately verified as stocked seller variations. Sizes S/M/L/XL and their measurements must be verified against the seller-provided chart, not generic UK conversions.
- Shipping speed, returns policy, and fibre composition are account/product facts requiring confirmation, not marketing filler.
- Seller-confirmed corrections supersede earlier generated content; preserve rejected versions in the audit trail. Show a claim-to-evidence table before approval.
