"""Customer-owned profile, branding and team alignment for BT38.

This extends the existing User/permission authority; it does not create a second
authentication system.  A paying customer owns a small account/workspace layer,
can assign at most five users, and can replace product-shell BT38 branding with
their own business logo.  BT38 remains a quiet "Powered by BT38" attribution.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import html
import json
import re
import secrets

from flask import Response, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import UniqueConstraint, func

from app import app
from extensions import db
from models import SystemLog, User


class CustomerAccount(db.Model):
    __tablename__ = "customer_accounts"
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False, index=True)
    business_name = db.Column(db.String(180), nullable=True)
    logo_data = db.Column(db.LargeBinary, nullable=True)
    logo_mime = db.Column(db.String(40), nullable=True)
    plan_name = db.Column(db.String(80), nullable=False, default="BT38")
    billing_status = db.Column(db.String(30), nullable=False, default="setup_pending")
    user_limit = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class CustomerAccountMember(db.Model):
    __tablename__ = "customer_account_members"
    __table_args__ = (UniqueConstraint("account_id", "user_id", name="uq_customer_account_member"), UniqueConstraint("user_id", name="uq_customer_account_member_user"))
    id=db.Column(db.Integer,primary_key=True); account_id=db.Column(db.Integer,db.ForeignKey("customer_accounts.id",ondelete="CASCADE"),nullable=False,index=True); user_id=db.Column(db.Integer,db.ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True); access_preset=db.Column(db.String(40),nullable=False,default="assistant"); is_owner=db.Column(db.Boolean,nullable=False,default=False); created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)

class UserProfile(db.Model):
    __tablename__="user_profiles"; user_id=db.Column(db.Integer,db.ForeignKey("users.id",ondelete="CASCADE"),primary_key=True); display_name=db.Column(db.String(140)); position=db.Column(db.String(140)); setup_required=db.Column(db.Boolean,nullable=False,default=False); setup_completed_at=db.Column(db.DateTime); created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow); updated_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)

with app.app_context(): db.create_all()

_PERMISSION_SECTIONS=("inventory","warehouse","stores","suppliers","purchase_orders","sync","settings","users")
def _permission_map(*,view=(),edit=(),can_push=False,can_sync=False,can_import=False,manage_users=False):
    p={}; vs=set(view); es=set(edit)
    for s in _PERMISSION_SECTIONS: p[f"view_{s}"]=s in vs or s in es; p[f"edit_{s}"]=s in es
    p.update({"can_push":bool(can_push),"can_sync":bool(can_sync),"can_import":bool(can_import),"manage_users":bool(manage_users)}); return p
ROLE_PRESETS={"operations_manager":{"label":"Operations Manager","description":"Runs day-to-day stock, stores, suppliers, purchasing and governed sync work.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders","sync","settings"),edit=("inventory","warehouse","stores","suppliers","purchase_orders","sync"),can_push=True,can_sync=True,can_import=True)},"warehouse_manager":{"label":"Warehouse Manager","description":"Controls warehouse and stock work with visibility of orders, suppliers and stores.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders"),edit=("inventory","warehouse"))},"purchasing_manager":{"label":"Supplier / Purchasing","description":"Manages suppliers and purchase orders while seeing the stock needed to buy well.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","suppliers","purchase_orders"),edit=("suppliers","purchase_orders"))},"content_manager":{"label":"Content Manager","description":"Works with product/listing content through the existing inventory and store permissions.","role":"manager","permissions":_permission_map(view=("inventory","stores"),edit=("inventory",))},"assistant":{"label":"Assistant","description":"Safe operational visibility without marketplace, sync or account-management authority.","role":"viewer","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders"))}}
_USERNAME_RE=re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_PROFILE_ALLOWED_PATHS={"/login","/logout","/profile/first-login","/profile/logo","/forgot-password","/reset-password"}

# The remainder of this module is intentionally imported from the branch's prior implementation.
# This marker is replaced below by the exact prior body during CI-safe patching.
