# Mandatory product identification and intended-use research

Status: specification only; no live visual recognition or marketplace search implementation yet.

## Principle
The engine, not the seller, owns the initial investigation into WHAT the photographed object is and WHAT it is used for. Do not make the seller choose a category before conducting evidence-based research. A photograph alone can be ambiguous; never present an inference as verified.

## Pipeline (before listing research and image generation)
1. Inspect all source images: structure, materials as appearance only, fastening, shape, scale cues, ornamentation, packaging, labels, logos and visible text.
2. Generate multiple plausible product identities and intended-use hypotheses; include culturally specific uses and alternative generic uses where visually plausible.
3. Search current authorised Amazon/eBay marketplace data for exact visual/model/GTIN matches, then close comparable matches; record URLs, title, category, photographed structure, seller descriptions, timestamps and strength of evidence. Do not infer that a category is correct just because a keyword match appears.
4. Cross-check candidate identification with visual evidence and market evidence. Score confidence with explicit reasons and distinguish verified facts from assumptions. Check conflicting evidence.
5. Select the best supported identity and intended use. If evidence is insufficient, keep category unverified, request only the minimum truly unavailable factual input and BLOCK publication; continue safe research and drafts with provisional labels if useful.
6. Only after classification, select marketplace categories, SEO keywords, required attributes, compliant hero images and suitable lifestyle/in-use images. Never generate misleading use images or assert dimensions/materials not verified.
7. Recheck classification and market evidence immediately before seller approval/publishing; retain audit evidence and allow seller correction.

## First test case (2026-10-09)
Source: user-provided photograph of a green-ribbon ornament with teal beads, pearl-effect white beads, gold-tone spacers and central pendant. Leading hypothesis: decorative beaded mala/haar potentially for Hindu deity/statue adornment. Alternative: human-worn necklace. **Classification remains provisional until market evidence corroborates it.** Do not claim exact match, deity specificity, real pearls, gold, dimensions or religious use as fact without evidence.

## Acceptance tests
- Product photo with deity jewellery vs similar human necklace must not automatically be labelled human jewellery.
- Search alternatives before asking seller what object is.
- Return top candidate, alternatives, evidence links, confidence, unresolved facts.
- Reject invented materials, dimensions, identity and intended use.
- Never publish if intended use/category unresolved.
- Both NEW_LISTING and REFRESH modes use this identification gate.
