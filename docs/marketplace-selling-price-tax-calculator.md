# Marketplace selling-price and tax calculator

Status: mandatory feature specification for the Marketplace Listing Engine; calculator implementation is not yet complete.

## Placement
Display an interactive **Compare alternative prices** calculator after opportunity research and before approval for NEW_LISTING and REFRESH. Prepopulate product facts and landed cost, retain seller overrides, and recalculate live as price, channel, category, delivery and taxes change. Do not publish without approval.

## Inputs
- Seller-entered product landed cost (Product 001: GBP 1.00), product weight (13g), dimensions (length 2cm, height/full length 27cm, width 1cm). Shipping charges must be based on **packed** weight/dimensions, not bare product size.
- Selling price, marketplace recommendation (Product 001 eBay suggested GBP 5.13, not a sold-price observation), selling country/currency, buyer-paid delivery, seller outbound postage, packaging, returns reserve, promotion percentage and other expenses.
- Marketplace, **actual leaf category ID**, account/business-seller status and applicable fee schedule version/effective date. Resolve percentage fee, per-order fixed fee, category exceptions, regulatory fees, listing and promotional charges using current official country-specific rate card. If category or rate cannot be verified, clearly mark as estimated and avoid pretending to be exact.
- Seller-editable taxes: sale VAT rate %, sale price is VAT-inclusive vs VAT-exclusive, VAT registration / marketplace tax collection treatment, marketplace-fee VAT rate %, fee VAT recoverable yes/no, optional other tax percentage or fixed amount with explicitly selected base, and seller-entered adjustments. Default unknown taxes to UNSET, not 0% as a factual assertion.
- Support multiple tax components and show assumptions. Never infer seller VAT registration or eligibility to reclaim input VAT.

## Calculations
Let item_price_entered = P, buyer_postage = S, sale VAT rate = v, and sale-price mode = inclusive/exclusive.
- If VAT-inclusive: item gross = P; item output VAT = P*v/(1+v).
- If VAT-exclusive: item gross = P*(1+v); item output VAT = P*v.
- Apply VAT to buyer postage according to its independently configured tax treatment; do not assume item and postage are always identical.
- Buyer total = item gross + buyer postage gross. Marketplace transaction fee base must follow marketplace rules, which may include delivery and taxes.
- Fee before fee VAT = rate-card variable fee + per-order fee + regulatory charge + promotional fee + any other verified marketplace charges.
- Fee VAT = applicable fee VAT rate * taxable fee base. Deduct unrecoverable fee VAT only; if recoverable, display separately as input tax credit, not as net cost. Explain when the seller's accounting cash flow differs from profit.
- Output VAT liability = output VAT collected by seller less relevant adjustments, accounting for any marketplace collection/remittance rules. Avoid double-deducting VAT already remitted by marketplace.
- Seller profit contribution = seller-attributable revenue net of output VAT - landed cost - outbound shipping - packaging - fee before VAT - unrecoverable fee VAT - applicable other taxes - returns reserve - other expenses.
- Margin = contribution / seller-attributable gross revenue (clearly labelled denominator); show a consistent VAT-exclusive margin when seller is VAT registered.
- Round final monetary display to pennies, retain sufficient precision internally and follow each platform's fee rounding rules.

## UI and outputs
- Slider and editable selling price with reset to platform-recommended price.
- Actual category picker/ID, live rate-card version, fees broken out (percentage, fixed, regulatory, promotion, VAT on fees).
- Seller controls for VAT on sale, VAT-inclusive/exclusive, VAT on fees and recoverability, additional taxes, buyer postage, postage cost, packaging and promotions.
- Show buyer pays, output VAT, seller revenue net of VAT, all marketplace fees, recoverable vs nonrecoverable fee VAT, total tax, profit, margin and break-even price.
- Compare scenarios across country-relevant marketplaces and independent storefronts; each channel has its own fee structure and tax treatment.
- Flag uncertain inputs; do not make unverified tax/legal assertions. Seller remains responsible for their tax settings. Save the scenario with source and timestamp.

## Product 001 baseline
Indian Traditional Mala for God – Artificial Ribbon Garland Haar; 27cm **full length including ribbon**, 13g, 2cm length, 1cm width; landed cost GBP 1.00; eBay suggested selling price GBP 5.13. Seller tax registration and actual eBay leaf category not confirmed; calculator must request or allow seller to set these rather than assuming them.

## Acceptance tests
- VAT-inclusive 20% on GBP 6.00 => GBP 1.00 output VAT; VAT-exclusive 20% on GBP 6.00 => GBP 7.20 buyer item gross and GBP 1.20 output VAT.
- Fee VAT recoverable toggle changes profit only by the unrecoverable portion.
- Buyer-paid delivery included in fee base where rate card specifies.
- Marketplace category change recomputes correct rate-card fees.
- Unknown tax and fee values remain visibly unverified, not silently 0.
- Additional taxes can be fixed or percentage, with clearly defined base.
- No automatic publishing.
