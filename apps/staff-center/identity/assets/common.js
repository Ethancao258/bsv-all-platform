"use strict";
window.BSV = (() => {
 const $ = (selector) => document.querySelector(selector);
 const node = (tag,text,cls) => {const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;};
 const notice = (message, bad=false) => {const x=$('#notice');if(!x)return;x.classList.remove('hidden');x.classList.toggle('error',bad);x.textContent=message;};
 const cookie = (name) => document.cookie.split('; ').map(x=>x.split('=')).find(x=>x[0]===name)?.slice(1).join('=')||'';
 const labels = {
   'pos.order.read':'查看门店点单','pos.order.create':'录入门店点单','hq.people.read':'查询人员',
   'grant.request':'发起岗位授权','grant.approve':'审批岗位授权','grant.revoke':'撤销岗位授权',
   'supply.dispatch':'发货','supply.receive':'收货','quality.self_check':'门店自查',
   'quality.independent.submit':'提交独立督查','quality.independent.review':'复核独立督查',
   'legacy.preview':'核对旧员工码','legacy.commit':'保存旧员工码关联',
   'EMP_ONBOARDING':'入职资格','BM_MANAGEMENT':'管理资格','POS_SERVICE':'点单上岗资格',
   'SUPPLY_SAFETY':'供货安全资格','QUALITY_INSPECTOR':'独立督查资格','QUALITY_REVIEWER':'督查复核资格',
   'staff':'员工','manager':'当班负责人','hq':'总部','DEMO_LEGAL':'内部演练公司',
 };
 const label = (key,fallback='查看详情') => labels[key]||fallback;
 const statusText = (status) => ({
   approved:'已批准',active:'有效',issued:'已发放',verified:'已核验',pending:'待审核',
   needs_review:'需要补充核验',not_started:'尚未申请',rejected:'未通过',revoked:'已撤销',
   suspended:'已停用',ended:'已结束',closed:'已结束',redacted:'已匿名化',
 }[status]||'请查看明细');
 const issues = {
   BAD_CREDENTIALS:'用户名或密码不正确，请核对后再试。',
   INVALID_CREDENTIALS:'用户名或密码不正确，请核对后再试。',
   INVALID_PASSWORD:'密码不符合要求，请按输入框说明调整。',
   DUPLICATE_USERNAME:'这个用户名已被使用，请换一个再试。',
   BAD_ORIGIN:'当前页面不能发起这项请求。请从工作台重新进入。',
   CSRF_REJECTED:'当前页面的登录状态已变化。请刷新页面后继续。',
   SEPARATION_OF_DUTIES:'不能批准自己提出的申请，请交由另一位有权限的同事处理。',
   SELF_APPROVAL:'不能批准自己提出的申请，请交由另一位有权限的同事处理。',
   QUALIFICATION_REQUIRED:'所需资格尚未生效。请先核对资格记录，再继续审批。',
   MAPPING_BUSY:'旧码正在核对。请先查询旧码关联结果，再决定是否重试。',
   MIGRATION_PRECHECK_FAILED:'旧码仍有冲突，请先查看核对结果再处理。',
 };
 const academyReasons={
   ENGAGEMENT_INACTIVE:'任职未生效。请联系总部核对入职或任职记录。',
   COMMON_TRAINING_REQUIRED:'基础培训未通过。请完成学院的基础课程和考核。',
   STORE_TRAINING_REQUIRED:'本店培训未通过。请完成店级课程和理论考核。',
   PRACTICAL_REQUIRED:'本店实操未通过。请联系有权限的培训官核验。',
   CREDENTIAL_INACTIVE:'本店资格已过期、撤销或需复训。请核对课程版本。',
   POS_GRANT_REQUIRED:'当前岗位未获得本店点单权限。请向负责人核对岗位授权。',
   SHIFT_UNCONFIRMED:'班次尚未确认。请打开学院与排班查看待办。',
   SHIFT_INACTIVE:'现在没有可用的本店班次。请核对安排和当班时间。',
   DEVICE_UNVERIFIED:'这台设备未获得本店授权。请联系负责人核验或更换已登记设备。',
   STORE_UNAUTHORIZED:'当前账号不能进入这家店。请核对门店和所属公司。',
   IDENTITY_UNAVAILABLE:'暂时无法核对权限。请恢复连接后重试。',
 };
 const academyReason=code=>academyReasons[code]||'当前权限需核对。请查看本人资格或联系负责人。';
 const shiftLabel=state=>({requested:'待审批',proposed:'待审批',pending:'待审批',approved:'待你确认',confirmed:'已确认',
   needs_reassignment:'需重新安排',NEEDS_REASSIGNMENT:'需重新安排',cancelled:'已取消',completed:'已结束'}[state]||'待查看');
 const shiftClock=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'});
 const formatShift=s=>{const start=new Date(s.start),end=new Date(s.end);
   return s.store_id+(Number.isFinite(+start)&&Number.isFinite(+end)?' · '+shiftClock.format(start)+' 至 '+shiftClock.format(end)+'（北京时间）':'');};
 const requestError = ({code,status,write=false,login=false}) => {
   const unknown = write && (status>=500||!status) && code!=='DB_UNAVAILABLE';
   let message=issues[code]||academyReasons[code];
   if(!message && status===401)message=login?'用户名或密码不正确，请核对后再试。':'登录已过期，请重新登录后继续。';
   if(!message && status===403)message='当前账号不能执行这项操作。请向总部申请相应门店权限。';
   if(!message && status===404)message='找不到可查看的记录，请核对编号和授权范围。';
   if(!message && status===409)message='当前记录状态与提交内容不一致。请先查看最新记录，再决定如何处理。';
   if(!message && status===422)message='请核对表单内容和格式后再提交。';
   if(!message && status===429)message='操作过于频繁。请稍等片刻再试。';
   if(!message && code==='DB_UNAVAILABLE')message='服务暂时不可用。请稍后重新核对这条记录。';
   if(!message)message=unknown?'结果暂未确认，请先查看记录再重试。':'暂时无法获取结果。请检查连接后刷新查询。';
   return Object.assign(new Error(message),{code,status,unknown});
 };
 const request = async (url,options={}) => {
   const headers={'Accept':'application/json', ...options.headers};
   const write=options.method==='POST'&&!url.endsWith('/dry-run');
   const login=url.endsWith('/login');
   if(options.body){headers['Content-Type']='application/json';headers['X-CSRF-Token']=cookie('bsv_csrf');}
   let response;
   try{
     response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(11000),...options,headers});
   }catch(error){throw requestError({code:error.name==='TimeoutError'?'REQUEST_TIMEOUT':'NETWORK_ERROR',write,login});}
   let data;
   try{data=await response.json();}
   catch{throw requestError({code:'RESPONSE_NOT_CONFIRMED',status:response.ok?undefined:response.status,write,login});}
   if(!response.ok)throw requestError({code:data.error?.code||data.detail?.code||data.code||'HTTP_'+response.status,status:response.status,write,login});
   return data;
 };
 const send=(url,body)=>request(url,{method:'POST',body:JSON.stringify(body)});
 const lines=(container,items,render)=>{container.replaceChildren();if(!items?.length){container.append(node('p','暂无记录','small'));return;}items.forEach(item=>container.append(render(item)));};
 const take = (form,key) => new FormData(form).get(key)?.toString().trim()||'';
 const iso=text=>{
   if(!text)return null;
   const local=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?$/.test(text);
   const date=new Date(local?text+'+08:00':text);
   return Number.isFinite(date.valueOf())?date.toISOString():null;
 };
 const safe=async fn=>{try{await fn();}catch(e){notice(e.message,true);}};
 function technical(target,error){
   if(!error.code)return;
   const detail=node('details','');
   detail.append(node('summary','查看问题编号'),node('p',error.code,'mono'));
   target.append(detail);
 }
 function action(element, pending, fn){
   const form=element.tagName==='FORM';
   element.addEventListener(form?'submit':'click',async event=>{
     event.preventDefault();
     if(element.getAttribute('aria-busy')==='true')return;
     const button=form?(event.submitter||element.querySelector('button')):element;
     const original=button.textContent;
     let result=document.getElementById(element.id+'-feedback');
     if(!result){
       result=node('div','','inline-feedback');
       result.id=element.id+'-feedback';
       result.setAttribute('role','status');
       button.insertAdjacentElement('afterend',result);
     }
     element.setAttribute('aria-busy','true');
     button.disabled=true;
     button.textContent=pending;
     result.dataset.state='pending';
     result.textContent=pending;
     try{
       const outcome=await fn(element);
       result.dataset.state='success';
       result.textContent=outcome;
     }catch(error){
       result.dataset.state=error.unknown?'unknown':'error';
       result.textContent=error.message;
       technical(result,error);
     }finally{
       element.removeAttribute('aria-busy');
       button.disabled=false;
       button.textContent=original;
     }
   });
 }
 return {$,notice,request,send,node,lines,take,iso,safe,action,technical,label,statusText,academyReason,shiftLabel,formatShift};
})();
