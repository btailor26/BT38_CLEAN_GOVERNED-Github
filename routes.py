"""
BT38 routes.py compatibility shell.

Single authority rule:
- governed_routes.py owns login, dashboard, settings, users, permissions, and runtime.
- This legacy blueprint remains empty only so app imports/registration do not break.
- Do not add user, settings, sync, warehouse, marketplace, or permission routes here.
"""

from flask import Blueprint

bp = Blueprint("routes", __name__)

# === AMAZON FBA READ ONLY STOCK PAGE ===
# One clear path: /amazon-fba-stock
# FBA/AFN inventory is imported from Amazon and never pushed from warehouse.
@bp.route('/amazon-fba-stock')
def amazon_fba_stock():
    """Amazon FBA read-only stock page. FBA/AFN is imported from Amazon and never pushed from warehouse."""
    from models import AmazonFBAInventory, Store

    page = request.args.get('page', 1, type=int)
    search = (request.args.get('search') or '').strip()
    status_filter = request.args.get('status', 'active')

    fba_stores = Store.query.filter(
        Store.platform.ilike('amazon'),
        Store.fba_import_enabled == True
    ).all()

    no_fba_store = len(fba_stores) == 0

    query = AmazonFBAInventory.query

    if search:
        like = f'%{search}%'
        query = query.filter(db.or_(
            AmazonFBAInventory.seller_sku.ilike(like),
            AmazonFBAInventory.title.ilike(like),
            AmazonFBAInventory.asin.ilike(like),
            AmazonFBAInventory.fnsku.ilike(like)
        ))

    if status_filter == 'orphaned':
        query = query.filter(AmazonFBAInventory.is_orphaned == True)
    elif status_filter == 'archived':
        query = query.filter(AmazonFBAInventory.is_archived == True)
    elif status_filter == 'all':
        pass
    else:
        status_filter = 'active'
        query = query.filter(AmazonFBAInventory.is_archived == False)

    fba_items = query.order_by(AmazonFBAInventory.seller_sku.asc()).paginate(
        page=page,
        per_page=50,
        error_out=False
    )

    total_skus = AmazonFBAInventory.query.filter(AmazonFBAInventory.is_archived == False).count()
    total_quantity = db.session.query(db.func.coalesce(db.func.sum(AmazonFBAInventory.available_quantity), 0)).scalar() or 0
    stores_count = len(fba_stores)
    orphaned_count = AmazonFBAInventory.query.filter(AmazonFBAInventory.is_orphaned == True).count()
    archived_count = AmazonFBAInventory.query.filter(AmazonFBAInventory.is_archived == True).count()

    stats = {
        'total_skus': total_skus,
        'total_quantity': total_quantity,
        'stores_count': stores_count
    }

    return render_template(
        'amazon_fba_stock.html',
        fba_items=fba_items,
        stats=stats,
        no_fba_store=no_fba_store,
        orphaned_count=orphaned_count,
        archived_count=archived_count,
        current_search=search,
        status_filter=status_filter
    )
