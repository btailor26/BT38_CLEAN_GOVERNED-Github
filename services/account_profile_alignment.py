"""Customer-owned profile, branding and team alignment for BT38."""
from __future__ import annotations
from datetime import datetime
import html,json,re,secrets
from flask import Response,flash,jsonify,redirect,render_template,request,session,url_for
from flask_login import current_user,login_required
from sqlalchemy import UniqueConstraint,func
from app import app
from extensions import db
from models import SystemLog,User

class CustomerAccount(db.Model):
 __tablename__="customer_accounts"; id=db.Column(db.Integer,primary_key=True); owner_user_id=db.Column(db.Integer,db.ForeignKey("users.id",ondelete="RESTRICT"),unique=True,nullable=False,index=True); business_name=db.Column(db.String(180)); logo_data=db.Column(db.LargeBinary); logo_mime=db.Column(db.String(40)); plan_name=db.Column(db.String(80),nullable=False,default="BT38"); billing_status=db.Column(db.String(30),nullable=False,default="setup_pending"); user_limit=db.Column(db.Integer,nullable=False,default=5); created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow); updated_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
class CustomerAccountMember(db.Model):
 __tablename__="customer_account_members"; __table_args__=(UniqueConstraint("account_id","user_id",name="uq_customer_account_member"),UniqueConstraint("user_id",name="uq_customer_account_member_user")); id=db.Column(db.Integer,primary_key=True); account_id=db.Column(db.Integer,db.ForeignKey("customer_accounts.id",ondelete="CASCADE"),nullable=False,index=True); user_id=db.Column(db.Integer,db.ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True); access_preset=db.Column(db.String(40),nullable=False,default="assistant"); is_owner=db.Column(db.Boolean,nullable=False,default=False); created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)
class UserProfile(db.Model):
 __tablename__="user_profiles"; user_id=db.Column(db.Integer,db.ForeignKey("users.id",ondelete="CASCADE"),primary_key=True); display_name=db.Column(db.String(140)); position=db.Column(db.String(140)); setup_required=db.Column(db.Boolean,nullable=False,default=False); setup_completed_at=db.Column(db.DateTime); created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow); updated_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
with app.app_context(): db.create_all()
_PERMISSION_SECTIONS=("inventory","warehouse","stores","suppliers","purchase_orders","sync","settings","users")
def _permission_map(*,view=(),edit=(),can_push=False,can_sync=False,can_import=False,manage_users=False):
 p={}; v=set(view); e=set(edit)
 for s in _PERMISSION_SECTIONS: p[f"view_{s}"]=s in v or s in e; p[f"edit_{s}"]=s in e
 p.update(can_push=bool(can_push),can_sync=bool(can_sync),can_import=bool(can_import),manage_users=bool(manage_users)); return p
ROLE_PRESETS={"operations_manager":{"label":"Operations Manager","description":"Runs day-to-day stock, stores, suppliers, purchasing and governed sync work.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders","sync","settings"),edit=("inventory","warehouse","stores","suppliers","purchase_orders","sync"),can_push=True,can_sync=True,can_import=True)},"warehouse_manager":{"label":"Warehouse Manager","description":"Controls warehouse and stock work with visibility of orders, suppliers and stores.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders"),edit=("inventory","warehouse"))},"purchasing_manager":{"label":"Supplier / Purchasing","description":"Manages suppliers and purchase orders while seeing the stock needed to buy well.","role":"manager","permissions":_permission_map(view=("inventory","warehouse","suppliers","purchase_orders"),edit=("suppliers","purchase_orders"))},"content_manager":{"label":"Content Manager","description":"Works with product/listing content through the existing inventory and store permissions.","role":"manager","permissions":_permission_map(view=("inventory","stores"),edit=("inventory",))},"assistant":{"label":"Assistant","description":"Safe operational visibility without marketplace, sync or account-management authority.","role":"viewer","permissions":_permission_map(view=("inventory","warehouse","stores","suppliers","purchase_orders"))}}
_USERNAME_RE=re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$"); _PROFILE_ALLOWED_PATHS={"/login","/logout","/profile/first-login","/profile/logo","/forgot-password","/reset-password"}
def _load_log_details(row):
 try: v=json.loads(row.details or "{}")
 except Exception:return {}
 return v if isinstance(v,dict) else {}
def _approved_application(email):
 email=str(email or "").strip().lower()
 if not email:return None
 for row in SystemLog.query.filter(SystemLog.log_type=="early_access_application").order_by(SystemLog.created_at.desc(),SystemLog.id.desc()).limit(500).all():
  d=_load_log_details(row)
  if str(d.get("email") or "").strip().lower()==email and str(d.get("status") or "").strip().lower()=="approved":return d
 return None
def _profile_for(uid):return db.session.get(UserProfile,int(uid))
def _membership_for(uid):return CustomerAccountMember.query.filter_by(user_id=int(uid)).first()
def _account_for_user(uid):
 m=_membership_for(uid); return (db.session.get(CustomerAccount,m.account_id),m) if m else (None,None)
def _create_owner_account(user,*,business_name=""):
 existing,_=_account_for_user(user.id)
 if existing:return existing
 a=CustomerAccount(owner_user_id=user.id,business_name=str(business_name or "").strip()[:180] or None,plan_name="BT38",billing_status="setup_pending",user_limit=5); db.session.add(a);db.session.flush();db.session.add(CustomerAccountMember(account_id=a.id,user_id=user.id,access_preset="owner",is_owner=True));return a
def _ensure_profile(user):
 p=_profile_for(user.id)
 if p:return p
 approved=_approved_application(user.email);p=UserProfile(user_id=user.id,display_name=(str(approved.get("full_name") or "").strip()[:140] if approved else str(user.username or "").strip()[:140]),position=None,setup_required=bool(approved),setup_completed_at=None if approved else datetime.utcnow());db.session.add(p)
 if approved:_create_owner_account(user,business_name=str(approved.get("business_name") or "").strip())
 db.session.commit();return p
def _ensure_legacy_admin_account(user):
 a,_=_account_for_user(user.id)
 if a:return a
 if str(getattr(user,"role","") or "")!="admin":return None
 a=_create_owner_account(user);db.session.commit();return a
def _member_count(aid):return CustomerAccountMember.query.filter_by(account_id=int(aid)).count()
def _display_name(user):
 p=_profile_for(user.id);return str(getattr(p,"display_name","") or "").strip() or str(user.username or user.email or "User")
def _first_name(user):return _display_name(user).split()[0]
def _is_owner(member):return bool(member and member.is_owner)
def _unique_username(value,*,exclude_user_id=None):
 u=str(value or "").strip().lower()
 if not _USERNAME_RE.fullmatch(u):return "","Use 3–32 lowercase letters, numbers, dots, dashes or underscores."
 q=User.query.filter(func.lower(User.username)==u)
 if exclude_user_id is not None:q=q.filter(User.id!=int(exclude_user_id))
 return ("","That username is already in use. Choose another.") if q.first() else (u,"")
def _apply_preset(user,key):
 key=str(key or "").strip().lower();p=ROLE_PRESETS.get(key)
 if not p:key="assistant";p=ROLE_PRESETS[key]
 user.role=p["role"];user.permissions=dict(p["permissions"]);return key
def _logo_kind(payload):
 if payload.startswith(b"\x89PNG\r\n\x1a\n"):return "image/png"
 if payload.startswith(b"\xff\xd8\xff"):return "image/jpeg"
 if len(payload)>=12 and payload[:4]==b"RIFF" and payload[8:12]==b"WEBP":return "image/webp"
 return None
def _brand_context():
 if not current_user.is_authenticated:return {"business_name":"BT38 Inventory","logo_url":"","is_customer_branded":False,"display_name":"","position":"","is_owner":False,"billing_visible":False}
 p=_profile_for(current_user.id);a,m=_account_for_user(current_user.id);return {"business_name":str(a.business_name or "").strip() if a else "","logo_url":url_for("bt38_profile_logo") if a and a.logo_data else "","is_customer_branded":bool(a and a.logo_data),"display_name":str(p.display_name or "").strip() if p else _display_name(current_user),"position":str(p.position or "").strip() if p else "","is_owner":_is_owner(m),"billing_visible":_is_owner(m)}
@app.context_processor
def bt38_account_profile_context():return {"account_brand":_brand_context(),"account_role_presets":ROLE_PRESETS}
@app.before_request
def bt38_first_login_profile_gate():
 if not current_user.is_authenticated:return None
 path=request.path.rstrip("/") or "/"
 if path.startswith("/static/") or path in _PROFILE_ALLOWED_PATHS:return None
 p=_ensure_profile(current_user)
 if not p.setup_required:return None
 if request.method=="GET":return redirect(url_for("bt38_profile_first_login"))
 return jsonify({"ok":False,"reason":"profile_setup_required","message":"Complete your username, name and position before continuing."}),409
@app.route("/profile/first-login",methods=["GET","POST"])
@login_required
def bt38_profile_first_login():
 p=_ensure_profile(current_user)
 if not p.setup_required:return redirect(url_for("governed.governed_dashboard_page"))
 if request.method=="GET":return render_template("profile_first_login.html",profile=p,suggested_username="")
 username,err=_unique_username(request.form.get("username"),exclude_user_id=current_user.id);name=str(request.form.get("display_name") or "").strip()[:140];position=str(request.form.get("position") or "").strip()[:140]
 err=err or ("Enter the name you want COFI and your team to use." if not name else "") or ("Enter your position." if not position else "")
 if err:return render_template("profile_first_login.html",profile=p,suggested_username=str(request.form.get("username") or ""),error=err,form=request.form),400
 current_user.username=username;p.display_name=name;p.position=position;p.setup_required=False;p.setup_completed_at=datetime.utcnow();db.session.commit();session["bt38_cofi_first_welcome"]=name;flash(f"Welcome, {name.split()[0]}. COFI is ready when you are.","success");return redirect(url_for("governed.governed_dashboard_page"))
@app.route("/profile",methods=["GET","POST"])
@login_required
def bt38_profile_page():
 p=_ensure_profile(current_user);a,m=_account_for_user(current_user.id)
 if not a and str(current_user.role or "")=="admin":a=_ensure_legacy_admin_account(current_user);a,m=_account_for_user(current_user.id)
 if request.method=="POST":
  section=str(request.form.get("section") or "personal").strip().lower()
  if section=="personal":
   username,err=_unique_username(request.form.get("username"),exclude_user_id=current_user.id);name=str(request.form.get("display_name") or "").strip()[:140];position=str(request.form.get("position") or "").strip()[:140]
   if err or not name or not position:flash(err or "Name and position are required.","danger")
   else:current_user.username=username;p.display_name=name;p.position=position;db.session.commit();flash("Your profile has been updated.","success")
   return redirect(url_for("bt38_profile_page")+"#personal")
  if section=="business":
   if not a or not _is_owner(m):flash("Only the account owner can change business branding.","danger");return redirect(url_for("bt38_profile_page")+"#business")
   name=str(request.form.get("business_name") or "").strip()[:180]
   if not name:flash("Enter your business name.","danger");return redirect(url_for("bt38_profile_page")+"#business")
   logo=request.files.get("logo")
   if logo and logo.filename:
    payload=logo.read(1024*1024+1)
    if len(payload)>1024*1024:flash("Logo must be 1 MB or smaller.","danger");return redirect(url_for("bt38_profile_page")+"#business")
    mime=_logo_kind(payload)
    if not mime:flash("Use a PNG, JPEG or WebP logo.","danger");return redirect(url_for("bt38_profile_page")+"#business")
    a.logo_data=payload;a.logo_mime=mime
   a.business_name=name;db.session.commit();flash("Business branding has been updated.","success");return redirect(url_for("bt38_profile_page")+"#business")
  flash("That profile section could not be updated.","danger");return redirect(url_for("bt38_profile_page"))
 team=[]
 if a:
  memberships=CustomerAccountMember.query.filter_by(account_id=a.id).order_by(CustomerAccountMember.is_owner.desc(),CustomerAccountMember.id.asc()).all();ids=[x.user_id for x in memberships];users={u.id:u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {};profiles={x.user_id:x for x in UserProfile.query.filter(UserProfile.user_id.in_(ids)).all()} if ids else {}
  for mm in memberships:
   u=users.get(mm.user_id)
   if u:team.append({"membership":mm,"user":u,"profile":profiles.get(u.id),"preset_label":"Owner" if mm.is_owner else ROLE_PRESETS.get(mm.access_preset,{}).get("label","Team member")})
 return render_template("profile.html",profile=p,account=a,member=m,team=team,role_presets=ROLE_PRESETS,seat_count=_member_count(a.id) if a else 0)
@app.post("/profile/team/add")
@login_required
def bt38_profile_team_add():
 _ensure_profile(current_user);a,m=_account_for_user(current_user.id)
 if not a or not _is_owner(m):flash("Only the paying account owner can add team members.","danger");return redirect(url_for("bt38_profile_page")+"#team")
 if _member_count(a.id)>=int(a.user_limit or 5):flash(f"Your plan includes {int(a.user_limit or 5)} users and all seats are currently assigned.","warning");return redirect(url_for("bt38_profile_page")+"#team")
 email=str(request.form.get("email") or "").strip().lower()[:120];key=str(request.form.get("access_preset") or "assistant").strip().lower()
 if "@" not in email or key not in ROLE_PRESETS:flash("Enter a valid team member email and role.","danger");return redirect(url_for("bt38_profile_page")+"#team")
 u=User.query.filter(func.lower(User.email)==email).first()
 if u:
  ex=_membership_for(u.id)
  if ex:flash("That user is already on a customer account.","info" if ex.account_id==a.id else "danger");return redirect(url_for("bt38_profile_page")+"#team")
 else:
  u=User(username=f"pending_{secrets.token_hex(10)}",email=email,role="viewer",permissions={},is_active=True);u.set_password(secrets.token_urlsafe(48));_apply_preset(u,key);db.session.add(u);db.session.flush();db.session.add(UserProfile(user_id=u.id,display_name=None,position=None,setup_required=True,setup_completed_at=None))
 db.session.add(CustomerAccountMember(account_id=a.id,user_id=u.id,access_preset=_apply_preset(u,key),is_owner=False));db.session.commit();flash("Team member added. They can use Google sign-in with that email, then choose Username, Name and Position.","success");return redirect(url_for("bt38_profile_page")+"#team")
@app.post("/profile/team/<int:user_id>/role")
@login_required
def bt38_profile_team_role(user_id):
 a,m=_account_for_user(current_user.id);tm=CustomerAccountMember.query.filter_by(account_id=a.id,user_id=user_id).first() if a else None;key=str(request.form.get("access_preset") or "assistant").strip().lower();u=db.session.get(User,user_id)
 if not a or not _is_owner(m) or not tm or tm.is_owner or key not in ROLE_PRESETS or not u:flash("Team access could not be changed.","danger");return redirect(url_for("bt38_profile_page")+"#team")
 tm.access_preset=_apply_preset(u,key);db.session.commit();flash("Team permissions updated.","success");return redirect(url_for("bt38_profile_page")+"#team")
@app.post("/profile/team/<int:user_id>/remove")
@login_required
def bt38_profile_team_remove(user_id):
 a,m=_account_for_user(current_user.id);tm=CustomerAccountMember.query.filter_by(account_id=a.id,user_id=user_id).first() if a else None
 if not a or not _is_owner(m) or not tm or tm.is_owner:flash("Team member cannot be removed.","danger");return redirect(url_for("bt38_profile_page")+"#team")
 u=db.session.get(User,user_id)
 if u:u.is_active=False
 db.session.delete(tm);db.session.commit();flash("Team member access has been removed.","success");return redirect(url_for("bt38_profile_page")+"#team")
@app.get("/profile/logo")
@login_required
def bt38_profile_logo():
 a,_=_account_for_user(current_user.id)
 if not a or not a.logo_data or not a.logo_mime:return Response(status=404)
 r=Response(bytes(a.logo_data),mimetype=a.logo_mime);r.headers["Cache-Control"]="private, max-age=300";return r
@app.get("/billing")
@login_required
def bt38_billing_page():
 _ensure_profile(current_user);a,m=_account_for_user(current_user.id)
 if not a or not _is_owner(m):flash("Billing is available to the paying account owner.","warning");return redirect(url_for("bt38_profile_page"))
 from services.billing_invoice_alignment import invoices_for_account
 return render_template("billing.html",account=a,seat_count=_member_count(a.id),invoices=invoices_for_account(a.id))
@app.after_request
def bt38_customer_owned_shell_alignment(response):
 if not current_user.is_authenticated or response.status_code>=400 or not response.content_type or "text/html" not in response.content_type:return response
 a,m=_account_for_user(current_user.id);p=_profile_for(current_user.id)
 if not p:return response
 body=response.get_data(as_text=True)
 if not body:return response
 display=html.escape(str(p.display_name or current_user.username or "Profile"));position=html.escape(str(p.position or ""));business=html.escape(str(a.business_name or "").strip()) if a else ""
 if a and a.logo_data:
  label=business or display;markup=f'<img src="{url_for("bt38_profile_logo")}" alt="{label}" style="height:30px;max-width:150px;object-fit:contain;border-radius:5px" class="me-2"><span>{label}</span>';body=body.replace('<i data-feather="package" class="me-2"></i>BT38 Inventory',markup);body=body.replace('<span class="text-muted small">BT38 Inventory Management</span>',f'<span class="text-muted small">{label} <span class="ms-2">Powered by BT38</span></span>')
 elif a and business:body=body.replace('<i data-feather="package" class="me-2"></i>BT38 Inventory',f'<i data-feather="package" class="me-2"></i>{business}')
 top='''<a class="nav-link text-light" href="/login">\n                    <i data-feather="log-in" class="me-1"></i>Login\n                </a>''';billing='<li><a class="dropdown-item" href="/billing"><i data-feather="credit-card" class="me-2"></i>Billing</a></li>' if _is_owner(m) else "";menu=f'''<div class="dropdown"><button class="btn btn-dark border-0 dropdown-toggle d-flex align-items-center gap-2" type="button" data-bs-toggle="dropdown"><span class="rounded-circle bg-light text-dark d-inline-flex align-items-center justify-content-center" style="width:30px;height:30px;font-weight:700">{html.escape(display[:1].upper())}</span><span class="d-none d-md-inline text-start"><span class="d-block">{display}</span>{f'<small class="text-secondary">{position}</small>' if position else ''}</span></button><ul class="dropdown-menu dropdown-menu-end shadow-sm"><li><a class="dropdown-item" href="/profile"><i data-feather="user" class="me-2"></i>Profile</a></li>{billing}<li><hr class="dropdown-divider"></li><li><a class="dropdown-item" href="/logout"><i data-feather="log-out" class="me-2"></i>Sign out</a></li></ul></div>''';body=body.replace(top,menu,1);response.set_data(body);return response
