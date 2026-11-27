'use strict';
const $ = id=>document.getElementById(id);
const state={me:null,stores:[],items:[],shipment:null,scanned:new Set(),camStream:null,camTimer:null,tab:'tasks',mode:'demo'};
const zhState={DRAFT:'草稿',READY:'待发货',DISPATCHED:'在途',PARTIAL_RECEIVED:'部分收货',RECEIVED:'已收齐',DISPUTED:'有差异',CLOSED:'已结案'};
const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const internal=location.pathname.startsWith('/supply-ui/');
const workspace=location.pathname.includes('/inspector/')?'inspector':location.pathname.includes('/store/')?'store':'hq';
const uid=()=>crypto.randomUUID();
function message(s,bad=false){let d=$('feedback');d.className='show '+(bad?'bad':'good');d.textContent=s;}
async function req(path,opts={}){
 let headers={...opts.headers};if(opts.body&&! (opts.body instanceof FormData))headers['Content-Type']='application/json';
 if(state.mode==='remote'&&state.token)headers.Authorization='Bearer '+state.token;
 if(state.mode==='demo'&&(state.demoActor||(workspace==='inspector'?'DEMO-E03':workspace==='store'?'DEMO-E02':null)))headers['X-Demo-Actor']=(state.demoActor||(workspace==='inspector'?'DEMO-E03':workspace==='store'?'DEMO-E02':null));
 if(internal&&opts.method&&opts.method!=='GET'){
  const csrf=document.cookie.split('; ').find(x=>x.startsWith('bsv_csrf='));
  if(csrf)headers['X-CSRF-Token']=csrf.slice('bsv_csrf='.length);
 }
 const writing=opts.method&&opts.method!=='GET';
 let r;
 try{r=await fetch((internal?'/supply-ui':'')+'/api'+path,{signal:AbortSignal.timeout(11000),...opts,headers});}
 catch{throw Error(writing?'结果暂未确认。请先查看记录，再决定是否重试。':'暂时无法获取结果。请检查连接后重试。');}
 if(opts.response==='html'&&r.ok&&r.headers.get('content-type')?.includes('text/html'))return r.text();
 const j=await r.json().catch(()=>null);
 if(!r.ok||!j){
   let detail='暂时无法获取结果。请稍后重试。';
   if(r.status===401)detail='登录已过期，请重新登录后继续。';
   else if(r.status===403)detail='当前账号不能执行这项操作。请向总部核对相应门店权限。';
   else if(j?.detail==='中央 D/E 权威服务未接入，未提交且未排队')detail='暂不能提交：中央台账尚未连接，本次未写入记录。';
   else if(writing&&(r.status>=500||!j))detail='结果暂未确认。请先查看记录，再决定是否重试。';
   else if(r.status===422)detail='请核对所填门店、数量和记录内容后再提交。';
   else if(r.status===409)detail='记录已变化。请查看最新记录，再继续。';
   if(opts.raw&&[404,409,422].includes(r.status)&&typeof j?.detail==='string')detail=j.detail.slice(0,200);
   throw Object.assign(Error(detail),{status:r.status});
 }
 if(opts.raw)return j;
 if(r.status===202)message('⚠ 已离线暂存，但尚未写入公司正式库存。必须在网络恢复后同步确认。',true);
 return j.state==='COMMITTED'&&j.data?j.data:j;
}
function on(id,evt,fn){$(id).addEventListener(evt,fn);}
function tab(k){if(state.camStream&&state.tab!==k)stopCamera();state.tab=k;document.querySelectorAll('.panel').forEach(x=>x.classList.add('hidden'));$('panel-'+k).classList.remove('hidden');document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.dataset.tab===k));if(k==='stock')loadInventory();if(k==='sources')loadSources();if(k==='inspect')loadInspections();if(k==='central')showCentralView();}
function opts(items,placeholder){return `${placeholder?'<option value="">'+placeholder+'</option>':''}${items.map(x=>`<option value="${escapeHtml(x.store_id)}">${escapeHtml(x.name_zh)} (${escapeHtml(x.store_id)})</option>`).join('')}`;}
async function boot(){if(internal)return internalReadOnly();try{let h=await req('/health');state.mode=h.mode;state.centralCandidate=h.central_candidate===true;$('mode').textContent=h.mode==='demo'?'独立演示 · 非生产':'公司中央 API 模式';if(state.mode==='remote'){let t=prompt('请输入公司统一身份令牌（仅本次页面内存持有，不保存至浏览器）');if(!t)return message('未登录：生产模式需要统一身份令牌。',true);state.token=t;}state.me=await req('/me');configureWorkspace();let [a,b]=await Promise.all([req('/stores'),req('/items')]);state.stores=a.data||[];state.items=b.data||[];let o=opts(state.stores);['filter-store','stock-store'].forEach(id=>$(id).innerHTML='<option value="">全部授权网点</option>'+o);['source-store','dest-store','inspect-store','count-store'].forEach(id=>$(id).innerHTML=o);$('count-item').innerHTML=state.items.map(x=>`<option value="${escapeHtml(x.item_id)}">${escapeHtml(x.name_zh)}</option>`).join('');$('create-item').innerHTML=state.items.map(x=>`<option value="${escapeHtml(x.item_id)}">${escapeHtml(x.name_zh)} · ${escapeHtml(x.item_id)}</option>`).join('');if(state.centralCandidate)enableCentral();if(workspace==='inspector')tab('inspect');else loadShipments();}catch(e){message(e.message,true);}}
async function internalReadOnly(){
 const inspector=workspace==='inspector';
 const title=inspector?'独立督查':'供货与库存';
 document.body.classList.add('internal-stage');
 $('mode').textContent='内部演练';
 document.querySelectorAll('main .panel').forEach(panel=>panel.classList.add('hidden'));
 $('stage-limits').classList.remove('hidden');
 $('stage-title').textContent=title;
 document.querySelector('.brand strong').textContent=title;
 document.querySelector('.brand small').textContent='BSV · 内部工作';
 const button=$('stage-refresh'),availability=$('stage-availability'),scope=$('stage-authorization');
 if(button.disabled)return;
 const buttonText=button.textContent;
 button.disabled=true;
 button.textContent='正在核对…';
 availability.textContent='正在核对服务与权限…';
 scope.replaceChildren();
 try{
   const health=await req('/health');
   if(health.mode!=='internal-stage')throw Error('暂时无法确认演练模式。请从工作台重新进入。');
   state.mode=health.mode;
   availability.textContent=inspector?'仅查看。正式检查台账尚未连接，暂不能提交或复核督查记录。':'暂未启用。中央台账尚未连接，暂不能创建配送单、收货或登记盘点。';
   const me=await req('/me');
   const keys=inspector?['inspect_independent','review_independent']:['dispatch','receive','inspect'];
   const actions={inspect_independent:'独立督查',review_independent:'复核督查',dispatch:'发货',receive:'收货',inspect:'门店自查'};
   const list=document.createElement('ul');
   for(const key of keys){
     const stores=me.role_stores?.[key];
     if(stores?.length){
       const row=document.createElement('li');
       row.textContent=actions[key]+' · '+stores.join('、');
       list.append(row);
     }
   }
   const heading=document.createElement('h2');
   heading.textContent='你的门店权限';
   scope.append(heading);
   if(list.children.length)scope.append(list);
   else{
     const unavailable=document.createElement('p');
     unavailable.textContent='当前没有这项工作的门店权限。需要时请联系总部。';
     scope.append(unavailable);
   }
 }catch(error){
   if(error.status===401||error.status===403){
     scope.textContent=error.status===401?'请先进入个人中心登录，再回来核对权限。':'当前账号没有这项工作的门店权限。需要时请联系总部。';
   }else{
     if(availability.textContent==='正在核对服务与权限…')availability.textContent='暂时无法确认服务状态。请检查连接后重新核对。';
     scope.textContent='暂时无法读取门店权限。请稍后重试。';
   }
 }finally{
   button.disabled=false;
   button.textContent=buttonText;
 }
}
$('stage-refresh').onclick=internalReadOnly;
function configureWorkspace(){
 const roles=state.me.roles||[];
 const sections=workspace==='inspector'?['inspect','sources']:
    workspace==='store'?['tasks','stock','inspect','sources']:['tasks','create','stock','inspect','sources'];
 document.querySelectorAll('nav button').forEach(button=>{
   button.hidden=!sections.includes(button.dataset.tab) || (button.dataset.tab==='create'&&!roles.includes('dispatch'));
 });
 $('inspect-submit').hidden=!roles.includes(workspace==='inspector'?'inspect_independent':'inspect');
}
async function loadShipments(){try{let id=$('filter-store').value;let r=await req('/shipments'+(id?'?store_id='+encodeURIComponent(id):''));$('shipments').innerHTML=(r.data||[]).length?(r.data||[]).map(x=>`<div class="card"><div><div class="card-title">${escapeHtml(x.src)} → ${escapeHtml(x.dest)}</div><div class="meta">${escapeHtml(x.id)} · ${escapeHtml(x.created_at||'')} · 版本 ${escapeHtml(x.version)}</div></div><div><span class="state">${escapeHtml(zhState[x.state]||x.state)}</span> <button data-open="${escapeHtml(x.id)}">打开</button></div></div>`).join(''):'<p class="hint">当前没有配送任务，可创建演示单据。</p>';document.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openShipment(b.dataset.open)));}catch(e){message(e.message,true);}}
async function openShipment(sid){try{let r=await req('/shipments/'+encodeURIComponent(sid));state.shipment=r.data;state.scanned.clear();drawShipment();}catch(e){message(e.message,true);}}
function drawShipment(){const s=state.shipment;if(!s)return;let d=$('shipment-detail');d.classList.remove('hidden');const packs=s.packages||[];let isDemo=state.mode==='demo';const action=s.state==='DRAFT'?'prepare':s.state==='READY'?'dispatch':(['DISPATCHED','PARTIAL_RECEIVED','DISPUTED'].includes(s.state)?'receive':'done');let pending=packs.filter(p=>p.state==='IN_TRANSIT');let target=action==='dispatch'?packs:pending;d.innerHTML=`<h2>配送单 ${escapeHtml(s.id)}</h2><p class="meta">${escapeHtml(s.src)} → ${escapeHtml(s.dest)}　｜ ${escapeHtml(zhState[s.state]||s.state)}　｜总数 ${packs.length}　｜已收 ${escapeHtml(s.received_count)}　｜当前版本 ${escapeHtml(s.version)}</p><div class="tablewrap"><table><thead><tr><th>中文品名</th><th>固定ID</th><th>包装二维码编号</th><th>状态</th></tr></thead><tbody>${packs.map(p=>`<tr><td>${escapeHtml(state.items.find(x=>x.item_id===p.item_id)?.name_zh||p.item_id)}</td><td>${escapeHtml(p.item_id)}</td><td>${escapeHtml(p.code)}</td><td>${escapeHtml(p.state)}</td></tr>`).join('')}</tbody></table></div>${action==='done'?'<div class="soft">这张配送单已全部收货，不允许再次入库。</div>':`<div class="soft">${action==='prepare'?'请先确认备货清单。':action==='dispatch'?'请逐件扫齐所有包装码，再确认发货。':'只扫描真正收到的包装码；未扫到的保持在途，不能凭空填齐。'}</div>`}${['dispatch','receive'].includes(action)?`<div class="scans"><input id="scan-input" placeholder="扫码枪/手输包装ID，按回车" autofocus><button id="add-scan">加入扫码</button><button id="open-camera">打开相机</button></div><div class="scans"><label>拍照辅助识别 <input id="photo-file" type="file" accept="image/*" capture="environment"></label><button id="photo-preview">分析照片</button></div>${isDemo?'<button id="demo-scan" class="outline">演示：填入待处理包装码</button>':''}<div id="scan-list" class="chips"></div>`:''}<div class="actions"><button class="primary" id="confirm-action" ${action==='done'?'disabled':''}>${action==='prepare'?'确认备货':action==='dispatch'?'确认发货':action==='receive'?'确认本次收货':'已结束'}</button>${action==='receive'?'<select id="condition"><option value="ACCEPTED">合格入库</option><option value="HOLD">异常隔离</option></select>':''}</div><p class="hint">所有正式库存动作以中央 API 返回 COMMITTED 为准；待同步不是已收货。</p>`;
 if(action==='done')return;
 if(action!=='prepare'){
  const add=()=>{let inp=$('scan-input');let code=inp.value.trim();if(!code)return;const available=target.some(p=>p.code===code);if(!available)return message('包装码不在当前可操作清单里，不能随意收货。',true);state.scanned.add(code);inp.value='';drawChips();inp.focus();};
  $('add-scan').onclick=add;$('scan-input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();add();}};
  $('open-camera').onclick=startCamera;
  $('photo-preview').onclick=async()=>{let f=$('photo-file').files[0];if(!f)return message('请先选择照片',true);let fd=new FormData();fd.append('file',f);try{let r=await req('/photo-preview',{method:'POST',body:fd});let added=0;(r.recognized_package_ids||[]).forEach(c=>{if(target.some(p=>p.code===c)){state.scanned.add(c);added++;}});drawChips();message(`照片模式 ${r.mode}；识别出并与本单匹配 ${added} 个包装码。仍需人工核对并确认。${(r.unknown_regions||[]).join(' ')}`);}catch(e){message(e.message,true);}};
  if(isDemo)$('demo-scan').onclick=()=>{target.forEach(p=>state.scanned.add(p.code));drawChips();};
  drawChips();
 }
 $('confirm-action').onclick=async()=>{if(!confirm('请确认已核对实际货物。提交之后会生成不可直接删除的交易事件。'))return;try{const body={request_id:uid(),expected_version:s.version};if(action!=='prepare')body.scanned_codes=[...state.scanned];if(action==='receive')body.condition=$('condition').value;const result=await req('/shipments/'+encodeURIComponent(s.id)+'/'+action,{method:'POST',body:JSON.stringify(body)});message(result.state==='QUEUED_NOT_COMMITTED'?'操作已排队，尚未入账':'操作成功：'+(zhState[result.state]||'已提交'));state.shipment=null;d.classList.add('hidden');await loadShipments();}catch(e){message(e.message,true);}};
}
function drawChips(){let n=$('scan-list');if(n)n.innerHTML=`已扫描 ${state.scanned.size} 个：`+[...state.scanned].map(c=>`<span class="chip">${escapeHtml(c)} <button data-rem="${escapeHtml(c)}" style="border:none;padding:0;background:none">×</button></span>`).join('');document.querySelectorAll('[data-rem]').forEach(b=>b.onclick=()=>{state.scanned.delete(b.dataset.rem);drawChips();});}
async function startCamera(onCode){if(!navigator.mediaDevices||!window.BarcodeDetector){return message('此浏览器不支持连续二维码识别。请用手机原生相机拍照辅助，或手动输入包装ID。',true);}try{let stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});state.camStream=stream;$('camera-modal').classList.remove('hidden');let video=$('camera-video');video.srcObject=stream;let decoder=new BarcodeDetector({formats:['qr_code']});state.camTimer=setInterval(async()=>{try{let rs=await decoder.detect(video);for(let r of rs){if(typeof onCode==='function'){onCode(r.rawValue);continue;}let input=$('scan-input');if(input){input.value=r.rawValue;$('add-scan').click();}}}catch(e){}},350);}catch(e){message('摄像头授权或HTTPS环境不满足：'+e.message,true);}}
function stopCamera(){if(state.camTimer)clearInterval(state.camTimer);state.camTimer=null;state.camStream?.getTracks().forEach(t=>t.stop());state.camStream=null;$('camera-modal').classList.add('hidden');}
async function loadInventory(){try{let id=$('stock-store').value;let r=await req('/inventory'+(id?'?store_id='+encodeURIComponent(id):''));$('stock-status').textContent=r.meta?.stale?'⚠ 当前展示本地或备用快照，不代表实时库存':'数据来源：'+(r.meta?.source||'中央');$('stock-list').innerHTML=(r.data||[]).map(x=>`<tr><td>${escapeHtml(x.location)}</td><td>${escapeHtml(state.items.find(i=>i.item_id===x.item_id)?.name_zh||x.item_id)}</td><td>${escapeHtml(x.item_id)}</td><td>${escapeHtml(x.qty)}</td></tr>`).join('')||'<tr><td colspan="4">暂无库存数据</td></tr>';}catch(e){message(e.message,true);}}
const checks=[['expiry','产品效期'],['temperature','储运温控'],['hygiene','现场卫生'],['equipment','设备安全'],['pricing','价格与团购'],['previous_actions','上次整改']];
function initInspect(){ $('inspect-fields').innerHTML=checks.map(([k,t],i)=>`<div class="inspect-row"><label>${i+1}. ${t}</label><select id="check-${k}"><option value="OK">正常</option><option value="ISSUE">异常</option><option value="NOT_CHECKED">未查</option></select></div>`).join('');}
async function submitInspect(){let d={request_id:uid(),store_id:$('inspect-store').value,subject_department:$('subject-dept').value,subject_employee:$('subject-person').value,kind:workspace==='inspector'?'independent':'self_check',results:{}};checks.forEach(([k])=>d.results[k]=$('check-'+k).value);try{let r=await req('/inspections',{method:'POST',body:JSON.stringify(d)});if(r.state==='QUEUED_NOT_COMMITTED')return;message('快检已记录。异常项目：'+((r.issues||[]).join('、')||'无')+'。如有安全问题必须同步现场处置。');loadInspections();}catch(e){message(e.message,true);}}
async function loadInspections(){
 try{
  const r=await req('/inspections');
  const kind=workspace==='inspector'?'independent':'self_check';
  $('inspections').innerHTML=(r.data||[]).filter(x=>x.kind===kind).slice(0,12).map(x=>{
    const canReview=!r.meta?.stale && kind==='independent' && !x.decision && state.me.roles.includes('review_independent')
      && x.inspector!==state.me.employee_id && x.subject_employee!==state.me.employee_id;
    return `<div class="card"><div><strong>${escapeHtml(x.store_id)}</strong>
      <p class="meta">核查人 ${escapeHtml(x.inspector)} · ${escapeHtml(x.created_at)} · ${escapeHtml(x.decision||'已记录')}</p>
      ${canReview?`<button data-review="${escapeHtml(x.id)}" data-decision="APPROVED">批准复核</button>
      <button data-review="${escapeHtml(x.id)}" data-decision="CHANGES_REQUIRED">要求整改</button>`:''}</div></div>`;
  }).join('')||'<p class="hint">尚无记录</p>';
  $('inspections').querySelectorAll('[data-review]').forEach(button=>button.onclick=async()=>{
    try{
      await req('/inspections/'+encodeURIComponent(button.dataset.review)+'/review',{
        method:'POST',body:JSON.stringify({request_id:uid(),decision:button.dataset.decision})
      });
      await loadInspections();
    }catch(e){message(e.message,true);}
  });
 }catch(e){message(e.message,true);}
}
async function loadSources(){try{let h=await req('/health');$('source-list').innerHTML=Object.entries(h.source_aliases).map(([k,v])=>`<div class="card"><div><strong>${k} · ${escapeHtml(v.name)}</strong><div class="meta">主数据源：${v.configured?'已配置':'未接入真实服务'}　｜备用只读：${v.standby_read?'已配置':'未配置'}</div></div></div>`).join('');let pending=await req('/pending');$('pending-status').textContent=`本人待同步/冲突记录：${pending.length}`;}catch(e){message(e.message,true);}}
on('reload','click',loadShipments);on('filter-store','change',loadShipments);on('stock-reload','click',loadInventory);on('count-submit','click',async()=>{try{const pct=$('count-percent').value;let d={request_id:uid(),store_id:$('count-store').value,item_id:$('count-item').value,full_packages:Number($('count-whole').value),opened_count:Number($('count-open').value),opened_percent:pct===''?null:Number(pct)};const r=await req('/stock-count',{method:'POST',body:JSON.stringify(d)});if(r.state==='QUEUED_NOT_COMMITTED')return;message('盘点已记录：'+r.status+'。这条观察不会直接调账。')}catch(e){message(e.message,true);}});on('stock-store','change',loadInventory);on('inspect-submit','click',submitInspect);on('pending-sync','click',async()=>{try{let r=await req('/pending/sync',{method:'POST'});message('同步执行完成：'+JSON.stringify(r));loadSources();}catch(e){message(e.message,true);}});on('create-submit','click',async()=>{try{let body={request_id:uid(),source_store_id:$('source-store').value,dest_store_id:$('dest-store').value,lines:[{item_id:$('create-item').value,packages:Number($('create-count').value)}]};let r=await req('/shipments',{method:'POST',body:JSON.stringify(body)});message(r.state==='QUEUED_NOT_COMMITTED'?'草稿已排队等待中央确认':'草稿创建成功 '+r.id);tab('tasks');await loadShipments();if(r.id)openShipment(r.id);}catch(e){message(e.message,true);}});on('camera-close','click',stopCamera);document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.tab)));initInspect();boot();
