(function(){
  'use strict';
  function b64ToBytes(value){
    const padding='='.repeat((4-value.length%4)%4);
    const base64=(value+padding).replace(/-/g,'+').replace(/_/g,'/');
    const raw=atob(base64);
    return Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));
  }
  function isIOS(){ return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform==='MacIntel' && navigator.maxTouchPoints>1); }
  function standalone(){ return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone===true; }
  function deviceName(){
    const ua=navigator.userAgent;
    if(isIOS()) return standalone() ? 'iPhone / iPad · FMTS PWA' : 'iPhone / iPad · Safari';
    if(/Android/i.test(ua)) return /Chrome/i.test(ua) ? 'Android · Chrome' : 'Android · браузер';
    if(/Windows/i.test(ua)) return 'Windows · браузер';
    if(/Macintosh/i.test(ua)) return 'Mac · браузер';
    return 'Браузер';
  }
  async function registration(){
    if(!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('Этот браузер не поддерживает Web Push.');
    return await navigator.serviceWorker.ready;
  }
  async function currentSubscription(){ const reg=await registration(); return await reg.pushManager.getSubscription(); }
  async function serverStatus(){
    const r=await fetch('/api/push/status',{headers:{'Accept':'application/json'}});
    if(!r.ok) throw new Error('Не удалось получить статус push.');
    return await r.json();
  }
  function setMessage(text,type){
    document.querySelectorAll('[data-push-message]').forEach(el=>{el.textContent=text||'';el.className='push-inline-message '+(type||'');el.hidden=!text;});
  }
  function setUi(state){
    const connected=!!state.connected;
    document.querySelectorAll('[data-push-state]').forEach(el=>{
      el.textContent=connected?'Подключено':'Не подключено';
      el.classList.toggle('is-on',connected); el.classList.toggle('is-off',!connected);
    });
    document.querySelectorAll('[data-push-enable]').forEach(b=>{b.hidden=connected;});
    document.querySelectorAll('[data-push-disable]').forEach(b=>{b.hidden=!connected;});
    document.querySelectorAll('[data-push-test]').forEach(b=>{b.disabled=!connected;});
  }
  async function refresh(){
    try{
      const [srv,sub]=await Promise.all([serverStatus(),currentSubscription().catch(()=>null)]);
      setUi({connected:!!sub && srv.configured});
      document.querySelectorAll('[data-push-device-count]').forEach(el=>el.textContent=String(srv.devices||0));
      return {server:srv,subscription:sub};
    }catch(e){ setUi({connected:false}); return null; }
  }
  async function enable(){
    try{
      setMessage('Подключаем уведомления…','working');
      if(isIOS() && !standalone()){
        throw new Error('На iPhone сначала добавьте FMTS на экран «Домой» через Safari, затем откройте установленное приложение и включите уведомления.');
      }
      if(!('Notification' in window)) throw new Error('Уведомления не поддерживаются этим браузером.');
      let permission=Notification.permission;
      if(permission!=='granted') permission=await Notification.requestPermission();
      if(permission!=='granted') throw new Error('Разрешение на уведомления не выдано. Его можно включить в настройках браузера/телефона.');
      const reg=await registration();
      const keyResp=await fetch('/api/push/public-key');
      if(!keyResp.ok) throw new Error('Не удалось получить ключ Web Push.');
      const {public_key}=await keyResp.json();
      if(!public_key) throw new Error('Web Push ещё не настроен администратором.');
      let sub=await reg.pushManager.getSubscription();
      if(!sub){
        sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64ToBytes(public_key)});
      }
      const json=sub.toJSON();
      const resp=await fetch('/api/push/subscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:json.endpoint,keys:json.keys||{},device_name:deviceName()})});
      if(!resp.ok){const data=await resp.json().catch(()=>({}));throw new Error(data.detail||'Не удалось сохранить push-подписку.');}
      localStorage.removeItem('fmts-push-nudge-dismissed');
      setMessage('Готово. FMTS может присылать уведомления на это устройство.','ok');
      setUi({connected:true});
      const n=document.getElementById('pushNudge'); if(n)n.hidden=true;
      await refresh();
    }catch(e){setMessage(e.message||String(e),'error'); throw e;}
  }
  async function disableCurrent(){
    try{
      const sub=await currentSubscription();
      if(sub){
        await fetch('/api/push/unsubscribe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({endpoint:sub.endpoint})});
        await sub.unsubscribe();
      }
      setMessage('Push отключён на этом устройстве.','ok'); setUi({connected:false}); await refresh();
    }catch(e){setMessage(e.message||String(e),'error');}
  }
  async function test(){
    try{
      setMessage('Отправляем тестовое уведомление…','working');
      const r=await fetch('/api/push/test',{method:'POST'});
      const data=await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(data.detail||'Не удалось отправить тест.');
      setMessage('Тест отправлен. Проверьте уведомления телефона.','ok');
    }catch(e){setMessage(e.message||String(e),'error');}
  }
  function bind(){
    document.querySelectorAll('[data-push-enable]').forEach(b=>b.addEventListener('click',()=>enable().catch(()=>{})));
    document.querySelectorAll('[data-push-disable]').forEach(b=>b.addEventListener('click',disableCurrent));
    document.querySelectorAll('[data-push-test]').forEach(b=>b.addEventListener('click',test));
    const dismiss=document.querySelector('[data-push-nudge-dismiss]');
    if(dismiss)dismiss.addEventListener('click',()=>{const n=document.getElementById('pushNudge');if(n)n.hidden=true;localStorage.setItem('fmts-push-nudge-dismissed',String(Date.now()));});
    refresh().then(state=>{
      const n=document.getElementById('pushNudge'); if(!n||!state||!state.server.configured)return;
      const dismissed=Number(localStorage.getItem('fmts-push-nudge-dismissed')||0);
      const recently=Date.now()-dismissed<7*24*3600*1000;
      if(!state.subscription && ('Notification' in window) && Notification.permission!=='denied' && !recently) setTimeout(()=>{n.hidden=false;},700);
    });
  }
  window.fmtsPush={enable,disableCurrent,test,refresh,deviceName,isIOS,standalone};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind);else bind();
})();
