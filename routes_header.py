from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import desc, or_, text
from datetime import datetime
import logging
import json
import requests
import base64
import secrets
from urllib.parse import urlencode
import os
import hashlib

# Import db + models from models module to avoid circular import
from models import db, InventoryItem, Store, SyncLog, ProductGroup, GroupExternalRef, PushSettings, WarehouseStock, StockLedgerEntry, MarketplaceListing, SystemConfig
from amazon_service import AmazonAPIService
from ebay_service import eBayAPIService
from smart_push_service import smart_push_service

# Create Blueprint instead of using app directly
bp = Blueprint('routes', __name__)

