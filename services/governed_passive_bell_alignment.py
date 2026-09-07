"""Keep the notification bell passive and movement-only.

The bell must never become a recovery, hydration, marketplace, provider or
persistent-database read surface. It only projects movement events that the
existing governed UI event signal has already published in this process.
Recovery/readback may update DB truth, but a scan that finds no movement must
never create a user action. Genuine lifecycle movement discovered by recovery
may still appear when it is emitted through the normal UI event path.
"""
from __future__ import annotations

from flask import jsonify, request


def _normalise(value) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _logical_key(record: dict) -> tuple[str, str, str]:
    return (
        str(record.get("order_id") or "").strip(),
        str(record.get("sku") or "").strip(),
        _normalise(record.get("status_label")),
    )


def _is_false_recovery_action(event: dict, record: dict) -> bool:
    """A recovery/readback scan may resolve truth, but may not invent dispatch work."""
    source = _normalise(event.get("source"))
    if not any(token in source for token in ("recovery", "hydrate", "hydration", "readback", "scan")):
        return False
    return str(record.get("status_label") or "").strip() in {
        "Sale",
        "Get ready to dispatch",
        "Partially dispatched",
    }


def passive_event_only_bell_reader():
    """Return only already-published UI movements; perform zero authority reads."""
    from services import governed_fbm_ready_landing_alignment as ready
    from services import governed_ui_event_signal as event_signal

    try:
        limit = int(request.args.get("limit") or 20)
    except Exception:
        limit = 20
    limit = max(1, min(limit, 50))

    with event_signal._condition:
        live_events = [dict(event) for event in list(event_signal._events)]

    records = []
    seen = set()
    for event in reversed(live_events):
        record = ready._event_to_bell_record(event)
        if record is None:
            continue
        if _is_false_recovery_action(event, record):
            continue
        key = _logical_key(record)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= limit:
            break

    action_count = sum(
        1 for record in records
        if record.get("requires_action") is True
        or str(record.get("status_label") or "").strip() in {
            "Get ready to dispatch",
            "Partially dispatched",
            "Return requested",
            "Refund requested",
            "Cancellation requested",
            "Replacement requested",
            "Chargeback",
            "Dispute",
            "Issue / case",
            "Late",
        }
    )

    return jsonify({
        "success": True,
        "records": records,
        "action_count": action_count,
        "latest_event_at": records[0].get("created_at") if records else None,
        "source": "published_ui_movements_only",
        "bell_authority": False,
        "database_calls": False,
        "marketplace_calls": False,
        "provider_calls": False,
        "polling": False,
        "recovery_started": False,
    })


def install_governed_passive_bell_alignment() -> None:
    """Patch the existing bell reader in place; do not add another endpoint."""
    from services import governed_fbm_ready_landing_alignment as ready

    ready._event_only_bell_reader = passive_event_only_bell_reader
    ready._bt38_passive_bell_alignment = True


install_governed_passive_bell_alignment()
