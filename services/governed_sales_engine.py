def is_sale(status: str) -> bool:
    return (status or "").lower() in {
        "order",
        "processed",
        "completed"
    }

def is_pending(status: str) -> bool:
    return (status or "").lower() in {
        "pending"
    }

def is_return(status: str) -> bool:
    return (status or "").lower() in {
        "failed",
        "cancelled",
        "refunded"
    }
