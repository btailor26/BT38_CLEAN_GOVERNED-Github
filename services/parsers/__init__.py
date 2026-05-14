"""
STEP A: Marketplace Template Registry - Parser Package
Provides parsers for normalizing marketplace data into canonical format.
"""
from services.parsers.base_parser import BaseParser
from services.parsers.amazon_transactions_parser import AmazonTransactionsParser
from services.parsers.ebay_parser import EbayParser

__all__ = ['BaseParser', 'AmazonTransactionsParser', 'EbayParser']
