"""BT38 governed warehouse push coordinator.

Single execution-routing authority for inventory propagation.

Rules:
- Product Linking remains relationship-only.
- Group resolution happens before propagation.
- WarehouseStock.sellable_quantity is inventory truth.
- MarketplaceListing.effective_quantity may only derive from warehouse truth and listing policy.
- Amazon FBA/AFN is skipped before runtime execution.
- All executable marketplace work passes through governed_execution.submit_governed_marketplace_action().
- Runtime permission remains owned by runtime_action_guard through governed_execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _safe_bool(value: Any) -> bool:
    return bool(value is True or str(value).lower() in {"true", "1", "yes", "on"})


class WarehousePushCoordinator:
    """One clear path coordinator for warehouse-driven marketplace propagation."""

    def __init__(self, actor: str = "warehouse-push-coordinator", dry_run: bool = False):
        self.actor = actor or "warehouse-push-coordinator"
        self.dry_run = bool(dry_run)

    def push_listing(
        self,
        listing_id: int,
        *,
        source: str = "warehouse_push_coordinator",
        actor: Optional[str] = None,
        dry_run: Optional[bool] = None,
        requested_quantity: Any = None,
    ) -> Dict[str, Any]:
        """Push one listing through the governed path.

        requested_quantity is accepted only for compatibility/audit context. It is
        never used as the propagation quantity. Quantity must be warehouse-derived.
        """
        from extensions import db
        from governed_execution import AMAZON_FBM_LIVE_APPROVAL_TYPE, submit_governed_marketplace_action
        from models import MarketplaceListing, SyncLog

        actor = actor or self.actor
        dry_run = self.dry_run if dry_run is None else bool(dry_run)

        listing = db.session.get(MarketplaceListing, int(listing_id))
        if not listing:
            return self._blocked("Marketplace listing was not found.", listing_id=listing_id, source=source)

        check = self._classify_listing(listing)
        if check.get("skip"):
            return self._blocked(
                check.get("reason") or "Listing is not eligible for governed propagation.",
                listing_id=listing.id,
                sku=getattr(listing, "external_sku", None),
                source=source,
                is_fba=check.get("is_fba"),
                is_pushable=False,
            )

        quantity = self._warehouse_quantity(listing)
        sku = (listing.external_sku or listing.warehouse_stock.sku or "").strip()
        marketplace = check.get("marketplace")

        payload = {
            "marketplace": marketplace,
            "action": "push_inventory",
            "sku": sku,
            "store_id": listing.store_id,
            "listing_id": listing.id,
            "external_listing_id": listing.external_listing_id,
            "quantity": quantity,
            "amazon_fulfillment_channel": (
                listing.normalized_amazon_fulfillment_channel
                or listing.amazon_fulfillment_channel
                or "MFN"
            ),
            "source": source,
            "group_id": listing.master_product_group_id,
            "warehouse_stock_id": listing.warehouse_stock_id,
            "requested_quantity_ignored": requested_quantity is not None,
        }

        result = submit_governed_marketplace_action(
            payload=payload,
            actor=actor,
            actor_user=None,
            approval_type=AMAZON_FBM_LIVE_APPROVAL_TYPE,
            approval_id=None,
            dry_run=dry_run,
        )

        ok = bool(result.get("ok") or result.get("success"))
        self._update_listing_push_state(listing, ok=ok, quantity=quantity, result=result)

        db.session.add(SyncLog(
            store_id=listing.store_id,
            status="success" if ok else "error",
            message=(
                f"governed_coordinator_push listing_id={listing.id} sku={sku} "
                f"marketplace={marketplace} source={source} ok={ok} dry_run={dry_run}"
            )[:500],
            items_synced=1 if ok else 0,
            created_at=datetime.utcnow(),
        ))
        db.session.commit()

        result.update({
            "success": ok,
            "ok": ok,
            "governed": True,
            "coordinator": "WarehousePushCoordinator",
            "one_clear_path": True,
            "source": source,
            "listing_id": listing.id,
            "store_id": listing.store_id,
            "group_id": listing.master_product_group_id,
            "warehouse_stock_id": listing.warehouse_stock_id,
            "sku": sku,
            "quantity": quantity,
            "dry_run": dry_run,
            "warehouse_truth_used": True,
            "requested_quantity_ignored": requested_quantity is not None,
        })
        return result

    def push_group(
        self,
        group_id: int,
        *,
        source: str = "warehouse_push_coordinator_group",
        actor: Optional[str] = None,
        dry_run: Optional[bool] = None,
        requested_quantity: Any = None,
    ) -> Dict[str, Any]:
        """Resolve a group, then propagate through warehouse truth."""
        from extensions import db
        from models import MarketplaceListing, MasterProductGroup

        actor = actor or self.actor
        dry_run = self.dry_run if dry_run is None else bool(dry_run)

        group = db.session.get(MasterProductGroup, int(group_id))
        if not group:
            return self._blocked("Master product group was not found.", group_id=group_id, source=source)

        listings = (
            db.session.query(MarketplaceListing)
            .filter(MarketplaceListing.master_product_group_id == int(group_id))
            .filter(MarketplaceListing.is_active == True)  # noqa: E712
            .order_by(MarketplaceListing.id)
            .all()
        )

        results: List[Dict[str, Any]] = []
        for listing in listings:
            results.append(self.push_listing(
                listing.id,
                source=source,
                actor=actor,
                dry_run=dry_run,
                requested_quantity=requested_quantity,
            ))

        summary = self._summarize(results)
        return {
            "success": summary["failed"] == 0,
            "ok": summary["failed"] == 0,
            "governed": True,
            "coordinator": "WarehousePushCoordinator",
            "one_clear_path": True,
            "group_id": int(group_id),
            "source": source,
            "dry_run": dry_run,
            "total": len(results),
            **summary,
            "results": results,
        }

    def propagate_group_quantity(self, group_id: int, **kwargs: Any) -> Dict[str, Any]:
        return self.push_group(group_id, source="governed_group_propagation", **kwargs)

    def run_for_store(
        self,
        store_id: int,
        *,
        source: str = "governed_warehouse_sync",
        actor: Optional[str] = None,
        dry_run: Optional[bool] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run governed propagation for linked listings in one store."""
        from extensions import db
        from models import MarketplaceListing, Store

        store = db.session.get(Store, int(store_id))
        if not store:
            return self._blocked("Store was not found.", store_id=store_id, source=source)

        query = db.session.query(MarketplaceListing).filter(
            MarketplaceListing.is_active == True,  # noqa: E712
            MarketplaceListing.warehouse_stock_id.isnot(None),
            MarketplaceListing.store_id == int(store_id),
        ).order_by(MarketplaceListing.id)

        if limit:
            query = query.limit(max(1, int(limit)))

        listings = query.all()
        results = [
            self.push_listing(
                listing.id,
                source=source,
                actor=actor or self.actor,
                dry_run=dry_run,
            )
            for listing in listings
        ]
        summary = self._summarize(results)
        return {
            "success": summary["failed"] == 0,
            "ok": summary["failed"] == 0,
            "governed": True,
            "manual": True,
            "coordinator": "WarehousePushCoordinator",
            "one_clear_path": True,
            "mode": "governed_warehouse_sync_via_coordinator",
            "store_id": int(store_id),
            "store_name": getattr(store, "name", None),
            "platform": getattr(store, "platform", None),
            "total": len(results),
            "checked": len(results),
            **summary,
            "results": results,
        }

    def _classify_listing(self, listing) -> Dict[str, Any]:
        platform = (listing.store.platform or "").strip().lower() if listing.store else ""
        channel = (listing.normalized_amazon_fulfillment_channel or listing.amazon_fulfillment_channel or "").upper()
        is_amazon = "amazon" in platform
        is_fbm = is_amazon and channel in {"MFN", "FBM", "MERCHANT"}
        is_fba = is_amazon and not is_fbm
        marketplace = "amazon" if is_amazon else "ebay" if "ebay" in platform else platform

        if not listing.store:
            return {"skip": True, "reason": "Listing has no store.", "marketplace": marketplace, "is_fba": False}
        if not listing.warehouse_stock:
            return {"skip": True, "reason": "Listing is not linked to warehouse stock.", "marketplace": marketplace, "is_fba": False}
        if is_fba:
            return {"skip": True, "reason": "Amazon FBA/AFN is read-only and must not be pushed.", "marketplace": marketplace, "is_fba": True}
        if not getattr(listing, "is_pushable", False):
            return {"skip": True, "reason": "Listing is not pushable under current listing state.", "marketplace": marketplace, "is_fba": False}
        if not listing.store.is_active:
            return {"skip": True, "reason": "Store is inactive.", "marketplace": marketplace, "is_fba": False}
        return {"skip": False, "reason": "pushable", "marketplace": marketplace, "is_fba": False}

    def _warehouse_quantity(self, listing) -> int:
        # Marketplace payload quantities are never authority. The listing property
        # is allowed only because it derives from warehouse sellable quantity and
        # listing buffer/max policy in models.py.
        try:
            return int(listing.effective_quantity or 0)
        except Exception:
            return int(getattr(listing.warehouse_stock, "sellable_quantity", 0) or 0)

    def _update_listing_push_state(self, listing, *, ok: bool, quantity: int, result: Dict[str, Any]) -> None:
        listing.last_push_at = datetime.utcnow()
        listing.last_push_quantity = quantity if ok else listing.last_push_quantity
        listing.last_push_status = "success" if ok else "error"
        listing.last_push_error = None if ok else str(result.get("reason") or result.get("failure_reason") or result)[:1000]
        listing.push_attempts = 0 if ok else (listing.push_attempts or 0) + 1
        listing.consecutive_failures = 0 if ok else (listing.consecutive_failures or 0) + 1

        current_channel = str(
            listing.normalized_amazon_fulfillment_channel
            or listing.amazon_fulfillment_channel
            or ""
        ).strip().upper()
        stale_error = str(listing.last_push_error or "").lower()
        if current_channel in {"MFN", "FBM", "MERCHANT"} and (
            "fba/afn is read-only" in stale_error
            or "no fba push path" in stale_error
            or "read-only" in stale_error
        ):
            listing.last_push_error = None
            listing.last_push_status = "pending"
            listing.consecutive_failures = 0

    def _summarize(self, results: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        pushed = 0
        blocked = 0
        skipped_read_only = 0
        failed = 0
        auth_failed = 0
        for row in results:
            if row.get("ok") or row.get("success"):
                pushed += 1
                continue
            text = " ".join(str(row.get(k) or "") for k in ("reason", "error", "message")).lower()
            if row.get("execution_blocked"):
                blocked += 1
            if "fba" in text or "read-only" in text:
                skipped_read_only += 1
                continue
            if "oauth" in text or "unauthorized" in text or "401" in text:
                auth_failed += 1
            failed += 1
        return {
            "pushed": pushed,
            "blocked": blocked,
            "skipped_read_only": skipped_read_only,
            "auth_failed": auth_failed,
            "failed": failed,
        }

    def _blocked(self, reason: str, **context: Any) -> Dict[str, Any]:
        return {
            "success": False,
            "ok": False,
            "governed": True,
            "execution_blocked": True,
            "coordinator": "WarehousePushCoordinator",
            "one_clear_path": True,
            "reason": reason,
            **context,
        }
