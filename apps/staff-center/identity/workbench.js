"use strict";
(() => {
 const {$,request,node,lines,academyReason,shiftLabel,formatShift}=BSV;
 const nav=[...document.querySelectorAll('.workbench-nav a')];
 function activate(focus=false){
   const key=(location.hash||'#today').slice(1);
   const target=document.getElementById(key);
   if(!target?.hasAttribute('data-workbench-view'))return;
   for(const page of document.querySelectorAll('[data-workbench-view]'))page.hidden=page!==target;
   for(const entry of nav){
     if(entry.hash==='#'+key)entry.setAttribute('aria-current','page');
     else entry.removeAttribute('aria-current');
   }
   if(focus){
     const heading=target.querySelector('h1');
     heading.setAttribute('tabindex','-1');
     heading.focus({preventScroll:true});
     window.scrollTo(0,0);
   }
 }
 window.addEventListener('hashchange',()=>activate(true));
 activate();
 const dock=document.querySelector('.workbench-nav');
 const fitDock=()=>{
   const viewport=window.visualViewport;
   const root=document.documentElement.style;
   const onMobile=window.matchMedia('(max-width:767px)').matches;
   if(!onMobile)return;
   const inset=viewport?Math.max(0,window.innerHeight-viewport.height-viewport.offsetTop):0;
   const left=viewport?.offsetLeft||0;
   const tail=viewport?Math.max(0,window.innerWidth-viewport.width-left):0;
   root.setProperty('--keyboard-inset',Math.round(inset)+'px');
   root.setProperty('--vv-left',Math.round(left)+'px');
   root.setProperty('--vv-right',Math.round(tail)+'px');
   root.setProperty('--dock-reserve',Math.ceil(dock.getBoundingClientRect().height)+'px');
 };
 window.visualViewport?.addEventListener('resize',fitDock);
 window.visualViewport?.addEventListener('scroll',fitDock);
 window.addEventListener('resize',fitDock);
 if(typeof ResizeObserver==='function')new ResizeObserver(fitDock).observe(dock);
 fitDock();
 function setPriority(message,url,title){
   $('#priority-copy').textContent=message;
   const link=$('#priority-link');
   link.href=url;
   link.textContent=title;
 }
 function status(copy){$('#work-status').textContent=copy;}
 function unavailable(copy){
   $('#task-list').textContent=copy;
   $('#access-list').textContent=copy;
   $('#current-shift').textContent=copy;
   status(copy);
 }
 function summary(work){
   const now=Date.now();
   const current=work.shifts.find(s=>s.status==='confirmed'&&new Date(s.start)<=now&&new Date(s.end)>now);
   $('#current-shift').textContent=current?formatShift(current):'现在没有已确认且有效的班次。';
   const shifts=work.shifts.filter(s=>['approved','NEEDS_REASSIGNMENT','needs_reassignment'].includes(s.status));
   const pending=work.courses.filter(c=>['in_progress','completed'].includes(c.progress)&&!c.latest_attempt?.passed);
   const tasks=[
     ...shifts.map(s=>({headline:shiftLabel(s.status),text:formatShift(s)})),
     ...pending.map(c=>({headline:'完成课程考核',text:c.title})),
   ];
   $('#task-list').replaceChildren();
   if(!tasks.length)$('#task-list').append(node('p','目前没有需要你处理的待办。','panel'));
   else for(const task of tasks){
     const card=node('article','','item');
     const link=node('a','打开学院与排班','action-link');
     link.href='/academy';
     card.append(node('h2',task.headline),node('p',task.text),link);
     $('#task-list').append(card);
   }
   lines($('#access-list'),work.stores,row=>{
     const card=node('article','','item');
     card.append(node('h2',row.name?row.name+' · '+row.store_id:row.store_id),
       node('p',row.can_schedule?'可排班':'暂不能排班'),
       node('p',row.can_pos?'可在本店已核验设备上点单':academyReason(row.reason)));
     if(row.can_pos){
       const link=node('a','选择此店并核对设备','action-link');
       link.href='/pos?store='+encodeURIComponent(row.store_id);card.append(link);
     }
     return card;
   });
   const available=work.stores.filter(s=>s.can_pos);
   if(available.length){
     const shops=available.map(s=>s.store_id).join('、');
     setPriority('当前可以在 '+shops+' 的已核验设备上点单。','/pos','打开点单台');
     card('pos','ready','可在登记设备点单','可核验的当班门店：'+shops+'。');
   }else{
     const first=shifts.find(s=>s.status==='approved');
     setPriority(first?'请确认 '+first.store_id+' 的班次。':(tasks[0]?.text||'先核对培训资格或需要确认的班次。'),'/academy',
         first?'确认班次':'打开文森特学院');
     card('pos','blocked','目前不可点单','请在权限页核对本店培训、岗位和班次。');
   }
   status('学院、班次和权限已核对 · '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(now)+'（北京时间）');
 }
 function card(id,state,label,description){
   const tag=$('#'+id+'-status');
   tag.dataset.state=state;
   tag.textContent=label;
   $('#'+id+'-next').textContent=description;
 }
 async function supply(me){
   const actions=new Set((me?.grants||[]).map(grant=>grant.action));
   const mayInspect=[...actions].some(action=>action.startsWith('quality.'));
   try{
     const health=await request('/supply-ui/api/health');
     if(health.mode!=='internal-stage')throw new Error('Unexpected service mode');
     card('supply','blocked','暂未启用','中央台账尚未连接。可查看授权范围，配送、收货与盘点都不能提交。');
     card('inspection','read','仅查看',
          mayInspect?'可核对已授权门店。督查记录和复核尚不能提交。'
                    :'可查看开放情况。需要督查权限时，请向总部申请对应门店。');
   }catch{
     card('supply','blocked','状态待确认','暂时无法获取供货状态。请检查连接，再刷新本页。');
     card('inspection','blocked','状态待确认','暂时无法获取督查状态。请检查连接，再刷新本页。');
   }
 }
 async function load(){
   let me;
   try{
     me=await request('/api/v1/identity/me');
   }catch(error){
     const signedOut=error.status===401;
     $('#session-summary').textContent=signedOut?'尚未登录':'暂时无法确认登录状态';
     $('#session-link').textContent=signedOut?'登录或申请入职':'前往个人中心';
     card('employee','read',signedOut?'可登录':'请检查连接','进入个人中心后查看入职进度和可用权限。');
     card('pos','blocked','待核验','先登录，再核对门店和登录条件。');
     card('hq','blocked','待核验','请用已获总部授权的账号登录。');
     unavailable(signedOut?'登录后可核对待办、班次和权限。':'暂时不能获取工作数据，请检查连接后重试。');
     setPriority(signedOut?'登录后查看今天在哪家店、接下来做什么。':'请核对连接后重新查看工作。','/staff','打开个人中心');
     await supply();
     return;
   }
   const grants=me.grants||[];
   const stores=[...new Set(grants.map(grant=>grant.store_id).filter(Boolean))];
   const orderStores=stores.filter(store=>['pos.order.read','pos.order.create'].every(action=>
      grants.some(grant=>grant.store_id===store&&grant.action===action)));
   const hq=grants.some(grant=>grant.action==='hq.people.read');
   const roles=[];
   if(me.emp_code&&me.active_legal_entities?.length)roles.push('员工');
   if(grants.some(grant=>grant.role==='manager'))roles.push('当班负责人');
   if(hq)roles.push('总部');
   if(grants.some(grant=>grant.action.startsWith('quality.independent.')))roles.push('独立督查');
   $('#session-summary').textContent=me.tr_code?'已登录 · '+(roles.join(' / ')||'可查看个人资料'):'已登录 · 入职待核验';
   $('#store-summary').textContent=stores.length?'可核对的门店：'+stores.join('、'):'当前没有门店授权';
   card('employee','ready','可操作',me.tr_code?'查看人员编号、已生效的任职和个人资格。':'在个人中心提交申请，或查看审核进度。');
   card('pos',orderStores.length?'ready':'blocked',orderStores.length?'可进行门店核验':'暂未授权',
        orderStores.length?'已获点单权限：'+orderStores.join('、')+'。进入点单台核对本店登录条件。'
                          :'如果今天需要点单，请向总部申请当班门店权限。');
   card('hq',hq?'ready':'blocked',hq?'可操作':'暂未授权',
        hq?'按已授权的所属公司查询人员和处理待审事项。':'切换到拥有总部权限的账号后继续。');
   await Promise.all([supply(me),(async()=>{
     try{
       const config=await request('/api/bootstrap');
       if(config.device_required!==true){
         unavailable('当前入口尚未开放学院与排班验收。已有门店仍需按页面核验。');
         setPriority('查看当前账号的入职进度和门店权限。','/staff','打开个人中心');
         return;
       }
       summary(await request('/api/v1/academy/work'));
     }catch{
       unavailable('学院和班次暂时无法核对。请检查连接后刷新，未确认前不能视作已获岗位资格。');
       card('pos','blocked','权限待核对','暂时无法确认当前班次和点单资格。');
       setPriority('请先重新核对班次和门店权限。','/academy','打开学院与排班');
     }
   })()]);
 }
 BSV.action($('#refresh-workbench'),'正在核对…',async()=>{await load();return $('#work-status').textContent;});
 load();
})();
