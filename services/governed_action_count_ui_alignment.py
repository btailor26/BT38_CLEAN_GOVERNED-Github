"""Align visible BT38 action counters to the existing governed bell action count.

The authority-backed bell reader returns ``action_count`` from current persisted
FBM/order/shipment truth. Support can additionally expose a separate
``support_attention_count`` from the existing case authority. The red bell badge
shows the combined attention total, while the assistant remains tied only to the
marketplace ``action_count`` so support cases are never described as marketplace
actions.

This alignment adds no read, poll, timer, marketplace call, worker or write. It
only observes the response from the bell request the browser already performs.
"""
from __future__ import annotations

from flask import request

from services import governed_fbm_small_alignment as small_alignment


_SCRIPT = r'''
<script id="bt38GovernedActionCountUIAlignment">
(function(){
  'use strict';
  if(window.bt38GovernedActionCountUIAligned)return;
  window.bt38GovernedActionCountUIAligned=true;

  var currentCount=null;
  var currentSupportCount=0;
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

    var marketplaceValue=Math.max(0,Number(currentCount)||0);
    var supportValue=Math.max(0,Number(currentSupportCount)||0);
    var value=marketplaceValue+supportValue;
    var expected=value>99?'99+':String(value);
    applyingBadge=true;
    if(badge.textContent!==expected)badge.textContent=expected;
    badge.classList.toggle('d-none',value===0);
    if(bell){
      bell.classList.toggle('text-warning',value>0);
      bell.setAttribute('aria-label',value>0?'Open notifications - current attention waiting':'Open notifications');
    }
    applyingBadge=false;
  }

  function applyCurrentCounts(actionCount,supportCount){
    var value=Number(actionCount);
    if(!Number.isFinite(value))return;
    var supportValue=Number(supportCount);
    currentCount=Math.max(0,Math.trunc(value));
    currentSupportCount=Number.isFinite(supportValue)?Math.max(0,Math.trunc(supportValue)):0;
    applyBadgeCount();
    applyAssistantCount();
    window.dispatchEvent(new CustomEvent('bt38-governed-action-count',{detail:{count:currentCount,support_count:currentSupportCount,total_count:currentCount+currentSupportCount}}));
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
    document.addEventListener('DOMContentLoaded',function(){
      bindAssistantObserver();
      applyBadgeCount();
    },{once:true});
  }else{
    bindAssistantObserver();
  }
  window.addEventListener('load',bindAssistantObserver,{once:true});

  var previousFetch=window.fetch.bind(window);
  window.fetch=async function(input,init){
    var response=await previousFetch(input,init);
    if(isNotificationRead(input)){
      response.clone().json().then(function(payload){
        if(payload&&payload.success===true&&payload.action_count!==undefined){
          applyCurrentCounts(payload.action_count,payload.support_attention_count||0);
        }
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


def install_governed_action_count_ui_alignment() -> None:
    """Patch the final bell installer so the client alignment is registered at startup."""
    original_install = small_alignment._install_final_bell_alignment
    if getattr(original_install, "_bt38_action_count_ui_aligned", False):
        return

    def aligned_install(app) -> None:
        original_install(app)
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
            "BT38 bell badge aligned to marketplace action_count plus scoped support attention; "
            "assistant marketplace action wording remains separate"
        )

    aligned_install._bt38_action_count_ui_aligned = True
    small_alignment._install_final_bell_alignment = aligned_install


install_governed_action_count_ui_alignment()
