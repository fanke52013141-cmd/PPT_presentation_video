(function () {
  'use strict';

  const MODAL_ID = 'modal-storyboard-background';

  function parseResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(parseResponse);
  }

  function apiPut(url, body) {
    return window.API?.put ? window.API.put(url, body) : fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(parseResponse);
  }

  function apiPostForm(url, body) {
    return fetch(url, { method: 'POST', body }).then(parseResponse);
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function activeProjectId() {
    const current = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (current) sessionStorage.setItem('ppt_storyboard_background_project_id', String(current));
    return current || sessionStorage.getItem('ppt_storyboard_background_project_id') || '';
  }

  function ensureStyle() {
    if (document.getElementById('storyboard-background-style')) return;
    const style = document.createElement('style');
    style.id = 'storyboard-background-style';
    style.textContent = `
      #step3-btn-background-settings{font-size:.85rem;padding:.35rem .9rem}
      .storyboard-bg-modal{width:min(1240px,95vw);max-width:1240px;padding:0!important;overflow:hidden;border-radius:20px}
      .storyboard-bg-header{height:78px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid #e5e9f2;background:#fff}
      .storyboard-bg-title{display:flex;align-items:center;gap:13px;margin:0;font-size:1.35rem;color:#172033}
      .storyboard-bg-title-icon{width:40px;height:40px;border-radius:10px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#8b7bff,#5939ec);box-shadow:0 8px 18px rgba(103,75,238,.22)}
      .storyboard-bg-close{display:flex;align-items:center;gap:7px;border:1px solid #dbe2ef!important;background:#fff!important;color:#344054!important;border-radius:10px!important;padding:.62rem .9rem!important}
      .storyboard-bg-body{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.08fr);min-height:590px;max-height:72vh;overflow:auto;background:#fff}
      .storyboard-bg-column{padding:26px 28px}
      .storyboard-bg-column+.storyboard-bg-column{border-left:1px solid #e5e9f2}
      .storyboard-bg-section{margin-bottom:24px}
      .storyboard-bg-section-title,.storyboard-bg-preview-title{margin:0 0 14px;font-weight:800;color:#172033;font-size:1rem}
      .storyboard-bg-choice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
      .storyboard-bg-choice{position:relative;min-height:128px;border:1.5px solid #dce3ef;border-radius:13px;padding:21px 20px;background:#fff;cursor:pointer;transition:.18s ease;box-sizing:border-box}
      .storyboard-bg-choice:hover{border-color:#9b8dff;transform:translateY(-1px)}
      .storyboard-bg-choice.active{border-color:#684cff;box-shadow:0 0 0 2px rgba(104,76,255,.08);background:linear-gradient(145deg,#fff,#fbfaff)}
      .storyboard-bg-choice input{position:absolute;right:15px;top:15px;width:22px;height:22px;accent-color:#684cff}
      .storyboard-bg-choice-icon{font-size:1.8rem;line-height:1;display:block;margin-bottom:15px;color:#6551e8}
      .storyboard-bg-choice strong{display:block;color:#202a3c;font-size:1rem;margin-bottom:6px}
      .storyboard-bg-choice small{display:block;color:#7a8497;font-size:.82rem;line-height:1.45}
      .storyboard-bg-mode-panel[hidden]{display:none!important}
      .storyboard-bg-hex-label{display:block;color:#344054;font-size:.88rem;margin-bottom:8px}
      .storyboard-bg-hex{height:52px;display:grid;grid-template-columns:52px 1fr 66px;border:1px solid #dbe2ef;border-radius:10px;overflow:hidden;background:#fff}
      .storyboard-bg-hex span{display:grid;place-items:center;border-right:1px solid #dbe2ef;color:#344054;font-weight:700}
      .storyboard-bg-hex input[type=text]{border:0!important;outline:0!important;padding:0 16px!important;box-shadow:none!important;font-weight:700;text-transform:uppercase}
      .storyboard-bg-hex input[type=color]{width:38px;height:32px;padding:0;border:0;background:none;align-self:center;justify-self:center;cursor:pointer}
      .storyboard-bg-help{margin:9px 0 0;color:#7a8497;font-size:.82rem;line-height:1.5}
      .storyboard-bg-upload-line{display:flex;align-items:center;border:1px solid #dbe2ef;border-radius:10px;min-height:44px;overflow:hidden;margin-bottom:12px}
      .storyboard-bg-file-button{display:inline-flex;align-items:center;gap:7px;padding:11px 16px;color:#5a41e8;background:#f8f7ff;border-right:1px solid #e2ddff;cursor:pointer;font-weight:700;font-size:.86rem}
      .storyboard-bg-file-name{padding:0 14px;color:#7a8497;font-size:.84rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      #storyboard-bg-file{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
      .storyboard-bg-dropzone{height:130px;border:1.5px dashed #b9afff;border-radius:12px;display:grid;place-items:center;text-align:center;color:#687386;background:linear-gradient(180deg,#fff,#fbfaff);cursor:pointer;transition:.18s}
      .storyboard-bg-dropzone.dragover{border-color:#684cff;background:#f6f3ff}
      .storyboard-bg-dropzone strong{display:block;color:#4f596c;margin:8px 0 2px}
      .storyboard-bg-dropzone span{font-size:1.8rem;color:#684cff}
      .storyboard-bg-preview-meta{display:inline-flex;padding:6px 13px;border-radius:9px;background:#f0edff;color:#6247ed;font-weight:800;font-size:.84rem;margin-bottom:14px}
      .storyboard-bg-preview{width:100%;aspect-ratio:16 / 9;border:1px solid #e0e5ef;border-radius:12px;display:grid;place-items:center;overflow:hidden;background:#fff;color:#fff;text-align:center;box-sizing:border-box;box-shadow:0 3px 12px rgba(24,32,51,.04)}
      .storyboard-bg-preview img{width:100%;height:100%;display:block}
      .storyboard-bg-preview-placeholder{color:#7b8496;padding:20px}
      .storyboard-bg-preview-placeholder strong{display:block;color:#50596b;margin-top:8px}
      .storyboard-bg-footer{display:flex;align-items:center;justify-content:flex-end;gap:14px;padding:18px 28px;border-top:1px solid #e5e9f2;background:#fff}
      .storyboard-bg-footer button{min-width:104px;border-radius:10px!important}
      .storyboard-bg-footer .primary{min-width:136px;background:linear-gradient(135deg,#745cff,#5334e7)!important}
      @media(max-width:860px){.storyboard-bg-body{grid-template-columns:1fr;max-height:76vh}.storyboard-bg-column+.storyboard-bg-column{border-left:0;border-top:1px solid #e5e9f2}.storyboard-bg-choice-grid{grid-template-columns:1fr}.storyboard-bg-preview{max-height:none}}
    `;
    document.head.appendChild(style);
  }

  function ensureButton() {
    document.getElementById('step2-btn-background-settings')?.remove();
    const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!toolbar || document.getElementById('step3-btn-background-settings')) return;
    const button = document.createElement('button');
    button.id = 'step3-btn-background-settings';
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = '最终视频背景';
    const confirmButton = document.getElementById('step3-btn-confirm');
    toolbar.insertBefore(button, confirmButton || null);
    button.addEventListener('click', openModal);
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content storyboard-bg-modal" role="dialog" aria-modal="true" aria-labelledby="storyboard-bg-title">
        <header class="storyboard-bg-header">
          <h3 id="storyboard-bg-title" class="storyboard-bg-title"><span class="storyboard-bg-title-icon">▧</span>最终视频背景设置</h3>
          <button id="btn-storyboard-bg-x" class="storyboard-bg-close" type="button"><span aria-hidden="true">×</span> 关闭</button>
        </header>
        <div class="storyboard-bg-body">
          <div class="storyboard-bg-column">
            <section class="storyboard-bg-section">
              <h4 class="storyboard-bg-section-title">1. 选择背景类型</h4>
              <div class="storyboard-bg-choice-grid">
                <label class="storyboard-bg-choice" data-mode-card="image">
                  <input type="radio" name="storyboard-bg-mode" value="image">
                  <span class="storyboard-bg-choice-icon">▧</span><strong>上传图片</strong><small>上传图片作为最终视频背景</small>
                </label>
                <label class="storyboard-bg-choice" data-mode-card="solid">
                  <input type="radio" name="storyboard-bg-mode" value="solid">
                  <span class="storyboard-bg-choice-icon">◉</span><strong>纯色背景</strong><small>使用纯色作为最终视频背景</small>
                </label>
              </div>
            </section>
            <section id="storyboard-bg-solid-panel" class="storyboard-bg-section storyboard-bg-mode-panel">
              <h4 class="storyboard-bg-section-title">2. 设置背景颜色</h4>
              <label class="storyboard-bg-hex-label" for="storyboard-bg-color-text">颜色值（HEX）</label>
              <div class="storyboard-bg-hex"><span>#</span><input id="storyboard-bg-color-text" type="text" maxlength="6" value="FFFFFF" inputmode="text"><input id="storyboard-bg-color" type="color" value="#FFFFFF" aria-label="选择背景颜色"></div>
              <p class="storyboard-bg-help">请输入 6 位 HEX 颜色值，例如 #7B61FF</p>
            </section>
            <div id="storyboard-bg-image-panel" class="storyboard-bg-mode-panel">
              <section class="storyboard-bg-section">
                <h4 class="storyboard-bg-section-title">2. 图片显示方式</h4>
                <div class="storyboard-bg-choice-grid">
                  <label class="storyboard-bg-choice" data-fit-card="cover"><input type="radio" name="storyboard-bg-fit-choice" value="cover"><span class="storyboard-bg-choice-icon">▣</span><strong>铺满画面</strong><small>等比放大铺满 16:9，超出边缘会被裁剪</small></label>
                  <label class="storyboard-bg-choice" data-fit-card="contain"><input type="radio" name="storyboard-bg-fit-choice" value="contain"><span class="storyboard-bg-choice-icon">▭</span><strong>完整显示</strong><small>完整显示图片，留白区域使用背景色补齐</small></label>
                </div>
                <select id="storyboard-bg-fit" hidden><option value="cover">铺满画面</option><option value="contain">完整显示</option></select>
              </section>
              <section class="storyboard-bg-section">
                <h4 class="storyboard-bg-section-title">3. 上传背景图片</h4>
                <div class="storyboard-bg-upload-line"><label class="storyboard-bg-file-button" for="storyboard-bg-file">⇧ 选择文件</label><span id="storyboard-bg-file-name" class="storyboard-bg-file-name">未选择任何文件</span></div>
                <input id="storyboard-bg-file" type="file" accept="image/jpeg,image/png,image/webp">
                <p class="storyboard-bg-help">支持 JPG / PNG / WEBP，建议尺寸 1920×1080，大小不超过 12MB</p>
                <label id="storyboard-bg-dropzone" class="storyboard-bg-dropzone" for="storyboard-bg-file"><div><span>⬆</span><strong>拖拽图片到这里，或点击上传</strong><small>始终以 16:9 画面预览</small></div></label>
              </section>
            </div>
          </div>
          <div class="storyboard-bg-column">
            <h4 class="storyboard-bg-preview-title">效果预览</h4>
            <span class="storyboard-bg-preview-meta">16:9 预览</span>
            <div id="storyboard-bg-preview" class="storyboard-bg-preview"></div>
            <p id="storyboard-bg-status" class="storyboard-bg-help"></p>
          </div>
        </div>
        <footer class="storyboard-bg-footer"><button id="btn-storyboard-bg-cancel" class="secondary" type="button">取消</button><button id="btn-storyboard-bg-save" class="primary" type="button">保存设置</button></footer>
      </div>`;
    document.body.appendChild(modal);

    const close = () => { modal.style.display = 'none'; };
    modal.addEventListener('click', event => { if (event.target === modal) close(); });
    modal.querySelector('#btn-storyboard-bg-cancel').addEventListener('click', close);
    modal.querySelector('#btn-storyboard-bg-x').addEventListener('click', close);
    modal.querySelector('#btn-storyboard-bg-save').addEventListener('click', saveBackground);
    modal.querySelectorAll('input[name="storyboard-bg-mode"]').forEach(input => input.addEventListener('change', () => setMode(input.value)));
    modal.querySelectorAll('input[name="storyboard-bg-fit-choice"]').forEach(input => input.addEventListener('change', () => {
      modal.querySelector('#storyboard-bg-fit').value = input.value;
      renderPreview();
    }));
    modal.querySelector('#storyboard-bg-color-text').addEventListener('input', syncColorFromText);
    modal.querySelector('#storyboard-bg-color').addEventListener('input', event => {
      modal.querySelector('#storyboard-bg-color-text').value = event.target.value.slice(1).toUpperCase();
      renderPreview();
    });
    modal.querySelector('#storyboard-bg-file').addEventListener('change', handleFileSelection);
    const dropzone = modal.querySelector('#storyboard-bg-dropzone');
    ['dragenter', 'dragover'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('dragover'); }));
    ['dragleave', 'drop'].forEach(name => dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('dragover'); }));
    dropzone.addEventListener('drop', event => {
      const files = Array.from(event.dataTransfer?.files || []).filter(file => file.type.startsWith('image/'));
      if (!files.length) return toast('请拖入有效的图片文件。');
      const transfer = new DataTransfer();
      transfer.items.add(files[0]);
      modal.querySelector('#storyboard-bg-file').files = transfer.files;
      handleFileSelection();
    });
    return modal;
  }

  function normalizedColor() {
    const modal = ensureModal();
    const value = String(modal.querySelector('#storyboard-bg-color-text').value || '').replace(/^#/, '').toUpperCase();
    return /^[0-9A-F]{6}$/.test(value) ? `#${value}` : '#FFFFFF';
  }

  function syncColorFromText() {
    const modal = ensureModal();
    const text = modal.querySelector('#storyboard-bg-color-text');
    text.value = text.value.replace(/[^0-9a-f]/gi, '').slice(0, 6).toUpperCase();
    if (text.value.length === 6) modal.querySelector('#storyboard-bg-color').value = `#${text.value}`;
    renderPreview();
  }

  function setMode(mode) {
    const modal = ensureModal();
    modal.dataset.mode = mode === 'image' ? 'image' : 'solid';
    modal.querySelectorAll('[data-mode-card]').forEach(card => {
      const active = card.dataset.modeCard === modal.dataset.mode;
      card.classList.toggle('active', active);
      card.querySelector('input').checked = active;
    });
    modal.querySelector('#storyboard-bg-image-panel').hidden = modal.dataset.mode !== 'image';
    modal.querySelector('#storyboard-bg-solid-panel').hidden = modal.dataset.mode !== 'solid';
    renderPreview();
  }

  function handleFileSelection() {
    const modal = ensureModal();
    const file = modal.querySelector('#storyboard-bg-file').files?.[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) {
      modal.querySelector('#storyboard-bg-file').value = '';
      return toast('背景图片不能超过 12MB。', 4500);
    }
    if (modal.dataset.previewObjectUrl) URL.revokeObjectURL(modal.dataset.previewObjectUrl);
    modal.dataset.previewObjectUrl = URL.createObjectURL(file);
    modal.querySelector('#storyboard-bg-file-name').textContent = file.name;
    setMode('image');
  }

  function renderPreview(background) {
    const modal = ensureModal();
    const mode = modal.dataset.mode || background?.mode || 'solid';
    const fit = modal.querySelector('#storyboard-bg-fit').value || background?.image_fit || 'cover';
    const color = normalizedColor();
    const preview = modal.querySelector('#storyboard-bg-preview');
    const imageUrl = modal.dataset.previewObjectUrl || background?.image_url || modal.dataset.imageUrl || '';
    const red = parseInt(color.slice(1, 3), 16);
    const green = parseInt(color.slice(3, 5), 16);
    const blue = parseInt(color.slice(5, 7), 16);
    preview.style.color = ((red * 299 + green * 587 + blue * 114) / 1000) > 155 ? '#344054' : '#FFFFFF';
    modal.querySelectorAll('[data-fit-card]').forEach(card => {
      const active = card.dataset.fitCard === fit;
      card.classList.toggle('active', active);
      card.querySelector('input').checked = active;
    });
    preview.style.background = color;
    if (mode === 'image' && imageUrl) {
      preview.innerHTML = `<img src="${imageUrl}" alt="最终视频背景预览" style="object-fit:${fit};background:${color}">`;
    } else if (mode === 'image') {
      preview.innerHTML = '<div class="storyboard-bg-preview-placeholder"><span>▧</span><strong>上传后在这里预览</strong><small>预览比例固定为 16:9</small></div>';
    } else {
      preview.innerHTML = `<strong>纯色背景预览<br><small>${color}</small></strong>`;
    }
  }

  async function openModal() {
    const projectId = activeProjectId();
    if (!projectId) return toast('请先打开项目。');
    ensureStyle();
    const modal = ensureModal();
    modal.style.display = 'flex';
    try {
      const result = await apiGet(`/api/projects/${encodeURIComponent(projectId)}/storyboard-background`);
      const background = result.background || {};
      modal.dataset.imageUrl = background.image_url || '';
      modal.querySelector('#storyboard-bg-fit').value = background.image_fit || 'cover';
      const color = String(background.solid_color || '#FFFFFF').toUpperCase();
      modal.querySelector('#storyboard-bg-color').value = color;
      modal.querySelector('#storyboard-bg-color-text').value = color.slice(1);
      modal.querySelector('#storyboard-bg-file').value = '';
      modal.querySelector('#storyboard-bg-file-name').textContent = background.image_exists ? '已上传背景图片' : '未选择任何文件';
      setMode(background.mode || (background.image_exists ? 'image' : 'solid'));
      renderPreview(background);
    } catch (error) {
      toast(`背景设置加载失败：${error.message}`, 6000);
    }
  }

  async function saveBackground() {
    const projectId = activeProjectId();
    if (!projectId) return;
    const modal = ensureModal();
    const button = modal.querySelector('#btn-storyboard-bg-save');
    const mode = modal.dataset.mode || 'solid';
    const file = modal.querySelector('#storyboard-bg-file').files?.[0];
    if (mode === 'image' && !file && !modal.dataset.imageUrl) return toast('请先上传一张背景图片。', 4500);
    const payload = { mode, solid_color: normalizedColor(), image_fit: modal.querySelector('#storyboard-bg-fit').value || 'cover' };
    button.disabled = true;
    button.textContent = '保存中...';
    try {
      // First persist the requested fit so the upload endpoint renders the new file correctly.
      await apiPut(`/api/projects/${encodeURIComponent(projectId)}/storyboard-background`, payload);
      if (file) {
        const form = new FormData();
        form.append('file', file);
        await apiPostForm(`/api/projects/${encodeURIComponent(projectId)}/storyboard-background/image`, form);
      }
      const result = await apiPut(`/api/projects/${encodeURIComponent(projectId)}/storyboard-background`, payload);
      if (modal.dataset.previewObjectUrl) URL.revokeObjectURL(modal.dataset.previewObjectUrl);
      modal.dataset.previewObjectUrl = '';
      modal.dataset.imageUrl = result.background?.image_url || modal.dataset.imageUrl || '';
      modal.style.display = 'none';
      toast('最终视频背景已保存。', 3500);
    } catch (error) {
      toast(`最终视频背景保存失败：${error.message}`, 7000);
    } finally {
      button.disabled = false;
      button.textContent = '保存设置';
    }
  }

  function boot() {
    ensureStyle();
    ensureButton();
  }

  const timer = setInterval(() => {
    boot();
    if (document.getElementById('step3-btn-background-settings')) clearInterval(timer);
  }, 500);
  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
