# Mandatory product claims evidence gate

Applies to NEW_LISTING, REFRESH, all listing text, attributes, SEO fields, and generated images. Specification only; enforcement code is not yet implemented.

## Rule
Never invent or imply material composition, manufacturing method, quality grade, performance, durability, authenticity, certification, origin, compatibility, or included accessories without verified seller-provided or authoritative product evidence. A photograph can establish visible appearance, not material composition or quality.

## Claims examples
- "Premium beads" -> "Decorative blue beads" unless quality grade is evidenced.
- "Genuine pearls" -> "White pearl-effect beads" unless authenticity is evidenced.
- "Gold-plated" -> "Gold-tone detailing" unless plating is evidenced.
- "Durable materials" -> omit unless durability is evidenced.
- "Handmade" -> omit unless production method is evidenced.
- "Fine finish", "quality craftsmanship" -> use objective visible details instead unless independently substantiated.

## Workflow
1. Extract each proposed factual or promotional claim from title, bullets, description, keywords, attributes, graphics, alt text and image captions.
2. Link each claim to evidence and classify VERIFIED / VISIBLE_APPEARANCE / UNVERIFIED / CONTRADICTED.
3. Allow VERIFIED claims; allow precise appearance descriptions without implying composition. Remove or qualify unverified claims; block contradicted claims.
4. If seller later provides credible material or quality specifications, update claim registry and regenerate affected images and listing copy; require fresh review and approval.
5. Refresh mode audits existing copy and images for unsupported claims and proposes removal or correction.
6. Show a claim-level before/after audit and evidence source; fail closed on regulated or safety-critical claims.
7. Preserve approved factual content and product identity. Do not use unverifiable adjectives such as premium as substitutes for facts.

## Image order
Image 1: marketplace-compliant main image.
Image 2: measurement plus clear design/feature ideas where verified size exists. Only annotate measurement endpoints that have been confirmed; never invent secondary dimensions.
Image 3: realistic lifestyle/use.
Image 4 onward: close-ups and other supported features.
No quality or materials claims in any image without evidence.

## Product 001
Indian Traditional Mala for God – Artificial Ribbon Garland Haar (27cm). 27cm supplied by seller, but measurement endpoints are not yet confirmed. Blue beads, white pearl-effect beads, gold-tone spacers and green ribbon are visible; material composition and quality are not verified. Remove "premium", "durable", "carefully crafted", and similar unsupported claims from future assets.
