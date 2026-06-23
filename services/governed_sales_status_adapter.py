def is_sale(status: str) -> bool:
    if not status:
        return False
    return status in ["order", "processed"]


def is_return(status: str) -> bool:
    if not status:
        return False
    return status in ["failed"]


def is_pending(status: str) -> bool:
    if not status:
        return False
    return status in ["pending"]
