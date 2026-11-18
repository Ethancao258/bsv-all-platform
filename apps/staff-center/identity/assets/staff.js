"use strict";
const {$,notice,request,send,node,lines,take,safe} = BSV;
let currentTr=null;
async function refresh(){
 const session=await request('/api/v1/auth/session');
 $('#auth-area').classList.add('hidden');$('#member-area').classList.remove('hidden');
 const me=await request('/api/v1/identity/me');currentTr=me.tr_code;
 $('#tr-view').textContent=me.tr_code||'核验中';
 $('#register-panel').classList.toggle('hidden',!!me.tr_code);
 $('#registration-state').textContent=me.registration_status||'';
 const stages=$('#stage-view');stages.replaceChildren();
 stages.append(node('p','EMP：'+(me.emp_code||'未颁发')));
 stages.append(node('p','BM：'+(me.bm_code||'未颁发')));
 if(me.bm_code)stages.append(node('p',me.bm_active_entities?.length?'管理任命有效法人：'+me.bm_active_entities.join('、'):'BM编码已发，但当前无有效管理任命','small'));
 lines($('#grants-view'),me.grants, (g)=>{const d=node('div',g.action,'item');d.append(node('p','岗位：'+g.role+' · 门店：'+(g.store_id||'法人范围'),'meta'));return d;});
 lines($('#qual-view'),me.qualifications,(q)=>{const d=node('div',q.code,'item');d.append(node('p','来源：'+q.credential_id,'meta'));return d;});
}
$('#login-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{await send('/api/v1/auth/isolated/login',{username:$('#login-user').value,password:$('#login-pass').value});notice('登录成功。');await refresh();});});
$('#signup-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{await send('/api/v1/auth/isolated/signup',{username:$('#signup-user').value,password:$('#signup-pass').value});notice('隔离测试账号已创建。');await refresh();});});
$('#register-form').addEventListener('submit',e=>{e.preventDefault();safe(async()=>{
 if(!$('#consent').checked)throw new Error('必须同意当前登记说明。');
 let key=sessionStorage.getItem('bsv-tr-register-key');if(!key){key=crypto.randomUUID();sessionStorage.setItem('bsv-tr-register-key',key);}
 const result=await send('/api/v1/identity/registrations',{legal_entity_id:$('#reg-entity').value,idempotency_key:key,display_label:$('#display-label').value,proof_hint:$('#proof-hint').value||null,consent_version:'2026-11-18'});
 notice('申请已保存。申请ID：'+result.registration_id+'，状态：'+result.status+'。需要不同管理员核验和审批。');await refresh();
});});
$('#logout').addEventListener('click',()=>safe(async()=>{await send('/api/v1/auth/logout',{});location.reload();}));
$('#history').addEventListener('click',()=>safe(async()=>{if(!currentTr)throw new Error('需先获得TR。');const history=await request('/api/v1/identity/'+encodeURIComponent(currentTr)+'/history');lines($('#history-view'),history.events, (ev)=>{const d=node('div',ev.event_type,'item');d.append(node('p',ev.occurred_at,'meta'));return d;});}));
safe(async()=>{const conf=await request('/api/v1/identity/public-config');
 const s=$('#reg-entity');for(const entity of conf.registration_entities){const op=node('option',entity);op.value=entity;s.append(op);}
 try{await refresh();}catch(e){if(e.message.startsWith('UNAUTHENTICATED'))return;throw e;}});
