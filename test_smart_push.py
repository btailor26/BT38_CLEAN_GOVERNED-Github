#!/usr/bin/env python3

"""
Quick test of the smart push service with EB-TJ-CR-25g SKU
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from smart_push_service import smart_push_service

def test_smart_push():
    """Test smart push service with EB-TJ-CR-25g"""
    with app.app_context():
        print("🚀 Testing Smart Push Service with EB-TJ-CR-25g")
        
        # Test pushing specific SKU
        results = smart_push_service.push_specific_sku('EB-TJ-CR-25g', 'beatsoutlet')
        
        print(f"📊 Push Results:")
        print(f"  - SKU: {results['sku']}")
        print(f"  - Listings found: {results['listings_found']}")
        print(f"  - Successful pushes: {results['successful']}")
        print(f"  - Failed pushes: {results['failed']}")
        
        if results['errors']:
            print(f"  - Errors: {results['errors']}")
        else:
            print(f"  - ✅ No errors!")
        
        return results

if __name__ == "__main__":
    test_smart_push()