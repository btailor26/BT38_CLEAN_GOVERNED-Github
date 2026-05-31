"""BT38 governed warehouse push coordinator.

One clear path:

listing / group / warehouse / notification correction
-> database relationship resolution
-> WarehouseStock.sellable_quantity truth
-> WarehousePushCoordinator
-> governed_execution.submit_governed_marketplace_action
-> marketplace adapter

This module does not call marketplace adapters directly.
This module does not trust marketplace/request payload quantity as truth.
This module does not create a second queue, worker, or task system.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from extensions import db
from governed_execution import submit_governed_marketplace_action
from models import MarketplaceListing, MasterProductGroup, Store, SystemLog, WarehouseStock


COORDINATOR_AUTHORITY = "warehouse_push_coordinator"
WAREHOUSE_PUSH_COORDINATOR_DISABLED = False
LEGACY_WAREHOUSE_PUSH_DISABLED = True


class WarehousePushCoordinator:
    """Single governed propagation coordinator.

    The coordinator owns:
    - listing/group/warehouse resolution
    - warehouse truth quantity
    - candidate marketplace listing selection
    - FBA/AFN skip
    - blocked listing skip
    - governed execution handoff
    - structured audit result

    It does not own:
    - marketplace API communication
    - Fuse Box authority
    - Product Linking relationship changes
    - dashboard action resolution
    """

    def run_for_listing(
        self,
        *,
        listing_id: int,
        source: str = "manual_listing_push",
        actor: str = "system",
        dry_run: bool = True,
        actor_user: Any = None,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        listing = self._get_listing(listing_id)
        if listing is None:
            return self._result(
                ok=False,
                reason="Listing not found.",
                source=source,
                actor=actor,
                dry_run=dry_run,
                input_type="listing",
                input_id=listing_id,
            )

        group = self._group_for_listing(listing)
        if group is not None:
            return self.run_for_group(
                group_id=group.id,
                source=source,
                actor=actor,
                dry_run=dry_run,
                actor_user=actor_user,
                approval_id=approval_id,
            )

        return self._run_candidates(
            candidates=[listing],
            source=source,
            actor=actor,
            dry_run=dry_run,
            actor_user=actor_user,
            approval_id=approval_id,
            input_type="listing",
            input_id=listing_id,
            group=None,
        )

    def run_for_group(
        self,
        *,
        group_id: int,
        source: str = "manual_group_push",
        actor: str = "system",
        dry_run: bool = True,
        actor_user: Any = None,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        group = self._get_group(group_id)
        if group is None:
            return self._result(
                ok=False,
                reason="Group not found.",
                source=source,
                actor=actor,
                dry_run=dry_run,
                input_type="group",
                input_id=group_id,
            )

        candidates = list(getattr(group, "marketplace_listings", []) or [])
        return self._run_candidates(
            candidates=candidates,
            source=source,
            actor=actor,
            dry_run=dry_run,
            actor_user=actor_user,
            approval_id=approval_id,
            input_type="group",
            input_id=group_id,
            group=group,
        )

    def run_for_warehouse_stock(
        self,
        *,
        warehouse_stock_id: int,
        source: str = "warehouse_stock_push",
        actor: str = "system",
        dry_run: bool = True,
        actor_user: Any = None,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        stock = self._get_stock(warehouse_stock_id)
        if stock is None:
            return self._result(
                ok=False,
                reason="Warehouse stock not found.",
                source=source,
                actor=actor,
                dry_run=dry_run,
                input_type="warehouse_stock",
                input_id=warehouse_stock_id,
            )

        group = getattr(stock, "master_group", None)
        if group is not None or getattr(stock, "master_product_group_id", None):
            group_id = getattr(group, "id", None) or getattr(stock, "master_product_group_id", None)
            return self.run_for_group(
                group_id=group_id,
                source=source,
                actor=actor,
                dry_run=dry_run,
                actor_user=actor_user,
                approval_id=approval_id,
            )

        candidates = list(getattr(stock, "marketplace_listings", []) or [])
        return self._run_candidates(
            candidates=candidates,
            source=source,
            actor=actor,
            dry_run=dry_run,
            actor_user=actor_user,
            approval_id=approval_id,
            input_type="warehouse_stock",
            input_id=warehouse_stock_id,
            group=None,
        )

    def run_for_store(
        self,
        *,
        store_id: int,
        source: str = "warehouse_sync",
        actor: str = "system",
        dry_run: bool = True,
        actor_user: Any = None,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        store = self._get_store(store_id)
        if store is None:
            return self._result(
                ok=False,
                reason="Store not found.",
                source=source,
                actor=actor,
                dry_run=dry_run,
                input_type="store",
                input_id=store_id,
            )

        candidates = list(getattr(store, "marketplace_listings", []) or [])
        return self._run_candidates(
            candidates=candidates,
            source=source,
            actor=actor,
            dry_run=dry_run,
            actor_user=actor_user,
            approval_id=approval_id,
            input_type="store",
            input_id=store_id,
            group=None,
        )

    def _run_candidates(
        self,
        *,
        candidates: Iterable[MarketplaceListing],
        source: str,
        actor: str,
        dry_run: bool,
        actor_user: Any,
        approval_id: Optional[str],
        input_type: str,
        input_id: Any,
        group: Optional[MasterProductGroup],
    ) -> Dict[str, Any]:
        seen: set[int] = set()
        cleaned: List[MarketplaceListing] = []

        for listing in candidates or []:
            listing_id = getattr(listing, "id", None)
            if listing_id is None or listing_id in seen:
                continue
            seen.add(listing_id)
            cleaned.append(listing)

        pushed: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for listing in cleaned:
            allowed, reason, context = self._classify_listing(listing, group=group)
            if not allowed:
                skipped.append(self._skip_payload(listing, reason=reason, context=context))
                continue

            payload = self._execution_payload(
                listing=listing,
                context=context,
                source=source,
                actor=actor,
                group=group,
            )

            execution = submit_governed_marketplace_action(
                payload=payload,
                dry_run=dry_run,
                actor=actor,
                actor_user=actor_user,
                approval_type=COORDINATOR_AUTHORITY,
                approval_id=approval_id,
            )

            row = {
                "listing_id": getattr(listing, "id", None),
                "store_id": getattr(listing, "store_id", None),
                "marketplace": payload.get("marketplace"),
                "sku": payload.get("sku"),
                "external_listing_id": payload.get("external_listing_id"),
                "quantity": payload.get("quantity"),
                "dry_run": dry_run,
                "execution": self._safe(execution),
            }

            if execution.get("ok") or execution.get("success"):
                pushed.append(row)
                self._record_listing_result(
                    listing=listing,
                    success=True,
                    quantity=payload.get("quantity"),
                    reason=execution.get("reason") or "Governed execution accepted.",
                    dry_run=dry_run,
                )
            else:
                failed.append(row)
                self._record_listing_result(
                    listing=listing,
                    success=False,
                    quantity=payload.get("quantity"),
                    reason=execution.get("reason") or "Governed execution blocked or failed.",
                    dry_run=dry_run,
                )

        ok = bool(pushed) and not failed
        if not pushed and (skipped or failed):
            ok = False
        if not cleaned:
            ok = False

        result = self._result(
            ok=ok,
            reason=self._summary_reason(cleaned=cleaned, pushed=pushed, skipped=skipped, failed=failed),
            source=source,
            actor=actor,
            dry_run=dry_run,
            input_type=input_type,
            input_id=input_id,
            group_id=getattr(group, "id", None),
            candidate_count=len(cleaned),
            pushed=pushed,
            skipped=skipped,
            failed=failed,
        )

        self._write_audit(result)
        if not dry_run:
            db.session.commit()

        return result

    def _classify_listing(
        self,
        listing: MarketplaceListing,
        *,
        group: Optional[MasterProductGroup],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        store = getattr(listing, "store", None)
        stock = self._stock_for_listing(listing, group=group)
        platform = self._platform_for_listing(listing)
        sku = self._sku_for_listing(listing)

        context = {
            "listing_id": getattr(listing, "id", None),
            "store_id": getattr(listing, "store_id", None),
            "warehouse_stock_id": getattr(stock, "id", None),
            "group_id": getattr(group, "id", None) or getattr(listing, "master_product_group_id", None),
            "platform": platform,
            "sku": sku,
        }

        if store is None:
            return False, "missing_store", context

        if getattr(store, "is_active", False) is not True:
            return False, "store_inactive", context

        store_mode = str(getattr(store, "store_mode", "") or "").strip().lower()
        if store_mode and store_mode != "live":
            return False, f"store_not_live:{store_mode}", context

        if getattr(listing, "is_active", False) is not True:
            return False, "listing_inactive", context

        if not sku:
            return False, "missing_sku", context

        if stock is None:
            return False, "missing_warehouse_stock", context

        if getattr(stock, "is_active", False) is not True:
            return False, "warehouse_stock_inactive", context

        if getattr(stock, "is_deleted", False) is True or getattr(stock, "is_archived", False) is True:
            return False, "warehouse_stock_not_active", context

        push_state = str(getattr(listing, "push_state", "") or "active").strip().lower()
        if push_state != "active":
            return False, f"listing_push_state:{push_state}", context

        if getattr(listing, "sync_quantity", True) is not True:
            return False, "listing_quantity_sync_disabled", context

        if "amazon" in platform:
            ch = str(
                getattr(listing, "normalized_amazon_fulfillment_channel", None)
                or getattr(listing, "amazon_fulfillment_channel", "")
                or ""
            ).strip().upper()

            if ch in {"AFN", "FBA"}:
                return False, "amazon_fba_afn_read_only", context

            if ch not in {"MFN", "FBM", "MERCHANT"}:
                return False, "amazon_fulfillment_unknown", context

            context["amazon_fulfillment_channel"] = ch

        quantity = self._quantity_for_listing(listing, stock)
        context["quantity"] = quantity

        return True, "eligible", context

    def _execution_payload(
        self,
        *,
        listing: MarketplaceListing,
        context: Dict[str, Any],
        source: str,
        actor: str,
        group: Optional[MasterProductGroup],
    ) -> Dict[str, Any]:
        store = getattr(listing, "store", None)
        platform = context.get("platform")
        action = "push_inventory"

        payload = {
            "marketplace": platform,
            "action": action,
            "sku": context.get("sku"),
            "store_id": getattr(store, "id", None),
            "listing_id": getattr(listing, "id", None),
            "external_listing_id": getattr(listing, "external_listing_id", None),
            "quantity": context.get("quantity"),
            "source": source,
            "actor": actor,
            "authority": COORDINATOR_AUTHORITY,
            "warehouse_stock_id": context.get("warehouse_stock_id"),
            "group_id": context.get("group_id") or getattr(group, "id", None),
        }

        if platform == "amazon":
            payload["amazon_fulfillment_channel"] = context.get("amazon_fulfillment_channel")

        return payload

    def _quantity_for_listing(self, listing: MarketplaceListing, stock: WarehouseStock) -> int:
        base = int(getattr(stock, "sellable_quantity", 0) or 0)

        buffer_qty = int(getattr(listing, "quantity_buffer", 0) or 0)
        quantity = max(0, base - buffer_qty)

        max_limit = getattr(listing, "max_quantity_limit", None)
        if max_limit is not None:
            try:
                quantity = min(quantity, int(max_limit))
            except Exception:
                pass

        return int(max(0, quantity))

    def _stock_for_listing(
        self,
        listing: MarketplaceListing,
        *,
        group: Optional[MasterProductGroup],
    ) -> Optional[WarehouseStock]:
        stock = getattr(listing, "warehouse_stock", None)
        if stock is not None:
            return stock

        if group is None:
            group = self._group_for_listing(listing)

        if group is None:
            return None

        stocks = list(getattr(group, "warehouse_stocks", []) or [])
        active_stocks = [
            s for s in stocks
            if getattr(s, "is_active", False) is True
            and getattr(s, "is_deleted", False) is not True
            and getattr(s, "is_archived", False) is not True
        ]
        if active_stocks:
            return active_stocks[0]
        return stocks[0] if stocks else None

    def _group_for_listing(self, listing: MarketplaceListing) -> Optional[MasterProductGroup]:
        group = getattr(listing, "master_group", None)
        if group is not None:
            return group

        stock = getattr(listing, "warehouse_stock", None)
        if stock is not None and getattr(stock, "master_group", None) is not None:
            return stock.master_group

        group_id = getattr(listing, "master_product_group_id", None)
        if group_id:
            return self._get_group(group_id)

        stock_group_id = getattr(stock, "master_product_group_id", None) if stock is not None else None
        if stock_group_id:
            return self._get_group(stock_group_id)

        return None

    def _platform_for_listing(self, listing: MarketplaceListing) -> str:
        store = getattr(listing, "store", None)
        platform = str(getattr(store, "platform", "") or "").strip().lower()

        if "amazon" in platform:
            return "amazon"
        if "ebay" in platform:
            return "ebay"
        return platform or "unknown"

    def _sku_for_listing(self, listing: MarketplaceListing) -> str:
        return str(
            getattr(listing, "external_sku", None)
            or getattr(listing, "sku", None)
            or ""
        ).strip()

    def _record_listing_result(
        self,
        *,
        listing: MarketplaceListing,
        success: bool,
        quantity: Any,
        reason: str,
        dry_run: bool,
    ) -> None:
        if dry_run:
            return

        now = datetime.utcnow()

        if success:
            listing.last_push_status = "success"
            listing.last_push_error = None
            listing.last_push_at = now
            listing.last_push_quantity = int(quantity or 0)
            listing.consecutive_failures = 0
        else:
            listing.last_push_status = "error"
            listing.last_push_error = str(reason or "")[:1000]
            listing.push_attempts = int(getattr(listing, "push_attempts", 0) or 0) + 1
            listing.consecutive_failures = int(getattr(listing, "consecutive_failures", 0) or 0) + 1

    def _write_audit(self, result: Dict[str, Any]) -> None:
        try:
            db.session.add(SystemLog(
                log_type="warehouse_push_coordinator",
                message=str(result.get("reason") or "Warehouse push coordinator completed.")[:500],
                details=json.dumps(self._safe(result), default=str),
            ))
        except Exception:
            # Audit logging must never become an execution blocker.
            pass

    def _skip_payload(
        self,
        listing: MarketplaceListing,
        *,
        reason: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "listing_id": getattr(listing, "id", None),
            "store_id": getattr(listing, "store_id", None),
            "warehouse_stock_id": context.get("warehouse_stock_id"),
            "group_id": context.get("group_id"),
            "marketplace": context.get("platform"),
            "sku": context.get("sku"),
            "reason": reason,
        }

    def _summary_reason(
        self,
        *,
        cleaned: List[MarketplaceListing],
        pushed: List[Dict[str, Any]],
        skipped: List[Dict[str, Any]],
        failed: List[Dict[str, Any]],
    ) -> str:
        return (
            f"Coordinator candidates={len(cleaned)} "
            f"accepted={len(pushed)} skipped={len(skipped)} failed={len(failed)}."
        )

    def _result(self, *, ok: bool, reason: str, source: str, actor: str, dry_run: bool, **extra: Any) -> Dict[str, Any]:
        result = {
            "ok": bool(ok),
            "success": bool(ok),
            "governed": True,
            "coordinator": COORDINATOR_AUTHORITY,
            "source": source,
            "actor": actor,
            "dry_run": bool(dry_run),
            "reason": reason,
        }
        result.update(extra)
        return result

    def _get_listing(self, listing_id: Any) -> Optional[MarketplaceListing]:
        try:
            return db.session.get(MarketplaceListing, int(listing_id))
        except Exception:
            return None

    def _get_group(self, group_id: Any) -> Optional[MasterProductGroup]:
        try:
            return db.session.get(MasterProductGroup, int(group_id))
        except Exception:
            return None

    def _get_stock(self, stock_id: Any) -> Optional[WarehouseStock]:
        try:
            return db.session.get(WarehouseStock, int(stock_id))
        except Exception:
            return None

    def _get_store(self, store_id: Any) -> Optional[Store]:
        try:
            return db.session.get(Store, int(store_id))
        except Exception:
            return None

    def _safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


def get_coordinator() -> WarehousePushCoordinator:
    return WarehousePushCoordinator()


def run_for_listing(**kwargs: Any) -> Dict[str, Any]:
    return get_coordinator().run_for_listing(**kwargs)


def run_for_group(**kwargs: Any) -> Dict[str, Any]:
    return get_coordinator().run_for_group(**kwargs)


def run_for_warehouse_stock(**kwargs: Any) -> Dict[str, Any]:
    return get_coordinator().run_for_warehouse_stock(**kwargs)


def run_for_store(**kwargs: Any) -> Dict[str, Any]:
    return get_coordinator().run_for_store(**kwargs)


def coordinate_listing_push(*, listing_id: int, **kwargs: Any) -> Dict[str, Any]:
    return run_for_listing(listing_id=listing_id, **kwargs)


def coordinate_group_push(*, group_id: int, **kwargs: Any) -> Dict[str, Any]:
    return run_for_group(group_id=group_id, **kwargs)


def coordinate_group_propagation(*, group_id: int, **kwargs: Any) -> Dict[str, Any]:
    return run_for_group(group_id=group_id, source=kwargs.pop("source", "group_quantity_propagation"), **kwargs)


def coordinate_warehouse_stock_push(*, warehouse_stock_id: int, **kwargs: Any) -> Dict[str, Any]:
    return run_for_warehouse_stock(warehouse_stock_id=warehouse_stock_id, **kwargs)
