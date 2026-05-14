from app import app, db
from models import Store

with app.app_context():
    print("\n=== BEFORE ===")
    stores = Store.query.order_by(Store.id).all()
    for s in stores:
        print(s.id, s.name, s.auth_status, s.sync_status)

    print("\n=== APPLYING RESET ===")

    for s in stores:
        s.is_active = True

        if hasattr(s, "store_mode"):
            s.store_mode = "safe"

        if hasattr(s, "sync_status"):
            s.sync_status = "pending"

        if hasattr(s, "auth_status"):
            s.auth_status = "needs_reconnect"

        if hasattr(s, "auto_push_enabled"):
            s.auto_push_enabled = False

    db.session.commit()

    print("\n=== AFTER ===")
    stores = Store.query.order_by(Store.id).all()
    for s in stores:
        print(s.id, s.name, s.auth_status, s.sync_status)

    print("\nDONE")
