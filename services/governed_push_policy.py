def should_push_listing(listing):
    """
    SINGLE RULE SOURCE OF TRUTH
    """

    is_fba = (
        bool(getattr(listing, "is_fba", False)) or
        str(getattr(listing, "amazon_fulfillment_channel", "")).upper() in {"FBA", "AFN"}
    )

    return {
        "allow_push": not is_fba,
        "is_fba": is_fba,
        "mode": "skip_fba" if is_fba else "push_allowed"
    }
