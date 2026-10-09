# Marketplace Listing Engine — governed workflow

Status: specification and intake validation only. No marketplace publication or image generation is implemented by this GitHub Action.

## Sequence
1. Receive original product photographs and seller-supplied facts, including SKU, brand, rights, variants, materials, actual dimensions, weight, packaging and applicable safety/compliance information.
2. Identify visible product characteristics; record confidence and questions. Never invent specifications or branding.
3. Search Amazon UK and eBay UK using authorised sources/APIs for exact GTIN/model matches first, then comparable products. Record URLs, observation time, price, delivery, competing features and keyword evidence. Do not copy competitors' text or images.
4. Plan and generate 3–5 images from owned/licensed source imagery: compliant marketplace-specific hero, product angles/features, in-use illustration, and accurate dimension/sizing chart where relevant. Clothing requires verified garment measurements and a professional size chart. Label illustrative scenes; do not imply accessories are included.
5. Produce separate Amazon and eBay listing drafts: category, title, bullets/item specifics, description, variations, relevant keywords, attributes, shipping, price and policy fields. Optimise concise mobile-first opening text and desktop detail; no keyword stuffing or unsupported claims.
6. Immediately before listing, refresh market observations and check category-specific rules, image restrictions, required attributes, product compliance, duplicate ASIN/GTIN and seller eligibility. Fail closed on missing evidence.
7. Produce review package: original facts, match confidence, source links/timestamps, price/fee assumptions, 3–5 images, channel-specific copy, compliance checklist and unresolved questions.
8. Require explicit seller approval per marketplace and SKU. Only an authorised marketplace adapter may publish; retain audit trail and marketplace response. Never auto-publish on GitHub workflow execution.

## State transitions
INTAKE -> FACTS_REVIEW -> MARKET_RESEARCH -> IMAGE_REVIEW -> LISTING_DRAFT -> PRE_PUBLISH_CHECK -> APPROVAL_REQUIRED -> PUBLISHED (or BLOCKED).

## Separation
This feature must not modify existing BT38 FBM/MCF, warehouse stock authority, OAuth, shipping, deployment readiness, or production deploy gates. Research and image-generation providers must be integrated separately; a GitHub Actions workflow alone cannot perform live market searches or create images without those integrations.

## Input manifest
A JSON file supplied to the validator must contain product_id, seller_sku, source_images (nonempty array), marketplaces (amazon_uk and/or ebay_uk), product_facts (object), and approval_status set to pending. No credentials, secrets, personal addresses, or buyer information in the manifest.
