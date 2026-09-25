"""Event-driven, privacy-bounded customer journey recorder.

Records actual BT38 browser and backend activity as live proof. The recorder is
available on operational workspaces too, but it is strictly event-driven: when
there is no browser or backend activity it emits nothing. Its own transport is
excluded from fetch instrumentation so recording cannot recursively create
recording traffic. There is no polling, timer loop, marketplace call, stock mutation, keystroke,
credential, payment-field, or user-entered form-value capture.
"""
from __future__ import annotations

from datetime import datetime
import json
import time

from flask import jsonify, request, render_template, abort, g
from sqlalchemy import event as sqlalchemy_event
from flask_login import current_user, login_required

from extensions import db
from models import SystemLog

_ENDPOINT = "/governed/ui/customer-behaviour"
_OPERATIONAL_PATH_PREFIXES = (
    "/governed/warehouse",
    "/warehouse",
    "/product-linking",
    "/admin/product-linking",
    "/mcf",
    "/governed/mcf",
)
_ALLOWED_EVENTS = {
    "page_view", "display_snapshot", "feature_view", "section_view",
    "scroll_depth", "click", "change", "form_start", "form_submit",
    "page_exit", "signup_complete", "browser_request", "browser_error", "visual_frame",
}
_ALLOWED_KEYS = {
    "event", "journey_id", "page", "title", "referrer_path", "section",
    "target", "target_text", "target_href", "form", "scroll_depth",
    "engaged_ms", "viewport", "sequence", "feature", "display_text",
    "display_state", "request_id", "method", "status_code", "duration_ms",
    "response_bytes", "request_origin", "query_keys", "error_name", "error_message",
    "frame", "scroll_x", "scroll_y",
}
_MAX_BODY = 24576
_SCRIPT = r'''<script id="bt38CustomerBehaviourRecorder">
(function(){
  "use strict";
  if(window.__bt38BehaviourRecorder)return;
  window.__bt38BehaviourRecorder=true;
  var endpoint="/governed/ui/customer-behaviour";
  var key="bt38.customerJourney.v1";
  var journey=sessionStorage.getItem(key);
  if(!journey){journey=(self.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+"-"+Math.random().toString(36).slice(2);sessionStorage.setItem(key,journey);}
  var seq=0, started=Date.now(), maxDepth=0, seenSections=new Set(), seenFeatures=new Set(), startedForms=new Set();
  function clean(v,n){return String(v||"").replace(/\s+/g," ").trim().slice(0,n||160);}
  function pathOnly(v){try{var u=new URL(v,location.origin);return u.origin===location.origin?u.pathname:"";}catch(e){return "";}}
  function safeText(el,n){
    if(!el)return "";
    if(el.matches&&el.matches("input,textarea,select,[contenteditable=true]"))return clean(el.getAttribute("data-behaviour-label")||el.getAttribute("aria-label")||el.id||el.name,n||160);
    return clean(el.getAttribute&&el.getAttribute("data-behaviour-label")||el.getAttribute&&el.getAttribute("aria-label")||el.textContent||el.id||"",n||160);
  }
  function send(event,data,beacon){
    var body=Object.assign({event:event,journey_id:journey,page:location.pathname,title:clean(document.title,120),referrer_path:pathOnly(document.referrer),viewport:innerWidth+"x"+innerHeight,sequence:++seq},data||{});
    var raw=JSON.stringify(body);
    if(beacon&&navigator.sendBeacon){navigator.sendBeacon(endpoint,new Blob([raw],{type:"application/json"}));return;}
    fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:raw,credentials:"same-origin",keepalive:!!beacon}).catch(function(){});
  }
  function selector(el){
    if(!el)return "";
    return clean(el.tagName.toLowerCase()+(el.id?"#"+el.id:"")+(el.getAttribute("data-behaviour-feature")?"[data-behaviour-feature]":"")+(el.name?"[name="+el.name+"]":""),120);
  }
  function state(el){
    if(!el)return "";
    var bits=[];
    if(el.disabled)bits.push("disabled");
    if(el.getAttribute("aria-expanded")!==null)bits.push("expanded="+el.getAttribute("aria-expanded"));
    if(el.getAttribute("aria-selected")!==null)bits.push("selected="+el.getAttribute("aria-selected"));
    if(el.getAttribute("aria-checked")!==null)bits.push("checked="+el.getAttribute("aria-checked"));
    if(el.classList&&el.classList.contains("active"))bits.push("active");
    return clean(bits.join(","),100);
  }
  function visible(el){var r=el.getBoundingClientRect();var cs=getComputedStyle(el);return r.width>0&&r.height>0&&cs.display!=="none"&&cs.visibility!=="hidden";}
  function snapshot(){
    var nodes=[].slice.call(document.querySelectorAll("main h1,main h2,main h3,main [data-behaviour-feature],main .card,main .alert,main .badge,main table,main nav"));
    var shown=[];
    nodes.forEach(function(el){if(!visible(el)||shown.length>=40)return;var t=safeText(el,180);if(!t)return;shown.push(selector(el)+":"+t);});
    send("display_snapshot",{display_text:clean(shown.join(" | "),4000)});
  }
  function visualFrame(reason){
    if(!document.body)return;
    var clone=document.body.cloneNode(true);
    [].slice.call(clone.querySelectorAll("script,style,noscript")).forEach(function(el){el.remove();});
    [].slice.call(clone.querySelectorAll("body *")).forEach(function(el){
      if(el.matches&&el.matches("input,textarea,select,[contenteditable=true]")){
        if(el.tagName==="INPUT")el.setAttribute("value","");
        if(el.tagName==="TEXTAREA")el.textContent="";
        if(el.tagName==="SELECT")[].slice.call(el.options||[]).forEach(function(o){o.removeAttribute("selected");});
        if(el.hasAttribute&&el.hasAttribute("contenteditable"))el.textContent="";
      }
      ["data-token","data-secret","data-password","data-credential"].forEach(function(name){if(el.removeAttribute)el.removeAttribute(name);});
    });
    send("visual_frame",{feature:clean(reason,40),frame:clone.outerHTML.slice(0,12000),scroll_x:Math.round(scrollX||0),scroll_y:Math.round(scrollY||0)});
  }
  var originalFetch=window.fetch;
  if(originalFetch){window.fetch=function(input,init){var started=performance.now(),method=String((init&&init.method)||"GET").toUpperCase(),url="";try{url=new URL(typeof input==="string"?input:input.url,location.origin);url=url.origin===location.origin?url.pathname:"external";}catch(e){url="unknown";}if(url===endpoint)return originalFetch.apply(this,arguments);return originalFetch.apply(this,arguments).then(function(response){send("browser_request",{target:url,method:method,status_code:response.status,duration_ms:Math.round(performance.now()-started)});return response;},function(error){send("browser_error",{target:url,method:method,duration_ms:Math.round(performance.now()-started),error_name:clean(error&&error.name,80),error_message:clean(error&&error.message,180)});throw error;});};}
  window.addEventListener("error",function(e){send("browser_error",{error_name:"window_error",error_message:clean(e.message,180)});});
  window.addEventListener("unhandledrejection",function(e){send("browser_error",{error_name:"unhandled_rejection",error_message:clean(e.reason&&e.reason.message||e.reason,180)});});
  send("page_view");
  snapshot();
  visualFrame("page_view");
  document.addEventListener("click",function(e){
    var el=e.target.closest("a,button,[role=button],input[type=submit],[data-behaviour-feature]"); if(!el)return;
    send("click",{target:selector(el),target_text:safeText(el,100),target_href:el.tagName==="A"?pathOnly(el.href):"",display_state:state(el)}); visualFrame("click");
  },true);
  document.addEventListener("change",function(e){
    var el=e.target;if(!el)return;
    send("change",{target:selector(el),target_text:safeText(el,100),display_state:state(el)}); visualFrame("change");
  },true);
  document.addEventListener("focusin",function(e){
    var form=e.target.closest&&e.target.closest("form"); if(!form)return;
    var name=clean(form.id||form.getAttribute("name")||form.getAttribute("action")||"form",100);
    if(startedForms.has(name))return; startedForms.add(name); send("form_start",{form:name});
  },true);
  document.addEventListener("submit",function(e){var f=e.target;if(!f||f.tagName!=="FORM")return;send("form_submit",{form:clean(f.id||f.getAttribute("name")||f.getAttribute("action")||"form",100)});},true);
  var sections=[].slice.call(document.querySelectorAll("main section[id],main [data-behaviour-section]"));
  if("IntersectionObserver" in window&&sections.length){
    var io=new IntersectionObserver(function(entries){entries.forEach(function(x){if(!x.isIntersecting||x.intersectionRatio<0.35)return;var s=clean(x.target.getAttribute("data-behaviour-section")||x.target.id,100);if(!s||seenSections.has(s))return;seenSections.add(s);send("section_view",{section:s,display_text:safeText(x.target,500)});});},{threshold:[0.35]});sections.forEach(function(s){io.observe(s);});
  }
  var features=[].slice.call(document.querySelectorAll("[data-behaviour-feature],main button,main a,main [role=button],main .card,main .alert,main table"));
  if("IntersectionObserver" in window&&features.length){
    var fio=new IntersectionObserver(function(entries){entries.forEach(function(x){if(!x.isIntersecting||x.intersectionRatio<0.5)return;var f=clean(x.target.getAttribute("data-behaviour-feature")||selector(x.target)+":"+safeText(x.target,80),140);if(!f||seenFeatures.has(f))return;seenFeatures.add(f);send("feature_view",{feature:f,display_text:safeText(x.target,500),display_state:state(x.target)});});},{threshold:[0.5]});features.forEach(function(f){fio.observe(f);});
  }
  if("MutationObserver" in window&&document.body){
    var domObserver=new MutationObserver(function(mutations){
      if(mutations.some(function(m){return m.type==="childList"&&(m.addedNodes.length||m.removedNodes.length);}))visualFrame("dom_change");
    });
    domObserver.observe(document.body,{childList:true,subtree:true});
  }
  var depths=[25,50,75,100];
  window.addEventListener("scroll",function(){var h=Math.max(document.documentElement.scrollHeight-innerHeight,1);var d=Math.min(100,Math.round(scrollY/h*100));depths.forEach(function(mark){if(d>=mark&&maxDepth<mark){maxDepth=mark;send("scroll_depth",{scroll_depth:mark});}});},{passive:true});
  window.addEventListener("pagehide",function(){send("page_exit",{scroll_depth:maxDepth,engaged_ms:Math.min(Date.now()-started,86400000)},true);});
})();
</script>'''


def _safe_text(value, limit=160):
    return str(value or "").replace("\x00", "").strip()[:limit]


def _details(row):
    try:
        value = json.loads(row.details or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _operational_path(path: str) -> bool:
    clean_path = str(path or "").rstrip("/") or "/"
    return any(
        clean_path == prefix or clean_path.startswith(prefix + "/")
        for prefix in _OPERATIONAL_PATH_PREFIXES
    )



_SECRET_TERMS = ("password", "passwd", "secret", "token", "authorization", "cookie", "session", "api_key", "apikey", "private_key", "card", "cvv", "credential")


def _safe_query_keys():
    return sorted({str(key)[:80] for key in request.args.keys() if not any(term in str(key).lower() for term in _SECRET_TERMS)})[:80]


def _request_origin():
    mode = _safe_text(request.headers.get("Sec-Fetch-Mode"), 40).lower()
    dest = _safe_text(request.headers.get("Sec-Fetch-Dest"), 40).lower()
    if mode == "navigate" or dest == "document": return "browser_navigation"
    if mode: return "browser_fetch"
    return "backend_or_unknown"


def _record_system_event(message, details):
    try:
        row = SystemLog(log_type="system_recorder", message=message, details=json.dumps(details, ensure_ascii=False))
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()

def install_governed_customer_behaviour_recorder(app):
    if getattr(app, "_bt38_customer_behaviour_recorder_installed", False):
        return
    app._bt38_customer_behaviour_recorder_installed = True

    @app.before_request
    def bt38_system_recorder_request_start():
        if request.path == _ENDPOINT: return
        g._bt38_system_started = time.perf_counter()
        g._bt38_system_request_id = _safe_text(request.headers.get("X-Request-ID"), 100) or f"local-{time.time_ns()}"
        g._bt38_db_queries = 0
        g._bt38_db_ms = 0.0

    @app.after_request
    def bt38_system_recorder_request_finish(response):
        if request.path == _ENDPOINT: return response
        started = getattr(g, "_bt38_system_started", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started is not None else None
        details = {
            "event": "request_complete", "request_id": getattr(g, "_bt38_system_request_id", None),
            "method": request.method, "page": request.path, "query_keys": _safe_query_keys(),
            "request_origin": _request_origin(), "status_code": int(response.status_code),
            "duration_ms": duration_ms, "response_bytes": int(response.calculate_content_length() or 0),
            "db_query_count": int(getattr(g, "_bt38_db_queries", 0) or 0),
            "db_duration_ms": round(float(getattr(g, "_bt38_db_ms", 0.0) or 0.0), 1),
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
        _record_system_event(f"Request {request.method} {request.path}", details)
        return response

    @app.errorhandler(Exception)
    def bt38_system_recorder_unhandled(error):
        details = {"event": "backend_error", "request_id": getattr(g, "_bt38_system_request_id", None), "method": request.method, "page": request.path, "error_type": type(error).__name__, "recorded_at": datetime.utcnow().isoformat() + "Z"}
        _record_system_event(f"Backend error {request.method} {request.path}: {type(error).__name__}", details)
        raise error

    @app.post(_ENDPOINT)
    def bt38_customer_behaviour_event():
        if request.content_length and request.content_length > _MAX_BODY:
            return jsonify({"ok": False}), 413
        if str(request.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            return jsonify({"ok": False}), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False}), 400
        event = _safe_text(payload.get("event"), 40)
        if event not in _ALLOWED_EVENTS:
            return jsonify({"ok": False}), 400
        details = {k: payload.get(k) for k in _ALLOWED_KEYS if k in payload}
        for key, value in list(details.items()):
            if isinstance(value, (dict, list)):
                details.pop(key, None)
            elif isinstance(value, str):
                details[key] = _safe_text(value, 12000 if key == "frame" else (4000 if key == "display_text" else 300))
        details["recorded_at"] = datetime.utcnow().isoformat() + "Z"
        details["authenticated"] = bool(current_user.is_authenticated)
        if current_user.is_authenticated:
            details["user_id"] = getattr(current_user, "id", None)
        row = SystemLog(log_type="customer_behaviour", message=f"Customer behaviour: {event}", details=json.dumps(details, ensure_ascii=False))
        db.session.add(row)
        db.session.commit()
        return jsonify({"ok": True}), 202

    @app.get("/admin/customer-behaviour")
    @login_required
    def bt38_customer_behaviour_admin():
        if getattr(current_user, "role", "") != "admin":
            abort(403)
        rows = SystemLog.query.filter(SystemLog.log_type == "customer_behaviour").order_by(SystemLog.created_at.desc(), SystemLog.id.desc()).limit(2000).all()
        grouped = {}
        for row in reversed(rows):
            details = _details(row)
            journey_id = _safe_text(details.get("journey_id"), 100) or "unknown"
            journey = grouped.setdefault(journey_id, {"journey_id": journey_id, "user_id": details.get("user_id"), "first_at": row.created_at, "last_at": row.created_at, "events": []})
            journey["last_at"] = row.created_at
            if details.get("user_id") is not None: journey["user_id"] = details.get("user_id")
            journey["events"].append({
                "created_at": row.created_at, "created_at_iso": row.created_at.isoformat() if row.created_at else "", "event": _safe_text(details.get("event"), 40), "page": _safe_text(details.get("page"), 300),
                "section": _safe_text(details.get("section"), 100), "target": _safe_text(details.get("target"), 120), "target_text": _safe_text(details.get("target_text"), 100),
                "form": _safe_text(details.get("form"), 100), "feature": _safe_text(details.get("feature"), 140), "display_text": _safe_text(details.get("display_text"), 4000),
                "display_state": _safe_text(details.get("display_state"), 100), "scroll_depth": details.get("scroll_depth"), "engaged_ms": details.get("engaged_ms"),
                "frame": _safe_text(details.get("frame"), 12000), "scroll_x": details.get("scroll_x"), "scroll_y": details.get("scroll_y"),
            })
        journeys = sorted(grouped.values(), key=lambda item: item["last_at"], reverse=True)
        return render_template("admin/customer_behaviour.html", journeys=journeys)

    @app.before_request
    def bt38_fbm_request_probe_start():
        # Reuse the existing SystemLog recorder authority for a narrow FBM
        # request-origin audit. This records no order/customer/marketplace data.
        if request.method == "GET" and (request.path.rstrip("/") or "/") == "/fbm":
            g._bt38_fbm_probe_started = time.perf_counter()

    @app.after_request
    def bt38_fbm_request_probe(response):
        if request.method != "GET" or (request.path.rstrip("/") or "/") != "/fbm":
            return response
        started = getattr(g, "_bt38_fbm_probe_started", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started is not None else None
        fetch_mode = _safe_text(request.headers.get("Sec-Fetch-Mode"), 40).lower()
        fetch_dest = _safe_text(request.headers.get("Sec-Fetch-Dest"), 40).lower()
        expansion = _safe_text(request.headers.get("X-BT38-FBM-History-Expansion"), 20) == "1"
        if expansion:
            origin = "history_expansion"
        elif fetch_mode == "navigate" or fetch_dest == "document":
            origin = "browser_navigation"
        elif fetch_mode:
            origin = "browser_fetch"
        else:
            origin = "unknown"
        details = {
            "event": "fbm_request_probe",
            "page": "/fbm",
            "request_origin": origin,
            "fbm_range": _safe_text(request.args.get("fbm_range") or "3d", 20),
            "has_custom_from": bool(request.args.get("fbm_from")),
            "has_custom_to": bool(request.args.get("fbm_to")),
            "status_code": int(response.status_code),
            "response_bytes": int(response.calculate_content_length() or 0),
            "duration_ms": duration_ms,
            "fetch_mode": fetch_mode,
            "fetch_dest": fetch_dest,
            "history_expansion_header": expansion,
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            row = SystemLog(
                log_type="customer_behaviour",
                message=f"FBM request probe: {origin}",
                details=json.dumps(details, ensure_ascii=False),
            )
            db.session.add(row)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("BT38 FBM request probe could not be recorded")
        return response

    @app.after_request
    def bt38_customer_behaviour_script(response):
        if request.path == _ENDPOINT or request.method != "GET": return response
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type or response.direct_passthrough or response.headers.get("Content-Encoding"): return response
        body = response.get_data(as_text=True)
        if "bt38CustomerBehaviourRecorder" in body or "</body>" not in body: return response
        body = body.replace("</body>", _SCRIPT + "\n</body>", 1)
        response.set_data(body)
        response.headers.pop("Content-Length", None)
        return response
