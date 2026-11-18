'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let csrf='',cur=null,storeId='',selected=null,pendingRev=null,dragging=null,layoutApproved=false;
function say(t,err=false){$('status').textContent=t;$('status').style.color=err?'#b83225':'#294b5c'}
async function api(path,method='GET',data=null){const r=await fetch(path,{method,credentials:'same-origin',headers:{...(data?{'Content-Type':'application/json','X-BSV-CSRF':csrf}:{})},body:data?JSON.stringify(data):undefined,cache:'no-store'});const j=await r.json();if(!r.ok)throw Error(j.error||'HTTP '+r.status);return j}
function active(){return cur?.layout?.seats?.find(s=>s.id===selected)}
function render(){if(!cur)return;let c=cur.layout; $('revision').textContent=`门店 ${storeId} · ${layoutApproved?'已批准地图 V':'待现场核验底稿 V'}${cur.version} · 地图座位 ${c.seats.length} 个`;
 $('mapArt').src=cur.layout.background_asset_id?`/api/hq/image?store_id=${encodeURIComponent(storeId)}&asset_id=${encodeURIComponent(cur.layout.background_asset_id)}`:`/api/hq/art?store_id=${encodeURIComponent(storeId)}&v=${cur.version}&t=${Date.now()}`;
 $('seatLayer').innerHTML=c.seats.map(s=>`<button class="seat ${s.id===selected?'active':''}" data-id="${esc(s.id)}" style="left:${Math.max(1,Math.min(99,s.x))}%;top:${Math.max(1,Math.min(99,s.y))}%">${esc(s.label)}<small>${esc(s.capacity??'?')}人</small></button>`).join('');
 document.querySelectorAll('.seat').forEach(e=>{
   e.addEventListener('pointerdown',ev=>{selected=e.dataset.id;dragging={id:selected};e.setPointerCapture(ev.pointerId);drawEditor();e.classList.add('active');});
   e.addEventListener('pointermove',ev=>{if(!dragging||dragging.id!==e.dataset.id)return;const r=$('canvas').getBoundingClientRect();const s=active();s.x=Math.max(1,Math.min(99,Math.round((ev.clientX-r.left)/r.width*1000)/10));s.y=Math.max(1,Math.min(99,Math.round((ev.clientY-r.top)/r.height*1000)/10));e.style.left=s.x+'%';e.style.top=s.y+'%';$('x').value=s.x;$('y').value=s.y;});
   e.addEventListener('pointerup',()=>{dragging=null;render();});e.addEventListener('pointercancel',()=>{dragging=null;render();});e.onclick=()=>{selected=e.dataset.id;render()};
 });drawEditor();
 $('history').innerHTML=cur.revisions.map(r=>`<button data-revision="${esc(r.revision_id)}" ${r.status==='DRAFT'?'data-draft="1"':''}>${r.status} · ${esc(r.revision_id.slice(0,22))} · ${esc(r.created_at.slice(0,19))}</button>`).join('');
 document.querySelectorAll('#history button').forEach(e=>e.onclick=()=>{if(e.dataset.draft){pendingRev=e.dataset.revision;$('publish').disabled=false;say('已选择草稿 '+pendingRev+'。请校验内容并谨慎发布。');}else{if(!confirm('从历史版本生成新草稿？不会立即发布。'))return;api('/api/hq/layout/restore','POST',{store_id:storeId,revision_id:e.dataset.revision}).then(j=>{pendingRev=j.revision_id;$('publish').disabled=false;say('已生成历史回滚草稿。请确认后发布。');}).catch(err=>say(err.message,true));}});
}
function drawEditor(){const s=active();$('editor').hidden=!s;$('noSelection').hidden=!!s;if(!s)return;
 for(const k of ['seatId','label','kind','capacity','order','x','y'])$(k).value=(k==='seatId'?s.id:s[k]??'');
 const options='<option value="">— 无 —</option>'+cur.layout.seats.filter(x=>x.id!==s.id).map(x=>`<option value="${esc(x.id)}">${esc(x.label)}</option>`).join('');
 for(const side of ['left','right']){$(side).innerHTML=options;$(side).value=cur.layout.neighbors[s.id]?.[side]||'';}
}
function onForm(){const s=active();if(!s)return;for(const k of ['label','kind'])s[k]=$(k).value.trim();for(const k of ['capacity','order'])s[k]=Number($(k).value);for(const k of ['x','y'])s[k]=Number($(k).value);cur.layout.neighbors[s.id]={left:$('left').value||null,right:$('right').value||null};render()}
async function load(id){storeId=id;pendingRev=null;$('publish').disabled=true;selected=null;cur=await api('/api/hq/layout?store_id='+encodeURIComponent(id));$('store').value=id;
 const d=(await api('/api/hq/stores')).stores.find(x=>x.id===id);layoutApproved=!!d?.layout_ready;$('storeInfo').textContent=d?`${d.district} · ${d.name} · ${d.layout_ready?'座位图已发布':'尚未发布地图'}`:'';render();say(`已加载 ${id} · ${layoutApproved?'已批准':'待现场校准'}地图 V${cur.version}`)}
async function refreshStores(){const all=(await api('/api/hq/stores')).stores;$('store').innerHTML=all.map(s=>`<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.name)}</option>`).join('');return all;}
$('store').onchange=()=>load($('store').value).catch(e=>say(e.message,true));
$('uploadImage').onclick=()=>$('floorImageInput').click();
$('floorImageInput').onchange=async ev=>{const file=ev.target.files?.[0];if(!file)return;try{
 if(!['image/png','image/jpeg'].includes(file.type)||file.size>2000000)throw Error('请使用不超过2MB的PNG或JPEG');
 const encoded=await new Promise((resolve,reject)=>{let r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=reject;r.readAsDataURL(file)});
 const j=await api('/api/hq/image/upload','POST',{store_id:storeId,mime:file.type,base64:encoded});
 cur.layout.background_asset_id=j.asset_id;render();say('场地图已安全上传并用于当前草稿预览；必须另行保存草稿、确认发布才会在点单区生效。');
 }catch(e){say(e.message,true)}finally{ev.target.value=''} };

$('newStore').onclick=async()=>{const sid=prompt('新店永久 ID（例如 BSVN，3—32位大写）');if(!sid)return;const name=prompt('门店名称');if(!name)return;const district=prompt('所在区县（例如 顺义区）');if(!district)return;const type=prompt('业务类型（例如 鸡尾酒吧）');if(!type)return;const cap=Number(prompt('设计最大人数（不清楚填0，待现场校核）','0'));try{await api('/api/hq/stores/create','POST',{store_id:sid,name,district,business_type:type,design_max_guests:cap});await refreshStores();await load(sid);say('新门店已注册，尚未发布座位图。请人工校准并发布。')}catch(e){say(e.message,true)}};
$('addSeat').onclick=()=>{if(!cur)return;const all=cur.layout.seats;let i=1;while(all.some(x=>x.id===`${storeId}-SEAT-${String(i).padStart(4,'0')}`))i++;
 const id=`${storeId}-SEAT-${String(i).padStart(4,'0')}`,max=Math.max(0,...all.map(x=>x.order||0));all.push({id,label:'新座位'+i,kind:'TABLE',x:50,y:50,order:max+10,capacity:2,group_id:null,is_secondary:false});cur.layout.neighbors[id]={left:null,right:null};selected=id;render();say('新增座位仅存在浏览器编辑草稿，保存后才能审核发布。')};
$('deleteSeat').onclick=()=>{const s=active();if(!s||!confirm(`从新地图移除 ${s.label}？正式ID不可重用；营业中的座位不能移除。`))return;
 cur.layout.seats=cur.layout.seats.filter(x=>x.id!==s.id);delete cur.layout.neighbors[s.id];Object.values(cur.layout.neighbors).forEach(x=>{if(x.left===s.id)x.left=null;if(x.right===s.id)x.right=null;});if(cur.layout.groups.some(g=>g.primary_seat===s.id||g.secondary_seat===s.id)){say('此座位有关联合分桌，请先处理合分桌组，暂不移除。',true);return load(storeId);}selected=null;render()};
$('save').onclick=async()=>{try{onForm();const j=await api('/api/hq/layout/draft','POST',{store_id:storeId,base_version:cur.version,layout:cur.layout});pendingRev=j.revision_id;$('publish').disabled=false;const old=storeId;await load(old);pendingRev=j.revision_id;$('publish').disabled=false;say(`草稿 ${pendingRev} 已保存到数据库，但未发布到点单地图`);}catch(e){say(e.message,true)}};
$('publish').onclick=async()=>{if(!pendingRev)return;if(!confirm(`确认发布 ${storeId} 的座位地图？\n要求：已现场校验坐标、人数、左右邻位；无开桌客人。`))return;
 try{const j=await api('/api/hq/layout/publish','POST',{store_id:storeId,revision_id:pendingRev});await load(storeId);say(`发布成功！${storeId} 当前版本 V${j.version}，员工刷新点单页面即可读取`);}catch(e){say(e.message,true)}};
$('export').onclick=()=>{if(!cur)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(cur.layout,null,2)],{type:'application/json'}));a.download=`${storeId}_layout_draft.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
$('import').onclick=()=>$('importFile').click();$('importFile').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;try{if(f.size>60000)throw Error('JSON 文件太大');const d=JSON.parse(await f.text());if(d.store_id!==storeId)throw Error('禁止导入其他门店地图');cur.layout=d;selected=null;render();say('AI 候选 JSON 已导入浏览器，尚未保存和发布。请先逐个核对。')}catch(err){say(err.message,true)}finally{e.target.value=''}};
for(const id of ['label','kind','capacity','order','x','y','left','right'])$(id).addEventListener('change',onForm);
(async()=>{try{const s=await api('/api/state');csrf=s.csrf;if(!csrf)throw Error('缺少登录会话 CSRF');await api('/api/hq/status');$('kind').innerHTML=['SOFA','ROUND','BAR','WINDOW','BOOTH','TEMP','TABLE','OTHER'].map(v=>`<option value="${v}">${v}</option>`).join('');const stores=await refreshStores();const mods=await api('/api/hq/modules');$('modules').innerHTML=mods.modules.map(m=>`<div class="mod"><b>${esc(m.name)}</b><small>${esc(m.state)}</small></div>`).join('');if(stores.length)await load(stores[0].id)}catch(e){say(e.message+'；请先返回点单工作台登录有 HQ 授权的管理员。',true)}})();
