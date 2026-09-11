"""Safety alignment for customer team roles and first-login team setup.

The existing User permission model does not yet separate listing-content writes
from inventory/stock writes. Keep Content Manager non-destructive until that
specific permission exists, and make sure an already-existing User attached to a
customer account still completes Username, Name and Position when their profile
is incomplete.
"""
from __future__ import annotations

from flask import request
from flask_login import current_user
from sqlalchemy import func

from app import app
from extensions import db
from models import User
from services.account_profile_alignment import (
    ROLE_PRESETS,
    UserProfile,
    _account_for_user,
    _is_owner,
    _membership_for,
)


# Do not smuggle stock authority into a content job title. The existing
# permissions only expose edit_inventory, which is broader than product/listing
# content. Content Manager stays view-only until a listing-content write
# permission is explicitly mapped through the governed listing authority.
_content = ROLE_PRESETS["content_manager"]
_content["role"] = "viewer"
_content["description"] = (
    "Reviews product and marketplace content without stock or marketplace-write "
    "authority. Content editing will unlock only through a dedicated governed "
    "listing-content permission."
)
for key in list(_content["permissions"]):
    if key.startswith("edit_") or key in {"can_push", "can_sync", "can_import", "manage_users"}:
        _content["permissions"][key] = False


@app.after_request
def bt38_existing_team_member_profile_setup_alignment(response):
    """Preserve one-time setup when an existing User is assigned to a customer."""
    if not current_user.is_authenticated:
        return response
    if request.method != "POST" or request.path.rstrip("/") != "/profile/team/add":
        return response
    if response.status_code >= 500:
        return response

    account, owner_membership = _account_for_user(current_user.id)
    if not account or not _is_owner(owner_membership):
        return response

    email = str(request.form.get("email") or "").strip().lower()
    if not email:
        return response

    user = User.query.filter(func.lower(User.email) == email).first()
    if not user:
        return response

    membership = _membership_for(user.id)
    if not membership or membership.account_id != account.id:
        return response

    profile = db.session.get(UserProfile, user.id)
    changed = False
    if profile is None:
        profile = UserProfile(
            user_id=user.id,
            display_name=None,
            position=None,
            setup_required=True,
            setup_completed_at=None,
        )
        db.session.add(profile)
        changed = True
    elif not str(profile.display_name or "").strip() or not str(profile.position or "").strip():
        profile.setup_required = True
        profile.setup_completed_at = None
        changed = True

    if changed:
        db.session.commit()
    return response
