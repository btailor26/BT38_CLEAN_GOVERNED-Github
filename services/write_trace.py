import logging
from datetime import datetime

def write_trace(source: str, action: str, meta=None):
    # FORCE ROOT LOGGER (THIS IS WHAT FLY SHOWS)
    logging.getLogger().warning(
        "[WRITE TRACE] source=%s action=%s time=%s meta=%s",
        source,
        action,
        datetime.utcnow().isoformat(),
        meta or {}
    )
