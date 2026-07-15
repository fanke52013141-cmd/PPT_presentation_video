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
    ensureButton();
  }

  const timer = setInterval(() => {
    boot();
    if (document.getElementById('step3-btn-background-settings')) clearInterval(timer);
  }, 500);
  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
