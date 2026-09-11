"""One-time COFI welcome after the customer's first profile setup.

The first-login profile flow stores a single session marker after Username, Name
and Position are saved. This alignment consumes that marker on the next rendered
dashboard response, injects one quiet welcome card into the existing shell, and
then removes the marker so the welcome cannot become recurring onboarding.
"""
from __future__ import annotations

import html

from flask import request, session
from flask_login import current_user

from app import app


_DASHBOARD_PATHS = {"/dashboard", "/governed/dashboard"}
_CONTAINER_MARKER = '<main class="container-fluid py-4">'


@app.after_request
def bt38_cofi_first_dashboard_welcome(response):
    if not current_user.is_authenticated:
        return response
    if response.status_code >= 400:
        return response
    if not response.content_type or "text/html" not in response.content_type:
        return response

    path = request.path.rstrip("/") or "/"
    if path not in _DASHBOARD_PATHS:
        return response

    raw_name = str(session.pop("bt38_cofi_first_welcome", "") or "").strip()
    if not raw_name:
        return response

    first_name = html.escape(raw_name.split()[0])
    body = response.get_data(as_text=True)
    if _CONTAINER_MARKER not in body:
        return response

    welcome = f'''\n<div class="alert alert-light border shadow-sm d-flex align-items-start gap-3 mb-4" role="status" data-bt38-cofi-first-welcome="true" style="border-radius:14px">\n  <div class="rounded-circle bg-dark text-white d-inline-flex align-items-center justify-content-center flex-shrink-0" style="width:38px;height:38px;font-weight:800">C</div>\n  <div>\n    <div class="fw-bold">Welcome, {first_name}. I’m COFI.</div>\n    <div class="text-muted small mt-1">I’ll help surface what matters across your business as your connected information becomes available. Nothing else to set up right now.</div>\n  </div>\n</div>\n'''
    body = body.replace(_CONTAINER_MARKER, _CONTAINER_MARKER + welcome, 1)
    response.set_data(body)
    return response
