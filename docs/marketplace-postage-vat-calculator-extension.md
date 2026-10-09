# Postage VAT extension to marketplace pricing calculator

Status: specification; not yet implemented in BT38.

Add seller-controlled, separate VAT treatment for **buyer-paid delivery** and **carrier-purchased delivery**.

## Seller inputs
- Buyer delivery charge, VAT rate and VAT-inclusive/exclusive setting; tax liability/collection party.
- Carrier postage paid, whether price includes VAT, carrier VAT rate (0%, 20%, or seller-entered other rate), and whether input VAT is recoverable.
- Seller VAT registration and recovery status are explicitly entered; never assume.
- Record carrier invoice/tax evidence when available; do not infer VAT from the postage price alone. UK postage services vary in VAT treatment.
- Existing marketplace fee VAT recovery settings remain independent of carrier postage VAT.

## Calculation
- Buyer delivery output VAT if inclusive: delivery_gross * rate/(1+rate). If exclusive: delivery_net * rate, added to buyer total.
- Carrier postage input VAT if inclusive: carrier_gross * rate/(1+rate). If exclusive: carrier_net * rate, added to carrier cost.
- For profit, subtract carrier postage net of **recoverable** input VAT; otherwise subtract full carrier gross.
- Show carrier input VAT recovered separately and output VAT on buyer delivery separately.
- Apply marketplace fees to the correct buyer gross transaction base including delivery/taxes according to the actual marketplace fee rules.
- Do not double-count output VAT or recoverable input VAT. Distinguish cash flow from contribution margin.
- VAT on postage and VAT on the item may differ, depending on the tax treatment of the supply; do not assume both are always 20%.

## Example
Carrier postage invoice GBP 3.00 VAT-inclusive at 20%: GBP 0.50 input VAT; if recoverable, economic postage cost GBP 2.50, otherwise GBP 3.00. If carrier postage is VAT-exempt/zero-rated and the invoice shows no VAT, no input VAT can be reclaimed.

## UI acceptance
Independent controls for delivery charged to buyer and carrier postage bought; rates, inclusion modes and recoverability. Live updates to buyer total, VAT breakdown, marketplace fee, estimated profit and margin. Unknown status must be visible, not silently assumed.
