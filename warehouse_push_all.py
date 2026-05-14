import argparse, json, re, time, sys
from datetime import datetime
from app import app
from extensions import db
from models import Store, WarehouseStock, MarketplaceListing
from ebay_service import eBayAPIService

def is_num(x): return x is not None and str(x).isdigit()

def build_service(store):
    creds = json.loads(store.api_key or "{}")
    svc = eBayAPIService()
    svc.auth_token = creds.get("user_token") or creds.get("access_token")
    svc.app_id = creds.get("app_id")
    svc.cert_id = creds.get("cert_id")
    svc.dev_id = creds.get("dev_id")
    # PROD unless explicitly marked sandbox
    svc.use_sandbox = bool(creds.get("sandbox", False))
    return svc

def choose_numeric_itemid(listings):
    """Pick the first numeric ItemID among listings."""
    for l in listings:
        if is_num(l.external_listing_id):
            return l.external_listing_id
    return None

def main():
    p = argparse.ArgumentParser(description="Warehouse-authoritative eBay quantity push")
    p.add_argument("--store", default="beatsoutlet", help="eBay store name (default: beatsoutlet)")
    p.add_argument("--only-sku", default="", help="Push only this SKU (optional)")
    p.add_argument("--only-item", default="", help="Push only this eBay ItemID (optional, numeric)")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen, don't call eBay")
    p.add_argument("--throttle", type=float, default=1.2, help="Seconds between calls (default 1.2)")
    args = p.parse_args()

    with app.app_context():
        store = Store.query.filter(Store.platform.ilike("eBay"), Store.name == args.store).first()
        if not store:
            print(f"[FATAL] eBay store not found: {args.store}")
            sys.exit(2)

        svc = build_service(store)

        # Build SKU set
        if args.only_sku:
            ws_rows = WarehouseStock.query.filter_by(sku=args.only_sku).all()
        else:
            ws_rows = WarehouseStock.query.order_by(WarehouseStock.id.asc()).all()

        total_success = total_fail = total_skip = 0
        details = []

        for ws in ws_rows:
            # If only pushing a specific ItemID, filter the listings later
            ml_q = MarketplaceListing.query.filter_by(warehouse_stock_id=ws.id, store_id=store.id)
            ml_rows = ml_q.all()
            if not ml_rows:
                continue

            # authoritative quantity = warehouse available
            qty = ws.available_quantity or 0

            # If a specific ItemID was provided, keep only that
            target_item = args.only_item.strip()
            if target_item:
                ml_rows = [l for l in ml_rows if str(l.external_listing_id) == target_item]

            # If still nothing, skip
            if not ml_rows:
                continue

            # Ensure we have at least one numeric ItemID for the SKU
            chosen = choose_numeric_itemid(ml_rows)
            if not chosen and not args.dry_run:
                total_skip += len(ml_rows)
                details.append({"sku": ws.sku, "result": "skipped", "reason": "no numeric ItemID linked"})
                continue

            # Normalize all non-numeric to chosen numeric (so future pushes work)
            changed = 0
            if chosen:
                for l in ml_rows:
                    if not is_num(l.external_listing_id):
                        l.external_listing_id = chosen
                        changed += 1
                if changed:
                    db.session.commit()

            for l in ml_rows:
                itemid = l.external_listing_id
                if not is_num(itemid):
                    total_skip += 1
                    details.append({"sku": ws.sku, "itemid": itemid, "result": "skipped", "reason": "non-numeric"})
                    continue

                if args.dry_run:
                    details.append({"sku": ws.sku, "itemid": itemid, "result": "dry-run", "qty": qty})
                    continue

                ok, msg = svc.update_listing_quantity(itemid, qty)
                if ok:
                    l.last_push_at = datetime.utcnow()
                    l.last_push_quantity = qty
                    l.last_push_status = "success"
                    total_success += 1
                else:
                    l.last_push_status = "error"
                    l.last_push_error = msg
                    total_fail += 1
                db.session.commit()
                details.append({"sku": ws.sku, "itemid": itemid, "result": "ok" if ok else "fail", "qty": qty, "msg": msg})
                time.sleep(max(args.throttle, 0.0))

        # summary
        out = {
            "store": store.name,
            "success": total_success,
            "failed": total_fail,
            "skipped": total_skip,
            "dry_run": args.dry_run,
            "throttle_sec": args.throttle,
            "count_details": len(details)
        }
        print(json.dumps(out, indent=2))
        # Show last 20 lines for quick glance
        if details:
            print("\nLast 20 results:")
            for row in details[-20:]:
                print(row)

if __name__ == "__main__":
    main()
