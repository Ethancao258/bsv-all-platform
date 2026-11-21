/* BSV POS integration entry: business POS must request an authorized short-lived visit context
   from its own trusted backend; never construct or sign this token in the browser. */
(()=>{'use strict';window.BSVGrowthPOS=Object.freeze({
 openCustomerPanel({storeId,context}){
   if(!/^[A-Za-z0-9_-]{3,40}$/.test(storeId)||typeof context!=='string'||context.length>3000||!context.includes('.'))
     throw Error('接待授权尚未核验');
   const url='/staff/growth/?'+new URLSearchParams({store_id:storeId})+'#service&context='+encodeURIComponent(context);
   window.location.assign(url);
 }
});})();
