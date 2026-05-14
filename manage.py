#!/usr/bin/env python3
"""
Management command-line interface for inventory system maintenance tasks
"""
import sys
import argparse
from app import app

def main():
    """Main entry point for management commands"""
    parser = argparse.ArgumentParser(description='Inventory System Management Commands')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # fix_ebay_prices command
    price_parser = subparsers.add_parser('fix_ebay_prices', help='Fix eBay listings with prices below minimum')
    price_parser.add_argument('--min', type=float, default=0.99, help='Minimum price (default: 0.99)')
    price_parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without applying')
    price_parser.add_argument('--apply', action='store_true', help='Actually apply the price changes')
    price_parser.add_argument('--store', type=str, help='Filter by store name (optional)')
    price_parser.add_argument('--batch-size', type=int, default=20, help='Batch size for API calls (default: 20)')
    
    # update_amazon_qty command
    amazon_parser = subparsers.add_parser('update_amazon_qty', help='Update Amazon SKU quantity immediately (bypasses Feeds quota)')
    amazon_parser.add_argument('sku', type=str, help='Amazon Seller SKU to update')
    amazon_parser.add_argument('quantity', type=int, help='New quantity')
    amazon_parser.add_argument('--store', type=str, required=True, help='Amazon store name (required)')
    amazon_parser.add_argument('--marketplace', type=str, default='A1F83G8C2ARO7P', help='Marketplace ID (default: A1F83G8C2ARO7P for UK)')
    
    # ebay_preflight command
    ebay_parser = subparsers.add_parser('ebay_preflight', help='Run preflight validation on eBay listings to detect missing ItemSpecifics')
    ebay_parser.add_argument('item_ids', type=str, nargs='+', help='eBay ItemIDs to validate (space-separated)')
    ebay_parser.add_argument('--store', type=str, required=True, help='eBay store name (required)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute the command within Flask app context
    with app.app_context():
        if args.command == 'fix_ebay_prices':
            from scripts.fix_ebay_prices import fix_ebay_prices
            success = fix_ebay_prices(
                min_price=args.min,
                dry_run=args.dry_run,
                apply=args.apply,
                store_name=args.store,
                batch_size=args.batch_size
            )
            sys.exit(0 if success else 1)
        
        elif args.command == 'update_amazon_qty':
            from models import Store, MarketplaceListing
            from amazon_service import AmazonAPIService
            
            # Find the store
            store = Store.query.filter_by(name=args.store, platform='Amazon').first()
            if not store:
                print(f"❌ Error: Amazon store '{args.store}' not found")
                sys.exit(1)
            
            # Find the listing to get fulfillment channel
            listing = MarketplaceListing.query.filter_by(
                store_id=store.id,
                external_sku=args.sku
            ).first()
            fulfillment_channel = listing.amazon_fulfillment_channel if listing else None
            
            # Update quantity via Listings PATCH
            print(f"Updating {args.sku} to quantity {args.quantity} on {args.store} (marketplace: {args.marketplace}, channel: {fulfillment_channel or 'N/A'})...")
            amazon_service = AmazonAPIService()
            success, message = amazon_service.update_listing_quantity_patch(
                store=store,
                sku=args.sku,
                quantity=args.quantity,
                marketplace_id=args.marketplace,
                amazon_fulfillment_channel=fulfillment_channel
            )
            
            if success:
                print(f"✅ {message}")
                sys.exit(0)
            else:
                print(f"❌ Failed: {message}")
                sys.exit(1)
        
        elif args.command == 'ebay_preflight':
            from models import Store
            from ebay_service import eBayAPIService
            
            # Find the store
            store = Store.query.filter_by(name=args.store, platform='eBay').first()
            if not store:
                print(f"❌ Error: eBay store '{args.store}' not found")
                sys.exit(1)
            
            # Run preflight checks
            ebay_service = eBayAPIService()
            print(f"\n🔍 Running preflight validation on {len(args.item_ids)} listing(s)...\n")
            
            results = []
            for item_id in args.item_ids:
                can_push, reason, missing = ebay_service.preflight_check(store, item_id)
                results.append((item_id, can_push, reason, missing))
                
                if can_push:
                    print(f"✅ {item_id}: {reason}")
                else:
                    print(f"❌ {item_id}: {reason}")
                    if missing:
                        print(f"   Missing: {', '.join(missing)}")
            
            # Summary
            passed = sum(1 for _, can_push, _, _ in results if can_push)
            failed = len(results) - passed
            print(f"\n📊 Summary: {passed} passed, {failed} blocked")
            
            sys.exit(0 if failed == 0 else 1)

if __name__ == '__main__':
    main()
