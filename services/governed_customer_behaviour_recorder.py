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
    "/fbm",
    "/governed/warehouse",
    "/warehouse",
    "/product-linking",
    "/admin/product-linking",
    "/mcf",
    "/governed/mcf",
)
_ALLOWED_EVENTS = {"browser_error"}
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
  function clean(v,n){return String(v||"").replace(/\\s+/g," ").trim().slice(0,n||180);}
  function sendError(data){var raw=JSON.stringify(Object.assign({event:"browser_error",page:location.pathname},data||{}));fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:raw,credentials:"same-origin",keepalive:true}).catch(function(){});}
  window.addEventListener("error",function(e){sendError({error_name:"window_error",error_message:clean(e.message,180)});});
  window.addEventListener("unhandledrejection",function(e){sendError({error_name:"unhandled_rejection",error_message:clean(e.reason&&e.reason.message||e.reason,180)});});
})();
</script>'''


_VIDEO_CONTROL_SCRIPT = r'''<script id="bt38JourneyVideoRecorder">
(function(){
  "use strict";
  if(window.__bt38JourneyVideoRecorder)return;
  window.__bt38JourneyVideoRecorder=true;
  if(!navigator.mediaDevices||typeof navigator.mediaDevices.getDisplayMedia!=="function"||typeof window.MediaRecorder!=="function")return;
  var stream=null,recorder=null,chunks=[],note="";
  var button=document.createElement("button");
  button.type="button";button.id="bt38JourneyVideoRecord";button.textContent="Video record";button.className="btn btn-dark border-0 d-inline-flex align-items-center justify-content-center gap-1";
  button.style.cssText="white-space:nowrap";
  button.setAttribute("aria-label","Record BT38 journey video");button.setAttribute("title","Video record");
  var bell=document.getElementById("bt38NotificationBell");
  if(bell&&bell.parentNode){bell.parentNode.insertBefore(button,bell);}else{document.body.appendChild(button);button.style.cssText="position:fixed;right:72px;top:8px;z-index:2147483647;white-space:nowrap";}

  var panel=document.createElement("div");
  panel.id="bt38JourneyVideoNotePanel";panel.hidden=true;
  panel.style.cssText="position:fixed;right:18px;top:62px;bottom:auto;width:min(420px,calc(100vw - 36px));max-height:calc(100vh - 80px);overflow:auto;z-index:2147483647;background:#fff;border:1px solid #ced4da;border-radius:8px;padding:14px;box-shadow:0 4px 18px rgba(0,0,0,.2)";
  panel.innerHTML='<label for="bt38JourneyVideoNote" class="form-label fw-semibold mb-1">What should we look at?</label><div class="small text-muted mb-2">Describe the issue this recording should demonstrate. Do not enter passwords, customer details or payment information.</div><textarea id="bt38JourneyVideoNote" class="form-control form-control-sm mb-2" rows="3" maxlength="500" placeholder="Example: Check the Journey column. Picked Up colour does not match the shipment journey popup."></textarea><div class="d-flex justify-content-end gap-2"><button type="button" class="btn btn-sm btn-outline-secondary" id="bt38JourneyVideoCancel">Cancel</button><button type="button" class="btn btn-sm btn-danger" id="bt38JourneyVideoStart">Continue to screen permission</button></div>';
  document.body.appendChild(panel);
  var noteInput=panel.querySelector("#bt38JourneyVideoNote"),startButton=panel.querySelector("#bt38JourneyVideoStart"),cancelButton=panel.querySelector("#bt38JourneyVideoCancel");

  function reset(){stream=null;recorder=null;chunks=[];note="";panel.hidden=true;noteInput.value="";button.disabled=false;button.textContent="Video record";button.className="btn btn-dark border-0 d-inline-flex align-items-center justify-content-center gap-1";}
  function stop(){if(recorder&&recorder.state!=="inactive")recorder.stop();}
  function hideNoteOverlay(){var el=document.getElementById("bt38JourneyVideoWhatToCheck");if(el)el.remove();}
  function showNoteOverlay(){
    hideNoteOverlay();if(!note)return;
    var overlay=document.createElement("div");overlay.id="bt38JourneyVideoWhatToCheck";
    overlay.style.cssText="position:fixed;left:18px;top:18px;max-width:min(620px,calc(100vw - 36px));z-index:2147483646;background:rgba(33,37,41,.94);color:#fff;border-radius:8px;padding:12px 14px;box-shadow:0 4px 18px rgba(0,0,0,.25);pointer-events:none";
    var title=document.createElement("div");title.className="fw-semibold mb-1";title.textContent="What to check";
    var body=document.createElement("div");body.className="small";body.textContent=note;
    overlay.appendChild(title);overlay.appendChild(body);document.body.appendChild(overlay);
    window.setTimeout(hideNoteOverlay,5000);
  }
  button.addEventListener("click",function(){
    if(recorder&&recorder.state==="recording"){stop();return;}
    panel.hidden=false;noteInput.focus();
  });
  cancelButton.addEventListener("click",function(){panel.hidden=true;noteInput.value="";});
  startButton.addEventListener("click",async function(){
    note=String(noteInput.value||"").replace(/\s+/g," ").trim().slice(0,500);
    panel.hidden=true;button.disabled=true;
    try{
      // Capture can start only from this explicit Continue action. The browser
      // owns the chooser/permission prompt and BT38 cannot auto-accept/bypass it.
      stream=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false});
      chunks=[];recorder=new MediaRecorder(stream);
      recorder.addEventListener("dataavailable",function(e){if(e.data&&e.data.size)chunks.push(e.data);});
      recorder.addEventListener("stop",function(){
        hideNoteOverlay();
        var blob=new Blob(chunks,{type:recorder.mimeType||"video/webm"});
        if(blob.size){var url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="bt38-journey-"+new Date().toISOString().replace(/[:.]/g,"-")+".webm";document.body.appendChild(a);a.click();a.remove();window.setTimeout(function(){URL.revokeObjectURL(url);},1000);}
        if(stream)stream.getTracks().forEach(function(track){track.stop();});reset();
      },{once:true});
      stream.getVideoTracks().forEach(function(track){track.addEventListener("ended",stop,{once:true});});
      recorder.start();showNoteOverlay();button.disabled=false;button.textContent="Stop recording";button.className="btn btn-danger d-inline-flex align-items-center justify-content-center gap-1";
    }catch(error){reset();if(error&&error.name!=="NotAllowedError")console.warn("[BT38 recorder] video capture unavailable",error);}
  });
  window.addEventListener("pagehide",stop,{once:true});
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
        if request.path == _ENDPOINT:
            return response
        if int(response.status_code) < 400:
            return response
        started = getattr(g, "_bt38_system_started", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started is not None else None
        details = {
            "event": "request_failed", "request_id": getattr(g, "_bt38_system_request_id", None),
            "method": request.method, "page": request.path, "query_keys": _safe_query_keys(),
            "request_origin": _request_origin(), "status_code": int(response.status_code),
            "duration_ms": duration_ms, "response_bytes": int(response.calculate_content_length() or 0),
            "db_query_count": int(getattr(g, "_bt38_db_queries", 0) or 0),
            "db_duration_ms": round(float(getattr(g, "_bt38_db_ms", 0.0) or 0.0), 1),
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
        _record_system_event(f"Failed request {request.method} {request.path}", details)
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

    @app.after_request
    def bt38_customer_behaviour_script(response):
        if request.path == _ENDPOINT or request.method != "GET": return response
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type or response.direct_passthrough or response.headers.get("Content-Encoding"): return response
        body = response.get_data(as_text=True)
        if "bt38CustomerBehaviourRecorder" in body or "</body>" not in body: return response
        injected = _SCRIPT
        if current_user.is_authenticated and getattr(current_user, "role", "") == "admin":
            injected += "\n" + _VIDEO_CONTROL_SCRIPT
        body = body.replace("</body>", injected + "\n</body>", 1)
        response.set_data(body)
        response.headers.pop("Content-Length", None)
        return response
