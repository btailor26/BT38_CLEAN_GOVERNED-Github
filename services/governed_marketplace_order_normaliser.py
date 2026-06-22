from datetime import datetime


def normalise_marketplace_order(payload: dict) -> dict:
    """
    SINGLE SOURCE OF TRUTH for MarketplaceOrder meaning.

    This ensures every order entering BT38 has:
    - correct status
    - correct quantity
    - consistent marketplace mapping
    """

    marketplace = (payload.get("marketplace") or "").lower()
    event_type = (payload.get("event_type") or "").lower()
    raw_status = (payload.get("status") or "").lower()

    # ----------------------------
    # 1. DEFAULT STATUS RULES
    # ----------------------------
    status = raw_status

    # AMAZON / EBAY NORMALISATION
    if marketplace in ["amazon", "ebay"]:

        # SALE EVENTS
        if event_type in [
            "order_created",
            "sale",
            "payment_completed",
            "order_fulfilled",
        ]:
            status = "sale"

        # RETURN EVENTS
        elif event_type in [
            "refund",
            "return",
            "chargeback",
        ]:
            status = "return"

        # CANCELLATIONS
        elif event_type in [
            "cancelled",
            "cancellation",
        ]:
            status = "cancelled"

        # fallback safety
        else:
            status = "sale"

    # ----------------------------
    # 2. QUANTITY NORMALISATION
    # ----------------------------
    quantity = payload.get("quantity") or 1

    try:
        quantity = int(quantity)
    except Exception:
        quantity = 1

    # ----------------------------
    # 3. RETURN CLEAN OBJECT
    # ----------------------------
    return {
        "marketplace": marketplace,
        "status": status,
        "quantity": quantity,
        "sku": payload.get("sku"),
        "order_id": payload.get("order_id"),
        "created_at": payload.get("created_at") or datetime.utcnow().isoformat(),
        "raw_payload": payload,
    }
