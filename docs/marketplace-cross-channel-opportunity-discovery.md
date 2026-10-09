# Cross-Marketplace Opportunity Discovery — mandatory listing-engine stage

Status: workflow specification, not implemented research automation.

## Trigger and placement
Run after product identification and before seller approval of any new or refreshed listing. Re-run when product facts, target markets, or pricing change, and immediately before publication when market evidence is stale.

## Reproducible research procedure
1. Establish verified product identity, intended use, visual features, size and known restrictions. Record uncertainty. For Product 001: Hindu deity mala/haar, decorative blue beads, white pearl-effect beads, gold-tone spacers, green ribbon; 27cm full length including ribbon.
2. Generate search synonyms from product use and regional terminology, e.g. "deity mala", "idol haar", "Laddu Gopal jewellery", "artificial beaded haar", "murti garland", "pooja mala"; add specific size, colour and UK qualifiers. Avoid over-restricting searches to exact title.
3. Search each marketplace separately: eBay UK, Etsy UK, Amazon UK, OnBuy UK; also search specialist Hindu/pooja retailers. Broaden to other relevant channels only where product-category evidence supports it.
4. Open actual product and category pages. Capture direct listing URL, product description, size, colour, included quantity, asking price, shipping, currency, listing availability, seller, and evidence retrieval timestamp. Distinguish exact matches, close comparables and broad category examples.
5. Investigate *demand*, not just supply. Prioritise dated completed/sold transactions and transaction-level prices. Where inaccessible, inspect dated product reviews and seller activity, explicitly recording the limitations. Shop-wide sales and ratings are NOT item-level sales. Never infer a last-sold date or sales velocity from an active listing or a review alone.
6. Look for dedicated categories, relevant product searches, repeated offerings and specialist stockists as market-fit signals. Mark them as weaker than verified completed sales.
7. Check product eligibility and policy for each channel before recommending: especially Etsy's creativity/handmade/vintage/craft-supply criteria; do not imply mass-produced resale is allowed. Check category restrictions and required attributes elsewhere.
8. Estimate economics when data is available: selling price range, marketplace fees, fulfilment, postage, VAT, return allowances, acquisition cost, expected contribution margin. If costs are unknown, flag profitability UNVERIFIED and ask seller only for truly necessary missing facts.
9. Rank channels by verified product-level demand, buyer fit, eligibility, competitive intensity, net margin and confidence. Do not promote a channel solely on seller/shop-wide metrics.
10. Produce a concise opportunity card per channel with recommendation, exact evidence URLs, dates, comparable differences, demand confidence, eligibility status, economics, and next validation action. Highlight strongest channel first and include counterevidence.
11. Seller approves or rejects opportunities; no automatic listing or publication.

## Example — 27cm deity mala (illustrative research, not validated live market feed)
- Etsy UK: comparable artificial beaded haar, seller reviews and shop-wide sales were found. Shop-wide sales do not establish this product's sales. Etsy eligibility requires verification.
- eBay UK: comparable deity mala listings were found, but asking prices are not completed sales.
- OnBuy UK: similar beaded haar offered, including a 27cm option with a DIFFERENT measurement convention; do not treat as exact.
- Specialist Hindu shops: dedicated deity jewellery categories demonstrate relevant retail channel, not unit demand.
- Amazon UK: no sufficiently verified comparable sales evidence from this research; mark unknown, not zero.

## Evidence schema
For each source store {marketplace, url, checked_at, title, product_match_level, size_definition, asking_price, shipping, item_level_sales, sold_date, product_reviews_dated, shop_sales, seller_rating, eligibility, fees, confidence, caveats}. Unknown values must be null/UNVERIFIED rather than fabricated.

## Quality gates
- Cite direct URLs; do not invent links, figures, sale dates, or price history.
- Separate evidence from inference; record research date and currency.
- Do not equate availability with demand, review with sale date, or seller total with item total.
- Do not assert profit without validated fees and costs.
- Do not automatically publish or create external marketplace listings.
- Recheck evidence and product policy before approval/publication.
