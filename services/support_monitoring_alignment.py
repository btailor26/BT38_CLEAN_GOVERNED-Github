"""Compact owner monitoring for the existing BT38 support case authority.

Reads only SupportCase/SupportCaseMessage. It does not create another support
queue, worker, poller, notification service, marketplace read or execution path.
The existing /admin/support/cases page remains the full support workspace.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from flask import request
from flask_login import current_user

from services.support_case_alignment import SupportCase, SupportCaseMessage

# First-response attention targets. These are monitoring thresholds, not customer
# contractual promises. They can later become package/SLA policy without changing
# the SupportCase authority.
_FIRST_RESPONSE_HOURS = {"urgent": 1, "high": 4, "normal": 24, "low": 48}
_ACTIVE_STATES = {"open", "in_progress", "waiting_customer"}


def _is_admin() -> bool:
    return bool(current_user and getattr(current_user, "is_authenticated", False)
                and str(getattr(current_user, "role", "")).strip().lower() == "admin")


def _has_admin_reply(case: SupportCase) -> bool:
    return (SupportCaseMessage.query.filter_by(case_pk=case.id, author_role="admin")
            .order_by(SupportCaseMessage.id.asc()).first()) is not None


def _needs_first_response(case: SupportCase, now: datetime | None = None) -> bool:
    if str(case.status or "") not in _ACTIVE_STATES or _has_admin_reply(case):
        return False
    now = now or datetime.utcnow()
    opened = case.created_at or now
    hours = _FIRST_RESPONSE_HOURS.get(str(case.priority or "normal").lower(), 24)
    return now >= opened + timedelta(hours=hours)


def support_monitor_snapshot() -> dict:
    """Bounded DB-only owner snapshot; no provider/marketplace/carrier calls."""
    active = (SupportCase.query.filter(SupportCase.status.in_(tuple(_ACTIVE_STATES)))
              .order_by(SupportCase.created_at.asc()).limit(500).all())
    urgent = [case for case in active if str(case.priority or "").lower() == "urgent"]
    waiting = [case for case in active if str(case.status or "") == "waiting_customer"]
    overdue = [case for case in active if _needs_first_response(case)]
    return {"open": len(active), "urgent": len(urgent), "waiting": len(waiting),
            "overdue": len(overdue), "overdue_cases": overdue[:25]}


def _section(snapshot: dict) -> str:
    rows = []
    for case in snapshot["overdue_cases"]:
        case_id = escape(str(case.case_id or "Case"))
        subject = escape(str(case.subject or "Support case"))
        priority = escape(str(case.priority or "normal").title())
        rows.append(f'<tr><td><a href="/support/cases/{case_id}"><strong>{case_id}</strong></a></td><td>{subject}</td><td>{priority}</td><td>First response due</td></tr>')
    body = "".join(rows) or '<tr><td colspan="4" class="bt38-support-monitor-empty">No first-response cases are overdue.</td></tr>'
    return f'''
<style id="bt38-support-monitor-style">
.bt38-support-monitor{{margin:0 0 12px;background:#fff;border:1px solid #ddd;border-radius:14px;overflow:hidden}}
.bt38-support-monitor-head{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;background:#111;color:#fff}}
.bt38-support-monitor-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:10px 12px}}
.bt38-support-monitor-stat{{border:1px solid #e5e7eb;border-radius:10px;padding:8px;text-decoration:none;color:#111;background:#fafafa}}
.bt38-support-monitor-stat small{{display:block;color:#667085;font-size:10px;text-transform:uppercase;font-weight:800}}.bt38-support-monitor-stat strong{{font-size:18px}}
.bt38-support-monitor-body{{display:none;padding:0 12px 10px}}.bt38-support-monitor.is-open .bt38-support-monitor-body{{display:block}}
.bt38-support-monitor table{{width:100%;border-collapse:collapse;font-size:12px}}.bt38-support-monitor th,.bt38-support-monitor td{{padding:7px;border-bottom:1px solid #eee;text-align:left}}
.bt38-support-monitor-empty{{text-align:center!important;color:#667085}}.bt38-support-monitor-toggle{{border:1px solid #fff;background:#fff;color:#111;border-radius:8px;padding:5px 9px;font-size:11px;font-weight:800;cursor:pointer}}
@media(max-width:700px){{.bt38-support-monitor-grid{{grid-template-columns:repeat(2,1fr)}}}}
</style>
<div class="bt38-support-monitor" id="bt38SupportMonitor" data-bt38-support-monitor="1">
 <div class="bt38-support-monitor-head"><strong>Support</strong><div><a class="bt38-support-monitor-toggle" href="/admin/support/cases">View cases</a> <button class="bt38-support-monitor-toggle" type="button" onclick="bt38ToggleSupportMonitor()">Overdue details</button></div></div>
 <div class="bt38-support-monitor-grid">
  <a class="bt38-support-monitor-stat" href="/admin/support/cases?status=open"><small>Active</small><strong>{snapshot['open']}</strong></a>
  <a class="bt38-support-monitor-stat" href="/admin/support/cases?priority=urgent"><small>Urgent</small><strong>{snapshot['urgent']}</strong></a>
  <a class="bt38-support-monitor-stat" href="/admin/support/cases?status=waiting_customer"><small>Waiting</small><strong>{snapshot['waiting']}</strong></a>
  <a class="bt38-support-monitor-stat" href="/admin/support/cases?attention=overdue"><small>First response due</small><strong>{snapshot['overdue']}</strong></a>
 </div>
 <div class="bt38-support-monitor-body"><table><thead><tr><th>Case</th><th>Subject</th><th>Priority</th><th>Attention</th></tr></thead><tbody>{body}</tbody></table></div>
</div>
<script>function bt38ToggleSupportMonitor(){{var e=document.getElementById('bt38SupportMonitor');if(e)e.classList.toggle('is-open');}}</script>
'''


def _inject(html: str) -> str:
    if 'data-bt38-support-monitor="1"' in html:
        return html
    section = _section(support_monitor_snapshot())
    # Put Support after Needs admin attention when present, otherwise before KPIs.
    marker = '<div class="bt38-kpis">'
    index = html.find(marker)
    return html[:index] + section + html[index:] if index >= 0 else html


def _install() -> None:
    from app import app
    if getattr(app, "_bt38_support_monitor_installed", False):
        return

    @app.after_request
    def bt38_support_monitor_after_request(response):
        try:
            if (response.status_code == 200 and "text/html" in str(response.content_type or "").lower()
                    and str(request.path or "") == "/settings" and _is_admin()):
                html = response.get_data(as_text=True)
                rendered = _inject(html)
                if rendered != html:
                    response.set_data(rendered)
                    response.headers["Content-Length"] = str(len(response.get_data()))
        except Exception:
            pass
        return response

    app._bt38_support_monitor_installed = True


_install()
