(function () {
  'use strict';

  const MODAL_ID = 'modal-storyboard-background';

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
  }

  function apiPut(url, body) {
    return window.API?.put ? window.API.put(url, body) : fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
  }

  function apiPost(url, body) {
    return window.API?.post ? window.API.post(url, body) : fetch(url, { method: 'POST', body }).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
  }

  function toast(msg, duration) {
    if (window.showToast) window.showToast(msg, duration || 3000);
    else console.log(msg);
  }

  function projectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) return fromWindow;
    const urls = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const match = urls.match(/\/api\/projects\/([^/]+)\//);
    if (match) return decodeURIComponent(match[1]);
    return sessionStorage.getItem('ppt_storyboard_background_project_id') || '';
  }

  function rememberProjectId(id) {
    if (!id) return;
    sessionStorage.setItem('ppt_storyboard_background_project_id', String(id));
  }

  function ensureStyle() {
    if (document.getElementById('storyboard-background-style')) return;
    const style = document.createElement('style');
    style.id = 'storyboard-background-style';
    style.textContent = `
      .storyboard-bg-layout{display:grid;gap:1rem;align-items:start}
      .storyboard-bg-panel{border:1px solid var(--color-border-default,#dbe2f0);border-radius:16px;padding:1rem;background:#fff;box-shadow:none}
      .storyboard-bg-panel label{display:block;margin:.7rem 0;font-weight:800}
      .storyboard-bg-fit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem;margin:.55rem 0 1rem}
      .storyboard-bg-fit-card{display:flex;align-items:center;gap:.75rem;border:1.5px solid var(--color-border-default,#dbe2f0);border-radius:14px;background:#fff;padding:.9rem;cursor:pointer}
      .storyboard-bg-fit-card input{width:auto;margin:0}
      .storyboard-bg-fit-card.active{border-color:var(--color-primary-base,#7c6df2);box-shadow:0 0 0 3px rgba(124,109,242,.12)}
      .storyboard-bg-fit-card strong{display:block;margin-bottom:.15rem}
      .storyboard-bg-fit-card span{display:block;color:#667085;font-size:.84rem;line-height:1.35}
      .storyboard-bg-upload-row{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap}
      .storyboard-bg-upload-row input{max-width:360px}
      .storyboard-bg-note{font-size:.88rem;line-height:1.55;color:#667085}
      .storyboard-bg-preview{width:100%;aspect-ratio:16/9;border:1px solid var(--color-border-default,#dbe2f0);border-radius:14px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#fff;text-align:center;padding:.5rem;box-sizing:border-box}
      .storyboard-bg-preview img{width:100%;height:100%;object-fit:cover}
      #step3-btn-background-settings{font-size:.85rem;padding:.35rem .9rem}
      @media(max-width:760px){.storyboard-bg-fit-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensureButton() {
    document.getElementById('step2-btn-background-settings')?.remove();
    const host = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!host || document.getElementById('step3-btn-background-settings')) return;
    const btn = document.createElement('button');
    btn.id = 'step3-btn-background-settings';
    btn.type = 'button';
    btn.className = 'secondary';
    btn.textContent = '最终视频背景';
    const next = document.getElementById('step3-btn-confirm');
    host.insertBefore(btn, next || null);
    btn.addEventListener('click', openModal);
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content config-editor-modal" style="max-width:980px;width:min(980px,94vw)">
        <div class="config-editor-scroll">
          <h3 class="highlight-title">最终视频背景</h3>
          <button id="btn-storyboard-bg-x" class="secondary" type="button" style="position:absolute;right:1.2rem;top:1.2rem">关闭</button>
          <div class="storyboard-bg-layout">
            <section class="storyboard-bg-panel">
              <label>图片填充方式</label>
              <div class="storyboard-bg-fit-grid">
                <label class="storyboard-bg-fit-card" data-fit-card="cover">
                  <input type="radio" name="storyboard-bg-fit-choice" value="cover">
                  <span><strong>铺满画面</strong><span>等比放大到铺满 16:9，超出边缘会被裁剪。</span></span>
                </label>
                <label class="storyboard-bg-fit-card" data-fit-card="contain">
                  <input type="radio" name="storyboard-bg-fit-choice" value="contain">
                  <span><strong>完整显示</strong><span>等比缩放完整展示，空白区域用背景色补齐。</span></span>
                </label>
              </div>
              <select id="storyboard-bg-fit" style="display:none">
                <option value="cover">铺满画面</option>
                <option value="contain">完整显示</option>
              </select>
              <label>上传最终视频背景图片</label>
              <div class="storyboard-bg-upload-row">
                <input id="storyboard-bg-file" type="file" accept="image/*">
              </div>
              <div id="storyboard-bg-preview" class="storyboard-bg-preview">暂无图片背景</div>
              <p id="storyboard-bg-status" class="storyboard-bg-note"></p>
            </section>
          </div>
        </div>
        <div class="config-editor-actions">
          <button id="btn-storyboard-bg-cancel" class="secondary" type="button">取消</button>
          <button id="btn-storyboard-bg-save" class="success" type="button">保存最终视频背景</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#btn-storyboard-bg-cancel').addEventListener('click', () => modal.style.display = 'none');
    modal.querySelector('#btn-storyboard-bg-x').addEventListener('click', () => modal.style.display = 'none');
    modal.querySelector('#btn-storyboard-bg-save').addEventListener('click', saveBackground);
    modal.querySelectorAll('input[name="storyboard-bg-fit-choice"]').forEach(input => {
      input.addEventListener('change', () => {
        modal.querySelector('#storyboard-bg-fit').value = input.value;
        renderPreview();
      });
    });
    modal.querySelector('#storyboard-bg-file').addEventListener('change', () => {
      const file = modal.querySelector('#storyboard-bg-file').files?.[0];
      if (file) {
        if (modal.dataset.previewObjectUrl) URL.revokeObjectURL(modal.dataset.previewObjectUrl);
        modal.dataset.imageUrl = URL.createObjectURL(file);
        modal.dataset.previewObjectUrl = modal.dataset.imageUrl;
      }
      renderPreview();
    });
    return modal;
  }

  function renderPreview(bg) {
    const modal = ensureModal();
    const mode = 'image';
    const color = '#FFFFFF';
    const fit = modal.querySelector('#storyboard-bg-fit').value || 'cover';
    const preview = modal.querySelector('#storyboard-bg-preview');
    const status = modal.querySelector('#storyboard-bg-status');
    modal.querySelectorAll('.storyboard-bg-fit-card').forEach(card => {
      card.classList.toggle('active', card.dataset.fitCard === fit);
      const input = card.querySelector('input');
      if (input) input.checked = card.dataset.fitCard === fit;
    });
    const imageUrl = bg?.image_url || modal.dataset.imageUrl || '';
    modal.dataset.imageUrl = imageUrl;
    preview.style.background = color;
    if (mode === 'image' && imageUrl) {
      preview.innerHTML = `<img src="${imageUrl}" alt="背景图片预览" style="object-fit:${fit}">`;
      status.textContent = '';
    } else {
      preview.innerHTML = '';
      preview.textContent = '上传后在这里预览';
      status.textContent = '';
    }
  }

  async function openModal() {
    const id = projectId();
    if (!id) { toast('请先打开项目。'); return; }
    rememberProjectId(id);
    ensureStyle();
    const modal = ensureModal();
    modal.style.display = 'flex';
    try {
      const res = await apiGet(`/api/projects/${encodeURIComponent(id)}/storyboard-background`);
      const bg = res.background || {};
      modal.querySelector('#storyboard-bg-fit').value = bg.image_fit || 'cover';
      modal.dataset.imageUrl = bg.image_url || '';
      renderPreview(bg);
    } catch (e) {
      toast(`背景设置加载失败：${e.message}`, 6000);
    }
  }

  async function saveBackground() {
    const id = projectId();
    if (!id) return;
    rememberProjectId(id);
    const modal = ensureModal();
    const btn = modal.querySelector('#btn-storyboard-bg-save');
    btn.disabled = true;
    try {
      const payload = {
        mode: 'image',
        solid_color: '#FFFFFF',
        image_fit: modal.querySelector('#storyboard-bg-fit').value
      };
      const file = modal.querySelector('#storyboard-bg-file').files?.[0];
      if (file) {
        const form = new FormData();
        form.append('file', file);
        await apiPost(`/api/projects/${encodeURIComponent(id)}/storyboard-background/image`, form);
      }
      const res = await apiPut(`/api/projects/${encodeURIComponent(id)}/storyboard-background`, payload);
      modal.querySelector('#storyboard-bg-file').value = '';
      if (modal.dataset.previewObjectUrl) {
        URL.revokeObjectURL(modal.dataset.previewObjectUrl);
        modal.dataset.previewObjectUrl = '';
      }
      modal.dataset.imageUrl = res.background?.image_url || modal.dataset.imageUrl || '';
      renderPreview(res.background || {});
      modal.style.display = 'none';
      toast(`✅ 最终视频背景已保存，已同步 ${res.background?.patched_prompt_count || 0} 个生图提示词说明。`);
    } catch (e) {
      toast(`❌ 最终视频背景保存失败：${e.message}`, 7000);
    } finally {
      btn.disabled = false;
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
})();
