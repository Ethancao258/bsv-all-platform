"use strict";
window.BSV = (() => {
 const $ = (selector) => document.querySelector(selector);
 const notice = (message, bad=false) => {const x = $('#notice');if(!x)return;x.classList.remove('hidden');x.classList.toggle('error',bad);x.textContent=message;};
 const cookie = (name) => document.cookie.split('; ').map(x=>x.split('=')).find(x=>x[0]===name)?.slice(1).join('=')||'';
 const request = async (url,options={}) => {
   const headers = {'Accept':'application/json', ...options.headers};
   if(options.body){headers['Content-Type']='application/json';headers['X-CSRF-Token']=decodeURIComponent(cookie('bsv_csrf'));}
   let response;try{response=await fetch(url,{credentials:'same-origin',...options,headers});}catch{throw new Error('无法连接服务；数据库A或服务器可能不可用，操作已中止。');}
   const data=await response.json().catch(()=>({}));
   if(!response.ok)throw new Error((data.error?.code||'HTTP_'+response.status)+'：'+(data.error?.message||'请求失败'));
   return data;
 };
 const send=(url,body)=>request(url,{method:'POST',body:JSON.stringify(body)});
 const node=(tag,text,cls)=>{const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;};
 const lines=(container,items,render)=>{container.replaceChildren();if(!items?.length){container.append(node('p','暂无记录','small'));return;}items.forEach(item=>container.append(render(item)));};
 const take = (form, key) => new FormData(form).get(key)?.toString().trim()||'';
 const iso=(text)=>{if(!text)return null;const normalized=text.length===16?text+':00+08:00':text;const d=new Date(normalized);return Number.isFinite(d.valueOf())?d.toISOString():null;};
 const safe=async fn=>{try{await fn();}catch(e){notice(e.message,true);}};
 return {$,notice,request,send,node,lines,take,iso,safe};
})();
