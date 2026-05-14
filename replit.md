# Overview

This Flask-based multi-channel inventory management system centralizes inventory tracking across Amazon, eBay, and Shopify. It provides a dashboard for managing inventory, store connections, and synchronizing stock levels. The system acts as the single source of truth for inventory, pushing updates from a central warehouse model to all connected marketplaces. The project aims to reduce operational overhead, prevent overselling through robust stock confirmation and unified push mechanisms, and offer advanced concurrency protection.

# User Preferences

Preferred communication style: Simple, everyday language.

Whenever new features or changes are made to the system, add corresponding entries to the FAQ page (`/faq`) to help users understand the new functionality. The FAQ supports multiple languages (English, Hindi, Urdu, Punjabi, Spanish, French) - update all language translations when adding new content.

# System Architecture

## Environment Configuration

The application supports `prod` and `dev` environments, controlled by the `APP_ENV` variable, with differing behaviors for API calls, background sync, and logging. A `/health` endpoint provides application status.

## Frontend

The frontend uses Jinja2 templates, Bootstrap with a dark theme for responsiveness, vanilla JavaScript, and Feather Icons.

## Backend

The backend is built with Flask and SQLAlchemy ORM. Core models include `InventoryItem`, `WarehouseStock`, `MarketplaceListing`, `Store`, `SyncLog`, and `SyncJob`. A threading-based, queue-driven system manages background synchronization. `WarehouseStock` serves as the single source of truth for inventory. Key principles include product grouping, stock confirmation (managing `pending_receipt_qty`, `available_quantity`, `quarantined_quantity`), a unified two-step queue-based push system, and deadlock prevention.

### Data Storage

SQLAlchemy with DeclarativeBase is used. **HARDENED: Both DEV and PROD use the same PostgreSQL database** to prevent login/data issues from database mismatch. SQLite is disabled by default in DEV - set `ALLOW_SQLITE_DEV=true` to explicitly allow it (not recommended). The app will fail fast at startup if DEV tries to use SQLite without explicit permission. Connection pooling and pre-ping are enabled.

### DEV Admin Password Reset

A token-protected endpoint `/dev-reset-admin?token=<DEV_RESET_TOKEN>` exists for emergencies. Requirements:
- Only works in DEV mode (returns 404 in production)
- Requires `DEV_RESET_TOKEN` environment variable to be set
- Returns 404 if token missing or wrong
- Resets admin password to `admin123`

### Authentication and Authorization

Flask-Login handles multi-user authentication with role-based access control (admin, manager, viewer) and granular permissions, requiring a `SESSION_SECRET` for production.

### Background Services

A queue-based sync system uses a database-backed work queue with per-store worker threads and a background scheduler. It includes row-level locking, automatic retry with exponential backoff, and separate tracking for Amazon FBA vs. FBM SKUs.

### Marketplace-Specific Features

-   **eBay**: Supports eBay UK with price remediation, quantity-only push, preflight validation, detailed error diagnostics, and bidirectional sync with concurrency protection.
-   **Unified Amazon Store Architecture**: Utilizes a single unified Amazon store. FBA inventory is read-only and stored in `AmazonFBAInventory`, while FBM inventory uses `WarehouseStock` as the source of truth for bidirectional sync.
-   **Multi-Channel Fulfillment (MCF)**: Enables using FBA inventory to fulfill orders from external channels, involving `MCFOrder` models and API interaction for estimates, creation, and tracking via Amazon Fulfillment Outbound API. MCF uses FBA inventory only.

### Architecture: Separation of Concerns

The system uses two complementary pages:
1.  **GroupView (`/product_linking`)**: Manages linking/unlinking warehouse SKUs to marketplace listings and can trigger group pushes using `WarehouseStock` quantities.
2.  **Warehouse/Master Stock (`/warehouse`)**: The authoritative source for adjusting quantities and can also trigger pushes.

### Critical Invariants

-   Each `warehouse_stock_id` can have many `marketplace_listings` pointing to it.
-   Quantity Push operations overwrite marketplace quantities with `warehouse_stock.available_quantity`.
-   Warehouse Quantity always wins; marketplace "sold" counts are ignored for warehouse updates.
-   Bidirectional sync from marketplace to warehouse is disabled; warehouse is never updated from marketplace quantities.
-   FBA (AFN) listings are read-only and excluded from all push operations; only FBM (MFN) and eBay listings are pushable.

### Group Push Architecture (Parallel Push)

The `/api/group-push` endpoint enables pushing from GroupView, always using `WarehouseStock.available_quantity`, and automatically filters to exclude FBA listings. It includes stale job protection to cancel pending jobs with old quantities before enqueueing new ones.

**Parallel Dispatch (MANDATORY):**
- All platform jobs (Amazon FBM + eBay) are dispatched IN PARALLEL (same batch, no sequential awaits)
- Each push generates a unique `group_push_id` for correlation (format: `grp_{warehouse_stock_id}_{timestamp}`)
- Jobs are queued within the same second (typically under 50ms total)
- Log pattern: `[GROUP_PUSH] === PARALLEL BATCH START/END === group_push_id=...`

### Linking Mechanism

A marketplace listing is "linked" if and only if `MarketplaceListing.warehouse_stock_id IS NOT NULL`. The `ProductMapping` model tracks explicit user-confirmed links between warehouse products and marketplace listings. Linking can be initiated from either the Warehouse tab or the Unlinked Listings tab.

### Diagnostics and Troubleshooting

A comprehensive SKU diagnostics endpoint (`/api/diagnostics/sku/<sku>`) offers detailed information, push calculation traces, automatic issue detection, and enforcement of warehouse authority.

### Push Status Monitoring

Endpoints provide queue status, detailed push history with filtering, and bulk push actions, tracking success/error/pending counts.

### Stock Transfers

The Stock Transfers system (`/stock_transfers`) manages inventory movement between FBA and Warehouse using a `StockTransfer` model, supporting FBA→Warehouse returns and Warehouse→FBA outbound transfers.

### Warehouse Bulk Actions

Bulk actions include Archive/Unarchive, Mark Discontinued, Delete (cascading), and "Transfer to FBA" for planning. Sync safeguards prevent deleted warehouse SKUs from reappearing.

### Inventory Repair Tools

An inventory repair dashboard (`/inventory_repair`) provides tools for quantity mismatch repair, orphaned listings cleanup, duplicate SKU resolution, bulk quantity adjustment, and warehouse sync resets.

### Multi-Channel Listings Bulk Actions

The Multi-Channel Listings page (`/listings`) offers bulk actions like Push to Marketplace, Unblock/Fix Blocked listings, Sync Quantity from Warehouse, and Activate/Deactivate listings, tracked by a `BulkJob` model.

### Routing Stability

A system for URL freeze prevention and routing stability includes frontend protection with page load/API timeouts, auto-recovery, and health checks, supported by backend logging endpoints.

### Notification Services

Integration with SendGrid for email notifications and Twilio for SMS/WhatsApp alerts.

# External Dependencies

-   **Web Framework**: Flask
-   **ORM**: Flask-SQLAlchemy, SQLAlchemy
-   **WSGI**: Werkzeug
-   **Frontend**: Bootstrap, Feather Icons
-   **E-commerce Platforms**: Amazon (SP-API), eBay (Trading API), Shopify
-   **Databases**: SQLite, PostgreSQL
-   **Email**: SendGrid
-   **SMS/WhatsApp**: Twilio