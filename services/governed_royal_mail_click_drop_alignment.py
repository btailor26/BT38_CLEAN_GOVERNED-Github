"""Install the merchant-owned Royal Mail Click & Drop connection.

This is connection/read alignment only. It does not create marketplace orders,
purchase postage, poll Royal Mail in the background, or introduce another
shipment table.
"""
from __future__ import annotations

from flask import request

from governed_royal_mail_routes import (
    ensure_royal_mail_connection_schema,
    governed_royal_mail_bp,
)


def install_governed_royal_mail_click_drop_alignment(app) -> None:
    if getattr(app, "_bt38_royal_mail_click_drop_alignment_installed", False):
        return

    with app.app_context():
        ensure_royal_mail_connection_schema()

    if "governed_royal_mail" not in app.blueprints:
        app.register_blueprint(governed_royal_mail_bp)

    marker = "royal_mail_click_drop_connection.js"

    @app.after_request
    def inject_royal_mail_click_drop_asset(response):
        if request.method != "GET" or request.path.rstrip("/") != "/fbm":
            return response
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return response
        html = response.get_data(as_text=True)
        if marker in html or "</body>" not in html:
            return response
        tag = f'<script src="/static/js/{marker}"></script>'
        response.set_data(html.replace("</body>", tag + "</body>", 1))
        response.headers["Content-Length"] = str(len(response.get_data()))
        return response

    app._bt38_royal_mail_click_drop_alignment_installed = True
