"""Event-driven, privacy-bounded customer journey recorder.

Records browser behaviour only when a real browser event occurs. There is no
polling, timer loop, marketplace call, stock mutation, or form-value capture.
The recorder is injected into HTML responses so it covers public and signed-in
BT38 pages without page-specific duplicate implementations.
"""
from __future__ import annotations

from datetime import datetime
import json

from flask import jsonify, request
from flask_login import current_user

from extensions import db
from models import SystemLog

_ENDPOINT = "/governed/ui/customer-behaviour"
_ALLOWED_EVENTS = {
    "page_view", "section_view", "scroll_depth", "click", "form_start",
    "form_submit", "page_exit", "signup_complete",
}
_ALLOWED_KEYS = {
    "event", "journey_id", "page", "title", "referrer_path", "section",
    "target", "target_text", "target_href", "form", "scroll_depth",
    "engaged_ms", "viewport", "sequence",
}
_MAX_BODY = 8192
_SCRIPT = r'''<script id="bt38CustomerBehaviourRecorder">
(function(){
  "use strict";
  if(window.__bt38BehaviourRecorder)return;
  window.__bt38BehaviourRecorder=true;
  var endpoint="/governed/ui/customer-behaviour";
  var key="bt38.customerJourney.v1";
  var journey=sessionStorage.getItem(key);
  if(!journey){journey=(self.crypto&&crypto.randomUUID)?crypto.randomUUID():String(Date.now())+"-"+Math.random().toString(36).slice(2);sessionStorage.setItem(key,journey);}
  var seq=0, started=Date.now(), maxDepth=0, seenSections=new Set(), startedForms=new Set();
  function clean(v,n){return String(v||"").replace(/\s+/g," ").trim().slice(0,n||160);}
  function pathOnly(v){try{var u=new URL(v,location.origin);return u.origin===location.origin?u.pathname+u.search:"";}catch(e){return "";}}
  function send(event,data,beacon){
    var body=Object.assign({event:event,journey_id:journey,page:location.pathname,title:clean(document.title,120),referrer_path:pathOnly(document.referrer),viewport:innerWidth+"x"+innerHeight,sequence:++seq},data||{});
    var raw=JSON.stringify(body);
    if(beacon&&navigator.sendBeacon){navigator.sendBeacon(endpoint,new Blob([raw],{type:"application/json"}));return;}
    fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:raw,credentials:"same-origin",keepalive:!!beacon}).catch(function(){});
  }
  function label(el){return clean(el.getAttribute("data-behaviour-label")||el.getAttribute("aria-label")||el.textContent||el.id||el.name,100);}
  send("page_view");
  document.addEventListener("click",function(e){
    var el=e.target.closest("a,button,[role=button],input[type=submit]"); if(!el)return;
    send("click",{target:clean(el.tagName.toLowerCase()+(el.id?"#"+el.id:"")+(el.name?"[name="+el.name+"]":""),120),target_text:label(el),target_href:el.tagName==="A"?pathOnly(el.href):""});
  },true);
  document.addEventListener("focusin",function(e){
    var form=e.target.closest&&e.target.closest("form"); if(!form)return;
    var name=clean(form.id||form.getAttribute("name")||form.getAttribute("action")||"form",100);
    if(startedForms.has(name))return; startedForms.add(name); send("form_start",{form:name});
  },true);
  document.addEventListener("submit",function(e){var f=e.target;if(!f||f.tagName!=="FORM")return;send("form_submit",{form:clean(f.id||f.getAttribute("name")||f.getAttribute("action")||"form",100)});},true);
  var sections=[].slice.call(document.querySelectorAll("main section[id],main [data-behaviour-section]"));
  if("IntersectionObserver" in window&&sections.length){
    var io=new IntersectionObserver(function(entries){entries.forEach(function(x){if(!x.isIntersecting||x.intersectionRatio<0.35)return;var s=clean(x.target.getAttribute("data-behaviour-section")||x.target.id,100);if(!s||seenSections.has(s))return;seenSections.add(s);send("section_view",{section:s});});},{threshold:[0.35]});sections.forEach(function(s){io.observe(s);});
  }
  var depths=[25,50,75,100];
  window.addEventListener("scroll",function(){var h=Math.max(document.documentElement.scrollHeight-innerHeight,1);var d=Math.min(100,Math.round(scrollY/h*100));depths.forEach(function(mark){if(d>=mark&&maxDepth<mark){maxDepth=mark;send("scroll_depth",{scroll_depth:mark});}});},{passive:true});
  window.addEventListener("pagehide",function(){send("page_exit",{scroll_depth:maxDepth,engaged_ms:Math.min(Date.now()-started,86400000)},true);});
})();
</script>'''


def _safe_text(value, limit=160):
    return str(value or "").replace("\x00", "").strip()[:limit]


def install_governed_customer_behaviour_recorder(app):
    if getattr(app, "_bt38_customer_behaviour_recorder_installed", False):
        return
    app._bt38_customer_behaviour_recorder_installed = True

    @app.post(_ENDPOINT)
    def bt38_customer_behaviour_event():
        if request.content_length and request.content_length > _MAX_BODY:
            return jsonify({"ok": False}), 413
        # Browser recorder is first-party only. Do not accept cross-site posts.
        if str(request.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            return jsonify({"ok": False}), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False}), 400
        event = _safe_text(payload.get("event"), 40)
        if event not in _ALLOWED_EVENTS:
            return jsonify({"ok": False}), 400
        details = {k: payload.get(k) for k in _ALLOWED_KEYS if k in payload}
        # Never accept arbitrary nested data or form/input values.
        for key, value in list(details.items()):
            if isinstance(value, (dict, list)):
                details.pop(key, None)
            elif isinstance(value, str):
                details[key] = _safe_text(value, 300)
        details["recorded_at"] = datetime.utcnow().isoformat() + "Z"
        details["authenticated"] = bool(current_user.is_authenticated)
        if current_user.is_authenticated:
            details["user_id"] = getattr(current_user, "id", None)
        row = SystemLog(
            log_type="customer_behaviour",
            message=f"Customer behaviour: {event}",
            details=json.dumps(details, ensure_ascii=False),
        )
        db.session.add(row)
        db.session.commit()
        return jsonify({"ok": True}), 202

    @app.after_request
    def bt38_customer_behaviour_script(response):
        if request.path == _ENDPOINT or request.method != "GET":
            return response
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type or response.direct_passthrough:
            return response
        body = response.get_data(as_text=True)
        if "bt38CustomerBehaviourRecorder" in body or "</body>" not in body:
            return response
        body = body.replace("</body>", _SCRIPT + "\n</body>", 1)
        response.set_data(body)
        response.headers.pop("Content-Length", None)
        return response
