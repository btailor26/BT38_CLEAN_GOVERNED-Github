"""
Services package - Business logic and external integrations
"""
import sys

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

# Amazon order idempotency is line-level, not order-level. Existing persisted
# siblings must never suppress the exact Orders.get_order_items read because one
# AmazonOrderId can contain multiple sizes/SKUs. This replaces only the existing
# bounded Amazon import function and keeps the same writer/stock bridge.
import services.governed_amazon_multiline_order_alignment  # noqa: F401,E402

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

# Show persisted Amazon FBA/AFN order lifecycle on the existing /fbm table only.
# Pending remains Pending; shipped/dispatched lifecycle appears under the local
# FBA tab. Rows are display-only and never enter FBM shipping eligibility.
import services.governed_fbm_fba_visibility_alignment  # noqa: F401,E402

# Some Amazon FBA webhook rows carry BT38's internal intake marker ``processed``
# while Amazon itself is still Pending. Preserve those rows in the existing
# Pending tab until real persisted shipment/lifecycle evidence moves them to FBA.
import services.governed_fbm_fba_pending_status_alignment  # noqa: F401,E402

# Amazon ORDER_CHANGE can carry the S02 identity for an already-existing MCF
# order. Attach that identity through the existing MCF seller-fulfilment item id
# before the ordinary Amazon order path continues. No second order path or read.
import services.governed_mcf_amazon_order_identity_alignment  # noqa: F401,E402

# MCF is its own fulfilment lifecycle, not FBA presentation. Reuse the existing
# /fbm table to expose persisted MCF orders under a dedicated MCF tab and prevent
# positive MCF/S02 rows from being absorbed into Pending/FBA. Presentation only.
import services.governed_fbm_mcf_visibility_alignment  # noqa: F401,E402

# The modules below register routes/after-request hooks and therefore require an
# already-created Flask app. A plain ``import services.x`` in contract tests must
# not bootstrap app.py or demand a Neon URL. In real application startup app.py is
# loaded first, so these installers still register against the existing app.
_app_module = sys.modules.get("app")
if _app_module is not None and getattr(_app_module, "app", None) is not None:
    # Until each audited fallback/default area is corrected individually, surface it
    # explicitly as "Needs admin attention" rather than allowing uncertainty to look
    # like verified business truth. Review requests use the existing SystemEvent
    # audit stream only and never mutate canonical marketplace/warehouse data.
    import services.governed_truth_attention_alignment  # noqa: F401,E402

    # The owner cockpit consumes the same SystemEvent review stream as one compact,
    # collapsed inbox. Anything explicitly marked under review is surfaced there;
    # no second review table, worker, poller or marketplace path is introduced.
    import services.governed_admin_attention_inbox_alignment  # noqa: F401,E402

    # COFI controls extend the existing owner fuse board and persist in SystemConfig.
    # No second settings page, worker, sync path or marketplace execution path.
    import services.cofi_settings_alignment  # noqa: F401,E402

    # BT38 owns invoice persistence and PDF/CSV generation. Revolut remains payment
    # authority only; this module makes no provider call and uses no paid document service.
    import services.billing_invoice_alignment  # noqa: F401,E402

    # Revolut subscription billing extends the existing package assignment only.
    # It registers explicit owner-start and signed webhook routes, stores provider
    # identifiers in a 1:1 binding row, and makes no provider call on application start.
    import services.revolut_subscription_alignment  # noqa: F401,E402

    # Customer/account support is a case workflow only. It uses the existing
    # CustomerAccount authority and never reads/writes marketplace, carrier or payment
    # provider truth. The existing public /support page remains separate.
    import services.support_case_alignment  # noqa: F401,E402

    # Private case evidence stays on the existing SupportCase authority and is stored
    # durably in Postgres, never under Fly's ephemeral/static filesystem. Downloads
    # re-use the same account/admin case scope and are forced as attachments.
    import services.support_attachment_alignment  # noqa: F401,E402

    # Owner monitoring reads the same support case/message authority and adds only a
    # compact /settings summary. No second queue, worker, provider call or poller.
    import services.support_monitoring_alignment  # noqa: F401,E402

    # Support reply attention extends the already-existing notification bell read.
    # Only safe case metadata is exposed; no message bodies, context secrets, second
    # notification table, worker, poller or external provider call is introduced.
    import services.support_notification_alignment  # noqa: F401,E402
