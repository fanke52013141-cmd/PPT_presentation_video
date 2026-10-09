// Shared video tools; native and composition previews keep their playback engines.
(function(){
  const audioNodes = new WeakMap();
  let audioContext;
  async function amplify(media, amount){
    audioContext ||= new AudioContext();
    await audioContext.resume();
    for(const node of media){
      let gain = audioNodes.get(node);
      if(!gain){const source=audioContext.createMediaElementSource(node);gain=audioContext.createGain();source.connect(gain);gain.connect(audioContext.destination);audioNodes.set(node,gain);}
      gain.gain.value=amount;
    }
  }
  window.attachVideoTools=function(host, adapter){
    if(!host) return;
    if(host.querySelector(':scope > .shared-video-tools')) return;
    const tools=document.createElement('div');tools.className='shared-video-tools';
    tools.innerHTML='<label>倍速 <select aria-label="播放倍速"><option>0.5</option><option selected>1</option><option>1.25</option><option>1.5</option><option>2</option></select></label><label>音量增强 <select aria-label="音量增强"><option value="1">100%</option><option value="1.5">150%</option><option value="2">200%</option></select></label><button type="button">全屏</button><button type="button">画中画</button>';
    const selects=tools.querySelectorAll('select');
    selects[0].onchange=()=>adapter.rate(Number(selects[0].value));
    selects[1].onchange=()=>amplify(adapter.media(),Number(selects[1].value)).catch(e=>showToast('音量增强不可用：'+e.message));
    const buttons=tools.querySelectorAll('button');
    buttons[0].onclick=()=>host.requestFullscreen().catch(e=>showToast(e.message));
    buttons[1].onclick=async()=>{
      try{
        const video=adapter.media().find(n=>n.tagName==='VIDEO');
        if(video&&document.pictureInPictureEnabled){await video.requestPictureInPicture();return;}
        if(!window.documentPictureInPicture){showToast('当前浏览器不支持此预览的画中画');return;}
        const pip=await window.documentPictureInPicture.requestWindow({width:800,height:500});
        document.querySelectorAll('style,link[rel=stylesheet]').forEach(style=>pip.document.head.append(style.cloneNode(true)));
        const marker=document.createComment('player');host.before(marker);pip.document.body.style.margin='0';pip.document.body.append(host);
        pip.addEventListener('pagehide',()=>{marker.replaceWith(host);});
      }catch(e){showToast('画中画不可用：'+e.message);}
    };
    if(adapter.download){const link=document.createElement('a');link.textContent='下载视频';link.href=adapter.download;link.download='video.mp4';tools.append(link);}
    host.append(tools);
  };
  const outputObserved = new WeakSet();
  let playerLoading;
  function loadOutputPlayer() {
    if (window.OutputVideoPlayer) return Promise.resolve();
    if (!playerLoading) playerLoading = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/annotation_player.bundle.js?v=20261007.4';
      script.onload = resolve;
      script.onerror = () => {playerLoading = null; reject(new Error('播放器加载失败，请刷新重试'));};
      document.head.appendChild(script);
    });
    return playerLoading;
  }
  function fitOutputPreview(host, video) {
    if (!host.isConnected || document.fullscreenElement === host) return;
    const ratio = (video.videoWidth || 1920) / (video.videoHeight || 1080);
    host.style.setProperty('--output-aspect-ratio', ratio);
    const toolsHeight = host.querySelector('.shared-video-tools')?.offsetHeight || 48;
    const actionsHeight = host.closest('.step8-video-card')?.querySelector('.step8-video-actions')?.offsetHeight || 48;
    const height = Math.max(120, Math.min(520, window.innerHeight - Math.max(140, host.getBoundingClientRect().top) - toolsHeight - actionsHeight - 48));
    host.style.setProperty('--output-preview-height', `${height}px`);
  }
  window.addEventListener('resize', () => {
    document.querySelectorAll('.step8-video-list .video-preview-box').forEach(host => {
      const video = host.querySelector(':scope > video');
      if (video) fitOutputPreview(host, video);
    });
  });
  function decorate(){
    window.OutputVideoPlayer?.cleanup();
    document.querySelectorAll('.step8-video-list video').forEach(video=>{
      if (video.closest('.output-composition-player') || outputObserved.has(video)) return;
      outputObserved.add(video);
      const host=video.parentElement;
      host.classList.add('shared-video-player');
      video.controls=true;
      requestAnimationFrame(() => fitOutputPreview(host, video));
      const mount = async () => {
        if (video.dataset.outputPlayer || !Number.isFinite(video.duration) || video.duration <= 0) return;
        video.dataset.outputPlayer='loading';
        try {
          await loadOutputPlayer();
          if (!video.isConnected) return;
          const node=document.createElement('div');node.className='output-composition-player';
          video.pause();video.hidden=true;video.style.display='none';
          host.insertBefore(node,video);
          const adapter=window.OutputVideoPlayer.mount(node,video.currentSrc||video.src,video.duration,video.videoWidth||1920,video.videoHeight||1080);
          host.querySelector(':scope > .shared-video-tools')?.remove();
          attachVideoTools(host,{rate:adapter.rate,media:()=>Array.from(node.querySelectorAll('video,audio')),download:video.currentSrc||video.src});
          video.dataset.outputPlayer='ready';
          requestAnimationFrame(() => fitOutputPreview(host, video));
        } catch(error) {delete video.dataset.outputPlayer;showToast(error.message);}
      };
      video.addEventListener('loadedmetadata',mount,{once:true});
      mount();
    });
  }
  document.addEventListener('DOMContentLoaded',()=>{decorate();new MutationObserver(decorate).observe(document.body,{childList:true,subtree:true});});
})();
