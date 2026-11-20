"use strict";
const {$,notice,request,send,node,lines,take,iso,safe}=BSV;
const entity=()=>$('#entity').value.trim();
const decision=(reason)=>({legal_entity_id:entity(),reason,separate_person_confirmed:false});
const display=(data)=>{const id=data.id||data.request_id||data.registration_id||data.grant_id||data.tr_code||data.code||'';notice('操作成功。'+(data.status?'状态：'+data.status+'。':'')+(id?' 记录/代码：'+id:'')+'。所有审批及授权以数据库A为准。');};
function item(text,rest){const d=node('div',text,'item');if(rest)d.append(node('p',rest,'meta'));return d;}
async function queues(){const d=await request('/api/v1/identity/admin/queue?legal_entity_id='+encodeURIComponent(entity()));
 lines($('#registration-queue'),d.registrations,x=>item(x.display_label+' · '+x.status,'申请ID '+x.id+(x.suspected_duplicate?' · 需人工去重核验':'')));
 ['stages','engagements','grants'].forEach(k=>{if(d[k]?.length)notice(k+'：'+d[k].length+'条待审；在相应表单按ID操作。');});
}
async function head(){try{const me=await request('/api/v1/identity/me');lines($('#actor-view'),me.grants,x=>item(x.action,x.legal_entity_id+' / '+(x.store_id||'法人与总部')));}catch(e){notice('请先从“个人中心”登录已授权管理员账号。'+e.message,true);}try{const a=await request('/api/v1/identity/allocator?legal_entity_id='+encodeURIComponent(entity()));const k=$('#capacity');k.replaceChildren(node('span','已使用 / 总容量'),node('b',a.allocated.toLocaleString()+' / '+a.capacity.toLocaleString()),node('span','剩余 '+a.remaining.toLocaleString()+(a.warning?' · 接近上限':'')));}catch{ /* current user may lack capacity privilege */ }}
$('#refresh').addEventListener('click',()=>safe(async()=>{await head();await queues();}));$('#load-queue').addEventListener('click',()=>safe(queues));
$('#logout').addEventListener('click',()=>safe(async()=>{await send('/api/v1/auth/logout',{});location.href='/staff';}));
$('#reg-decision').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;const id=take(f,'id');const op=take(f,'operation');const result=await send('/api/v1/identity/registrations/'+encodeURIComponent(id)+'/'+op,{...decision(take(f,'reason')),separate_person_confirmed:!!f.querySelector('[name=separate]').checked});display(result);await queues();});});
$('#eng-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/engagements',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),type:take(f,'type'),effective_from:iso(take(f,'start')),effective_to:null,evidence_ref:take(f,'evidence')}));});});
$('#eng-review').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/engagements/'+encodeURIComponent(take(f,'id'))+'/'+take(f,'operation'),decision(take(f,'reason'))));});});
$('#qual-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/qualifications',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),qualification_code:take(f,'qualification'),learning_credential_id:take(f,'credential'),source_evidence_ref:take(f,'evidence'),effective_from:new Date().toISOString(),effective_to:null}));});});
$('#stage-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target,tr=take(f,'tr').toUpperCase(),stage=take(f,'stage'),op=take(f,'operation');const body={...decision(take(f,'reason'))};if(op==='issue')body.request_id=take(f,'request_id');display(await send('/api/v1/identity/'+encodeURIComponent(tr)+'/'+stage+'/'+op,body));});});
$('#grant-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/grants',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),store_id:take(f,'store')||null,role:take(f,'role'),action:take(f,'action'),required_qualification:take(f,'qualification')||null,valid_from:iso(take(f,'start')),valid_to:iso(take(f,'end')),reason:take(f,'reason')}));});});
$('#grant-review').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/grants/'+encodeURIComponent(take(f,'id'))+'/'+take(f,'operation'),decision(take(f,'reason'))));});});
$('#legacy-form').addEventListener('submit',e=>{
 e.preventDefault();
 const output=$('#legacy-result');
 const submit=e.target.querySelector('button[type="submit"],button:not([type])');
 output.setAttribute('role','status');
 output.setAttribute('aria-live','polite');
 output.replaceChildren(node('p','正在执行只读预检…','small'));
 if(submit)submit.disabled=true;
 (async()=>{
  try{
   const rows=take(e.target,'rows').split('\n').map(s=>s.trim()).filter(Boolean).map(line=>{
    const p=line.split(',');
    if(p.length!==3)throw new Error('每行必须恰好包含3个字段：来源,旧码,TR。');
    return {source_system:p[0].trim(),legacy_value:p[1].trim(),tr_code:p[2].trim().toUpperCase()};
   });
   if(!rows.length)throw new Error('请至少输入一条旧码映射。');
   const d=await send('/api/v1/identity/legacy-import/dry-run',{legal_entity_id:entity(),rows});
   lines(output,d.records,x=>item(x.legacy_value+' → '+x.tr_code,x.status+' · '+(x.issues.join(',')||'无冲突')));
   const message='只读预检完成：写入0，冲突'+d.blocked+'条。';
   output.prepend(node('p',message,d.blocked?'error':'small'));
   notice(message,!!d.blocked);
  }catch(err){
   const message='只读预检失败：'+err.message;
   output.replaceChildren(node('p',message,'error'));
   notice(message,true);
  }finally{
   if(submit)submit.disabled=false;
   output.scrollIntoView({block:'nearest'});
  }
 })();
});
$('#people-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const d=await request('/api/v1/identity/admin/people?legal_entity_id='+encodeURIComponent(entity())+'&q='+encodeURIComponent(take(e.target,'query')));lines($('#people-result'),d.people,x=>item(x.tr_code+' · '+(x.display_label||'已匿名化'),x.status));});});
$('#history-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const tr=take(e.target,'tr').toUpperCase();const d=await request('/api/v1/identity/'+encodeURIComponent(tr)+'/history?legal_entity_id='+encodeURIComponent(entity()));lines($('#audit-result'),d.events,x=>item(x.event_type,x.occurred_at));});});
safe(head);

$('#recovery-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/auth-recovery/requests',{
 tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),new_auth_subject_id:take(f,'subject'),
 evidence_ref:take(f,'evidence')}));});});
$('#recovery-review').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{display(await send('/api/v1/identity/auth-recovery/'+encodeURIComponent(take(e.target,'id'))+'/approve',decision(take(e.target,'reason'))));});});
$('#redaction-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{const f=e.target;display(await send('/api/v1/identity/redaction/requests',{
 tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),evidence_ref:take(f,'evidence'),reason:take(f,'reason')}));});});
$('#redaction-review').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{display(await send('/api/v1/identity/redaction/'+encodeURIComponent(take(e.target,'id'))+'/approve',decision(take(e.target,'reason'))));});});
// The page remains readable without client-side navigation; tabs reduce admin workload on phones.
const tabTargets=['registration','employment','stage','grants','legacy','recovery','audit'];
const anchors=document.querySelectorAll('.tab-list a');
function showTab(id){if(!tabTargets.includes(id))return;
 for(const target of tabTargets){const el=document.getElementById(target);if(el)el.classList.toggle('hidden',target!==id);}
 for(const anchor of anchors)anchor.setAttribute('aria-current',anchor.getAttribute('href')==='#'+id?'page':'false');
}
for(const anchor of anchors)anchor.addEventListener('click',()=>showTab(anchor.getAttribute('href').slice(1)));
showTab(location.hash.slice(1)||'registration');
