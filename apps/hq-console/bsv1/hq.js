'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let cur=null,storeId='',selected=null,dragging=null,layoutApproved=false;
function say(t,err=false){$('status').textContent=t;$('status').style.color=err?'#b83225':'#294b5c'}
function identityCsrf(){const part=document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith('bsv_csrf='));return part?decodeURIComponent(part.slice('bsv_csrf='.length)):''}
async function api(path,method='GET',data=null){const headers={};if(data){headers['Content-Type']='application/json';headers['X-CSRF-Token']=identityCsrf()}let r;try{r=await fetch(path,{method,credentials:'same-origin',headers,body:data?JSON.stringify(data):undefined,cache:'no-store'})}catch(error){error.uncertain=true;throw error}let j;try{j=await r.json()}catch{j={}}if(!r.ok){const error=Error(j.error||'请求未成功');error.status=r.status;throw error}return j}
function active(){return cur?.layout?.seats?.find(s=>s.id===selected)}
function render(){if(!cur)return;let c=cur.layout; $('revision').textContent=`门店 ${storeId} · ${layoutApproved?'已批准地图 V':'待现场核验底稿 V'}${cur.version} · 地图座位 ${c.seats.length} 个`;
 $('mapArt').src=cur.layout.background_asset_id?`/api/hq/image?store_id=${encodeURIComponent(storeId)}&asset_id=${encodeURIComponent(cur.layout.background_asset_id)}`:`/api/hq/art?store_id=${encodeURIComponent(storeId)}&v=${cur.version}&t=${Date.now()}`;
 $('seatLayer').innerHTML=c.seats.map(s=>`<button class="seat ${s.id===selected?'active':''}" data-id="${esc(s.id)}" style="left:${Math.max(1,Math.min(99,s.x))}%;top:${Math.max(1,Math.min(99,s.y))}%">${esc(s.label)}<small>${esc(s.capacity??'?')}人</small></button>`).join('');
 document.querySelectorAll('.seat').forEach(e=>{
   e.addEventListener('pointerdown',ev=>{selected=e.dataset.id;dragging={id:selected};e.setPointerCapture(ev.pointerId);drawEditor();e.classList.add('active');});
   e.addEventListener('pointermove',ev=>{if(!dragging||dragging.id!==e.dataset.id)return;const r=$('canvas').getBoundingClientRect();const s=active();s.x=Math.max(1,Math.min(99,Math.round((ev.clientX-r.left)/r.width*1000)/10));s.y=Math.max(1,Math.min(99,Math.round((ev.clientY-r.top)/r.height*1000)/10));e.style.left=s.x+'%';e.style.top=s.y+'%';$('x').value=s.x;$('y').value=s.y;});
   e.addEventListener('pointerup',()=>{dragging=null;render();});e.addEventListener('pointercancel',()=>{dragging=null;render();});e.onclick=()=>{selected=e.dataset.id;render()};
 });drawEditor();
 $('history').innerHTML=cur.revisions.map(r=>`<button type="button" data-revision="${esc(r.revision_id)}">${r.status} · ${esc(r.revision_id.slice(0,22))} · ${esc(r.created_at.slice(0,19))}</button>`).join('');
 document.querySelectorAll('#history button').forEach(e=>e.onclick=()=>say('当前仅开放历史记录查看；恢复写入暂未开放。'));
}
function drawEditor(){const s=active();$('editor').hidden=!s;$('noSelection').hidden=!!s;if(!s)return;
 for(const k of ['seatId','label','kind','capacity','order','x','y'])$(k).value=(k==='seatId'?s.id:s[k]??'');
 const options='<option value="">— 无 —</option>'+cur.layout.seats.filter(x=>x.id!==s.id).map(x=>`<option value="${esc(x.id)}">${esc(x.label)}</option>`).join('');
 for(const side of ['left','right']){$(side).innerHTML=options;$(side).value=cur.layout.neighbors[s.id]?.[side]||'';}
}
function onForm(){const s=active();if(!s)return;for(const k of ['label','kind'])s[k]=$(k).value.trim();for(const k of ['capacity','order'])s[k]=Number($(k).value);for(const k of ['x','y'])s[k]=Number($(k).value);cur.layout.neighbors[s.id]={left:$('left').value||null,right:$('right').value||null};render()}
async function load(id){storeId=id;selected=null;cur=await api('/api/hq/layout?store_id='+encodeURIComponent(id));$('store').value=id;
 const d=(await api('/api/hq/stores')).stores.find(x=>x.id===id);layoutApproved=!!d?.layout_ready;$('storeInfo').textContent=d?`${d.district} · ${d.name} · ${d.layout_ready?'座位图已发布':'尚未发布地图'}`:'';render();say(`已加载 ${id} · ${layoutApproved?'已批准':'待现场校准'}地图 V${cur.version}`)}
async function refreshStores(){const all=(await api('/api/hq/stores')).stores;$('store').innerHTML=all.map(s=>`<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.name)}</option>`).join('');return all;}
$('store').onchange=()=>load($('store').value).catch(e=>say(e.message,true));
$('newStore').disabled=true;$('uploadImage').disabled=true;$('publish').disabled=true;
$('addSeat').onclick=()=>{if(!cur)return;const all=cur.layout.seats;let i=1;while(all.some(x=>x.id===`${storeId}-SEAT-${String(i).padStart(4,'0')}`))i++;
 const id=`${storeId}-SEAT-${String(i).padStart(4,'0')}`,max=Math.max(0,...all.map(x=>x.order||0));all.push({id,label:'新座位'+i,kind:'TABLE',x:50,y:50,order:max+10,capacity:2,group_id:null,is_secondary:false});cur.layout.neighbors[id]={left:null,right:null};selected=id;render();say('新增座位仅存在浏览器编辑草稿，保存后才能审核发布。')};
$('deleteSeat').onclick=()=>{const s=active();if(!s||!confirm(`从新地图移除 ${s.label}？正式ID不可重用；营业中的座位不能移除。`))return;
 cur.layout.seats=cur.layout.seats.filter(x=>x.id!==s.id);delete cur.layout.neighbors[s.id];Object.values(cur.layout.neighbors).forEach(x=>{if(x.left===s.id)x.left=null;if(x.right===s.id)x.right=null;});if(cur.layout.groups.some(g=>g.primary_seat===s.id||g.secondary_seat===s.id)){say('此座位有关联合分桌组，请先处理，暂不修改草稿。',true);return load(storeId);}selected=null;render()};
$('save').onclick=async()=>{const button=$('save');button.disabled=true;let acknowledged=false;try{onForm();const j=await api('/api/hq/layout/draft','POST',{store_id:storeId,base_version:cur.version,layout:cur.layout});acknowledged=true;await load(storeId);if(!cur.revisions.some(r=>r.revision_id===j.revision_id)){say('草稿请求已返回，但刷新后未找到记录，结果暂未确认；请检查门店历史后再决定是否重试。',true);return}say(`草稿 ${j.revision_id} 已确认保存；正式POS地图仍为 V${cur.version}，未发布。`)}catch(e){if(acknowledged||e.uncertain)say('保存结果暂未确认，请检查当前地图版本和历史后再决定是否重试。',true);else say('草稿未保存：'+e.message,true)}finally{button.disabled=false}};
$('export').onclick=()=>{if(!cur)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(cur.layout,null,2)],{type:'application/json'}));a.download=`${storeId}_layout_draft.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('import').onclick=()=>$('importFile').click();$('importFile').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;try{if(f.size>60000)throw Error('JSON 文件太大');const d=JSON.parse(await f.text());if(d.store_id!==storeId)throw Error('禁止导入其他门店地图');cur.layout=d;selected=null;render();say('AI 候选 JSON 已导入浏览器，尚未保存和发布。请先逐个核对。')}catch(err){say(err.message,true)}finally{e.target.value=''}};
for(const id of ['label','kind','capacity','order','x','y','left','right'])$(id).addEventListener('change',onForm);
(async()=>{try{await api('/api/hq/status');$('kind').innerHTML=['SOFA','ROUND','BAR','WINDOW','BOOTH','TEMP','TABLE','OTHER'].map(v=>`<option value="${v}">${v}</option>`).join('');const stores=await refreshStores();const mods=await api('/api/hq/modules');$('modules').innerHTML=mods.modules.map(m=>`<div class="mod"><b>${esc(m.name)}</b><small>${esc(m.state)}</small></div>`).join('');if(stores.length)await load(stores[0].id);else say('当前身份暂未获准查看地图。',true)}catch(e){say(e.message+'；请检查总部地图授权或返回总部人员管理。',true)}})();
