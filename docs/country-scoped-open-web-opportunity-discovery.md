# Country-scoped, open-web opportunity discovery

Status: specification only; automated discovery not yet implemented.

## Governing principle
Search **all publicly discoverable online sales channels**, not a fixed marketplace allowlist. The seller selects the intended sales country (or explicitly multiple countries). This is the mandatory geographical filter for product opportunities, competitor pricing, fulfilment, currency, taxation and marketplace eligibility. Competitors may be headquartered anywhere provided they demonstrably sell or ship to the selected destination country. A country-code domain alone does not prove availability.

## Discovery strategy
1. Record the seller's destination country, product identity, intended use, verified attributes, synonyms and language(s) appropriate to that market.
2. Run multiple discovery passes using product names, regional synonyms, image/visual descriptions where available, product category, use cases, dimensions, colours, alternate spellings and buyer-intent queries. Broaden iteratively beyond first-page results and initial marketplaces.
3. Discover sellers dynamically: Amazon, eBay, Etsy, OnBuy and other marketplaces; standalone brands; Shopify/WooCommerce/Magento and custom storefronts; independent shops; specialist retailers; distributors and direct-to-consumer websites; niche/community commerce channels where publicly accessible.
4. Follow related products, brand/storefront references, category navigation, comparison sites and search results to uncover additional retailers. Do not cap discoveries by a hard-coded platform list or arbitrary fixed result count. Use sensible crawl budgets, deduplication, rate limits and diminishing-return stopping rules; record coverage and gaps.
5. For each candidate, verify the product is purchasable/deliverable in the selected country using shipping policy, checkout destination, localized offer or other direct evidence. Mark uncertain destinations as unverified rather than assuming.
6. Capture direct product URL, observed date, retailer, marketplace vs own website, country availability evidence, product match level, exact size convention, item price, shipping, taxes and fees where available, stock status, and source confidence.
7. Seek completed sales, product-level review dates and independently corroborated demand. Distinguish listed asking prices from sold prices; shop-wide sales from product sales; a review date from a sale date. Private-store sales volumes are often unavailable: do not invent them.
8. Normalize landed buyer price into the seller's market currency, accounting for delivery, taxes and quantity. Compare like-for-like items; highlight uncertain or missing costs.
9. Rank discovered **channels and product opportunities** by market fit, country eligibility, demand evidence, competitive prices, marketplace eligibility, fulfilment and expected seller contribution margin. Separate verified results from hypotheses.
10. Output strongest opportunities with direct source links, checked timestamps, seller country, destination-country evidence, price comparison, uncertainty, gaps and actionable next steps. Require seller approval before listing or publishing.

## Scope and limitations
- "No limits" means no arbitrary website, marketplace or retailer category exclusions. It does **not** imply unlimited crawling, guaranteed complete internet coverage, access to private analytics, bypassing logins/paywalls/robots controls, or access to confidential sales data.
- Comply with site access terms, rate limits, applicable laws and privacy obligations. Prefer authorized feeds/APIs when available.
- Search results are evidence snapshots, not proof of current stock or completed sales. Refresh before action.
- Multiple destination countries require separate country-specific comparisons and eligibility checks; never silently mix UK prices with other markets.

## Example: 27cm deity mala, seller targets UK
Search Etsy UK, eBay UK, OnBuy UK, Amazon UK, UK-serving independent religious shops, own-domain Hindu/pooja retailers, niche storefronts and other dynamically discovered sites. Include overseas stores only if they ship to the UK. Record 27cm as **full length including ribbon** and do not compare directly to 27cm beaded-section-only measurements without a warning. Material claims must pass the separate evidence gate.

## Integration
This document extends the mandatory Cross-Marketplace Opportunity Discovery stage and supersedes any interpretation of its example marketplace list as exhaustive.
