"""Align visible BT38 action counters and FBM lifecycle presentation.

The governed bell action count remains authority-backed. FBM lifecycle badges are
bound to the existing selected-history workflow snapshot when that legacy hook is
present. Browser-local FBM working-set lifecycle counts remain owner when the hook
has been retired. This adds no marketplace/provider read, polling, worker or write.
"""
from __future__ import annotations

from flask import request

from services import governed_fbm_small_alignment as small_alignment


_SCRIPT = r'''
<style id="bt38GovernedActionBadgeSpacing">
#bt38NotificationBell{position:relative;margin-right:.55rem}
#bt38NotificationBadge{right:-.2rem!important;top:-.25rem!important;transform:none!important;font-size:.62rem!important;min-width:1.15rem;padding:.22rem .32rem!important}
.navbar .ms-auto .rounded-circle:not(#bt38NotificationBadge){width:28px!important;height:28px!important;min-width:28px!important;font-size:.72rem!important}
</style>
<script id="bt38GovernedActionCountUIAlignment">
(function(){
  'use strict';
  if(window.bt38GovernedActionCountUIAligned)return;
  window.bt38GovernedActionCountUIAligned=true;

  var currentCount=null;
  var applyingBadge=false;
  var applyingAssistant=false;
  var badgeObserver=null;
  var assistantObserver=null;

  function asUrl(input){
    if(typeof input==='string')return input;
    if(input&&input.url)return String(input.url||'');
    return '';
  }

  function isNotificationRead(input){
    var url=asUrl(input);
    return url.indexOf('/governed/ui/notifications')>=0;
  }

  function normalAssistantMessage(count){
    if(count===0)return '☕ <strong>All done.</strong> I’ll keep watch.';
    if(count===1)return '💪 <strong>Nearly there.</strong> Just 1 action left.';
    if(count<=3)return '👍 <strong>Great progress.</strong> '+count+' actions left.';
    return '🤖 <strong>'+count+' actions to sort.</strong> I’ll help you through them.';
  }

  function assistantIsNormalCountMessage(node){
    var text=String(node&&node.textContent||'').trim();
    if(!text)return true;
    return /all done|nearly there|great progress|action left|actions left|actions to sort/i.test(text);
  }

  function applyAssistantCount(){
    if(currentCount===null||applyingAssistant)return;
    var bubble=document.getElementById('bt38AssistantBubble');
    if(!bubble||!assistantIsNormalCountMessage(bubble))return;
    var expected=normalAssistantMessage(currentCount);
    if(bubble.innerHTML===expected)return;
    applyingAssistant=true;
    bubble.innerHTML=expected;
    applyingAssistant=false;
  }

  function applyBadgeCount(){
    if(currentCount===null||applyingBadge)return;
    var badge=document.getElementById('bt38NotificationBadge');
    var bell=document.getElementById('bt38NotificationBell');
    if(!badge)return;
    var value=Math.max(0,Number(currentCount)||0);
    var expected=value>99?'99+':String(value);
    applyingBadge=true;
    if(badge.textContent!==expected)badge.textContent=expected;
    badge.classList.toggle('d-none',value===0);
    if(bell){
      bell.classList.toggle('text-warning',value>0);
      bell.setAttribute('aria-label',value>0?'Open notifications - current actions waiting':'Open notifications');
    }
    applyingBadge=false;
  }

  function applyCurrentCount(count){
    var value=Number(count);
    if(!Number.isFinite(value))return;
    currentCount=Math.max(0,Math.trunc(value));
    applyBadgeCount();
    applyAssistantCount();
    window.dispatchEvent(new CustomEvent('bt38-governed-action-count',{detail:{count:currentCount}}));
  }

  function bindBadgeObserver(){
    var badge=document.getElementById('bt38NotificationBadge');
    if(!badge||badgeObserver)return;
    badgeObserver=new MutationObserver(function(){applyBadgeCount();});
    badgeObserver.observe(badge,{attributes:true,childList:true,characterData:true,subtree:true});
  }

  function bindAssistantObserver(){
    var bubble=document.getElementById('bt38AssistantBubble');
    if(!bubble||assistantObserver)return;
    assistantObserver=new MutationObserver(function(){applyAssistantCount();});
    assistantObserver.observe(bubble,{childList:true,characterData:true,subtree:true});
    applyAssistantCount();
  }

  bindBadgeObserver();
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){bindAssistantObserver();applyBadgeCount();},{once:true});
  }else{bindAssistantObserver();}
  window.addEventListener('load',bindAssistantObserver,{once:true});

  var previousFetch=window.fetch.bind(window);
  window.fetch=async function(input,init){
    var response=await previousFetch(input,init);
    if(isNotificationRead(input)){
      response.clone().json().then(function(payload){
        if(payload&&payload.success===true&&payload.action_count!==undefined){applyCurrentCount(payload.action_count);}
      }).catch(function(){/* Existing notification error path remains owner. */});
    }
    return response;
  };
})();
</script>
'''


def _inject(html: str) -> str:
    value = str(html or "")
    if 'id="bt38GovernedActionCountUIAlignment"' in value:
        return value
    marker = "</body>"
    return value.replace(marker, _SCRIPT + marker, 1) if marker in value else value + _SCRIPT


def _align_fbm_lifecycle_counts() -> None:
    """Align the legacy server count hook only while that hook still exists."""
    from services import governed_fbm_dispatch_queue_alignment as dispatch_queue
    from services import governed_fbm_global_search_alignment as global_search

    current = getattr(dispatch_queue, "_selected_history_counts", None)
    if current is None:
        return
    if getattr(current, "_bt38_selected_snapshot_aligned", False):
        return

    def selected_history_counts() -> dict[str, int]:
        snapshot = global_search._persisted_workflow_snapshot()
        counts = snapshot.get("counts", {}) if isinstance(snapshot, dict) else {}
        return {
            name: int(counts.get(name, 0) or 0)
            for name in dispatch_queue._WORKFLOW_LABELS
        }

    selected_history_counts._bt38_selected_snapshot_aligned = True
    dispatch_queue._selected_history_counts = selected_history_counts


def install_governed_action_count_ui_alignment() -> None:
    """Patch final presentation only; preserve existing authorities and structure."""
    original_install = small_alignment._install_final_bell_alignment
    if getattr(original_install, "_bt38_action_count_ui_aligned", False):
        return

    def aligned_install(app) -> None:
        original_install(app)
        _align_fbm_lifecycle_counts()
        if getattr(app, "_bt38_action_count_ui_alignment_installed", False):
            return

        @app.after_request
        def bt38_action_count_ui_response(response):
            if (
                request.method == "GET"
                and response.status_code == 200
                and response.content_type
                and "text/html" in response.content_type
            ):
                response.set_data(_inject(response.get_data(as_text=True)))
            return response

        app._bt38_action_count_ui_alignment_installed = True
        app.logger.info(
            "BT38 visible action counters remain on governed bell action_count; retired FBM server lifecycle hook is optional; browser-local working-set counts remain owner; no extra marketplace read, polling or write"
        )

    aligned_install._bt38_action_count_ui_aligned = True
    small_alignment._install_final_bell_alignment = aligned_install


install_governed_action_count_ui_alignment()
