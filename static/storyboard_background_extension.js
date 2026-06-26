(function () {
  'use strict';

  const MODAL_ID = 'modal-storyboard-background';
  function apiGet(url){return window.API?.get ? window.API.get(url) : fetch(url).then(r=>r.json().then(d=>{if(!r.ok)throw new Error(d.detail||r.statusText);return d;}));}
  function apiPut(url,body){return window.API?.put ? window.API.put(url,body) : fetch(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json().then(d=>{if(!r.ok)throw new Error(d.detail||r.statusText);return d;}));}
  function apiPost(url,body){return window.API?.post ? window.API.post(url,body) : fetch(url,{method:'POST',body}).then(r=>r.json().then(d=>{if(!r.ok)throw new Error(d.detail||r.statusText);return d;}));}
  function toast(msg,duration){if(window.showToast) window.showToast(msg,duration||3000); else console.log(msg);}
  function projectId(){return window.state?.currentProject?.id || null;}

  function ensureStyle(){
    if(document.getElementById('storyboard-background-style'))return;
    const style=document.createElement('style');style.id='storyboard-background-style';
    style.textContent=`.storyboard-bg-layout{display:grid;grid-template-columns:1fr 360px;gap:1rem;align-items:start}.storyboard-bg-panel{border:2px solid var(--ink-color,#111);border-radius:14px;padding:1rem;background:#fffef9;box-shadow:3px 3px 0 rgba(0,0,0,.12)}.storyboard-bg-panel label{display:block;margin:.7rem 0;font-weight:700}.storyboard-bg-panel input[type=color]{width:72px;height:38px;padding:0;border:2px solid #111;border-radius:8px;background:#fff}.storyboard-bg-note{font-size:.88rem;line-height:1.55;color:#444}.storyboard-bg-preview{width:100%;aspect-ratio:16/9;border:2px dashed #111;border-radius:14px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#fff}.storyboard-bg-preview img{width:100%;height:100%;object-fit:cover}.storyboard-bg-warning{background:#fff8dc;border-left:4px solid #d6a100;padding:.7rem;margin:.8rem 0;font-size:.88rem;line-height:1.5}@media(max-width:900px){.storyboard-bg-layout{grid-template-columns:1fr}}`;
    document.head.appendChild(style);
  }

  function ensureButton(){
    const host=document.querySelector('#step-panel-2 .step2-sticky-header div[style*="align-items"] div');
    if(!host||document.getElementById('step2-btn-background-settings'))return;
    const btn=document.createElement('button');
    btn.id='step2-btn-background-settings';btn.type='button';btn.className='secondary';btn.style.cssText='font-size:0.85rem;padding:0.35rem 0.9rem;';btn.textContent='背景设置';
    const next=document.getElementById('step2-btn-save');
    host.insertBefore(btn,next||null);
    btn.addEventListener('click',openModal);
  }

  function ensureModal(){
    let modal=document.getElementById(MODAL_ID);if(modal)return modal;
    modal=document.createElement('div');modal.id=MODAL_ID;modal.className='modal-overlay';modal.style.display='none';
    modal.innerHTML=`<div class="modal-content config-editor-modal" style="max-width:980px;width:min(980px,94vw)"><div class="config-editor-scroll"><h3 class="highlight-title">分镜 / 最终视频背景设置</h3><p class="config-editor-note">生成图片仍然强制保持纯白底，用于 AI Mask 和手动 Mask 的白底连通抠除。这里设置的是最终 Reveal / 视频合成阶段的背景：可以是纯色，也可以是上传的图片。</p><div class="storyboard-bg-warning"><strong>重要：</strong>不要把复杂背景直接写进生图提示词。复杂背景会破坏白底自动抠图。系统会把背景作为独立配置写入项目，并同步到 prompt 说明和 reveal_manifest.canvas。</div><div class="storyboard-bg-layout"><section class="storyboard-bg-panel"><label>背景类型 / Background mode</label><select id="storyboard-bg-mode"><option value="solid">纯色背景 / Solid color</option><option value="image">图片背景 / Image background</option></select><label>纯色颜色 / Solid color</label><div style="display:flex;align-items:center;gap:.8rem"><input id="storyboard-bg-color" type="color" value="#FFFFFF"><input id="storyboard-bg-color-text" type="text" value="#FFFFFF" maxlength="7" style="max-width:120px"></div><label>图片填充方式 / Image fit</label><select id="storyboard-bg-fit"><option value="cover">Cover：铺满画面，可能裁剪边缘</option><option value="contain">Contain：完整显示，可能留白</option></select><label>上传背景图片 / Upload background image</label><input id="storyboard-bg-file" type="file" accept="image/*"><p class="storyboard-bg-note">建议上传 16:9 或接近 1920×1080 的图片。系统会保存为 planning/storyboard_background.png。</p></section><section class="storyboard-bg-panel"><h4>当前背景预览</h4><div id="storyboard-bg-preview" class="storyboard-bg-preview">暂无图片背景</div><p id="storyboard-bg-status" class="storyboard-bg-note"></p></section></div></div><div class="config-editor-actions"><button id="btn-storyboard-bg-cancel" class="secondary" type="button">取消</button><button id="btn-storyboard-bg-save" class="success" type="button">保存背景设置</button></div></div>`;
    document.body.appendChild(modal);
    modal.querySelector('#btn-storyboard-bg-cancel').addEventListener('click',()=>modal.style.display='none');
    modal.querySelector('#btn-storyboard-bg-save').addEventListener('click',saveBackground);
    modal.querySelector('#storyboard-bg-color').addEventListener('input',e=>{modal.querySelector('#storyboard-bg-color-text').value=e.target.value.toUpperCase();renderPreview();});
    modal.querySelector('#storyboard-bg-color-text').addEventListener('input',e=>{const v=String(e.target.value||'').trim();if(/^#[0-9a-fA-F]{6}$/.test(v))modal.querySelector('#storyboard-bg-color').value=v;renderPreview();});
    modal.querySelector('#storyboard-bg-mode').addEventListener('change',renderPreview);
    return modal;
  }

  function renderPreview(bg){
    const modal=ensureModal();
    const mode=modal.querySelector('#storyboard-bg-mode').value;
    const color=modal.querySelector('#storyboard-bg-color-text').value||'#FFFFFF';
    const preview=modal.querySelector('#storyboard-bg-preview');
    const status=modal.querySelector('#storyboard-bg-status');
    const imageUrl=bg?.image_url||modal.dataset.imageUrl||'';
    modal.dataset.imageUrl=imageUrl;
    if(mode==='image'&&imageUrl){preview.innerHTML=`<img src="${imageUrl}" alt="背景图片预览">`;status.textContent='图片背景会作为最终视频底图；visual_draft.png 仍保持纯白。';}
    else{preview.innerHTML='';preview.style.background=color;preview.textContent=mode==='image'?'尚未上传图片，保存时会回退到纯色背景':'纯色背景预览';status.textContent='纯色背景会写入 reveal_manifest.canvas.background。';}
  }

  async function openModal(){
    const id=projectId();if(!id){toast('请先打开项目。');return;}
    ensureStyle();const modal=ensureModal();modal.style.display='flex';
    try{const res=await apiGet(`/api/projects/${id}/storyboard-background`);const bg=res.background||{};modal.querySelector('#storyboard-bg-mode').value=bg.mode||'solid';modal.querySelector('#storyboard-bg-color').value=bg.solid_color||'#FFFFFF';modal.querySelector('#storyboard-bg-color-text').value=bg.solid_color||'#FFFFFF';modal.querySelector('#storyboard-bg-fit').value=bg.image_fit||'cover';modal.dataset.imageUrl=bg.image_url||'';renderPreview(bg);}catch(e){toast(`背景设置加载失败：${e.message}`,6000);}
  }

  async function saveBackground(){
    const id=projectId();if(!id)return;
    const modal=ensureModal();const btn=modal.querySelector('#btn-storyboard-bg-save');btn.disabled=true;
    try{
      const payload={mode:modal.querySelector('#storyboard-bg-mode').value,solid_color:modal.querySelector('#storyboard-bg-color-text').value,image_fit:modal.querySelector('#storyboard-bg-fit').value};
      const file=modal.querySelector('#storyboard-bg-file').files?.[0];
      if(file){const form=new FormData();form.append('file',file);await apiPost(`/api/projects/${id}/storyboard-background/image`,form);}
      const res=await apiPut(`/api/projects/${id}/storyboard-background`,payload);
      modal.querySelector('#storyboard-bg-file').value='';modal.dataset.imageUrl=res.background?.image_url||modal.dataset.imageUrl||'';renderPreview(res.background||{});modal.style.display='none';toast(`✅ 背景设置已保存，已同步 ${res.background?.patched_prompt_count||0} 个生图提示词。`);
    }catch(e){toast(`❌ 背景设置保存失败：${e.message}`,7000);}finally{btn.disabled=false;}
  }

  function boot(){ensureStyle();ensureButton();}
  const timer=setInterval(()=>{boot();if(document.getElementById('step2-btn-background-settings'))clearInterval(timer);},500);
  document.addEventListener('DOMContentLoaded',boot);
})();
