/* BSV1 V2.7: three isolated store maps; protected staging; payments never verified. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const yuan=c=>'¥'+(Number(c||0)/100).toFixed(2);
const chinaTime=iso=>iso?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(iso)):'—';
const chinaFull=iso=>iso?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(iso)):'—';
let allStores=[], data=null, activeVisitId=null, page='map', transfer=null;
let focusedSeat=null, modalConfirm=null, modalCancel=null, busy=false, toastTimer, serverOffset=0, ageBucket='';
let criticalAcknowledged=new Set(),historyRange='today',auditRange='today',auditCategory='ALL',syncFailures=0,systemHealth=null,historyOffset=0;
// 纯数据驱动：邻接规则来自当前门店的 SQLite 地图快照。
function neighborGraph(){return data?.layout?.neighbors||{};}
const STAGELABEL={PENDING:'待出品',SERVED:'已上桌',CANCELLED:'已撤销'};
function nowMs(){return Date.now()+serverOffset;}
function elapsed(iso){return iso?Math.max(0,Math.floor((nowMs()-Date.parse(iso))/1000)):0;}
function duration(sec){const m=Math.floor(sec/60),s=Math.floor(sec%60);return (m>=60?Math.floor(m/60)+'小时':'')+(m%60)+'分'+String(s).padStart(2,'0')+'秒';}
function severity(sec){const t=data?.severity_thresholds||{};return sec>=t.service_critical?'critical':sec>=t.service_late?'late':sec>=t.service_warn?'warning':'normal';}
function shortDuration(sec){const n=Math.max(0,Math.round(sec));return `${Math.floor(n/60)}分${String(n%60).padStart(2,'0')}秒`;}
function waitLabel(seconds){const t=data?.severity_thresholds||{};return seconds>=t.service_critical?'严重超时 '+shortDuration(seconds-t.service_critical):seconds>=t.service_late?'已超时 '+shortDuration(seconds-t.service_late)+' · 严重超时倒计时 '+shortDuration(t.service_critical-seconds):seconds>=t.service_warn?'距超时 '+shortDuration(t.service_late-seconds):'正常等待 '+shortDuration(seconds);}
function bathroomStage(b){const at=b.last_clean_at||b.monitor_started_at;const seconds=at?elapsed(at):0;
 if(!b.last_clean_at)return {sev:seconds>=b.interval_seconds+data.severity_thresholds.bathroom_critical_after?'critical':'late',text:'首次待清洁 · 已等待 '+shortDuration(seconds)};
 const rem=b.interval_seconds-seconds,crit=data.severity_thresholds.bathroom_critical_after;
 if(rem<=-crit)return {sev:'critical',text:'严重逾期 '+shortDuration(-rem-crit)};
 if(rem<=0)return {sev:'late',text:'逾期 '+shortDuration(-rem)+' · 距严重 '+shortDuration(crit+rem)};
 if(rem<=data.severity_thresholds.bathroom_warn_before)return {sev:'warning',text:'距应清洁 '+shortDuration(rem)};
 return {sev:'normal',text:'距下次清洁 '+shortDuration(rem)};}
function seatCleaningStage(seat){if(seat.cleaning_state!=='DIRTY')return {sev:'normal',text:''};
 const a=seat.dirty_at?elapsed(seat.dirty_at):0,t=data.severity_thresholds;
 if(a>=t.seat_critical)return {sev:'critical',text:'严重逾期 '+shortDuration(a-t.seat_critical)};
 if(a>=t.seat_late)return {sev:'late',text:'清桌超时 '+shortDuration(a-t.seat_late)+' · 距严重 '+shortDuration(t.seat_critical-a)};
 if(a>=t.seat_warning)return {sev:'warning',text:'距清桌超时 '+shortDuration(t.seat_late-a)};
 return {sev:'late-soft',text:'待清桌 · 剩 '+shortDuration(t.seat_late-a)};}
function chinaDay(offset=0){const d=new Date(Date.now()+offset*86400000);return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);}
function getRangeParams(scope){const value=scope==='audit'?auditRange:historyRange;let a='',b='';
 if(value==='today')a=b=chinaDay();
 else if(value==='yesterday')a=b=chinaDay(-1);
 else if(value==='week'){a=chinaDay(-6);b=chinaDay();}
 else if(value==='month'){a=chinaDay().slice(0,8)+'01';b=chinaDay();}
 else {a=$(scope+'From')?.value||'';b=$(scope+'To')?.value||'';}
 return new URLSearchParams({from:a,to:b}).toString();}
function validateHistoryFilter(){
 if(historyRange==='custom'){
   const from=$('historyFrom').value,to=$('historyTo').value;
   if(!from||!to)throw new Error('请选择完整的开始和结束日期');
   if(from>to)throw new Error('结束日期不得早于开始日期');
 }
}
function taskSeverityClass(s){return s==='critical'?'critical':s==='warning'?'warning':s==='late'?'late':s==='late-soft'?'late-soft':'normal';}
function healthTone(status){return status==='正常'?'ok':status==='警告'?'warn':'error';}
function healthSummaryText(h){if(!h)return '本地系统：未检查';if(h.status!=='正常')return '本地系统：'+(h.status||'未检查');return Number(h.approved_quote_count||0)<1?'系统正常 · AJ售价待补齐':'本地系统：正常';}
function renderSystemHealth(){
 const login=$('loginSystemStatus'),badge=$('systemCheckBadge');
 if(login){login.className='login-system-status '+(systemHealth&&systemHealth.status==='正常'&&Number(systemHealth.approved_quote_count||0)<1?'warn':systemHealth?healthTone(systemHealth.status):'warn');login.innerHTML=systemHealth?`<strong>系统自检：${esc(systemHealth.status)}</strong><span>数据库：${systemHealth.db_exists?'已找到':'缺失'}；V9 Excel：${systemHealth.excel_exists?'已找到':'缺失'}；V9同步：${systemHealth.catalog_sync?.imported_at?chinaFull(systemHealth.catalog_sync.imported_at):'未同步'}</span><span>${Number(systemHealth.approved_quote_count||0)<1?'AJ售价无效，暂不可形成有效金额订单':'请按本店销售权限操作'}；真实支付尚未连接。</span>`:'<strong>系统自检</strong><span>尚未完成检查</span>';}
 if(badge){badge.className='system-pill '+(systemHealth&&systemHealth.status==='正常'&&Number(systemHealth.approved_quote_count||0)<1?'warn':systemHealth?healthTone(systemHealth.status):'warn');badge.textContent=healthSummaryText(systemHealth);}
}
async function loadHealth(silent=false){
 try{systemHealth=await getJson('/api/health');renderSystemHealth();return systemHealth;}
 catch(e){systemHealth={status:'异常',message:e.message,checks:[]};renderSystemHealth();if(!silent)flash('系统自检失败：'+e.message,true);return systemHealth;}
}
function openHealthDialog(){
 const h=systemHealth||{status:'未检查',checks:[]};
 const rows=(h.checks||[]).map(x=>`<div class="health-item"><div><b>${esc(x.label)}</b><small>${esc(x.detail||'')}</small></div><span class="health-tag ${x.ok?'ok':'error'}">${x.ok?'正常':'异常'}</span></div>`).join('');
 dialog({eyebrow:'系统自检 · 当前工作台',title:'当前系统状态：'+(h.status||'未检查'),body:`<div class="health-list">${rows||'<div class="health-item"><div><b>暂无数据</b><small>请先执行系统自检</small></div><span class="health-tag warn">待检查</span></div>'}</div><p class="modal-caption">数据库：${esc(h.db_path||'—')}<br/>V9 Excel：${esc(h.excel_path||'—')}</p>`,confirmText:'重新自检',cancelText:'关闭',onConfirm:async()=>{await loadHealth();flash({title:'自检已更新',subject:healthSummaryText(systemHealth),detail:'收款机构未接入；结账登记不能作为到账凭证'});}});
}

function flash(msg,error=false,critical=false){
 const el=$('toast');el.replaceChildren();
 if(typeof msg==='object' && msg){
   const h=document.createElement('strong');h.className='toast-action';h.textContent=msg.title||'操作已记录';el.appendChild(h);
   if(msg.subject){const p=document.createElement('div');p.className='toast-subject';p.textContent=msg.subject;el.appendChild(p);}
   if(msg.amount!==undefined){const p=document.createElement('div');p.className='toast-amount';p.textContent=msg.amount;el.appendChild(p);}
   if(msg.detail){const p=document.createElement('div');p.className='toast-detail';p.textContent=msg.detail;el.appendChild(p);}
 }else{el.textContent=msg;}
 el.className='toast'+(error?' error':'')+(critical?' critical':'');clearTimeout(toastTimer);
 if(!critical){const chars=typeof msg==='object'?([msg.title,msg.subject,msg.amount,msg.detail].filter(Boolean).join(' ').length):String(msg).length;
 const ms=error?Math.min(7000,4700+Math.max(0,chars-40)*38):Math.min(6500,3500+Math.max(0,chars-38)*35);
 toastTimer=setTimeout(()=>el.classList.add('hidden'),ms);}
}
function isActiveCritical(e){
 if(!data)return false;
 if(e.category==='SERVICE')return data.visits.some(v=>v.lines.some(l=>l.id===e.entity_id && l.status==='PENDING' && l.created_at===e.cycle_key));
 if(e.category==='SEAT'){const seat=getSeat(e.entity_id);return seat?.cleaning_state==='DIRTY'&&seat.dirty_at===e.cycle_key;}
 if(e.category==='BATHROOM'){const b=data.bathrooms.find(x=>x.id===e.entity_id);return b&&(b.last_clean_at||b.monitor_started_at)===e.cycle_key;}
 return false;
}
function showPendingCritical(){const newest=(data?.alert_escalations||[]).find(e=>isActiveCritical(e)&&!criticalAcknowledged.has(e.id));
 if(newest&&$('criticalOverlay').classList.contains('hidden')&&$('modal').classList.contains('hidden'))displayCritical(newest);
}
function displayCritical(incident){if(!incident||criticalAcknowledged.has(incident.id))return;
 const title=incident.category==='SERVICE'?'出品严重超时':incident.category==='SEAT'?'桌位清洁严重超时':'卫生间清洁严重超时';
 $('criticalTitle').textContent=title;
 $('criticalDetail').textContent=incident.category==='SERVICE'?('立即处理 '+seatName(incident.detail.seat_id)+' 的待出品项目'):
 incident.category==='SEAT'?('立即清洁 '+seatName(incident.detail.seat_id)):('立即清洁 '+(incident.detail.label||'卫生间'));
 $('criticalOverlay').classList.remove('hidden');
 $('criticalGo').onclick=()=>{criticalAcknowledged.add(incident.id);$('criticalOverlay').classList.add('hidden');setPage(incident.category==='SERVICE'?'queue':'clean');};
}

function getSeat(id){return data?.seats.find(s=>s.id===id);}
function getVisit(id){return data?.visits.find(v=>v.id===id);}
function visitAt(seatId){return data?.visits.find(v=>v.seat_id===seatId);}
function seatName(id){return getSeat(id)?.label||id;}
function productionTask(lineId){return (data?.production_tasks||[]).find(t=>t.line_id===lineId);}
function myTask(t){return t && t.assigned_staff_id===data?.staff?.id;}
function lockedSeat(seatId){return (data?.seat_edit_locks||[]).find(l=>l.seat_id===seatId && l.staff_id!==data.staff.id);}
async function heartbeat(){if(!data||busy)return;try{await send('/api/presence/heartbeat',{seat_id:activeVisitId?getVisit(activeVisitId)?.seat_id:null});await getState();render();}catch(e){if(!String(e.message).includes('正在处理另一项操作'))console.warn('presence heartbeat failed',e.message);}}
async function releaseSeat(seatId){if(!seatId||!data)return;try{await send('/api/seats/release-edit',{seat_id:seatId});}catch(e){console.warn('release seat',e.message);}}
function pinyinMatch(p,query){const q=query.trim().toLowerCase();if(!q)return true;return String(p.initials||'').toLowerCase().startsWith(q)||[p.name,p.id,p.series,p.readable_sku].some(v=>String(v||'').toLowerCase().includes(q));}
function allPending(){return (data?.visits||[]).flatMap(v=>v.lines.filter(l=>l.status==='PENDING').map(l=>({...l,visit_id:v.id,seat_id:v.seat_id,guests:v.guests}))).sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at));}
async function getJson(path){
 let r;try{r=await fetch(path,{credentials:'same-origin',cache:'no-store'});}catch{throw new Error('服务器暂时无法连接，请检查后台服务并刷新页面');}
 let j;try{j=await r.json();}catch{throw new Error('服务器返回数据异常，请检查后端程序日志');}
 if(!r.ok){if(r.status===401)showLogin();throw new Error(j.error||'读取失败');}return j;
}
async function getState(){const s=await getJson('/api/state');serverOffset=s.server_time_ms-Date.now();data=s;return s;}
async function send(path,params={}){if(busy)throw new Error('当前正在处理另一项操作');busy=true;
 try{const id=globalThis.crypto?.randomUUID?.()||('bsv-'+Date.now()+'-'+Math.random().toString(36).slice(2));
 const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-BSV-CSRF':data?.csrf||''},body:JSON.stringify({...params,_action_id:id})});
 const j=await r.json();if(!r.ok){if(r.status===401)showLogin();throw new Error(j.error||'操作失败');}return j;
 }finally{busy=false;}}
async function refresh(preserve=false){if(preserve && ['memberLast4'].includes(document.activeElement?.id))return;
 const oldScroll=document.querySelector('#orderPanel .order-content')?.scrollTop||0;
 const quickBefore=$('quickProductSearch'),searchText=quickBefore?.value||'',searchFocused=document.activeElement===quickBefore;
 await getState();if(activeVisitId&&!getVisit(activeVisitId))activeVisitId=null;render();
 const newContent=document.querySelector('#orderPanel .order-content');if(newContent)newContent.scrollTop=oldScroll;
 const quickAfter=$('quickProductSearch');if(quickAfter&&searchText){quickAfter.value=searchText;quickAfter.dispatchEvent(new Event('input'));if(searchFocused)quickAfter.focus();}
 showPendingCritical();
}
function safe(fn){return async(...args)=>{try{await fn(...args);}catch(e){flash(e.message,true);}};}
function showLogin(){if(guideShown())guideClose();document.documentElement.classList.remove('bsv-logged-in');data=null;activeVisitId=null;focusedSeat=null;transfer=null;$('appPage').classList.add('hidden');$('loginPage').classList.remove('hidden');}
function showApp(){$('loginPage').classList.add('hidden');$('appPage').classList.remove('hidden');document.documentElement.classList.add('bsv-logged-in');}
function closeDialog(){ $('modal').classList.add('hidden');$('seatOuterNav').classList.add('hidden');modalConfirm=null;modalCancel=null; }
function dialog({eyebrow='BSV1 · 请确认',title='请确认',body='',confirmText='确认',cancelText='返回',danger=false,onConfirm,onCancel}){
 clearTimeout(toastTimer);$('toast').classList.add('hidden');
 $('modalEyebrow').textContent=eyebrow;$('modalTitle').textContent=title;$('modalBody').innerHTML=body;
 $('modalConfirm').textContent=confirmText;$('modalCancel').textContent=cancelText;
 $('modalConfirm').className=danger?'danger-button':'primary';modalConfirm=onConfirm;modalCancel=onCancel;
 $('modal').classList.remove('hidden');$('modalConfirm').focus();
}
$('modalConfirm').addEventListener('click',async()=>{if(busy)return;const fn=modalConfirm;try{if(fn)await fn();closeDialog();showPendingCritical();}catch(e){flash(e.message,true);try{if(data)await refresh();}catch{}}});
$('modalCancel').addEventListener('click',()=>{const fn=modalCancel;closeDialog();if(fn)fn();});
function wireLocation(){const ds=[...new Set(allStores.map(x=>x.district))];$('loginDistrict').innerHTML='<option value="">请选择地区</option>'+ds.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');}
function storesForDistrict(d){return allStores.filter(s=>s.district===d);}
$('loginDistrict').addEventListener('change',()=>{const v=$('loginDistrict').value;const s=storesForDistrict(v);
 $('loginStore').disabled=!v;$('loginStore').innerHTML='<option value="">请选择具体门店</option>'+s.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}（${esc(x.business_type)}）</option>`).join('');$('loginStorePreview').textContent=v?'请进一步选择具体门店':'尚未选择门店';});
$('loginStore').addEventListener('change',()=>{const s=allStores.find(x=>x.id===$('loginStore').value);
 $('loginStorePreview').innerHTML=s?`<strong>${esc(s.district)} · ${esc(s.name)}</strong><span>${esc(s.business_type)} · ${esc(s.id)} · ${s.layout_ready?'已有座位图':'图纸待导入'}</span>`:'尚未选择门店';});
$('loginForm').addEventListener('submit',e=>{e.preventDefault();const s=allStores.find(x=>x.id===$('loginStore').value),code=$('staffCode').value.trim(),pin=$('staffPin').value;
 if(!s||s.district!==$('loginDistrict').value){$('loginError').textContent='请先完整选择地区和具体门店';return;}
 if(!code||!pin){$('loginError').textContent='请输入员工代码和PIN';return;}
 dialog({eyebrow:'防误登录 · 二次核对',title:'你确认正在这家店工作吗？',
 body:`<div class="confirm-store"><span>北京市 · ${esc(s.district.replace('北京市',''))}</span><strong>${esc(s.name)}</strong><span>${esc(s.business_type)} · ${esc(s.id)}</span></div><p class="modal-caption">登录后本会话只允许访问这一家门店。若选错，请返回修改，不能跨店操作。</p>`,
 confirmText:'确认门店，登录',cancelText:'返回修改',onConfirm:async()=>{
 const r=await fetch('/api/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({store_id:s.id,confirmed_store_id:s.id,staff_code:code,pin})});const j=await r.json();
 if(!r.ok)throw new Error(j.error||'登录失败');$('staffPin').value='';await getState();showApp();render();flash('已核验门店：'+s.name);
 }});
});
function renderCatalogSummary(){
 const items=data?.catalog_items||[],sync=data?.catalog_sync;
 const countC=items.filter(x=>x.domain==='C').length,countK=items.filter(x=>x.domain==='K').length,ready=items.filter(x=>x.sale_enabled).length;
 $('catalogSummary').innerHTML=`<span>现场成品 <b>${countC}</b></span><span>套餐资料 <b>${countK}</b></span><span>AJ可下单 <b class="${ready?'ready':'not-ready'}">${ready}</b></span><span>来源校验 <b>${sync?'V9已同步':'尚未导入'}</b></span>`;
}
function renderCatalogList(){if(!data)return;
 const term=($('catalogSearch').value||'').trim().toLowerCase(),kind=$('catalogDomain').value;
 const rows=(data.catalog_items||[]).filter(p=>(kind==='ALL'||kind==='READY'&&p.sale_enabled||kind===p.domain)&&
    pinyinMatch(p,term));
 const list=$('catalogList');
 list.innerHTML=rows.length?rows.map(p=>`<button type="button" class="catalog-item" data-cid="${esc(p.id)}">
   <span class="catalog-item-main"><b>${esc(p.name)}</b><small>${esc(p.id)} · ${esc(p.series|| (p.domain==='K'?'套餐':'现场成品'))}${p.readable_sku?' · 分类码 '+esc(p.readable_sku):''}</small></span>
   <span class="catalog-item-status ${p.sale_enabled?'ready':'pending'}">${p.sale_enabled?yuan(p.price_cents)+' · AJ统一价':p.domain==='C'?'AJ待定价':'套餐定价待配置'}</span></button>`).join(''):'<div class="catalog-empty">没有符合条件的商品</div>';
 list.querySelectorAll('[data-cid]').forEach(b=>b.onclick=()=>showCatalogItem(b.dataset.cid));
}
async function showCatalogItem(id){
 try{const r=await getJson('/api/catalog/item?id='+encodeURIComponent(id));const f=r.fields||{};
 const sections=[['商品身份','商品名称','销售系列','英文名称','套餐名称','套餐包含内容'],
 ['制作资料','配方文字','完整制作步骤','寻酒指引','杯具','制作时长（秒）','过敏原'],
 ['发布审核','内容审核状态','上架状态','审批状态','业务审批状态','销售状态']];
 const html=sections.map(section=>{const fields=section.slice(1).filter(k=>f[k]!==undefined&&f[k]!==null&&String(f[k]).trim());
 return fields.length?`<section class="catalog-detail-section"><h3>${esc(section[0])}</h3>${fields.map(k=>`<div class="catalog-detail-row"><b>${esc(k)}</b><p>${esc(String(f[k]))}</p></div>`).join('')}</section>`:'';}).join('');
 const rawFields=Object.entries(f).filter(([k,v])=>v!==undefined&&v!==null&&String(v).trim())
  .map(([k,v])=>`<div class="catalog-detail-row"><b>${esc(k)}</b><p>${esc(String(v))}</p></div>`).join('');
 $('catalogDetailBody').innerHTML=`<p class="eyebrow">BSV ALL · ${esc(id)} · 资料只读</p><h2>${esc(r.name)}</h2><div class="catalog-detail-state">${r.sale_enabled?'集团统一售价 · C表AJ列':r.id.startsWith('C')?'AJ未标价，请在Excel补齐':'套餐价格未配置'}</div>${html||'<p>该商品暂无详细资料。</p>'}
 <details class="catalog-all-fields"><summary>查看全部原始业务字段（${Object.keys(f).length}列）</summary>${rawFields}</details>
 <p class="small-muted">制作资料来自 V9，商品过敏原等字段如未核实，请务必人工查验；支付尚未接入。</p>
 <p class="small-muted">商品标价仅以 V9 Excel「C_现场成品」AJ列为准。所有门店使用相同价格；缺价请在原Excel补齐后执行同步。</p>`;
 $('catalogDetailModal').classList.remove('hidden');}catch(e){flash(e.message,true);}
}
function render(){if(!data)return;
 $('storeIdentity').textContent=data.store.district.replace('北京市','北京')+' · '+data.store.name;
 $('staffIdentity').textContent=data.staff.code+' · '+data.store.id;
 $('workEyebrow').textContent='BSV1 · '+data.store.id+' · '+data.store.district;
 $('storeSubhead').textContent=data.store.business_type+' · 本会话仅属于 '+data.store.name;
 const visits=data.visits, pending=allPending(),dirty=data.seats.filter(x=>x.cleaning_state==='DIRTY' && x.enabled);
 $('statSeats').innerHTML=`${visits.length}<span> / ${data.seats.filter(x=>x.enabled).length} 可用位置</span>`;
 const maximum=data.store.design_max_guests;
 $('statGuests').innerHTML=`${visits.reduce((n,v)=>n+v.guests,0)}<span> ${maximum?'/ '+maximum+' 图纸设计上限':'/ 上限未导入'}</span>`;
 $('statVisits').textContent=pending.length+' 待出品';
 $('queueBadge').textContent=pending.length?pending.length:'';
 const overdueBathroom=data.bathrooms.filter(b=>!b.last_clean_at||elapsed(b.last_clean_at)>=b.interval_seconds);
 $('cleanBadge').textContent=dirty.length+overdueBathroom.length||'';
 renderAlerts(pending,dirty,overdueBathroom);renderFloor();renderTransferBanner();renderGroups();renderOrderPanel();renderVisits();renderQueue();renderCleaning();renderAudit();renderCatalogSummary();renderSystemHealth();
 for(const b of document.querySelectorAll('.nav-button'))b.classList.toggle('active',b.dataset.page===page);
 $('pageMap').classList.remove('hidden');
 for(const k of ['Catalog','Orders','Queue','Clean','History','Audit'])$('page'+k).classList.toggle('hidden',page!==k.toLowerCase());
 $('detailSheet').classList.toggle('hidden',page==='map');
 $('detailHeading').textContent=({catalog:'统一商品资料库',orders:'进行中桌次',queue:'全店待出品队列',clean:'清洁与复位',history:'历史结账记录',audit:'员工操作记录'})[page]||'';
 $('pageTitle').textContent='座位点单 · '+data.store.name;
}
function renderAlerts(pending,dirty,overdue){const el=$('alertStrip');let bits=[];
 const latePending=pending.filter(x=>['late','critical'].includes(severity(elapsed(x.created_at))));
 if(latePending.length)bits.push('<button class="alert-pill danger" data-goto="queue">请立即制作并送达 '+esc(seatName(latePending[0].seat_id))+' 的待出品商品'+(latePending.length>1?' 等'+latePending.length+'项':'')+'</button>');
 if(overdue.length)bits.push('<button class="alert-pill danger" data-goto="clean">卫生间需清洁 · '+overdue.length+'</button>');
 if(dirty.length)bits.push('<button class="alert-pill danger" data-goto="clean">请清理 '+dirty.slice(0,2).map(x=>esc(x.label)).join('、')+(dirty.length>2?' 等'+dirty.length+'处':'')+'</button>');
 for(const v of data.visits.filter(v=>v.drafts.length))bits.push('<button class="alert-pill draft-warning" data-seat="'+esc(v.seat_id)+'">？ '+esc(seatName(v.seat_id))+' 有 '+v.drafts.length+' 项待下单商品</button>');
 const activeCr=(data.alert_escalations||[]).filter(isActiveCritical);
 if(activeCr.length){const x=activeCr[0];const loc=x.category==='BATHROOM'?(x.detail.label||'卫生间'):seatName(x.detail.seat_id);
 const verb=x.category==='SERVICE'?'立即制作并送达':'立即清洁';
 bits.unshift('<button class="alert-pill critical" data-goto="'+(x.category==='SERVICE'?'queue':'clean')+'">严重超时 · '+verb+' '+esc(loc)+(activeCr.length>1?'（共'+activeCr.length+'项）':'')+'</button>');}
 if(!bits.length)bits.push('<span class="quiet-alert">暂无需要立即处理的任务</span>');
 el.innerHTML=bits.join('');el.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>setPage(b.dataset.goto));
 el.querySelectorAll('[data-seat]').forEach(b=>b.onclick=()=>{setPage('map');clickSeat(b.dataset.seat);});
}
function seatNavigation(){const active=getSeat(focusedSeat);if(!active)return {prev:null,next:null};
 const graph=neighborGraph(),cfg=graph[active.id]||{};
 const ok=id=>id && getSeat(id)?.enabled?getSeat(id):null;
 // Explicit position graph: bartender viewpoint, never derive from SVG coordinates or alphabetical order.
 let prev=ok(cfg.left),next=ok(cfg.right);
 if(!prev && cfg.left){const nested=graph[cfg.left];prev=ok(nested?.left);}
 if(!next && cfg.right){const nested=graph[cfg.right];next=ok(nested?.right);}
 return {prev,next};}
function renderSeatNav(){const el=$('seatNavigator');const s=getSeat(focusedSeat);
 if(!s||!s.enabled){el.innerHTML='<span class="small-muted">点选座位后，这里出现大号座位编号及左右切换键</span>';return;}
 const n=seatNavigation();el.innerHTML=`<div class="nav-seat-info"><span>当前指向</span><strong>${esc(s.label)}</strong><small>${visitAt(s.id)?'正在使用':s.cleaning_state==='DIRTY'?'需要清桌':'可点单'}</small></div>
 <button id="navPrev" class="outline nav-seat-btn">← ${esc(n.prev?.label||'上一位')}</button>
 <button id="navSelect" class="primary nav-seat-btn">确认选择 ${esc(s.label)}</button>
 <button id="navNext" class="outline nav-seat-btn">${esc(n.next?.label||'下一位')} →</button>`;
 $('navPrev').disabled=!n.prev;$('navNext').disabled=!n.next;
 $('navPrev').onclick=()=>n.prev&&selectFocused(n.prev.id);$('navNext').onclick=()=>n.next&&selectFocused(n.next.id);$('navSelect').onclick=()=>clickSeat(focusedSeat);
}
function selectFocused(id){focusedSeat=id;renderSeats();renderSeatNav();}
function renderFloor(){if($('hqEntry'))$('hqEntry').style.display=(data?.staff?.can_manage_hq?'inline-block':'none');const allowed=Boolean(data.store.layout_ready),floor=$('floorStage');
 floor.classList.toggle('hidden',!allowed);$('groupControls').classList.toggle('hidden',!allowed);
 const scroll=floor.parentElement;let p=$('layoutPlaceholder');if(!p){p=document.createElement('div');p.id='layoutPlaceholder';p.className='layout-placeholder';scroll.appendChild(p);}
 p.classList.toggle('hidden',allowed);p.innerHTML=allowed?'':`<strong>${esc(data.store.name)} · 本店座位图待导入</strong><p>门店档案已建立，座位管理暂不可用。</p><p>禁止跨店点单。后续上传本店图纸并校验座位代码后才开放使用。</p>`;
 $('seatNavigator').classList.toggle('hidden',!allowed);$('bathroomLayer').classList.toggle('hidden',!allowed || !data.bathrooms.length);
 if(allowed){
   const artKey=data.store.id+':'+(data.layout?.version||0),current=floor.querySelector('.floor-svg');
   if(floor.dataset.drawnFor!==artKey){
     const img=document.createElement('img');img.className='floor-svg';img.alt=data.store.name+'的门店平面图';
     // 浏览器只请求当前登录门店的 SVG，服务器会验证会话和门店权限。
     img.src=data.layout?.background_url||'';
     img.addEventListener('error',()=>{
       // Never show a stale floorplan from another store after an image load failure.
       img.alt='本店底图加载失败，请刷新页面或联系管理员';
       img.classList.add('floor-art-error');
     },{once:true});
     current.replaceWith(img);floor.dataset.drawnFor=artKey;
   }
   renderSeats();renderSeatNav();
 }else{$('seatLayer').replaceChildren();}
}
function renderSeats(){const layer=$('seatLayer');layer.replaceChildren();
 for(const seat of data.seats){const v=visitAt(seat.id),wait=v?.lines.filter(l=>l.status==='PENDING').map(l=>severity(elapsed(l.created_at)))||[];
 const urgent=wait.includes('critical')?'critical':wait.includes('late')?'late':wait.includes('warning')?'warning':'';
 const clean=seatCleaningStage(seat);
 const btn=document.createElement('button');btn.type='button';btn.dataset.seat=seat.id;btn.style.left=seat.x+'%';btn.style.top=seat.y+'%';
 btn.className='seat-button'+(lockedSeat(seat.id)?' is-being-edited':'')+(v?' is-occupied':'')+(v?.drafts?.length?' has-draft':'')+(seat.cleaning_state==='DIRTY'?' is-dirty':'')+
 (!seat.enabled?' is-blocked':'')+(focusedSeat===seat.id?' is-focused':'')+(activeVisitId===v?.id?' is-selected':'')+
 (urgent?' has-'+urgent:'')+(seat.cleaning_state==='DIRTY'?' cleaning-'+taskSeverityClass(clean.sev):'')+(transfer?.from===seat.id?' origin':'')+(transfer?.to===seat.id?' target':'');
 btn.innerHTML=esc(seat.label)+`<small>${lockedSeat(seat.id)?'他人点单中':!seat.enabled?'合桌停用':v?.drafts?.length?'？ '+v.drafts.length+'项待下单':v?wait.length?wait.length+'项待出品':v.guests+'人在店':seat.cleaning_state==='DIRTY'?esc(clean.text):seat.seat_capacity?seat.seat_capacity+'人位':'空闲'}</small>`;
 btn.setAttribute('aria-label',seat.label+' '+(v?'正在使用':seat.cleaning_state==='DIRTY'?'待清桌':'空闲'));
 btn.onclick=()=>{focusedSeat=seat.id;if(transfer){handleTransferSeat(seat.id);}else{renderSeats();renderSeatNav();clickSeat(seat.id);}};
 layer.appendChild(btn);
 }
 const path=$('transferPath');path.replaceChildren();
 if(transfer?.from&&transfer?.to){const a=getSeat(transfer.from),b=getSeat(transfer.to);
 if(a&&b){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('class','transfer-vector');svg.setAttribute('viewBox','0 0 1100 580');
 const l=document.createElementNS('http://www.w3.org/2000/svg','line');l.setAttribute('x1',String(a.x*11));l.setAttribute('y1',String(a.y*5.8));l.setAttribute('x2',String(b.x*11));l.setAttribute('y2',String(b.y*5.8));svg.appendChild(l);path.appendChild(svg);}}
 // 多个卫生间分别按本店配置定位和计时，禁止使用全局写死坐标。
 const bathLayer=$('bathroomLayer');bathLayer.replaceChildren();
 for(const bath of data.bathrooms){const pos=data.layout?.bathroom_pins?.[bath.id];if(!pos)continue;
   const st=bathroomStage(bath),pin=document.createElement('button');pin.type='button';pin.className='bathroom-pin '+taskSeverityClass(st.sev);
   pin.style.left=pos.x+'%';pin.style.top=pos.y+'%';pin.innerHTML='<strong>'+esc(bath.label)+'</strong><small>'+esc(st.text)+'</small>';
   pin.onclick=()=>setPage('clean');bathLayer.appendChild(pin);}
}
function clickSeat(id){const seat=getSeat(id);const editing=lockedSeat(id);if(editing){flash({title:'该桌正在点单中',subject:seat.label+' · '+editing.staff_code,detail:'请等对方完成或等待90秒锁超时'},true);return;}if(!seat?.enabled){flash('当前座位不可独立使用',true);return;}
 if(seat.cleaning_state==='DIRTY'&&!visitAt(id)){confirmSeatClean(seat);return;}
 focusedSeat=id;renderSeats();renderSeatNav();
 const s=seat,v=visitAt(id),n=seatNavigation();
 dialog({eyebrow:v?'座位确认 · 继续管理':'座位确认 · 新客入座',title:s.label,
  body:`<div class="modal-action-heading">请确认客人所在位置</div><div class="modal-caption">${v?'此座位有客人在店 · 进入后继续管理该桌订单':'此座位当前空闲 · 确认后建立新桌次'}</div>`,
  confirmText:v?'继续管理 '+s.label:'确认 '+s.label+'，开始点单',onConfirm:async()=>{
    if(s.cleaning_state==='DIRTY'&&!v)throw new Error('请先清桌');
    const lock=await send('/api/seats/claim-edit',{seat_id:s.id});if(!lock.ok)throw new Error('该桌正在由 '+lock.editor+' 点单，请勿重复下单');
    const prior=activeVisitId?getVisit(activeVisitId)?.seat_id:null;if(prior&&prior!==s.id)await releaseSeat(prior);
    const r=await send('/api/seats/open',{seat_id:s.id});activeVisitId=r.visit_id;page='map';await refresh();
    flash({title:r.new?'已安排客人到 '+s.label:'已回到 '+s.label,subject:r.new?'请为 '+s.label+' 开始点单':'继续管理 '+s.label+'，处理本桌订单'});}});
 const side=$('seatOuterNav');side.classList.remove('hidden');
 $('modalOuterLeft').innerHTML=n.prev?'←<span>向左调至</span><strong>'+esc(n.prev.label)+'</strong>':'←<span>左侧无可选座位</span>';
 $('modalOuterRight').innerHTML=n.next?'<span>向右调至</span><strong>'+esc(n.next.label)+'</strong>→':'<span>右侧无可选座位</span>→';
 $('modalOuterLeft').disabled=!n.prev;$('modalOuterRight').disabled=!n.next;
 $('modalOuterLeft').onclick=()=>{if(n.prev){closeDialog();selectFocused(n.prev.id);clickSeat(n.prev.id);}};
 $('modalOuterRight').onclick=()=>{if(n.next){closeDialog();selectFocused(n.next.id);clickSeat(n.next.id);}};
}
function renderGroups(){const box=$('groupControls');let s='<span class="group-label">组合桌状态 · 以现场摆放为准</span>';
 for(const g of data.groups){const nm=seatName(g.primary_seat);if(data.staff.role==='MANAGER')s+=`<button data-group="${esc(g.id)}" class="group-btn">${esc(nm)}：${g.mode==='SPLIT'?'分桌 · 合桌':'合桌 · 分桌'}</button>`;
 else s+=`<span class="group-readonly">${esc(nm)}：${g.mode==='SPLIT'?'分桌':'合桌'}</span>`;}
 box.innerHTML=s;box.querySelectorAll('[data-group]').forEach(b=>b.onclick=()=>toggleGroup(b.dataset.group));}
function toggleGroup(id){const g=data.groups.find(x=>x.id===id);if(!g)return;const to=g.mode==='SPLIT'?'MERGED':'SPLIT';
 dialog({title:'调整现场合桌 / 分桌',body:`确认将 ${esc(seatName(g.primary_seat))} 和 ${esc(seatName(g.secondary_seat))} 切换为 <strong>${to==='MERGED'?'合桌':'分桌'}</strong>？<p>两处不能有进行中的桌次。</p>`,
 onConfirm:async()=>{await send('/api/groups/set-mode',{group_id:id,mode:to});await refresh();flash('桌位结构已更新');}});}
function renderOrderPanel(){const panel=$('orderPanel'),v=getVisit(activeVisitId);
 if(!data.store.layout_ready){panel.innerHTML='<div class="empty-state"><h2>本店图纸待导入</h2><p>禁止误用密云座位。</p></div>';return;}
 if(!v){panel.innerHTML='<div class="empty-state"><h2>请选择客人位置</h2><p>在左侧点击座位，二次确认后进入点单。</p></div>';return;}
 const pending=v.lines.filter(l=>l.status==='PENDING'),served=v.lines.filter(l=>l.status==='SERVED');
 const dTotal=v.drafts.reduce((sum,d)=>sum+d.price_cents*d.quantity,0);
 const previewDiscount=v.member?v.drafts.reduce((sum,d)=>sum+(d.discount_eligible?Math.floor((d.price_cents*10+50)/100):0)*d.quantity,0):0;
 const dNet=dTotal-previewDiscount;
 const memberTxt=v.member?`<b>银卡 · 9折</b> ${esc(v.member.surname)} · ${esc(v.member.masked_phone)}`:
                         '未确认会员 · 默认原价（银卡会员最高9折）';
 const productBtns=(data.products||[]).filter(p=>p.demo_only).map(p=>`<button class="product-btn" data-product="${esc(p.id)}"><span>＋ ${esc(p.name)}${p.demo_only?' <small class="product-drill-tag">演练</small>':''}</span><span>${yuan(p.price_cents)}</span></button>`).join('');
 const catalogCount=(data.catalog_items||[]).filter(x=>x.domain==='C').length;
 const readyCount=(data.catalog_items||[]).filter(x=>x.domain==='C'&&x.sale_enabled).length;
 const draftItems=v.drafts.map(d=>`<div class="draft-row"><span>● ${esc(d.product_name)} ×${d.quantity}</span><strong>${yuan(d.price_cents*d.quantity)}</strong><button class="tiny-danger" data-dremove="${esc(d.id)}">撤销</button></div>`).join('');
 const items=v.lines.filter(l=>l.status!=='CANCELLED').map(l=>{
   const st=l.status==='PENDING',sev=st?severity(elapsed(l.created_at)):'served';
   return `<div class="work-item ${st?'timing '+sev:'served'}"><div class="work-item-main"><strong>${esc(l.product_name_snapshot)}</strong><span>${yuan(l.price_cents*l.quantity)} · ${l.checkout_id?'已有结账登记':'尚未登记结账'}</span></div>
   <div class="work-item-meta"><span>${st?'<b class="time-counter" data-start="'+esc(l.created_at)+'">'+esc(waitLabel(elapsed(l.created_at)))+'</b>':'✓ 已送到桌上 '+chinaTime(l.served_at)}</span>
   ${st?`<button data-serve="${esc(l.id)}" class="serve-btn">制作完成并上桌</button>`:''}</div></div>`;}).join('');
 const history=v.checkouts.map((c,i)=>`<div class="settlement-row"><span>第 ${i+1} 次 · ${chinaTime(c.created_at)}</span><b>${yuan(c.amount_cents)}</b><small>结账登记 · 待支付核验</small></div>`).join('');
 panel.innerHTML=`<div class="order-top"><div class="order-eyebrow">BSV1 · ${esc(data.store.id)} · 本桌次</div>
 <div class="order-title"><h2>${esc(seatName(v.seat_id))}</h2><span class="status-tag">客人在店 · 可以继续加单</span></div>
 <div class="order-sub">到店 ${chinaFull(v.created_at)} · ${v.guests}人</div></div>
 <div class="order-content">
 <div class="compact-row"><strong>当前人数</strong><span class="counter"><button id="guestMinus">−</button><strong>${v.guests}</strong><button id="guestPlus">＋</button></span></div>
 <div class="member-area"><div class="section-label">会员识别｜输入手机后四位</div><div class="member-row"><input id="memberLast4" inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="输入4位尾号"/><button id="memberSearchBtn" class="outline">查询会员</button></div>
 <p class="member-note">${memberTxt} ${v.member?'<button id="memberRemove" class="inline-link">移除关联</button>':''}</p></div>
 <div class="section-label">添加商品 · 搜索中文或拼音首字母</div><input id="quickProductSearch" class="quick-product-search" type="search" autocomplete="off" placeholder="输入商品名称 / 拼音首字母，如 yl、mjt"/><div id="quickSearchResults" class="quick-search-results"></div>
 <div class="catalog-status-mini">已上架 ${catalogCount} 种现场成品；其中 ${readyCount} 款有AJ统一售价可下单，其余请在Excel补价。正式支付仍未接入，结账登记不代表真实到账。</div>

 <div class="draft-panel"><div class="section-label">？ 待下单商品 <b>${v.drafts.length}</b> 项 · 切桌/刷新后保留</div>
 ${draftItems||'<p class="small-muted">点击商品开始点单，确认下单后进入制作队列。</p>'}
 <div class="draft-total">待下单预计应收：<b>${yuan(dNet)}</b>${previewDiscount?`<small>含银卡优惠 −${yuan(previewDiscount)}</small>`:''}</div></div>
 <div class="section-label">已正式下单 ${v.lines.filter(l=>l.status!=='CANCELLED').length} 项 · 待出品 ${pending.length}</div>
 <div class="work-items">${items||'<p class="small-muted">尚无正式下单项目</p>'}</div>
 <div class="section-label">已完成的历史分次结账</div><div class="settlement-history">${history||'<p class="small-muted">暂无记录</p>'}</div>
 <div class="section-label">临时加菜 · 演练项</div><div class="product-buttons compact-training-products">${productBtns||''}</div><button type="button" id="catalogInline" class="catalog-inline-link">查看全部 V9 商品资料 ↗</button>
 <div class="totals"><div><span>本桌累计已下单</span><strong>${yuan(v.total_cents)}</strong></div><div><span>已下单待结账</span><strong>${yuan(v.unsettled_cents)}</strong></div></div>
 <button id="settleRound" class="outline full-width" ${v.unsettled_cents?'':'disabled'}>结账此前已下单商品（不离店）</button>
 <div class="disabled-notice">支付通道尚未启用：结账登记属于待核账记录，不能证明顾客已付款。</div>
 </div><div class="order-fixed-actions">
 <button id="submitOrder" class="primary full-width" ${v.drafts.length?'':'disabled'}>下单 · ${v.drafts.length}项 ${yuan(dNet)}</button>
 <div class="work-actions"><button id="transferBtn" class="outline">⇄ 转桌</button><button id="departBtn" class="primary">客人离店 · 最终结账</button><button id="cancelBtn" class="danger-button">撤单</button></div>
 </div>`;
 function showQuickResults(term){const box=$('quickSearchResults');if(!String(term||'').trim()){box.innerHTML='';return;}const matches=(data.catalog_items||[]).filter(p=>pinyinMatch(p,term)).slice(0,11);
  box.innerHTML=matches.map(p=>`<button type="button" class="quick-result ${p.sale_enabled?'ready':'unpriced'}" data-quick-id="${esc(p.id)}"><span><strong>${esc(p.name)}</strong><small>${esc(p.initials||'')} · ${esc(p.id)}</small></span><b>${p.sale_enabled?yuan(p.price_cents):p.domain==='C'?'AJ待定价':'套餐待定价'}</b></button>`).join('')||'<p class="small-muted">未找到匹配商品</p>';
  box.querySelectorAll('[data-quick-id]').forEach(btn=>btn.onclick=safe(async()=>{const id=btn.dataset.quickId,product=(data.catalog_items||[]).find(x=>x.id===id);
    if(!product?.sale_enabled){await showCatalogItem(id);return;}
    const res=await send('/api/drafts/add',{visit_id:v.id,product_id:id});await refresh();flash({title:'已添加待下单商品',subject:product.name+' ×1 · '+seatName(v.seat_id),amount:'增加 '+yuan(product.price_cents),detail:'尚未正式下单'});
  }));}
 const searchEl=$('quickProductSearch');searchEl.oninput=()=>showQuickResults(searchEl.value);showQuickResults('');
 panel.querySelectorAll('[data-product]').forEach(b=>b.onclick=safe(async()=>{
    const prod=data.products.find(x=>x.id===b.dataset.product);
    await send('/api/drafts/add',{visit_id:v.id,product_id:b.dataset.product});await refresh();
    flash({title:'已添加待下单商品',subject:(prod?.name||'商品')+' ×1 · '+seatName(v.seat_id),amount:'增加 '+yuan(prod?.price_cents||0),detail:'尚未正式下单'});
 }));
 panel.querySelectorAll('[data-dremove]').forEach(b=>b.onclick=safe(async()=>{
   const d=v.drafts.find(x=>x.id===b.dataset.dremove);
   await send('/api/drafts/remove',{visit_id:v.id,draft_id:b.dataset.dremove});await refresh();
   flash({title:'已撤销',subject:(d?.product_name||'商品')+' · '+seatName(v.seat_id),amount:'减少 '+yuan((d?.price_cents||0)*(d?.quantity||1))});
 }));
 panel.querySelectorAll('[data-serve]').forEach(b=>b.onclick=safe(async()=>{
   const line=v.lines.find(x=>x.id===b.dataset.serve);
   setPage('queue');await openRecipeGuide(b.dataset.serve);
 }));
 $('catalogInline').onclick=()=>setPage('catalog');
 $('memberSearchBtn').onclick=safe(()=>searchMember(v));$('memberLast4').onkeydown=e=>{if(e.key==='Enter')$('memberSearchBtn').click();};
 if($('memberRemove'))$('memberRemove').onclick=()=>dialog({title:'移除本桌会员关联？',body:'只影响以后正式提交的商品，不修改已下单商品的价格快照。',onConfirm:async()=>{await send('/api/members/assign',{visit_id:v.id,member_id:null});await refresh();}});
 $('guestMinus').onclick=safe(async()=>{await send('/api/visits/set-guests',{visit_id:v.id,guests:v.guests-1});await refresh();});
 $('guestPlus').onclick=safe(async()=>{await send('/api/visits/set-guests',{visit_id:v.id,guests:v.guests+1});await refresh();});
 $('submitOrder').onclick=()=>confirmSubmit(v,dNet);
 $('settleRound').onclick=()=>confirmRound(v);$('transferBtn').onclick=()=>beginTransfer(v);
 $('departBtn').onclick=()=>confirmDepart(v);$('cancelBtn').onclick=()=>confirmCancel(v);
}
async function searchMember(v){const last4=$('memberLast4').value.trim();if(!/^\d{4}$/.test(last4))throw new Error('请输入完整的手机号后四位');
 const obj=await getJson('/api/members/search?last4='+encodeURIComponent(last4));
 if(!obj.matches.length){flash('会员库暂无该尾号，不能自动打折',true);return;}
 const choices=obj.matches.map((m,i)=>`<label class="member-option"><input type="radio" name="memberCandidate" value="${esc(m.id)}" ${obj.matches.length===1?'checked':''}/><strong>${esc(m.surname)} · ${esc(m.masked_phone)}</strong><small>银卡 · 9折</small></label>`).join('');
 dialog({eyebrow:'会员实名核对 · 仅本店已授权员工可见',title:obj.ambiguity?'尾号重复，请核对会员':'请核对会员身份',body:`<p>尾号 ${esc(last4)} 对应 ${obj.matches.length} 位会员，请确认姓氏和脱敏电话：</p><div class="member-choices">${choices}</div>`,confirmText:'确认绑定会员',onConfirm:async()=>{const id=document.querySelector('input[name="memberCandidate"]:checked')?.value;if(!id)throw new Error('请先选一位正确的会员');await send('/api/members/assign',{visit_id:v.id,member_id:id});await refresh();flash('已关联银卡会员：符合条件的未下单商品9折');}});
}
function confirmSubmit(v,estimate){dialog({eyebrow:'正式下单 · 请确认操作',title:'请选择本次操作',
 body:`<div class="submit-choice-intro">${esc(seatName(v.seat_id))} · ${v.drafts.length}项 · 预计 ${yuan(estimate)}</div>
 <div class="submit-option-grid"><button type="button" id="modeOrderOnly" class="submit-option"><b>① 下单</b><span>通知调酒师制作，客人尚未结账</span></button>
 <button type="button" id="modeOrderPay" class="submit-option"><b>② 下单并结账</b><span>现在结算本次商品；客人仍在店，不生成离店结账单</span></button></div>
 <p class="warning-note">支付服务尚未接通；本地结账记录必须经支付机构核实后才可认定收款成功。</p>`,confirmText:'请先选择上方操作',cancelText:'返回点单',
 onConfirm:()=>{throw new Error('请先选择“下单”或“下单并结账”');}});
 const run=async pay_now=>{try{const r=await send('/api/orders/submit',{visit_id:v.id,pay_now});closeDialog();await refresh();flash({title:pay_now?'已下单并登记结账':'已正式下单',subject:v.drafts.map(d=>d.product_name+' ×'+d.quantity).join('、'),amount:'本次 '+yuan(r.amount_cents),detail:pay_now?'客人仍在店 · 收款待核验':'已进入待制作队列'});}catch(e){flash(e.message,true);}};
 $('modeOrderOnly').onclick=()=>run(false);$('modeOrderPay').onclick=()=>run(true);
}
function confirmItemRemove(v,id){const l=v.lines.find(x=>x.id===id);dialog({eyebrow:'撤单 · '+seatName(v.seat_id),title:seatName(v.seat_id),body:`<div class="modal-action-heading">确认撤销 ${esc(l?.product_name_snapshot||'这项商品')}？</div><p>只允许撤销尚未上桌、尚未结账的商品。</p>`,danger:true,confirmText:'确认撤销',
 onConfirm:async()=>{await send('/api/orders/remove-item',{visit_id:v.id,line_id:id});await refresh();flash({title:'已撤销',subject:l?.product_name_snapshot||'商品',amount:'减少 '+yuan((l?.price_cents||0)*(l?.quantity||1))});}});}
function confirmRound(v){dialog({eyebrow:'本桌结账登记',title:seatName(v.seat_id),body:`<div class="modal-action-heading">确认结算本次已下单商品？</div><div class="demo-total">${yuan(v.unsettled_cents)}</div><p>仅记录尚未结账的已下单商品。客人仍在店，可继续加单；离店时才提供最终结账单。</p><p class="warning-note">支付接口未启用，本操作会记为待核账记录，不能代替收款确认。</p>`,confirmText:'登记本次结账',
 onConfirm:async()=>{await send('/api/checkouts/settle-demo',{visit_id:v.id});await refresh();flash({title:'已登记 '+seatName(v.seat_id)+' 本次结账',amount:yuan(v.unsettled_cents),detail:'客人在店 · 可继续加单 · 待支付核验'});}});}
function confirmDepart(v){
 const name=seatName(v.seat_id),deadline=data.severity_thresholds.seat_late||300;
 dialog({eyebrow:'最终结账 · 离店复位',title:name,
 body:`<div class="modal-action-heading">确认 ${esc(name)} 的客人已离店，并结束本桌订单？</div>
 <div class="close-summary"><b>${esc(name)} · 本桌累计消费 ${yuan(v.total_cents)}</b><br/>待出品 ${v.lines.filter(l=>l.status==='PENDING').length} 项 · 待下单 ${v.drafts.length} 项 · 待结账 ${yuan(v.unsettled_cents)}</div>
 <p>离店后保存到店时间、离店时间、商品明细、会员及转桌历史。结束后请立即检查并清理 ${esc(name)}。</p>
 <div class="print-choice"><label class="choice-no"><strong>不需要纸质版</strong><small>默认 · 保存完整电子消费记录</small><input type="radio" name="paperChoice" value="NONE" checked aria-label="不需要纸质版"/></label>
 <label class="choice-yes"><strong>需要纸质版</strong><small>打开浏览器打印预览</small><input type="radio" name="paperChoice" value="PAPER" aria-label="需要纸质版"/></label></div>
 <p class="warning-note">请确认外部收款状态；目前支付通道未接入，记录不代表真实到账。</p>`,
 confirmText:'确认 '+name+' 客人离店',onConfirm:async()=>{
 const radio=document.querySelector('input[name="paperChoice"]:checked');const pref=radio?.value||'NONE';
 const result=await send('/api/visits/depart-demo',{visit_id:v.id,print_preference:pref});
 activeVisitId=null;focusedSeat=v.seat_id;await refresh();
 flash({title:name+' 客人已离店',subject:'请立即检查并清理 '+name,detail:'请在 '+shortDuration(deadline)+' 内完成 · 检查遗留物品，如无法联系客人，妥善保管'});
 if(pref==='PAPER')await showReceipt(result.visit_id,true);
 }});
}
function confirmCancel(v){dialog({eyebrow:'撤单 · 危险操作',title:seatName(v.seat_id),body:`<div class="modal-action-heading">确认撤销 ${esc(seatName(v.seat_id))} 的本桌订单？</div>仅允许整桌尚无上桌商品、尚无历史结算的情况。撤单后不删除历史记录。${v.lines.length?' 若已有商品，位置会进入清洁检查。':''}`,danger:true,
 confirmText:'确认整桌撤单',onConfirm:async()=>{await send('/api/visits/cancel',{visit_id:v.id});activeVisitId=null;await refresh();flash('订单已撤销并审计留痕');}});}
function beginTransfer(v){dialog({eyebrow:'转桌 · 0/3',title:seatName(v.seat_id),body:`<div class="modal-action-heading">确定从本座位发起转桌操作吗？</div><p>转桌表示整桌客人从原位置移到新的空闲位置：订单、人数、会员和历史结算都会保留。原桌将变为红色待清桌。</p><p>你需要依次<strong>重新点原座位</strong>、<strong>点目标座位</strong>，最后核对红叉与绿勾。</p>`,confirmText:'确认，开始转桌',
 onConfirm:()=>{transfer={stage:'source',visitId:v.id,from:v.seat_id,to:null};page='map';focusedSeat=v.seat_id;render();flash('请重新点击原座位 '+seatName(v.seat_id));}});}
function handleTransferSeat(id){const s=getSeat(id);if(!s?.enabled){flash('该座位不可使用',true);return;}
 if(transfer.stage==='source'){if(id!==transfer.from){flash('原座位应为 '+seatName(transfer.from)+'，请重新点选',true);return;}
 transfer.stage='target';render();flash('原座位已确认。请选择换到的新位置');return;}
 if(transfer.stage==='target'){if(id===transfer.from){flash('新位置不能与原位置相同',true);return;}
 if(visitAt(id)||s.cleaning_state==='DIRTY'){flash('目标位置正在使用或未清洁',true);return;}
 transfer.to=id;transfer.stage='preview';render();dialog({eyebrow:'转桌 · 3/3',title:seatName(transfer.from)+' → '+seatName(id),body:`<div class="modal-action-heading">请确认客人转到了正确的新座位</div><div class="modal-transfer"><div class="from">✕<div>${esc(seatName(transfer.from))}</div><small>原座位</small></div><div class="arrow">➜<br>➜<br>➜</div><div class="to">✓<div>${esc(seatName(id))}</div><small>新座位</small></div></div><p class="modal-caption">确认后整桌订单和会员一起转移，原位置需重新清理。</p>`,confirmText:'确认转到 '+seatName(id),cancelText:'返回重新选择',
 onCancel:()=>{if(transfer){transfer.stage='target';transfer.to=null;render();}},onConfirm:async()=>{const t={...transfer};await send('/api/visits/transfer',{visit_id:t.visitId,source_seat_id:t.from,target_seat_id:t.to});transfer=null;activeVisitId=t.visitId;focusedSeat=t.to;await refresh();flash({title:'已转入 '+seatName(t.to),subject:'请清理原座位 '+seatName(t.from),detail:'原座位已加入清洁任务，请在 '+shortDuration(data.severity_thresholds.seat_late)+' 内完成'});}});}}
function renderTransferBanner(){const b=$('transferBanner');if(!transfer){b.classList.add('hidden');return;}
 const phrases={source:'请点击客人之前坐的位置',target:'请点击客人现在要转到的位置',preview:'请核对原座位红叉与新座位绿勾'};
 b.classList.remove('hidden');b.innerHTML=`<div><span class="step-number">${transfer.stage==='source'?'1':transfer.stage==='target'?'2':'3'} / 3</span><strong>${phrases[transfer.stage]}</strong><div><small>原：${esc(seatName(transfer.from))}${transfer.to?' → 新：'+esc(seatName(transfer.to)):''}</small></div></div><button id="abortTransfer" class="outline">取消转桌</button>`;
 $('abortTransfer').onclick=()=>{transfer=null;closeDialog();render();flash('已取消转桌，原数据未修改');};}
function renderVisits(){const box=$('ordersList');if(!data.visits.length){box.innerHTML='<p class="small-muted">当前无进行中的桌次</p>';return;}
 box.innerHTML=data.visits.map(v=>`<div class="visit-row"><div><div class="visit-seat">${esc(seatName(v.seat_id))} · ${v.guests}人</div>
 <div class="visit-caption">到店 ${chinaTime(v.created_at)} · 待制作 ${v.lines.filter(l=>l.status==='PENDING').length} 项 · 累计 ${yuan(v.total_cents)} · 新增待结 ${yuan(v.unsettled_cents)}</div></div>
 <button class="outline" data-visit="${esc(v.id)}">进入点单</button></div>`).join('');
 box.querySelectorAll('[data-visit]').forEach(b=>b.onclick=safe(async()=>{const target=getVisit(b.dataset.visit);if(!target)return;const locked=await send('/api/seats/claim-edit',{seat_id:target.seat_id});if(!locked.ok)throw new Error('该桌正在由 '+locked.editor+' 点单，请勿重复下单');const prior=activeVisitId?getVisit(activeVisitId)?.seat_id:null;if(prior&&prior!==target.seat_id)await releaseSeat(prior);activeVisitId=b.dataset.visit;focusedSeat=target.seat_id;page='map';render();}));}
function renderQueue(){const lines=(data.production_tasks||[]),online=data.online_staff_count||0;
 const my=lines.filter(t=>myTask(t)),others=lines.filter(t=>!myTask(t));
 $('queueList').innerHTML=`<div class="dispatch-banner"><strong>当前在线调酒师：${online} 人</strong><span>我的任务 ${my.length} 项 · 待制作/上桌 ${lines.length} 项</span><small>制作完成不等于上桌；已领取任务不会在断线时自动重新分配</small></div>`+
 (lines.length?[...my,...others].map(t=>{const sev=severity(elapsed(t.created_at)),mine=myTask(t),ready=t.workflow_state==='READY_TO_SERVE',claimed=t.state==='CLAIMED';return `<div class="queue-task ${sev} ${ready?'is-ready':''} ${mine?'is-mine':'is-others'}"><div class="queue-main"><span class="queue-seat">${esc(t.seat_label)}</span><strong>${esc(t.product_name_snapshot)} ${t.quantity>1?'×'+t.quantity:''}</strong><small>${ready?'✓ 已制作完成 · 等待送达':claimed?'制作中':'等待制作'} · 下单 ${chinaTime(t.created_at)} · ${esc(t.maker_code||t.assigned_code||'等待分配')}</small></div><div class="queue-time"><b>${esc(waitLabel(elapsed(t.created_at)))}</b></div><div class="production-actions"><button class="outline" data-guide="${esc(t.line_id)}">查看引导</button>${ready?`<button class="serve-btn" data-guide="${esc(t.line_id)}">确认上桌</button>`:mine?`<button class="serve-btn" data-claim="${esc(t.line_id)}">${claimed?'继续制作':'领取制作'}</button>`:''}${claimed && !mine && data.staff.role==='MANAGER' && !ready?`<button class="outline" data-reassign="${esc(t.line_id)}">核实后重分配</button>`:''}</div></div>`;}).join(''):'<div class="task-empty">当前没有待出品或待送达任务</div>');
 $('queueList').querySelectorAll('[data-guide]').forEach(b=>b.onclick=safe(()=>openRecipeGuide(b.dataset.guide,false)));
 $('queueList').querySelectorAll('[data-claim]').forEach(b=>b.onclick=safe(async()=>{await send('/api/production/claim',{line_id:b.dataset.claim});await refresh();await openRecipeGuide(b.dataset.claim,true);}));
 $('queueList').querySelectorAll('[data-reassign]').forEach(b=>b.onclick=()=>{const t=(data.production_tasks||[]).find(x=>x.line_id===b.dataset.reassign);if(!t)return;
  dialog({eyebrow:'管理操作 · 防止重复制作',title:'确认重新分配 '+t.product_name_snapshot,
   body:`<p class="modal-caption">座位 ${esc(t.seat_label)} · 原调酒师 ${esc(t.claimed_code||'未知')}</p><p class="recipe-warning">必须现场确认原调酒师没有继续制作、没有已完成待上桌；仅设备失联不能证明酒未做。</p>`,
   confirmText:'现场已核实，重新分配',cancelText:'返回',onConfirm:async()=>{await send('/api/production/reassign',{line_id:t.line_id,confirm_checked:true});await refresh();flash({title:'任务已重新分配',subject:t.product_name_snapshot,detail:'请核对新负责人'});}});
 });
}
// Visual guide is strictly muted. Never calls WebAudio, Audio(), play(), speechSynthesis or vibrate().
// Browser code cannot disable physical Android speaker routing, so sound cues are NOT implemented.
const SOUND_OUTPUT_ENABLED=false;
let guideLine=null,guideInfo=null,guideTimerState={phase:'paused',origin:0,period:0,seconds:0};
function guideCurrentTask(){return (data?.production_tasks||[]).find(t=>t.line_id===guideLine);}
function guideShown(){return !$('guideOverlay').classList.contains('hidden');}
function guideStopTimer(){guideTimerState.phase='paused';guideTimerState.origin=0;guideTimerState.seconds=0;guideUpdateTimer();}
function guideStartTimer(){const t=guideCurrentTask();
 if(!t||t.workflow_state==='READY_TO_SERVE'||t.state!=='CLAIMED'||t.claimed_by!==data?.staff?.id){
  guideTimerState.phase='paused';guideUpdateTimer();return;
 }
 const raw=guideInfo?.fields?.['制作时长（秒）'];const sec=Number(raw);
 if(raw===undefined||raw===null||String(raw).trim()===''||!Number.isFinite(sec)||sec<1||sec>180){guideTimerState={phase:'unavailable',origin:0,period:0,seconds:0};guideUpdateTimer();return;}
 guideTimerState={phase:'prepare',origin:performance.now(),period:0,seconds:sec};guideUpdateTimer();}
function guideUpdateTimer(){const box=$('guideTimer');if(!box)return;const tm=guideTimerState;
 if(guideCurrentTask()?.workflow_state==='READY_TO_SERVE' && guideShown()){box.className='guide-timer is-paused';$('guideTimerLabel').textContent='制作已完成 · 等待送达';$('guideCountdown').textContent='✓';$('guideTimerHint').textContent='操作计时已停止 · 核对座位后完成上桌';return;}
 if(tm.phase==='paused'){box.className='guide-timer is-paused';
  const t=guideCurrentTask();const permitted=t?.state==='CLAIMED'&&t?.claimed_by===data?.staff?.id;
  $('guideTimerLabel').textContent=permitted?'计时已暂停':'只读预览 · 请先由本人领取制作';$('guideCountdown').textContent='Ⅱ';
  $('guideTimerHint').textContent=permitted?'再次点击从黄色准备开始':'未领取任务不能启动操作计时';return;}
 if(tm.phase==='unavailable'){$('guideTimer').className='guide-timer is-paused';$('guideTimerLabel').textContent='尚未核准操作秒数';$('guideCountdown').textContent='—';$('guideTimerHint').textContent='请查看 V9 原始制作说明，勿使用推测时间';return;}
 const durations={prepare:2700,work:tm.seconds*1000,stop:3750};
 let delta=performance.now()-tm.origin;
 let loop=2700+tm.seconds*1000+3750;
 if(delta>=loop){tm.origin+=Math.floor(delta/loop)*loop;delta=performance.now()-tm.origin;}
 let phase='prepare',remain=2700-delta;
 if(delta>=2700&&delta<2700+tm.seconds*1000){phase='work';remain=2700+tm.seconds*1000-delta;}
 else if(delta>=2700+tm.seconds*1000){phase='stop';remain=loop-delta;}
 tm.phase=phase;box.className='guide-timer is-'+phase;
 $('guideTimerLabel').textContent=phase==='prepare'?'准备 · 请拿起壶':phase==='work'?'操作中 · 保持标准动作':'停止 · 时间到';
 $('guideCountdown').textContent=phase==='stop'?'停':(Math.max(0,Math.ceil(remain/100)/10)).toFixed(1)+'s';
 $('guideTimerHint').textContent=phase==='prepare'?'黄色准备2.7秒 · 随后进入标准操作':phase==='work'?'按照 V9 标准操作 '+tm.seconds+' 秒':'红色停止3.75秒 · 随后再次循环';
}
function guideTaskList(){const list=$('guideTaskList');if(!data||!list)return;
 const tasks=(data.production_tasks||[]).slice().sort((a,b)=>Number(b.workflow_state==='READY_TO_SERVE')-Number(a.workflow_state==='READY_TO_SERVE')||Number(myTask(b))-Number(myTask(a))||Date.parse(a.created_at)-Date.parse(b.created_at));
 $('guideTaskCount').textContent=tasks.length;
 list.innerHTML=tasks.length?tasks.map(t=>`<button type="button" class="guide-task ${t.line_id===guideLine?'selected':''} ${t.workflow_state==='READY_TO_SERVE'?'ready':''}" data-task-line="${esc(t.line_id)}"><span class="guide-task-meta">${esc(t.seat_label)} · ${t.workflow_state==='READY_TO_SERVE'?'待上桌':myTask(t)?'我的制作任务':'其他员工任务'}</span><strong>${esc(t.product_name_snapshot)} ×${t.quantity}</strong><small>${esc(t.maker_code||t.claimed_code||t.assigned_code||'待分配')} · ${esc(waitLabel(elapsed(t.created_at)))}</small></button>`).join(''):'<div class="task-empty">本店暂无待办</div>';
 list.querySelectorAll('[data-task-line]').forEach(b=>b.onclick=safe(async()=>{const id=b.dataset.taskLine;const task=(data.production_tasks||[]).find(t=>t.line_id===id);if(task?.state==='PENDING'&&myTask(task)){await send('/api/production/claim',{line_id:id});await getState();}await openRecipeGuide(id,false);}));
}
function guideSetImage(kind,target){const photo=guideInfo?.photos?.[kind];const el=$(target);const label=kind==='materials'?'原料合照':'成品照片';
 if(photo?.available){el.innerHTML=`<img alt="${esc(label)} · ${esc(guideInfo.name)}" loading="eager" src="/api/production/photo?line_id=${encodeURIComponent(guideLine)}&kind=${kind}"/>`;}
 else{el.innerHTML=`<div class="guide-missing">${label}待导入<small>${esc(photo?.filename||'V9未填写文件名')}</small></div>`;}}
function guideShowInfo(title,inner){$('guideInfoTitle').textContent=title;$('guideInfoContent').innerHTML=inner;$('guideInfoPop').classList.remove('hidden');}
function guideCloseInfo(){$('guideInfoPop').classList.add('hidden');}
function guideClose(){guideStopTimer();guideLine=null;guideInfo=null;guideCloseInfo();$('guideOverlay').classList.add('hidden');}
function guideImageZoom(kind){if(!guideInfo)return;
 const ph=guideInfo.photos?.[kind];const isMaterial=kind==='materials';const name=isMaterial?'原料备齐与寻酒':'标准成品对照';
 guideShowInfo(name,`${ph?.available?`<img class="guide-zoom-image" alt="${esc(name)}" src="/api/production/photo?line_id=${encodeURIComponent(guideLine)}&kind=${kind}"/>`:`<div class="guide-missing guide-large-missing">当前未提供图像文件：${esc(ph?.filename||'未填写')}</div>`}${isMaterial?`<div class="guide-guide-note"><h4>寻酒指引</h4><p>${esc(guideInfo.fields?.['寻酒指引']||'尚未导入寻酒指引。请以本店最新库位清单为准。')}</p></div>`:''}`);
}
function guideUpdateActions(){const t=guideCurrentTask();if(!t)return;
 const ready=t.workflow_state==='READY_TO_SERVE';const mine=t.claimed_by===data.staff.id;
 $('guideStatusTag').textContent=ready?'✓ 已制作完成 · 等待送达':t.state==='CLAIMED'?'制作中 · 待完成':'等待领取制作';
 $('guideResponsibility').textContent=ready?`制作人：${t.maker_code||'未识别'} · 请核对桌号并送达`:`当前责任人：${t.claimed_code||t.assigned_code||'待分配'} · 送达前不能结束等待`;
 $('guideFinish').classList.toggle('hidden',ready||!mine);$('guideDeliver').classList.toggle('hidden',!ready);
 if(ready){guideStopTimer();$('guideTimerLabel').textContent='制作已完成 · 待送达';$('guideCountdown').textContent='✓';$('guideTimerHint').textContent='本任务的操作计时已停止，请将商品交给正确客人';}
}
async function openRecipeGuide(lineId){const t=(data.production_tasks||[]).find(x=>x.line_id===lineId);if(!t)throw new Error('该任务已完成或不属于本店');
 const info=await getJson('/api/production/recipe?line_id='+encodeURIComponent(lineId));guideLine=lineId;guideInfo=info;
 $('guideContext').textContent=`${data.store.name} · ${t.seat_label} · ${t.quantity} 份 · 任务编号 ${lineId.slice(0,8)}`;
 $('guideName').textContent=info.name||t.product_name_snapshot;
 $('guideAction').textContent=String(info.fields?.['操作方式']||'待核准');
 const secs=info.fields?.['制作时长（秒）'];$('guideSeconds').textContent=secs?`${esc(secs)} 秒`:'未核准';
 $('guideFlavor').textContent=String(info.fields?.['风味标签']||'风味详情');
 $('guideTaste').onclick=()=>guideShowInfo('风味描述',`<p>${esc(info.fields?.['风味描述']||'暂无已核准风味描述')}</p>`);
 $('guideStory').onclick=()=>guideShowInfo('产品故事',`<p>${esc(info.fields?.['产品故事']||'暂无已核准产品故事')}</p>`);
 guideSetImage('materials','guideMaterialsImg');guideSetImage('final','guideFinalImg');
 const fields=info.fields||{};
 const instructions=[['配方与用量',fields['配方文字']],['制作步骤',fields['完整制作步骤']],['补充提醒',fields['补充制作说明']],['杯具与装饰',fields['杯具']],['操作力度',fields['操作力度']],['过敏原提醒',fields['过敏原']]].filter(([,val])=>val!==undefined&&val!==null&&String(val).trim());
 $('guideInstructions').innerHTML=instructions.map(([label,val])=>`<div><b>${esc(label)}</b><p>${esc(val)}</p></div>`).join('')||'<div><b>暂无制作资料</b><p>请暂停盲目制作，核对正式配方。</p></div>';
 $('guideSourceNote').textContent=`V9 制作文字 · ${fields['配方版本']||'版本未标注'} · 未核准资料必须人工复核`;
 $('guideOverlay').classList.remove('hidden');guideCloseInfo();guideTaskList();guideStartTimer();guideUpdateActions();
}
function guideFinishConfirm(){const t=guideCurrentTask();if(!t)return;
 if(t.claimed_by!==data.staff.id||t.workflow_state==='READY_TO_SERVE'){flash('此任务不能由当前员工再次确认制作完成',true);return;}
 dialog({eyebrow:'制作完成 · 责任记录',title:t.seat_label+' · '+t.product_name_snapshot,
 body:`<div class="modal-action-heading">请确认已制作完成全部 ${t.quantity} 份</div><p>此步骤<strong>仅登记制作完成</strong>，并不代表客人已收到。制作人将记录为 ${esc(data.staff.code)}，该商品随后转入待上桌。</p>`,confirmText:'确认：我已做完',onConfirm:async()=>{const r=await send('/api/production/finished',{line_id:t.line_id});await refresh();guideTaskList();guideUpdateActions();flash({title:'已完成制作',subject:r.product,detail:t.seat_label+' · 已转入待上桌 · 制作人 '+r.maker_code});}});
}
function guideDeliverConfirm(){const t=guideCurrentTask();if(!t||t.workflow_state!=='READY_TO_SERVE')return;
 dialog({eyebrow:'送达确认 · 最终复核',title:t.seat_label+' · '+t.product_name_snapshot,
 body:`<div class="modal-action-heading">确认已将 ${t.quantity} 份 ${esc(t.product_name_snapshot)} 送达 ${esc(t.seat_label)}？</div><p>请核对：桌号、商品名称和数量。送达人会记录为 ${esc(data.staff.code)}，制作人为 ${esc(t.maker_code||'未知')}。</p>`,confirmText:'确认已送达客人',onConfirm:async()=>{const r=await send('/api/production/serve',{line_id:t.line_id,confirmed_delivered:true});guideClose();await refresh();flash({title:'已送达 '+seatName(r.seat_id),subject:r.product,detail:'制作 '+r.maker_code+' · 送达 '+r.delivered_by+' · 已保存时间'});}});
}
$('guideClose').onclick=guideClose;$('guideInfoClose').onclick=guideCloseInfo;$('guideInfoPop').addEventListener('click',e=>{if(e.target===$('guideInfoPop'))guideCloseInfo();});
$('guideMaterials').onclick=()=>guideImageZoom('materials');$('guideFinishedImage').onclick=()=>guideImageZoom('final');
$('guideTimer').onclick=()=>{if(guideTimerState.phase==='paused'||guideTimerState.phase==='unavailable')guideStartTimer();else guideStopTimer();};
$('guideFinish').onclick=guideFinishConfirm;$('guideDeliver').onclick=guideDeliverConfirm;
setInterval(()=>{if(guideShown())guideUpdateTimer();},80);
function cleanStatus(b){return ['late','critical'].includes(bathroomStage(b).sev);}
function renderCleaning(){const box=$('cleanList');let html='';for(const b of data.bathrooms){const st=bathroomStage(b);html+=`<div class="clean-task ${taskSeverityClass(st.sev)}"><div><span class="task-seat-badge">卫生间</span><strong class="task-command">${st.sev==='normal'?'检查 '+esc(b.label):'立即清洁 '+esc(b.label)}</strong>
 <p>${b.last_clean_at?'上次清洁：'+chinaFull(b.last_clean_at):'暂无清洁记录，首次检查必须立即执行'}</p>
 <b class="clean-timer">${esc(st.text)}</b></div><button class="${st.sev==='normal'?'outline':'danger-button'}" data-cleanbath="${esc(b.id)}">逐项检查并确认</button></div>`;}
 for(const seat of data.seats.filter(x=>x.enabled && x.cleaning_state==='DIRTY')){const st=seatCleaningStage(seat);
 html+=`<div class="clean-task ${taskSeverityClass(st.sev)}"><div><span class="task-seat-badge">${esc(seat.label)}</span><strong class="task-command">请清理 ${esc(seat.label)}</strong><p>检查遗留物品，整理桌面、椅子与纸品</p><b class="clean-timer">${esc(st.text)}</b></div><button class="danger-button" data-cleanseat="${esc(seat.id)}">确认清桌</button></div>`;}
 box.innerHTML=html||'<div class="task-empty">✓ 当前没有清洁任务</div>';
 box.querySelectorAll('[data-cleanbath]').forEach(b=>b.onclick=()=>confirmBathroom(b.dataset.cleanbath));
 box.querySelectorAll('[data-cleanseat]').forEach(b=>b.onclick=()=>confirmSeatClean(getSeat(b.dataset.cleanseat)));
}
function confirmSeatClean(seat){if(!seat)return;dialog({eyebrow:'桌位复位 · 员工确认',title:seat.label,
 body:`<div class="modal-action-heading">请确认 ${esc(seat.label)} 已经清理干净</div><p>请先确认客人已经离开，桌面、器皿、纸品和椅子已整理，恢复到开店标准。</p>
 <label class="task-check"><input id="seatCheck" type="checkbox"/> 我已清理此桌，并恢复到原来的摆放状态</label>`,
 confirmText:'确认清桌，恢复空闲',onConfirm:async()=>{if(!$('seatCheck')?.checked)throw new Error('请先完成现场清洁并勾选确认');
 await send('/api/housekeeping/clean-seat',{seat_id:seat.id,confirmed:true});await refresh();flash({title:'清桌完成',subject:seat.label+' 已恢复空闲',detail:'已记录清洁员工和时间'});}});}
function confirmBathroom(id){const b=data.bathrooms.find(x=>x.id===id);if(!b)return;
 dialog({eyebrow:'卫生间清洁 · 每2小时提醒',title:'卫生间',
 body:`<div class="modal-action-heading">请逐项完成卫生间清洁检查</div><p>当前门店：<strong>${esc(data.store.name)}</strong> · ${esc(b.label)}。四项都完成后才能将红色提示改为绿色。</p>
 <div class="checklist"><label><input type="checkbox" data-bathcheck="paper"/> 已检查并补充厕纸</label>
 <label><input type="checkbox" data-bathcheck="toilet"/> 已清洁马桶和坐圈</label>
 <label><input type="checkbox" data-bathcheck="sink"/> 已清洁洗手台及接触面</label>
 <label><input type="checkbox" data-bathcheck="floor_trash"/> 已检查地面及垃圾</label></div>`,
 confirmText:'四项全部完成，重新计时',onConfirm:async()=>{const checks={};document.querySelectorAll('[data-bathcheck]').forEach(x=>checks[x.dataset.bathcheck]=x.checked);
 if(Object.values(checks).filter(Boolean).length!==4)throw new Error('有清洁检查项未完成');
 await send('/api/housekeeping/clean-bathroom',{bathroom_id:id,checks});await refresh();flash({title:'卫生间清洁完成',subject:b.label+' 已恢复绿色',detail:'下次清洁截止：2小时后'});}});}
const AUDIT_NAMES={LOGIN:'登录门店',OPEN_VISIT:'开桌',OPEN_EXISTING:'查看桌次',ADD_DRAFT:'新增待下单商品',REMOVE_DRAFT:'撤销待下单商品',SUBMIT_ORDER_TEST:'正式下单',SUBMIT_AND_TEST_CHECKOUT:'下单并登记结账',ADD_DEMO_ITEM:'旧记录：商品录入',CANCEL_ITEM:'撤销商品',SERVED:'确认已送达上桌',FINISHED_PRODUCTION:'制作完成待上桌',CLAIM_PRODUCTION:'领取制作任务',SET_MEMBER_TEST:'旧记录：会员编号',ASSIGN_MEMBER:'核实并绑定会员',SET_GUESTS:'修改人数',TRANSFER:'转桌',TEST_SETTLE_ROUND:'登记分次结账',DEPART_DEMO:'客人离店',CANCEL_VISIT:'撤单',SEAT_CLEAN:'清桌',BATHROOM_CLEAN:'卫生间清洁',CHANGE_TABLE_MODE:'调整合分桌',CRITICAL_OVERDUE:'⚠ 严重超时事件'};
function renderAudit(){if(page!=='audit')return;loadAudit().catch(e=>flash(e.message,true));}
async function loadAudit(){const p=getRangeParams('audit')+'&category='+encodeURIComponent(auditCategory),obj=await getJson('/api/audit?'+p);
 const box=$('auditList');box.innerHTML=obj.audit.map(x=>`<div class="audit-entry ${x.action==='CRITICAL_OVERDUE'?'critical-entry':''}"><div class="audit-mark"></div><div><div class="audit-info"><strong>${esc(AUDIT_NAMES[x.action]||x.action)}</strong> · ${esc(x.staff_code||'系统自动监测')}</div><div class="audit-time">${chinaFull(x.created_at)} · ${esc(data.store.id)} · 记录 #${x.id}</div>${x.action==='CRITICAL_OVERDUE'?`<p class="audit-critical-note">严重异常 · ${esc(x.detail.category||'')} · 已生成系统事件</p>`:''}</div></div>`).join('')||'<p class="small-muted">当前筛选条件下无记录</p>';}
async function renderHistory(loadMore=false){
 validateHistoryFilter();
 if(!loadMore)historyOffset=0;
 const params=getRangeParams('history')+'&offset='+historyOffset;
 const obj=await getJson('/api/history?'+params);
 const summary=obj.summary||{};
 if(!loadMore){
   const cards=[
     ['结账登记笔数',String(summary.checkout_count||0),'包含未离店桌次的分次结账'],
     ['账面金额',yuan(summary.gross_cents),'已结账商品原价'],
     ['优惠金额',yuan(summary.discount_cents),'下单时优惠快照'],
     ['折后应收',yuan(summary.due_cents),'账面金额－优惠金额'],
     ['登记结账',yuan(summary.registered_cents),'尚未连接支付机构核验']
   ];
   $('historySummary').innerHTML=cards.map(([label,amount,desc],i)=>`<div class="history-card ${i===4?'emphasis':''}"><span>${esc(label)}</span><b>${esc(amount)}</b><small>${esc(desc)}</small></div>`).join('');
   const mismatch=Number(summary.mismatch_count||0),missing=Number(summary.missing_items_count||0);
   const delta=Number(summary.difference_cents||0);
   $('historyRisk').innerHTML=(mismatch||missing)?`<strong>发现 ${mismatch} 笔结账金额与商品行不一致</strong><span>登记差额合计 ${yuan(delta)}；其中商品关联缺失 ${missing} 笔。请打开明细逐笔复核，不要直接视为真实多收或少收。</span>`:`<strong>登记结账与对应商品金额一致</strong><span>本期已登记结账金额与已结账商品折后应收一致；真实到账仍需支付平台核验。</span>`;
   $('historyRisk').className='history-risk-note '+((mismatch||missing)?'has-risk':'');
   const daily=obj.report||[];
   const max=Math.max(1,...daily.map(r=>Math.max(0,Number(r.registered_cents||0))));
   const chartRows=[...daily].reverse();
   $('historyChart').innerHTML=chartRows.length?chartRows.map(r=>`<div class="history-chart-col" title="${esc(r.date)} · 登记 ${yuan(r.registered_cents)}"><div class="history-bar-value">${yuan(r.registered_cents)}</div><div class="history-bar-track"><div class="history-bar" style="height:${Math.max(4,Number(r.registered_cents||0)/max*100)}%"></div></div><span>${esc(r.date.slice(5))}</span></div>`).join(''):'<p class="history-report-empty">选定日期内暂无结账登记</p>';
   $('historyReport').innerHTML=daily.length?`<div class="report-row head"><span>日期</span><span>账面</span><span>优惠</span><span>折后应收</span><span>登记结账</span></div>${daily.map(r=>`<div class="report-row"><span class="report-date"><b>${esc(r.date)}</b><small>${r.checkout_count}笔</small></span><span class="mono">${yuan(r.gross_cents)}</span><span class="mono">${yuan(r.discount_cents)}</span><span class="mono">${yuan(r.due_cents)}</span><b class="mono">${yuan(r.registered_cents)}</b></div>`).join('')}`:'<div class="history-report-empty">当前日期范围内没有结账数据</div>';
   const closed=obj.history||[];
   $('historyClosures').innerHTML=closed.length?closed.map(v=>`<div class="visit-row"><div><div class="visit-seat">${esc(v.seat_label)} · ${v.status==='CANCELLED'?'已撤单':'已离店'}</div><div class="visit-caption">${chinaFull(v.created_at)} 至 ${chinaFull(v.closed_at)} · 桌次 ${esc(v.id.slice(0,8))}</div></div><button class="outline" data-receipt="${esc(v.id)}">查看完整单据</button></div>`).join(''):'<p class="small-muted">选定日期暂无已结束的桌次；未离店但已分次结账的登记仍统计在上方</p>';
   $('historyClosures').querySelectorAll('[data-receipt]').forEach(b=>b.onclick=safe(()=>showReceipt(b.dataset.receipt,false)));
 }
 const items=obj.checkouts||[];
 const html=items.map(c=>`<div class="visit-row"><div class="history-checkout-main"><div class="visit-seat">${esc(c.seat_label)} · ${yuan(c.registered_cents)}</div><div class="visit-caption">${chinaFull(c.created_at)} · ${c.item_count}件商品 · ${c.visit_status==='OPEN'?'客人仍在店':'桌次已结束'}</div><div class="visit-caption">账面 ${yuan(c.gross_cents)} · 优惠 ${yuan(c.discount_cents)} · 折后应收 ${yuan(c.due_cents)} ${c.difference_cents?' · ⚠ 差额 '+yuan(c.difference_cents):''}</div></div><button class="outline" data-receipt="${esc(c.visit_id)}">查完整结账单</button></div>`).join('');
 const list=$('historyList');
 if(loadMore)list.insertAdjacentHTML('beforeend',html);
 else list.innerHTML=html||'<p class="small-muted">当前筛选日期没有结账登记</p>';
 list.querySelectorAll('[data-receipt]').forEach(b=>{if(!b.dataset.wired){b.dataset.wired='1';b.onclick=safe(()=>showReceipt(b.dataset.receipt,false));}});
 historyOffset=obj.offset+items.length;
 $('historyCount').textContent=`已显示 ${historyOffset} / ${summary.checkout_count||0} 笔结账登记`;
 $('historyMore').classList.toggle('hidden',!obj.has_more);
}
async function showReceipt(visitId,printWanted){const r=await getJson('/api/receipt?visit_id='+encodeURIComponent(visitId)),v=r.visit,store=r.store;
 const seatTrace=v.seat_history.map(x=>`${esc(x.from_label||'初始入座')} → ${esc(x.to_label)}（${chinaTime(x.created_at)}）`).join('<br/>');
 const lines=v.lines.filter(x=>x.status!=='CANCELLED');const total=lines.reduce((sum,l)=>sum+l.price_cents*l.quantity,0);
 const settled=v.checkouts.reduce((sum,x)=>sum+x.amount_cents,0);
 $('receiptContent').innerHTML=`<div class="receipt-paper"><div class="receipt-watermark">消费记录 · 收款待核验</div>
 <h2>BAR ST. VINCENT</h2><p class="receipt-sub">电子消费记录 / 结账单</p><h3>${esc(store.name)}</h3>
 <p>${esc(store.district)} · ${esc(store.business_type)}</p><p>门店编号：${esc(store.id)}</p><p>桌次编号：${esc(v.id)}</p>
 <p>到店时间：${chinaFull(v.created_at)}<br/>离店时间：${chinaFull(v.closed_at)}</p>
 <p>座位变更：<br/>${seatTrace||esc(v.seat_id)}</p>
 <p>登记人数：${v.guests}<br/>关联会员：${esc(v.member_references.map(x=>x.member_reference).join('、')||'未关联')}</p>
 <div class="receipt-divider"></div><h4>商品 / 下单时间 / 上桌时间</h4>
 ${lines.map(l=>`<div class="receipt-line"><strong>${esc(l.product_name_snapshot)} ×${l.quantity}</strong><span>${yuan(l.price_cents*l.quantity)}</span></div><small>下单 ${chinaTime(l.created_at)} · 制作 ${esc(l.maker_code||'未记录')} · 送达 ${esc(l.delivered_by||'未记录')} · 上桌 ${chinaTime(l.served_at)} · ${esc(l.status)}</small>`).join('')}
 <div class="receipt-divider"></div><div class="receipt-line"><strong>商品消费累计</strong><strong>${yuan(total)}</strong></div>
 <div class="receipt-line"><span>已登记结账合计</span><strong>${yuan(settled)}</strong></div><div class="receipt-divider"></div>
 <p>结账登记次数：${v.checkouts.length}</p>${v.checkouts.map((x,i)=>`<p>${i+1}. ${chinaFull(x.created_at)} · ${yuan(x.amount_cents)}</p>`).join('')}
 <p>纸质选择：${v.closure?.print_preference==='PAPER'?'需要纸质版':'不需要纸质版或尚未离店'}</p>
 <p class="receipt-disclaimer">支付机构尚未连接：以上结账登记均未核验真实到账，不是发票或有效收款证明。</p></div>`;
 $('receiptModal').classList.remove('hidden');if(printWanted)flash({title:'已生成结账单',subject:'请选择是否打印纸质版',detail:'打印预览并不代表收款已核验'});}
function openManual(){const store=data.store;
 const available=data.documents.filter(d=>d.available && d.kind.startsWith('FLOOR'));
 const docImg=available.map(d=>d.file_url?`<details class="original-image"><summary>${esc(d.title)}</summary><img class="manual-floor-image" src="${esc(d.file_url)}" alt="${esc(d.title)}" /></details>`:'').join('');
 $('manualContent').innerHTML=`<p class="eyebrow">BSV1 · ${esc(store.id)} · 门店资料</p><h2>${esc(store.name)}｜工作资料</h2>
 <div class="manual-meta"><span>${esc(store.district)}</span><span>${esc(store.business_type)}</span><span>${esc(store.id)}</span></div>
 <div class="manual-section"><h3>员工手册与设备工作流程</h3><p>本店正式员工手册 PDF 尚未导入。未来这里展示设备使用注意事项、交接和安全规则，仅允许本店授权员工访问。</p><button class="outline" disabled>员工手册 PDF · 待导入</button></div>
 <div class="manual-section"><h3>本店原始图纸与座位编号</h3>${docImg||'<p>本店图纸尚未上传。</p>'}</div>
 <div class="manual-section"><h3>方向识别原则</h3><p>座位左右关系以调酒师在吧台内实际工作位置的视角为准；左右邻座由本店独立定义，不能跨店继承。</p></div>`;
 $('manualModal').classList.remove('hidden');
}
function updateClockUI(){if(!data)return;
 document.querySelectorAll('.time-counter').forEach(node=>{const age=elapsed(node.dataset.start),sev=severity(age);node.textContent=waitLabel(age);
 const parent=node.closest('.work-item,.queue-task');if(parent){parent.classList.remove('normal','warning','late','critical');parent.classList.add(sev);}});
 const buck=allPending().map(x=>severity(elapsed(x.created_at))).join('|')+'|'+data.bathrooms.map(b=>bathroomStage(b).sev).join('|')+
 '|'+data.seats.filter(s=>s.cleaning_state==='DIRTY').map(s=>seatCleaningStage(s).sev).join('|');
 if(buck!==ageBucket){ageBucket=buck;renderAlerts(allPending(),data.seats.filter(x=>x.enabled&&x.cleaning_state==='DIRTY'),data.bathrooms.filter(cleanStatus));}
 if(page==='map'){renderSeats();}if(page==='queue'){renderQueue();}if(page==='clean')renderCleaning();
}
function setPage(next){page=next;render();if(next==='catalog')renderCatalogList();if(next==='history')renderHistory().catch(e=>flash(e.message,true));
 if(next==='audit')loadAudit().catch(e=>flash(e.message,true));}

document.querySelectorAll('.nav-button').forEach(b=>b.onclick=()=>setPage(b.dataset.page));
 document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{const [scope,range]=b.dataset.range.split(':');
  if(scope==='audit')auditRange=range;else {historyRange=range;if(range==='custom'&&(!$('historyFrom').value||!$('historyTo').value)){$('historyFrom').value=chinaDay().slice(0,8)+'01';$('historyTo').value=chinaDay();}}
  document.querySelectorAll('[data-range^="'+scope+':"]').forEach(x=>x.classList.toggle('is-active',x===b));
  if(scope==='audit')loadAudit().catch(e=>flash(e.message,true));else renderHistory().catch(e=>flash(e.message,true));});
 $('auditCategory').onchange=()=>{auditCategory=$('auditCategory').value;loadAudit().catch(e=>flash(e.message,true));};
 ['audit','history'].forEach(scope=>{['From','To'].forEach(part=>$(scope+part).onchange=()=>{
   if(scope==='audit')auditRange='custom';else historyRange='custom';
   document.querySelectorAll('[data-range^="'+scope+':"]').forEach(x=>x.classList.remove('is-active'));
   (scope==='audit'?loadAudit():renderHistory()).catch(e=>flash(e.message,true));
 });});

async function logoutCurrent(){await send('/api/logout');showLogin();flash('已退出当前门店，请重新选择地区和具体门店');}
$('logoutBtn').onclick=safe(logoutCurrent);
$('switchStoreBtn').onclick=()=>dialog({eyebrow:'防误操作 · 门店切换',title:'退出当前门店并重新选择？',
 body:`<p>当前为 <b>${esc(data.store.name)}</b>。切换门店必须重新选择地区、具体门店，并以授权员工代码重新登录。</p>`,
 confirmText:'确认退出，重新选择',onConfirm:logoutCurrent});
$('refreshBtn').onclick=safe(async()=>{await refresh();await loadHealth(true);if(page==='history')await renderHistory();flash('已从本店数据库刷新');});
$('systemCheckBtn').onclick=safe(async()=>{await loadHealth();openHealthDialog();});
$('systemCheckBadge').onclick=safe(async()=>{if(!systemHealth)await loadHealth();openHealthDialog();});
$('historyMore').onclick=safe(()=>renderHistory(true));
$('historyExport').onclick=safe(async()=>{validateHistoryFilter();const path='/api/reports/checkout-csv?'+getRangeParams('history');const a=document.createElement('a');a.href=path;a.download='';document.body.appendChild(a);a.click();a.remove();});
$('catalogBtn').onclick=()=>setPage('catalog');
$('catalogSearch').oninput=renderCatalogList;$('catalogDomain').onchange=renderCatalogList;
$('closeCatalogDetail').onclick=()=>$('catalogDetailModal').classList.add('hidden');
$('catalogDetailModal').onclick=e=>{if(e.target===$('catalogDetailModal'))$('catalogDetailModal').classList.add('hidden');};
$('sourceImageBtn').onclick=openManual;$('closeManual').onclick=()=>$('manualModal').classList.add('hidden');
$('manualModal').onclick=e=>{if(e.target===$('manualModal'))$('manualModal').classList.add('hidden');};
$('closeReceipt').onclick=()=>$('receiptModal').classList.add('hidden');
$('printReceiptBtn').onclick=()=>window.print();$('receiptModal').onclick=e=>{if(e.target===$('receiptModal'))$('receiptModal').classList.add('hidden');};

$('detailSheet').addEventListener('click',e=>{if(e.target===$('detailSheet'))setPage('map');});
$('detailDismiss').onclick=()=>setPage('map');
$('modal').addEventListener('click',e=>{if(e.target===$('modal'))$('modalCancel').click();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){
 if(guideShown()){if(!$('guideInfoPop').classList.contains('hidden'))guideCloseInfo();else guideClose();return;}
 if(!$('modal').classList.contains('hidden'))$('modalCancel').click();
 $('manualModal').classList.add('hidden');$('receiptModal').classList.add('hidden');$('catalogDetailModal').classList.add('hidden');if(page!=='map')setPage('map');}});
window.addEventListener('resize',()=>{document.documentElement.style.setProperty('--app-height',window.innerHeight+'px');});document.documentElement.style.setProperty('--app-height',window.innerHeight+'px');
setInterval(updateClockUI,1000);
setInterval(()=>{if(data&&document.visibilityState==='visible'&&!busy)heartbeat();},20000);
setInterval(()=>{if(data&&!busy&&!transfer&&$('modal').classList.contains('hidden')&&document.visibilityState==='visible'){
 refresh(true).then(()=>{if(guideShown()){guideTaskList();if(!guideCurrentTask()){guideClose();flash('当前制作任务已发生变化，请重新确认');}else guideUpdateActions();}syncFailures=0;$('syncOffline').classList.add('hidden');}).catch(e=>{
   syncFailures++;if(syncFailures>=2){$('syncOffline').classList.remove('hidden');}
   else flash('数据同步失败，请检查连接：'+e.message,true);
 });
 }},9000);
$('offlineRetry').onclick=safe(async()=>{await refresh();await loadHealth(true);syncFailures=0;$('syncOffline').classList.add('hidden');flash({title:'数据连接已恢复',detail:'请核实当前门店订单与清洁状态'});});
async function init(){try{const init=await getJson('/api/bootstrap');allStores=init.stores;wireLocation();await loadHealth(true);
 try{await getState();showApp();render();showPendingCritical();}catch{showLogin();renderSystemHealth();}}catch(e){$('loginError').textContent='服务器未初始化：'+e.message;showLogin();renderSystemHealth();}}
setInterval(()=>{if(document.visibilityState==='visible')loadHealth(true);},30000);
init();
})();
