"""
Services package - Business logic and external integrations
"""

# Global Amazon FBA settlement rule. Importing the services package installs a
# narrow wrapper around the existing exact-event runtime so any delayed Amazon
# FBA Seller-SKU change committed to Neon wakes the same targeted UI channel.
# It does not create a second inventory authority, worker, scan, or push path.
import services.governed_fba_settlement_ui_alignment  # noqa: F401,E402

# MCF tracking recovery must be installed before the governed runtime performs
# its bounded startup recovery. The recovery keeps already-dispatched external
# marketplace MCF orders alive until Amazon tracking enrichment is complete,
# including multi-package tracking that arrives after a Fly sleep/restart.
# This reuses the existing MCF refresh and marketplace enrichment path.
import services.governed_mcf_tracking_startup_alignment  # noqa: F401,E402

# Exact eBay shipment hydration also checks the exact order's eBay Finances
# SHIPPING_LABEL truth when shipment fulfilment exists. This remains read-only,
# zero-polling, and persists only into the existing shipping spend ledger.
import services.governed_ebay_shipping_label_finance_alignment  # noqa: F401,E402

# Existing Amazon FBM profile hydration also recovers Seller Central-purchased
# Buy Shipping label authority from exact Amazon Finances + Merchant Fulfillment
# reads. Tracking is optional; the validated Amazon ShipmentId is the durable
# shipment identity. No worker, poller, second order path, or marketplace write.
import services.governed_amazon_shipping_label_readback_alignment  # noqa: F401,E402

# Exact Amazon order verification must also reuse the existing Orders v2026
# PACKAGES readback so shipped FBM orders persist Amazon-owned carrier/tracking
# truth when it is available. This remains one exact-order read with no scan,
# poller, worker, shipment-table proxy, marketplace write, or second order path.
import services.governed_amazon_tracking_runtime_alignment  # noqa: F401,E402

# Successful shipment lifecycle events finish only that exact existing FBM
# order's marketplace shipment authority. This reuses the established Amazon
# and eBay exact readbacks and never introduces polling, startup recovery or a
# broad marketplace/database scan.
import services.governed_fbm_shipment_event_alignment  # noqa: F401,E402

# The bounded FBM workspace must still bootstrap exact Amazon classification for
# visible/selected rows when no complete FBMOrderProfile exists. This restores
# the existing profile authority (Prime/SFP, fulfilment, promise and shipped-order
# readbacks) without making the health aggregation a marketplace-read surface.
import services.governed_fbm_amazon_profile_alignment  # noqa: F401,E402

# The existing 8-hour governed recovery must also invoke the already-built
# bounded exact eBay missing-tracking readback. This only restores invocation of
# eBay shipment truth for existing MarketplaceOrder rows; it adds no new writer,
# poller, worker, shipment table or marketplace mutation path.
import services.governed_ebay_runtime_recovery_alignment  # noqa: F401,E402

# Historical provider-line siblings are audit evidence, not separate commercial
# bell actions. Patch the existing small FBM bell installer so pending/unshipped
# siblings collapse to one logical sale and later shipment events retire that
# stale sale. This adds no DB/provider read or polling path.
import services.governed_fbm_logical_bell_alignment  # noqa: F401,E402

# The authority-backed bell already exposes a governed action_count. Keep the
# red badge and assistant presentation tied to that one count rather than their
# older unread-history/dashboard-attention counters. This observes only the bell
# request the browser already makes; no extra read, polling or marketplace call.
import services.governed_action_count_ui_alignment  # noqa: F401,E402

# The authority-backed bell reader can still see more than one historical
# MarketplaceOrder provider-line sibling for the same commercial order. Collapse
# those siblings to one Ready action and retire all stale Ready siblings when the
# same projection already contains a persisted shipment lifecycle. No new read,
# write, polling or provider path is introduced.
import services.governed_fbm_logical_action_count_alignment  # noqa: F401,E402
