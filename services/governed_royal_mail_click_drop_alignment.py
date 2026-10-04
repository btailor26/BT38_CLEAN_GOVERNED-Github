"""Install the merchant-owned Royal Mail Click & Drop connection.

The /fbm template owns the browser asset explicitly. This installer owns only
the persisted connection schema and governed routes; it does not inject UI,
purchase postage, poll Royal Mail, or introduce another shipment table.
"""
from __future__ import annotations

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

    app._bt38_royal_mail_click_drop_alignment_installed = True
