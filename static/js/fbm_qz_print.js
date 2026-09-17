/* FBM QZ Tray local printing bridge.
 * Printing is deliberately separate from postage purchase. A failed print
 * must never retry or duplicate a marketplace/provider shipment purchase.
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'bt38_fbm_qz_printer';
    const FBM_FETCH_TIMEOUT_MS = 15000;

    function installFbmFetchTimeout() {
        if (!global.fetch || global.fetch.__bt38FbmTimeoutWrapped) return;
        const nativeFetch = global.fetch.bind(global);
        const wrappedFetch = async function (input, init = {}) {
            const rawUrl = typeof input === 'string' ? input : String(input && input.url || '');
            let isFbmRequest = false;
            let isBulkShippingOptions = false;
            try {
                const parsed = new URL(rawUrl, global.location.href);
                isFbmRequest = parsed.origin === global.location.origin && (parsed.pathname.startsWith('/fbm/') || parsed.pathname.startsWith('/governed/fbm/'));
                if (parsed.pathname === '/fbm/shipping-options') {
                    isBulkShippingOptions = String(parsed.searchParams.get('order_ids') || '').split(',').map(v => v.trim()).filter(Boolean).length > 1;
                }
            } catch (_) {}
            if (!isFbmRequest || isBulkShippingOptions || init.signal) return nativeFetch(input, init);
            const controller = new AbortController();
            const timeoutId = global.setTimeout(() => controller.abort(), FBM_FETCH_TIMEOUT_MS);
            try {
                return await nativeFetch(input, {...init, signal: controller.signal});
            } catch (error) {
                if (error && error.name === 'AbortError') throw new Error('Shipping request timed out after 15 seconds. Please try again.');
                throw error;
            } finally { global.clearTimeout(timeoutId); }
        };
        wrappedFetch.__bt38FbmTimeoutWrapped = true;
        global.fetch = wrappedFetch;
    }
    installFbmFetchTimeout();

    function requireQz() {
        if (!global.qz) throw new Error('QZ Tray browser library is not loaded.');
        return global.qz;
    }
    async function connect() {
        const qz = requireQz();
        if (!qz.websocket.isActive()) await qz.websocket.connect({retries: 2, delay: 1});
        return true;
    }
    async function printers() {
        await connect();
        const found = await global.qz.printers.find();
        return Array.isArray(found) ? found : [found].filter(Boolean);
    }
    function savedPrinter() { try { return global.localStorage.getItem(STORAGE_KEY) || ''; } catch (_) { return ''; } }
    function savePrinter(name) {
        const value = String(name || '').trim();
        if (!value) throw new Error('Choose a printer first.');
        global.localStorage.setItem(STORAGE_KEY, value);
        return value;
    }
    async function resolvePrinter() {
        await connect();
        const saved = savedPrinter();
        if (saved) {
            const match = await global.qz.printers.find(saved);
            if (match) return Array.isArray(match) ? match[0] : match;
        }
        return global.qz.printers.getDefault();
    }
    function labelData(label) {
        const format = String(label && label.format || '').toUpperCase();
        const data = label && (label.data || label.base64 || label.url);
        if (!data) throw new Error('The purchased shipment has no printable label document.');
        if (format === 'ZPL' || format === 'ZPLII') return [{type:'raw', format:'command', flavor:label.base64?'base64':'plain', data}];
        if (format === 'PDF') return [{type:'pixel', format:'pdf', flavor:label.base64?'base64':'file', data}];
        if (format === 'PNG' || format === 'JPG' || format === 'JPEG') return [{type:'pixel', format:'image', flavor:label.base64?'base64':'file', data}];
        throw new Error('Unsupported label format: ' + (format || 'unknown'));
    }
    async function printLabel(label) {
        const printer = await resolvePrinter();
        if (!printer) throw new Error('No QZ printer is available.');
        const options = {};
        if (label && label.width && label.height) {
            options.units = label.units || 'in';
            options.size = {width:Number(label.width), height:Number(label.height)};
        }
        await global.qz.print(global.qz.configs.create(printer, options), labelData(label));
        return {printer, sent:true};
    }
    async function packlinkStatus(shipmentId) {
        const response = await global.fetch(`/fbm/shipments/${encodeURIComponent(shipmentId)}/packlink/status`, {method:'GET', credentials:'same-origin', cache:'no-store', headers:{'Accept':'application/json'}});
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success !== true) throw new Error(payload.message || `Packlink status check failed (HTTP ${response.status}).`);
        return payload;
    }
    function downloadBase64Label(label) {
        const raw = String(label && label.base64 || '');
        if (!raw) return false;
        const binary = global.atob(raw), bytes = new Uint8Array(binary.length);
        for (let i=0;i<binary.length;i+=1) bytes[i]=binary.charCodeAt(i);
        const format=String(label.format||'pdf').toLowerCase();
        const url=URL.createObjectURL(new Blob([bytes],{type:format==='pdf'?'application/pdf':'application/octet-stream'}));
        const a=document.createElement('a'); a.href=url; a.download=`BT38-Packlink-label.${format}`; a.click();
        global.setTimeout(()=>URL.revokeObjectURL(url),1000); return true;
    }
    function ensureRowLabelFallback(row,label) {
        if (!row || !label || !(label.url || label.base64 || label.data)) return;
        const cells=row.querySelectorAll('td[data-no-row-click="1"]'), cell=cells.length?cells[cells.length-1]:row.lastElementChild;
        if (!cell) return;
        let button=cell.querySelector('.packlink-row-label-download');
        if (!button) {
            button=document.createElement(label.url?'a':'button');
            button.className='btn btn-sm btn-outline-primary mt-1 packlink-row-label-download';
            button.textContent='Print / download label'; button.setAttribute('data-no-row-click','1'); cell.appendChild(button);
        }
        if (label.url) { button.href=label.url; button.target='_blank'; button.rel='noopener'; }
        else { button.type='button'; button.onclick=e=>{e.stopPropagation();downloadBase64Label(label);}; }
    }
    function selectedPacklinkShipments() {
        const selected=[],seen=new Set();
        document.querySelectorAll('.fbm-order-checkbox:checked').forEach(checkbox=>{
            const row=checkbox.closest('.fbm-order-row'), statusButton=row&&row.querySelector('.packlink-existing-status[data-shipment-id]');
            const shipmentId=statusButton&&String(statusButton.dataset.shipmentId||'').trim();
            if (!row||!shipmentId||seen.has(shipmentId)) return; seen.add(shipmentId); selected.push({shipmentId,row});
        });
        return selected;
    }
    function updateBulkPacklinkAction() {
        const button=document.getElementById('bulkPacklinkLabels'); if(!button)return;
        const count=selectedPacklinkShipments().length; button.disabled=count===0;
        button.textContent=count?`Get ${count} Packlink label${count===1?'':'s'}`:'Get Packlink labels';
    }
    async function consumePacklinkLabel(shipmentId,row) {
        const payload=await packlinkStatus(shipmentId), label=payload.label||null;
        if (!payload.label_ready || !label || !(label.url||label.base64||label.data)) return {ready:false,payload};
        const autoPrint=document.getElementById('qzAutoPrint');
        if (autoPrint && autoPrint.checked) {
            try { const printed=await printLabel(label); return {ready:true,printed:true,printer:printed.printer,payload,label}; }
            catch (error) { ensureRowLabelFallback(row,label); return {ready:true,printed:false,fallback:true,error,payload,label}; }
        }
        ensureRowLabelFallback(row,label); return {ready:true,printed:false,fallback:true,payload,label};
    }
    async function checkSelectedPacklinkLabels(button) {
        const rows=selectedPacklinkShipments(); if(!rows.length)return; button.disabled=true;
        let ready=0,printed=0,pending=0,fallback=0,failed=0;
        for(const item of rows){try{const result=await consumePacklinkLabel(item.shipmentId,item.row);if(!result.ready){pending+=1;continue;}ready+=1;if(result.printed)printed+=1;else fallback+=1;}catch(_){failed+=1;}}
        const status=document.getElementById('qzStatus'); if(status){status.className=failed?'small text-warning mt-2':'small text-success mt-2';status.textContent=`${ready} Packlink label${ready===1?'':'s'} ready · ${printed} printed · ${fallback} download fallback · ${pending} pending${failed?` · ${failed} check failed`:''}.`;}
        button.disabled=false; updateBulkPacklinkAction();
    }
    function installBulkPacklinkAction(){
        const ready=document.getElementById('readyToShipSelected'); if(!ready||document.getElementById('bulkPacklinkLabels'))return;
        const button=document.createElement('button');button.id='bulkPacklinkLabels';button.type='button';button.className='btn btn-sm btn-outline-success';button.textContent='Get Packlink labels';button.disabled=true;ready.parentNode.insertBefore(button,ready.nextSibling);
        button.addEventListener('click',e=>{e.stopPropagation();checkSelectedPacklinkLabels(button);});
        document.addEventListener('change',e=>{if(e.target&&(e.target.matches('.fbm-order-checkbox')||e.target.matches('#selectAllOrders')))global.setTimeout(updateBulkPacklinkAction,0);});updateBulkPacklinkAction();
    }
    function installExistingPacklinkPrintAction(){
        document.addEventListener('click',async event=>{
            const button=event.target&&event.target.closest?event.target.closest('.packlink-existing-status[data-shipment-id]'):null;
            if(!button)return;
            event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation();
            if(button.dataset.bt38LabelBusy==='1')return; button.dataset.bt38LabelBusy='1'; button.disabled=true;
            const original=button.textContent, row=button.closest('.fbm-order-row'), status=document.getElementById('qzStatus'); button.textContent='Getting label…';
            try{
                const result=await consumePacklinkLabel(button.dataset.shipmentId,row);
                if(!result.ready){button.textContent='Label pending';if(status){status.className='small text-warning mt-2';status.textContent='Packlink payment is not complete or the provider label is not ready yet.';}return;}
                button.textContent=result.printed?'Printed':'Print / download';
                if(status){status.className=result.printed?'small text-success mt-2':'small text-warning mt-2';status.textContent=result.printed?`Packlink label sent to ${result.printer}.`:`Packlink label is ready. QZ did not print it, so the safe download fallback is available on this order.${result.error?' '+result.error.message:''}`;}
            }catch(error){button.textContent='Check Packlink';if(status){status.className='small text-danger mt-2';status.textContent=error.message;}}
            finally{button.disabled=false;button.dataset.bt38LabelBusy='0';if(button.textContent==='Label pending')global.setTimeout(()=>{button.textContent=original;},2500);}
        },true);
    }
    function ensureDownloadFallback(root){
        const scope=root&&root.querySelectorAll?root:document,boxes=[];if(root&&root.matches&&root.matches('.rate-results'))boxes.push(root);scope.querySelectorAll('.rate-results').forEach(box=>boxes.push(box));
        boxes.forEach(box=>{if(!box.dataset||!box.dataset.label||box.querySelector('.label-download'))return;let label=null;try{label=JSON.parse(box.dataset.label);}catch(_){return;}if(!label||!(label.url||label.base64))return;const button=document.createElement('button');button.type='button';button.className='btn btn-sm btn-outline-primary label-download mt-2';button.textContent='Download label';box.appendChild(button);});
    }
    function alignPacklinkPaymentHandoff(root){
        const scope=root&&root.querySelectorAll?root:document,drafts=[],statuses=[];if(root&&root.matches&&root.matches('.packlink-draft'))drafts.push(root);if(root&&root.matches&&root.matches('.packlink-status'))statuses.push(root);scope.querySelectorAll('.packlink-draft').forEach(b=>drafts.push(b));scope.querySelectorAll('.packlink-status').forEach(b=>statuses.push(b));
        drafts.forEach(b=>{if(b.textContent!=='Prepare Packlink')b.textContent='Prepare Packlink';});statuses.forEach(b=>{if(b.textContent!=='Check payment / get label')b.textContent='Check payment / get label';});
    }
    function start(){ensureDownloadFallback(document);alignPacklinkPaymentHandoff(document);installBulkPacklinkAction();installExistingPacklinkPrintAction();}
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
    global.BT38FBMQZ={connect,printers,savedPrinter,savePrinter,resolvePrinter,printLabel,packlinkStatus,consumePacklinkLabel};
})(window);
