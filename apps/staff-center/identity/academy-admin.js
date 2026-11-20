"use strict";
(() => {
 const {$,action,request,send,node,notice,lines,take,iso,shiftLabel,formatShift}=BSV;
 const root='/api/v1/academy', encode=encodeURIComponent, role='bartender';
 let availableCourses=[], selectedStore='', shiftRequest=null, questionCount=0;
 const courseUrl=(course,step)=>root+'/courses/'+encode(course.course_id)+'/'+encode(course.version)+'/'+step;
 const statusNames={draft:'草稿',published:'已发布',retired:'已停用',active:'已启用',revoked:'已撤销'};
 function makeAction(id,title,pending,fn){
   const button=node('button',title);
   button.type='button';button.id=id;
   action(button,pending,fn);
   return button;
 }
 function addQuestion(){
   const host=$('#draft-questions');
   if(host.children.length>=20)return '单版最多录入 20 道题。';
   const fieldset=node('fieldset',''), key='question-'+(++questionCount);
   const legend=node('legend','理论题 '+questionCount);
   fieldset.append(legend);
   for(const [name,caption] of [['prompt','问题'],['a','选项一'],['b','选项二'],['c','选项三（可不填）']]){
     const label=node('label',caption),input=node('input','');
     input.name=name;input.required=name!=='c';input.maxLength=300;
     label.append(input);fieldset.append(label);
   }
   const label=node('label','正确选项');
   const answer=node('select',''); answer.name='correct';
   ['选项一','选项二','选项三'].forEach((text,i)=>{
     const option=node('option',text);option.value=String(i);answer.append(option);
   });
   label.append(answer);fieldset.append(label);
   const remove=node('button','移除此题','secondary');
   remove.type='button';remove.addEventListener('click',()=>{
     if(host.children.length===1){notice('至少保留一道理论题。',true);return;}
     fieldset.remove();notice('已移除未保存的题目。');
   });
   remove.id=key+'-remove';fieldset.append(remove);host.append(fieldset);
   return '请填写新增题目的内容。';
 }
 async function refresh(message){
   const admin=await request(root+'/admin');
   availableCourses=admin.courses||[];
   $('#admin-content').hidden=false;
   $('#admin-status').textContent='已核对你的管理范围。';
   const grants=admin.management||{}, schedules=grants.scheduling_stores||[];
   for(const [id,visible] of Object.entries({
     courses:grants.training||grants.publication, practical:grants.training,
     shifts:schedules.length>0, devices:grants.devices,
   }))document.getElementById(id).hidden=!visible;
   $('#draft-course').hidden=!grants.training;
   const datalist=$('#academy-store-list');datalist.replaceChildren();
   for(const store of admin.stores||[]){
     const option=node('option',store);option.value=store;datalist.append(option);
   }
   lines($('#course-admin-list'),availableCourses,(row,i)=>courseCard(row,i,admin.media_ready===true,grants));
   const select=$('#practical-courses');
   select.replaceChildren();
   const published=availableCourses.filter(c=>c.store_id&&(c.status||c.publish_status)==='published');
   for(const course of published){
     const option=node('option',course.title+' · '+course.store_id+' · 版本 '+course.version);
     option.value=String(availableCourses.indexOf(course));select.append(option);
   }
   if(!published.length){
     const option=node('option','当前没有已发布门店课程');option.value='';select.append(option);
   }
   lines($('#shift-admin-list'),admin.shifts,shiftCard);
   lines($('#device-admin-list'),admin.devices,deviceCard);
   if(message)notice(message);
   return '已核对有权查看的记录。';
 }
 function courseCard(course,i,mediaReady,grants){
   const card=node('article','','item'),state=course.status||course.publish_status;
   card.append(node('strong',course.title+' · 版本 '+course.version),node('p',(course.store_id||'集团基础课')+' · '+(statusNames[state]||'待核对')));
   if(state==='draft'){
     if(grants.training){
       if(mediaReady)card.append(uploadForm(course,i));
       else card.append(node('p','课件上传暂不可用。私有存储或安全扫描未就绪，请联系负责人。','small'));
     }
     if(grants.publication)card.append(makeAction('publish-'+i,'独立审批并发布','正在提交…',async()=>{
       await send(courseUrl(course,'publish'),{});
       return refresh('已确认发布。员工现在可查看本版本。');
     }));
   }
   if(state==='published'&&grants.publication)card.append(makeAction('retire-'+i,'停用此版本','正在停用…',async()=>{
     await send(courseUrl(course,'retire'),{});
     return refresh('此课程版本已停用。请核对需要复训或重新排班的人员。');
   }));
   for(const media of course.media||[])card.append(node('p','已登记课件：'+media.filename,'small'));
   return card;
 }
 function uploadForm(course,i){
   const form=node('form','');
   form.id='upload-'+i;
   const label=node('label','课件文件'),file=node('input','');
   file.type='file';file.name='media';file.accept='video/mp4,image/png,image/jpeg,application/pdf';file.required=true;
   label.append(file);
   const rights=node('label','课件版权与内部使用记录编号'),ref=node('input','');
   ref.name='rights_ref';ref.required=true;ref.maxLength=250;rights.append(ref);
   form.append(label,rights,node('p','支持 MP4、PNG、JPEG、PDF。单个隔离演练文件最大约 2.8 MiB。','small'),node('button','上传私有课件'));
   action(form,'上传及扫描中…',async element=>{
     const attachment=file.files[0];
     if(!attachment||attachment.size>2_850_000)throw new Error('请选择尺寸合规的演练课件。');
     const base64=await new Promise((resolve,reject)=>{
       const reader=new FileReader();
       reader.onerror=()=>reject(new Error('无法读取所选文件。请重新选择。'));
       reader.onload=()=>resolve(String(reader.result).split(',')[1]);
       reader.readAsDataURL(attachment);
     });
     await send(courseUrl(course,'media'),{filename:attachment.name,mime:attachment.type,content_base64:base64,rights_ref:take(element,'rights_ref')});
     return refresh('私有课件已登记。请核对草稿后交给独立发布人。');
   });
   return form;
 }
 function shiftCard(shift,i){
   const card=node('article','','item');
   card.append(node('strong',formatShift(shift)),node('p',shiftLabel(shift.status)+(shift.tr_code?' · '+shift.tr_code:'')),node('p',shift.shift_id,'small'));
   if(['pending','proposed','requested'].includes(shift.status))card.append(makeAction('approve-shift-'+i,'审批此班次','正在审批…',async()=>{
     await send(root+'/shifts/'+encode(shift.shift_id)+'/approve',{});
     return refresh('已批准班次。请提醒员工确认。');
   }));
   if(['pending','proposed','requested','approved','confirmed','needs_reassignment','NEEDS_REASSIGNMENT'].includes(shift.status))
     card.append(makeAction('cancel-shift-'+i,'取消此班次','正在取消…',async()=>{
       await send(root+'/shifts/'+encode(shift.shift_id)+'/cancel',{});
       return refresh('班次已取消。请核对是否需要重新安排。');
     }));
   return card;
 }
 function deviceCard(device,i){
   const card=node('article','','item'),state=device.state||device.status;
   card.append(node('strong',device.device_id),node('p',device.store_id+' · '+(statusNames[state]||'待核对')));
   if(state==='active')card.append(makeAction('revoke-device-'+i,'撤销此设备','正在撤销…',async()=>{
     await send(root+'/devices/'+encode(device.device_id)+'/revoke',{});
     return refresh('设备权限已撤销。请核对旧设备是否已收回。');
   }));
   return card;
 }
 action($('#admin-refresh'),'正在核对…',()=>refresh());
 action($('#add-question'),'正在添加…',addQuestion);
 action($('#draft-course'),'正在保存草稿…',async form=>{
   const questions=[...$('#draft-questions').children].map(group=>{
     const read=name=>group.querySelector('[name="'+name+'"]').value.trim();
     const options=[read('a'),read('b'),read('c')].filter(Boolean),correct_index=Number(read('correct'));
     if(correct_index>=options.length)throw new Error('有一道题选中了未填写的正确选项。');
     return {prompt:read('prompt'),options,correct_index};
   });
   await send(root+'/courses',{course_id:take(form,'course_id'),version:Number(take(form,'version')),
     title:take(form,'title'),store_id:take(form,'store_id').toUpperCase()||null,role,
     passing_score:Number(take(form,'passing_score')),questions,rights_ref:take(form,'rights_ref'),
     practical_requirements:take(form,'practical_requirements')});
   return refresh('课程草稿已保存。请核对课程、课件和题库后交给另一位有权同事发布。');
 });
 action($('#practical-review'),'正在核验…',async form=>{
   const index=take(form,'course'),course=index===''?null:availableCourses[Number(index)];
   if(!course?.store_id||(course.status||course.publish_status)!=='published')throw new Error('请选择实际已发布的门店课程。');
   const result=await send(courseUrl(course,'practical'),{tr_code:take(form,'tr_code'),decision:take(form,'decision'),
      evidence_ref:take(form,'evidence_ref'),reason:take(form,'reason')});
   return refresh('实操复核结果已登记。'+(result.credential_id?'门店资格编号 '+result.credential_id+'。':'')+'员工可在权限页核对本店资格。');
 });
 action($('#credential-control'),'正在核对资格变更…',async form=>{
   const id=take(form,'credential_id'),operation=take(form,'operation');
   const result=await send(root+'/credentials/'+encode(id)+'/'+encode(operation),{});
   if(!['revoked','suspended'].includes(result.status))throw new Error('还不能确认资格已变更，请核对资格编号。');
   return refresh((result.status==='revoked'?'资格已撤销。':'资格已暂停。')+'请核对需重新安排的班次。');
 });
 $('#eligible-filter').addEventListener('input',()=>{
   selectedStore='';shiftRequest=null;$('#assign-shift').hidden=true;
 });
 action($('#eligible-filter'),'正在查询人选…',async form=>{
   const shop=take(form,'store_id').toUpperCase();
   const result=await request(root+'/eligible?store_id='+encode(shop)+'&role='+encode(role));
   const eligible=Array.isArray(result)?result:(result.eligible||result.people||result.candidates||[]);
   if(take(form,'store_id').toUpperCase()!==shop)return '门店已更改，请重新查询人选。';
   selectedStore=shop;shiftRequest=null;
   const select=$('#eligible-employees');select.replaceChildren();
   for(const person of eligible){
     const code=typeof person==='string'?person:person.tr_code;
     const option=node('option',code);option.value=code;select.append(option);
   }
   $('#shift-store-caption').textContent='当前安排门店：'+shop;
   $('#assign-shift').hidden=!eligible.length;
   return eligible.length?'请选择该店可以排班的员工。':'当前没有可安排班次的员工。';
 });
 $('#assign-shift').addEventListener('input',()=>{shiftRequest=null;});
 action($('#assign-shift'),'正在安排班次…',async form=>{
   if(!selectedStore)throw new Error('请先按门店查询合格人选。');
   if(!shiftRequest)shiftRequest=crypto.randomUUID();
   const replacement=take(form,'replaces_shift_id');
   await send(root+'/shifts',{store_id:selectedStore,role,tr_code:take(form,'tr_code'),start:iso(take(form,'start')),
     end:iso(take(form,'end')),timezone:'Asia/Shanghai',request_id:shiftRequest,...(replacement?{replaces_shift_id:replacement}:{})});
   shiftRequest=null;
   return refresh('已保存班次安排。请由有权限的同事办理审批。');
 });
 action($('#register-device'),'正在登记…',async form=>{
   const result=await send(root+'/devices',{device_id:take(form,'device_id'),store_id:take(form,'store_id').toUpperCase()});
   const target=$('#device-result');target.replaceChildren();
   if(result.device_token){
     const explanation=node('p','请在刚登记的设备输入这次显示的设备口令。页签关闭后将不再显示。');
     const value=node('output',result.device_token,'mono');
     const clear=node('button','清除屏幕口令','secondary');clear.type='button';
     clear.addEventListener('click',()=>{target.textContent='已从当前屏幕清除口令。';});
     target.append(explanation,value,clear);
   }
   return refresh('已登记设备。请在受控设备完成核验。');
 });
 addQuestion();
 refresh().catch(error=>{
   $('#admin-status').textContent=error.status===401?'请先在个人中心登录。':error.status===403?'当前账号没有可用的培训或门店管理权限。':'暂时无法核对管理权限。';
   notice(error.message,true);
 });

})();
