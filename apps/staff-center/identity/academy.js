"use strict";
(() => {
 const {$,action,request,send,node,notice,lines,academyReason,shiftLabel,formatShift}=BSV;
 const root='/api/v1/academy';
 const encode=encodeURIComponent;
 const courseUrl=(course,step)=>root+'/courses/'+encode(course.course_id)+'/'+encode(course.version)+'/'+step;
 const courseState={not_started:'尚未开始',in_progress:'学习中',completed:'已完成学习'};
 const practical={verified:'实操已通过',rejected:'实操未通过，请联系培训官核对训练内容'};
 function button(id,title,pending,fn){
   const control=node('button',title);
   control.type='button';
   control.id=id;
   action(control,pending,fn);
   return control;
 }
 async function record(path,body,message){
   await send(path,body);
   notice(message);
   await refresh(true);
   return message;
 }
 function media(entry){
   if(typeof entry.url!=='string'||!/^\/api\/v1\/academy\/media\/[a-zA-Z0-9_-]+$/.test(entry.url))return node('p','这份课件暂不可用。');
   const box=node('div','');
   const link=node('a',entry.filename||'查看私有课件');
   link.href=entry.url;
   link.rel='noreferrer';
   box.append(link);
   if(entry.mime==='video/mp4'){
     const video=node('video','');
     video.controls=true;
     video.preload='none';
     video.src=entry.url;
     video.addEventListener('error',()=>box.append(node('p','暂时无法读取视频。请联系培训官核对课件。','error')),{once:true});
     box.append(video);
   }
   return box;
 }
 function exam(course,key){
   const form=node('form','');
   form.id=key+'-exam';
   let pendingId=null;
   form.addEventListener('input',()=>{pendingId=null;});
   form.append(node('h3','理论测验'));
   course.questions.forEach((question,index)=>{
     const group=node('fieldset','');
     group.append(node('legend',question.prompt));
     question.options.forEach((choice,i)=>{
       const label=node('label','');
       const input=node('input','');
       input.type='radio';input.name='question-'+index;input.value=String(i);input.required=true;
       label.append(input,document.createTextNode(choice));
       group.append(label);
     });
     form.append(group);
   });
   form.append(node('button','提交理论答案'));
   action(form,'正在批阅…',async element=>{
     const formData=new FormData(element);
     pendingId ||= crypto.randomUUID();
     const result=await send(courseUrl(course,'exam'),{
       request_id:pendingId,answers:course.questions.map((_,i)=>Number(formData.get('question-'+i))),
     });
     pendingId=null;
     const score=Number.isFinite(result.score)?'得分 '+result.score+'。':'';
     const message=result.passed===true?'理论考核通过。'+score+'店级课程还需培训官核验实操。':
        '理论考核未通过。'+score+'请复习本版本材料后再试。';
     notice(message);
     await refresh(true);
     return message;
   });
   return form;
 }
 function courseCard(course,index){
   const key='course-'+index;
   const card=node('article','','panel');
   card.dataset.courseId=course.course_id;
   card.append(node('h3',course.title),node('p',(course.store_id||'集团基础课程')+' · 版本 '+course.version,'small'));
   card.append(node('p',courseState[course.progress]||'待核对'));
   if(course.latest_attempt){
     card.append(node('p',(course.latest_attempt.passed?'理论已通过':'理论未通过')+' · 得分 '+course.latest_attempt.score));
   }
   if(course.store_id)card.append(node('p',practical[course.practical_status]||'实操尚待培训官核验。'));
   if(course.practical_reason)card.append(node('p',course.practical_reason));
   if(course.practical_requirements&&course.store_id){
     const details=node('details','');details.append(node('summary','查看现场实操要求'),node('p',course.practical_requirements));card.append(details);
   }
   for(const item of course.media||[])card.append(media(item));
   if(course.media_available===false){
     card.append(node('p','课件暂无法核对。这一版本暂不能继续学习或考核，请联系培训官。','error'));
     return card;
   }
   if(course.progress==='not_started')card.append(button(key+'-enroll','开始学习','正在登记…',()=>
     record(courseUrl(course,'enroll'),{},'已开始学习。请阅读本版本的课件。')));
   if(course.progress==='in_progress')card.append(button(key+'-complete','确认已学习','正在登记…',()=>
     record(courseUrl(course,'complete'),{},'已记录学习完成。接下来请参加理论考核。')));
   if(course.progress==='completed'&&!course.latest_attempt?.passed&&course.questions?.length)card.append(exam(course,key));
   return card;
 }
 function storeCard(store){
   const row=node('article','','item');
   row.append(node('strong',store.name?store.name+' · '+store.store_id:store.store_id),node('p',store.can_schedule?'当前可安排班次。':'目前不能安排班次。'),
       node('p',store.can_pos?'可以使用本店已登记设备点单。':academyReason(store.reason)));
   return row;
 }
 function shiftCard(shift,index){
   const card=node('article','','item');
   card.append(node('strong',formatShift(shift)),node('p',shiftLabel(shift.status)));
   if(shift.status==='approved')card.append(button('confirm-shift-'+index,'确认参加本班次','正在确认…',()=>
     record(root+'/shifts/'+encode(shift.shift_id)+'/confirm',{},'班次已确认。请按约定时间到店。')));
   return card;
 }
 async function refresh(retainMessage=false){
   try{
     const work=await request(root+'/work');
     $('#academy-status').textContent='已核对本人培训、资格和班次。';
     lines($('#academy-courses'),work.courses,courseCard);
     lines($('#academy-stores'),work.stores,storeCard);
     lines($('#academy-shifts'),work.shifts,shiftCard);
     return '已核对培训、资格和班次。';
   }catch(error){
     $('#academy-status').textContent=error.status===401?'请先到个人中心登录，再查看培训和班次。':'暂时无法核对培训和班次。';
     for(const key of ['#academy-courses','#academy-stores','#academy-shifts'])$(key).replaceChildren();
     if(!retainMessage)throw error;
   }
 }
 action($('#academy-refresh'),'正在核对…',refresh);
 refresh().catch(error=>notice(error.message,true));
})();
