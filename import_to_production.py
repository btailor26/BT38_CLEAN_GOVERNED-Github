#!/usr/bin/env python3
"""
Production Database Import Script
This script imports all development data into the production database.
"""
import os
import sys
import subprocess

def main():
    # Get database URL from environment
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    print(f"🔄 Starting database import to production...")
    print(f"📊 Database: {database_url[:30]}...")
    
    # Check if export file exists
    export_file = '/tmp/dev_database_export.sql'
    if not os.path.exists(export_file):
        print(f"ERROR: Export file not found at {export_file}")
        print("Please run this script in development first to generate the export.")
        sys.exit(1)
    
    # Get file size
    file_size = os.path.getsize(export_file) / (1024 * 1024)  # MB
    print(f"📦 Export file size: {file_size:.2f} MB")
    
    # Confirm before proceeding
    env = os.environ.get('APP_ENV', 'unknown')
    print(f"\n⚠️  Current environment: {env}")
    print(f"⚠️  This will import all data into the production database.")
    print(f"⚠️  Existing data will be preserved (new records added).")
    
    # Import the data
    print(f"\n🚀 Importing data...")
    
    try:
        # Use psql to import
        result = subprocess.run(
            ['psql', database_url, '-f', export_file],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            print(f"✅ Import completed successfully!")
            print(f"\n📊 Checking imported data...")
            
            # Count records
            from app import app, db
            from models import InventoryItem, Store, MarketplaceListing, WarehouseStock
            
            with app.app_context():
                inventory_count = db.session.query(InventoryItem).count()
                store_count = db.session.query(Store).count()
                listing_count = db.session.query(MarketplaceListing).count()
                warehouse_count = db.session.query(WarehouseStock).count()
                
                print(f"  • Inventory Items: {inventory_count}")
                print(f"  • Stores: {store_count}")
                print(f"  • Marketplace Listings: {listing_count}")
                print(f"  • Warehouse Stock: {warehouse_count}")
            
            print(f"\n✅ Import complete! Visit your published site to verify.")
        else:
            print(f"❌ Import failed with exit code {result.returncode}")
            print(f"Error output: {result.stderr}")
            sys.exit(1)
            
    except subprocess.TimeoutExpired:
        print(f"❌ Import timed out after 5 minutes")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Import failed with error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
