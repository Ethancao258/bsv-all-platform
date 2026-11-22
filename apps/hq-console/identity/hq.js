"use strict";
const {$,notice,request,send,node,lines,take,iso,safe,action,technical,label,statusText}=BSV;
const entity=()=>$('#entity').value.trim();
const decision=(reason)=>({legal_entity_id:entity(),reason,separate_person_confirmed:false});
const confirmed=(data,next)=> {
 const id=data.id||data.request_id||data.registration_id||data.grant_id||data.tr_code||data.code||'';
 return (id?'已确认，记录编号 '+id+'。':'已确认。')+(data.status?statusText(data.status)+'。':'')+' '+next;
};
function item(text,rest){const d=node('div',text,'item');if(rest)d.append(node('p',rest,'meta'));return d;}
async function queues(){
 const d=await request('/api/v1/identity/admin/queue?legal_entity_id='+encodeURIComponent(entity()));
 lines($('#registration-queue'),d.registrations,x=>item(x.display_label+' · '+statusText(x.status),'申请编号 '+x.id+(x.suspected_duplicate?' · 请核对是否重复申请':'')));
 const lookup=[
   ['engagement-queue',d.engagements,x=>item(x.tr_code,'任职编号 '+x.id)],
   ['stage-queue',d.stages,x=>item(x.tr_code+' · '+(x.stage==='BM'?'管理身份':'员工身份'),'申请编号 '+x.id)],
   ['grant-queue',d.grants,x=>item(x.tr_code+' · '+label(x.action,'待审工作权限'),'授权编号 '+x.id+' · '+(x.store_id||'所属公司'))],
 ];
 for(const [target,list,render] of lookup)lines($('#'+target),list,render);
 return '已更新待办。进入相应页签处理申请。';
}
async function head(){
 const me=await request('/api/v1/identity/me');
 const permissions=me.grants.filter(g=>g.legal_entity_id===entity());
 const selector=$('#grant-store-scope');
 const currentStore=$('#grant-form-store').value;
 const storeIds=[...new Set(permissions.map(g=>g.store_id).filter(Boolean))].sort();
 selector.replaceChildren(node('option','总部/所属公司范围'));
 for(const storeId of storeIds){
   const option=node('option',storeId);
   option.value=storeId;
   selector.append(option);
 }
 selector.value=storeIds.includes(currentStore)?currentStore:'';
 lines($('#actor-view'),permissions,x=>item(label(x.action,'已授权的管理工作'),label(x.legal_entity_id,'所属公司')+' / '+(x.store_id||'总部')));
 const mayReview=permissions.some(g=>g.action==='hq.people.read');
 if(!mayReview)notice('当前账号无此公司的人事权限。请核对所属公司，或联系总部开通。',true);
 try{
   const a=await request('/api/v1/identity/allocator?legal_entity_id='+encodeURIComponent(entity()));
   $('#capacity').replaceChildren(node('span','已使用 / 总容量'),node('b',a.allocated.toLocaleString()+' / '+a.capacity.toLocaleString()),node('span','剩余 '+a.remaining.toLocaleString()+(a.warning?' · 接近上限':'')));
 }catch(error){
   $('#capacity').replaceChildren(node('span',error.status===403?'当前账号不能查看编号容量。':'暂时无法读取编号容量。'));
 }
}
$('#grant-store-scope').addEventListener('change',()=>{
 $('#grant-form-store').value=$('#grant-store-scope').value;
});
action($('#refresh'),'正在刷新待办…',async()=>{await head();return queues();});
action($('#load-queue'),'正在查看待审核名单…',queues);
action($('#logout'),'正在退出…',async()=>{await send('/api/v1/auth/logout',{});location.href='/staff';return '已退出。';});
function routine(selector,pending,fn,next){
 action($(selector),pending,async form=>confirmed(await fn(form),next));
}
routine('#reg-decision','正在提交审核…',f=>send('/api/v1/identity/registrations/'+encodeURIComponent(take(f,'id'))+'/'+take(f,'operation'),{...decision(take(f,'reason')),separate_person_confirmed:!!f.querySelector('[name=separate]').checked}),'请刷新待办。核验后的申请由另一位有权限的同事批准。');
routine('#eng-form','正在登记任职…',f=>send('/api/v1/identity/engagements',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),type:take(f,'type'),effective_from:iso(take(f,'start')),effective_to:null,evidence_ref:take(f,'evidence')}),'请将任职编号交给另一位审核同事。');
routine('#eng-review','正在办理任职…',f=>send('/api/v1/identity/engagements/'+encodeURIComponent(take(f,'id'))+'/'+take(f,'operation'),decision(take(f,'reason'))),'可在待办中检查最新状态。');
routine('#qual-form','正在关联工作资格…',f=>send('/api/v1/identity/qualifications',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),qualification_code:take(f,'qualification'),learning_credential_id:take(f,'credential'),source_evidence_ref:take(f,'evidence'),effective_from:new Date().toISOString(),effective_to:null}),'请让员工在个人中心核对资格。');
routine('#stage-form','正在办理身份…',f=>{
 const body={...decision(take(f,'reason'))};
 const op=take(f,'operation');
 if(op==='issue')body.request_id=take(f,'request_id');
 return send('/api/v1/identity/'+encodeURIComponent(take(f,'tr').toUpperCase())+'/'+take(f,'stage')+'/'+op,body);
},'请在待办中核对最新进度。');
routine('#grant-form','正在发起岗位授权…',f=>send('/api/v1/identity/grants',{tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),store_id:take(f,'store')||null,role:take(f,'role'),action:take(f,'action'),required_qualification:take(f,'qualification')||null,valid_from:iso(take(f,'start')),valid_to:iso(take(f,'end')),reason:take(f,'reason')}),'请另一位有权限的同事审批该授权编号。');
routine('#grant-review','正在办理岗位授权…',f=>send('/api/v1/identity/grants/'+encodeURIComponent(take(f,'id'))+'/'+take(f,'operation'),decision(take(f,'reason'))),'请让员工从个人中心核对最新权限。');
$('#legacy-form').addEventListener('submit',e=>{
 e.preventDefault();
 if(e.submitter?.disabled)return;
 const output=$('#legacy-result');
 const submit=e.target.querySelector('button[type="submit"],button:not([type])');
 output.setAttribute('role','status');
 output.setAttribute('aria-live','polite');
 // 正在执行只读预检，按钮保持焦点且不会重复提交。
 const original=submit?.textContent;
 if(submit)submit.textContent='正在核对编码…';
 output.replaceChildren(node('p','正在核对编码…','small'));
 if(submit)submit.disabled=true;
 (async()=>{
  try{
   const rows=take(e.target,'rows').split('\n').map(s=>s.trim()).filter(Boolean).map(line=>{
    const p=line.split(/[,，]/);
    if(p.length!==3)throw new Error('每行填写三项：来源、旧员工码、人员编号。');
    return {source_system:p[0].trim(),legacy_value:p[1].trim(),tr_code:p[2].trim().toUpperCase()};
   });
   if(!rows.length)throw new Error('请至少输入一条旧码映射。');
   const d=await send('/api/v1/identity/legacy-import/dry-run',{legal_entity_id:entity(),rows});
   lines(output,d.records,x=>{
     let detail='校验通过：这条旧员工码可关联到 '+x.tr_code+'。本次仅检查，尚未保存。';
     if(x.status==='blocked')detail='这条旧员工码暂不能关联。请核对原记录和人员编号。';
     else if(x.issues.includes('ALREADY_MAPPED'))detail='这条员工码已关联到 '+x.tr_code+'，无需重复提交。';
     const row=item(x.legacy_value,detail);
     if(x.issues.length)technical(row,{code:x.issues.join(' · ')});
     return row;
   });
   const message=d.blocked?'核对完成，发现 '+d.blocked+' 条冲突。尚未保存任何关联。':'核对完成。本次仅检查，未保存任何关联。';
   output.prepend(node('p',message,d.blocked?'error':'small'));
  }catch(err){
   const message='此次核对未取得结果。'+err.message; // 只读预检失败时保留原输入。
   output.replaceChildren(node('p',message,'error'));
   technical(output,err);
  }finally{
   if(submit){submit.disabled=false;submit.textContent=original;}
   output.scrollIntoView({block:'nearest'});
  }
 })();
});
$('#people-form').addEventListener('reset',()=>$('#people-result').replaceChildren());
action($('#people-form'),'正在查询人员…',async f=>{
 const d=await request('/api/v1/identity/admin/people?legal_entity_id='+encodeURIComponent(entity())+'&q='+encodeURIComponent(take(f,'query')));
 lines($('#people-result'),d.people,x=>item(x.tr_code+' · '+(x.display_label||'已匿名化'),statusText(x.status)));
 return d.people.length?'已找到 '+d.people.length+' 条授权范围内的记录。':'没有找到本公司范围内的记录。';
});
action($('#history-form'),'正在查询历史…',async f=>{
 const d=await request('/api/v1/identity/'+encodeURIComponent(take(f,'tr').toUpperCase())+'/history?legal_entity_id='+encodeURIComponent(entity()));
 lines($('#audit-result'),d.events,x=>{
   const event=item('历史记录',new Date(x.occurred_at).toLocaleString('zh-CN'));
   technical(event,{code:x.event_type});
   return event;
 });
 return d.events.length?'已载入历史，可展开查看事件编号。':'没有找到可查看的历史记录。';
});
routine('#recovery-form','正在提交重绑申请…',f=>send('/api/v1/identity/auth-recovery/requests',{
 tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),new_auth_subject_id:take(f,'subject'),
 evidence_ref:take(f,'evidence')}),'请另一位有权限的同事核对并处理。');
routine('#recovery-review','正在核对重绑申请…',f=>send('/api/v1/identity/auth-recovery/'+encodeURIComponent(take(f,'id'))+'/approve',decision(take(f,'reason'))),'请通知该员工用新的账号登录。');
routine('#redaction-form','正在提交隐私处理申请…',f=>send('/api/v1/identity/redaction/requests',{
 tr_code:take(f,'tr').toUpperCase(),legal_entity_id:entity(),evidence_ref:take(f,'evidence'),reason:take(f,'reason')}),'请另一位有权限的同事复核。');
routine('#redaction-review','正在核对隐私处理申请…',f=>send('/api/v1/identity/redaction/'+encodeURIComponent(take(f,'id'))+'/approve',decision(take(f,'reason'))),'如需核对，可查看该人员编号的历史。');
safe(async()=>{await head();});
// The page remains readable without client-side navigation; tabs reduce admin workload on phones.
const tabTargets=['registration','employment','stage','grants','legacy','recovery','audit'];
const anchors=document.querySelectorAll('.tab-list a');
function showTab(id){if(!tabTargets.includes(id))return;
 for(const target of tabTargets){const el=document.getElementById(target);if(el)el.classList.toggle('hidden',target!==id);}
 for(const anchor of anchors)anchor.setAttribute('aria-current',anchor.getAttribute('href')==='#'+id?'page':'false');
}
window.addEventListener('hashchange',()=>showTab(location.hash.slice(1)||'registration'));
showTab(location.hash.slice(1)||'registration');
