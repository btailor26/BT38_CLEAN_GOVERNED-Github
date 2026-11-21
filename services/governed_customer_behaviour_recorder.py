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

from flask import jsonify, request, g, got_request_exception
from flask_login import current_user

from extensions import db
from models import SystemLog

_ENDPOINT = "/governed/ui/customer-behaviour"
_OPERATIONAL_PATH_PREFIXES = (
    "/dashboard",
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
  var button=document.createElement("button");
  button.type="button";button.id="bt38JourneyVideoRecord";button.textContent="Video record";
  button.className="btn btn-dark border-0 d-inline-flex align-items-center justify-content-center gap-1";
  button.style.cssText="white-space:nowrap";
  button.setAttribute("aria-label","Record BT38 journey video");button.title="Video record";
  var bell=document.getElementById("bt38NotificationBell");
  if(bell&&bell.parentNode){bell.parentNode.insertBefore(button,bell);}
  else{document.body.appendChild(button);button.style.cssText="position:fixed;right:72px;top:8px;z-index:2147483647;white-space:nowrap";}
  var panel=document.createElement("div");panel.id="bt38JourneyVideoNotePanel";panel.hidden=true;
  panel.style.cssText="position:fixed;right:18px;top:62px;width:min(420px,calc(100vw - 36px));z-index:2147483647;background:#fff;border:1px solid #ced4da;border-radius:8px;padding:14px;box-shadow:0 4px 18px rgba(0,0,0,.2)";
  panel.innerHTML='<label for="bt38JourneyVideoNote">What should we look at?</label><textarea id="bt38JourneyVideoNote" class="form-control form-control-sm my-2" rows="3" maxlength="500" placeholder="Describe the issue. Do not include private information."></textarea><div class="d-flex justify-content-end gap-2"><button type="button" class="btn btn-sm btn-outline-secondary" id="bt38JourneyVideoCancel">Cancel</button><button type="button" class="btn btn-sm btn-danger" id="bt38JourneyVideoStart">Continue to screen permission</button></div>';
  document.body.appendChild(panel);
  var noteInput=panel.querySelector("#bt38JourneyVideoNote"),startButton=panel.querySelector("#bt38JourneyVideoStart");
  panel.querySelector("#bt38JourneyVideoCancel").addEventListener("click",function(){panel.hidden=true;});
  var controller=null;
  function controllerHtml(note){
    var safeNote=JSON.stringify(note).replace(/</g,"\\u003c");
    return '<!doctype html><html><head><meta charset="utf-8"><title>BT38 recording controller</title></head><body style="font:15px system-ui;padding:20px;max-width:540px"><h2>BT38 journey recorder</h2><p>Keep this small controller window open while navigating BT38. Select the <strong>BT38 tab</strong> in the browser sharing dialog, not this controller window. The recording will follow that tab through full-page navigation.</p><p id="state">Ready to start</p><button id="start">Start recording</button> <button id="stop" disabled>Stop and save</button><p id="note"></p><script>\n'+
      '(()=>{const note='+safeNote+';let stream=null,recorder=null,chunks=[];const state=document.getElementById("state"),start=document.getElementById("start"),stop=document.getElementById("stop");document.getElementById("note").textContent=note;'+
      'function cleanup(){if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;recorder=null;start.disabled=false;stop.disabled=true;}'+
      'start.addEventListener("click",async function(){start.disabled=true;try{stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:"browser"},audio:false,preferCurrentTab:true,selfBrowserSurface:"exclude",surfaceSwitching:"exclude",monitorTypeSurfaces:"exclude"});'+
      'var captureTrack=stream.getVideoTracks()[0];if(!captureTrack||captureTrack.getSettings().displaySurface!=="browser"){stream.getTracks().forEach(t=>t.stop());stream=null;throw Error("Choose the BT38 browser tab, not a window or screen.");}'+
      'chunks=[];recorder=new MediaRecorder(stream);recorder.addEventListener("dataavailable",e=>{if(e.data&&e.data.size)chunks.push(e.data);});recorder.addEventListener("stop",()=>{let blob=new Blob(chunks,{type:recorder.mimeType||"video/webm"});if(blob.size){let url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="bt38-journey-"+new Date().toISOString().replace(/[:.]/g,"-")+".webm";document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}cleanup();state.textContent="Recording saved";},{once:true});'+
      'captureTrack.addEventListener("ended",()=>{if(recorder&&recorder.state!=="inactive")recorder.stop();},{once:true});recorder.start();stop.disabled=false;state.textContent="Recording BT38 tab. Navigate within BT38; recording continues.";'+
      '}catch(e){cleanup();state.textContent=e&&e.message||"Capture cancelled";}});'+
      'stop.addEventListener("click",()=>{if(recorder&&recorder.state!=="inactive")recorder.stop();});'+
      'window.addEventListener("beforeunload",e=>{if(recorder&&recorder.state==="recording"){e.preventDefault();e.returnValue="";}});'+
      '})();<\\/script></body></html>';
  }
  button.addEventListener("click",function(){panel.hidden=false;noteInput.focus();});
  startButton.addEventListener("click",async function(){
    var note=String(noteInput.value||"").replace(/\\s+/g," ").trim().slice(0,500);
    // Popup is opened by the explicit user click, not by navigation or polling.
    if(controller&&!controller.closed){controller.focus();panel.hidden=true;return;}
    controller=window.open("","bt38JourneyRecorderController","popup=yes,width=620,height=540");
    if(!controller){window.alert("Allow the BT38 recorder popup and try again.");return;}
    controller.document.open();controller.document.write(controllerHtml(note));controller.document.close();
    panel.hidden=true;
  });
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
    """Persist recorder evidence without touching the request's ORM transaction."""
    try:
        with db.engine.begin() as connection:
            connection.execute(
                SystemLog.__table__.insert().values(
                    log_type="system_recorder",
                    message=message,
                    details=json.dumps(details, ensure_ascii=False),
                    created_at=datetime.utcnow(),
                )
            )
    except Exception:
        # Recorder evidence must never change or replace the operational outcome.
        return

def install_governed_customer_behaviour_recorder(app):
    if getattr(app, "_bt38_customer_behaviour_recorder_installed", False):
        return
    app._bt38_customer_behaviour_recorder_installed = True

    @app.before_request
    def bt38_system_recorder_request_start():
        if request.path == _ENDPOINT or not _operational_path(request.path): return
        g._bt38_system_started = time.perf_counter()
        g._bt38_system_request_id = _safe_text(request.headers.get("X-Request-ID"), 100) or f"local-{time.time_ns()}"

    @app.after_request
    def bt38_system_recorder_request_finish(response):
        if request.path == _ENDPOINT or not _operational_path(request.path):
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
            "recorded_at": datetime.utcnow().isoformat() + "Z",
        }
        _record_system_event(f"Failed request {request.method} {request.path}", details)
        return response

    @got_request_exception.connect_via(app)
    def bt38_system_recorder_unhandled(sender, exception, **extra):
        # Observe Flask's exception signal only. The recorder does not own,
        # replace, retry or re-raise the application's exception path.
        if request.path == _ENDPOINT or not _operational_path(request.path):
            return
        details = {"event": "backend_error", "request_id": getattr(g, "_bt38_system_request_id", None), "method": request.method, "page": request.path, "error_type": type(exception).__name__, "recorded_at": datetime.utcnow().isoformat() + "Z"}
        _record_system_event(f"Backend error {request.method} {request.path}: {type(exception).__name__}", details)

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
        if not _operational_path(_safe_text(payload.get("page"), 300)):
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
        _record_system_event(f"Customer behaviour: {event}", details)
        return jsonify({"ok": True}), 202

    @app.after_request
    def bt38_customer_behaviour_script(response):
        if request.path == _ENDPOINT or request.method != "GET" or not _operational_path(request.path): return response
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type or response.direct_passthrough or response.headers.get("Content-Encoding"): return response
        body = response.get_data(as_text=True)
        if "bt38CustomerBehaviourRecorder" in body or "</body>" not in body: return response
        injected = _SCRIPT
        if current_user.is_authenticated:
            injected += "\n" + _VIDEO_CONTROL_SCRIPT
        body = body.replace("</body>", injected + "\n</body>", 1)
        response.set_data(body)
        response.headers.pop("Content-Length", None)
        return response
