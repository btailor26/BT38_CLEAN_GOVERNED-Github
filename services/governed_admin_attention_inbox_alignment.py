"""Owner-only inbox for BT38 items that require admin review.

This extends the existing Needs admin attention review event stream. It does not
create another truth table, worker, poller or marketplace path. The owner settings
cockpit reads a bounded set of existing SystemEvent rows and presents them in a
collapsed section so the cockpit stays compact.
"""
from __future__ import annotations

from html import escape

from flask import request
from flask_login import current_user

from models import SystemEvent


_REVIEW_CATEGORY = "admin_truth_review_request"
_REVIEW_STATES = {
    "under_review",
    "under review",
    "needs_admin_attention",
    "needs admin attention",
    "review",
}


def _is_admin() -> bool:
    return bool(
        current_user
        and getattr(current_user, "is_authenticated", False)
        and str(getattr(current_user, "role", "")).strip().lower() == "admin"
    )


def _normalise(value) -> str:
    return str(value or "").strip().lower()


def _event_is_under_review(event: SystemEvent) -> bool:
    """One predicate for the owner inbox, including future SystemEvent reviews."""
    if _normalise(getattr(event, "category", None)) == _REVIEW_CATEGORY:
        return True

    details = dict(getattr(event, "details_json", None) or {})
    for key in ("review_status", "status", "state"):
        if _normalise(details.get(key)) in _REVIEW_STATES:
            return True
    return False


def _review_events(limit: int = 100) -> list[SystemEvent]:
    # Bounded audit-stream read only. No provider/marketplace call and no write.
    candidates = (
        SystemEvent.query
        .order_by(SystemEvent.id.desc())
        .limit(500)
        .all()
    )
    return [event for event in candidates if _event_is_under_review(event)][:limit]


def _row(event: SystemEvent) -> str:
    details = dict(getattr(event, "details_json", None) or {})
    section = str(details.get("section") or getattr(event, "description", None) or "Review item")
    reason = str(details.get("reason") or "Review requested")
    source = str(details.get("source_page") or "—")
    requested_by = str(
        details.get("requested_by_username")
        or details.get("requested_by_email")
        or getattr(event, "actor", None)
        or "—"
    )
    timestamp = getattr(event, "timestamp", None)
    when = timestamp.strftime("%d %b %Y %H:%M") if timestamp else "—"
    entity_type = str(getattr(event, "entity_type", None) or "—")
    entity_id = getattr(event, "entity_id", None)
    entity = f"{entity_type} #{entity_id}" if entity_id is not None else entity_type

    return (
        '<tr>'
        f'<td><strong>{escape(section)}</strong><br><small>{escape(reason)}</small></td>'
        f'<td>{escape(entity)}</td>'
        f'<td>{escape(source)}</td>'
        f'<td>{escape(requested_by)}</td>'
        f'<td>{escape(when)}</td>'
        '<td><span class="bt38-admin-review-state">Under review</span></td>'
        '</tr>'
    )


def _section(events: list[SystemEvent]) -> str:
    count = len(events)
    rows = "".join(_row(event) for event in events)
    if not rows:
        rows = '<tr><td colspan="6" class="bt38-admin-attention-empty">Nothing is under review.</td></tr>'

    return f'''
<style id="bt38-admin-attention-style">
.bt38-admin-attention-section{{margin:0 0 12px 0;background:#fff;border:1px solid #ddd;border-radius:14px;overflow:hidden}}
.bt38-admin-attention-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;background:#111;color:#fff}}
.bt38-admin-attention-head strong{{font-size:14px}}.bt38-admin-attention-count{{display:inline-flex;min-width:22px;height:22px;align-items:center;justify-content:center;border-radius:999px;background:#dc3545;color:#fff;font-size:11px;font-weight:800}}
.bt38-admin-attention-body{{display:none;padding:0}}.bt38-admin-attention-section.is-open .bt38-admin-attention-body{{display:block}}
.bt38-admin-attention-table{{width:100%;border-collapse:collapse;font-size:12px}}.bt38-admin-attention-table th,.bt38-admin-attention-table td{{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}.bt38-admin-attention-table th{{background:#f2f3f5;font-size:10px;text-transform:uppercase;color:#555}}.bt38-admin-attention-table small{{color:#666}}.bt38-admin-review-state{{white-space:nowrap;border-radius:999px;background:#fff3cd;color:#856404;padding:3px 7px;font-weight:700}}.bt38-admin-attention-empty{{color:#667085;text-align:center!important;padding:16px!important}}
.bt38-admin-attention-toggle{{border:1px solid #fff;background:#fff;color:#111;border-radius:8px;padding:5px 9px;font-size:11px;font-weight:800;cursor:pointer}}
@media(max-width:900px){{.bt38-admin-attention-body{{overflow-x:auto}}.bt38-admin-attention-table{{min-width:760px}}}}
</style>
<div class="bt38-admin-attention-section" id="bt38AdminAttention" data-bt38-admin-attention="1">
  <div class="bt38-admin-attention-head">
    <div><strong>Needs admin attention</strong> <span class="bt38-admin-attention-count">{count}</span></div>
    <button type="button" class="bt38-admin-attention-toggle" onclick="bt38ToggleAdminAttention()">View reviews</button>
  </div>
  <div class="bt38-admin-attention-body">
    <table class="bt38-admin-attention-table">
      <thead><tr><th>Review</th><th>Entity</th><th>Source</th><th>Requested by</th><th>Time</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
<script id="bt38-admin-attention-script">
function bt38ToggleAdminAttention(){{
  var section=document.getElementById('bt38AdminAttention');
  if(!section)return;
  section.classList.toggle('is-open');
  var button=section.querySelector('.bt38-admin-attention-toggle');
  if(button)button.textContent=section.classList.contains('is-open')?'Hide reviews':'View reviews';
  if(section.classList.contains('is-open'))section.scrollIntoView({{behavior:'smooth',block:'start'}});
}}
</script>
'''


def _inject_owner_inbox(html: str) -> str:
    if 'data-bt38-admin-attention="1"' in html:
        return html
    events = _review_events()
    section = _section(events)

    # Keep the cockpit tidy: place one collapsed section immediately after the
    # header/actions area, before the existing KPI/control sections.
    marker = '<div class="bt38-kpis">'
    index = html.find(marker)
    if index >= 0:
        return html[:index] + section + html[index:]

    body_end = html.rfind("</body>")
    return html[:body_end] + section + html[body_end:] if body_end >= 0 else html + section


def _install() -> None:
    from app import app

    if getattr(app, "_bt38_admin_attention_inbox_after_request", False):
        return

    @app.after_request
    def bt38_admin_attention_inbox_after_request(response):
        try:
            if (
                response.status_code == 200
                and "text/html" in str(response.content_type or "").lower()
                and str(request.path or "") == "/settings"
                and _is_admin()
            ):
                html = response.get_data(as_text=True)
                rendered = _inject_owner_inbox(html)
                if rendered != html:
                    response.set_data(rendered)
                    response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            # Owner monitoring must never break the canonical settings page.
            pass
        return response

    app._bt38_admin_attention_inbox_after_request = True


_install()
