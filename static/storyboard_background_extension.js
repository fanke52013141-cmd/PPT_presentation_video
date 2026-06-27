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
      .storyboard-bg-layout{display:grid;grid-template-columns:1fr 360px;gap:1rem;align-items:start}
      .storyboard-bg-panel{border:2px solid var(--ink-color,#111);border-radius:14px;padding:1rem;background:#fffef9;box-shadow:3px 3px 0 rgba(0,0,0,.12)}
      .storyboard-bg-panel label{display:block;margin:.7rem 0;font-weight:700}
      .storyboard-bg-panel input[type=color]{width:72px;height:38px;padding:0;border:2px solid #111;border-radius:8px;background:#fff}
      .storyboard-bg-note{font-size:.88rem;line-height:1.55;color:#444}
      .storyboard-bg-preview{width:100%;aspect-ratio:16/9;border:2px dashed #111;border-radius:14px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#fff;text-align:center;padding:.5rem;box-sizing:border-box}
      .storyboard-bg-preview img{width:100%;height:100%;object-fit:cover}
      .storyboard-bg-warning{background:#fff8dc;border-left:4px solid #d6a100;padding:.7rem;margin:.8rem 0;font-size:.88rem;line-height:1.5}
      .storyboard-bg-flow{border:1.5px dashed #111;border-radius:12px;padding:.75rem;margin:.75rem 0;background:#fff;font-size:.86rem;line-height:1.55;color:#444}
      #step2-btn-background-settings{font-size:.85rem;padding:.35rem .9rem}
      @media(max-width:900px){.storyboard-bg-layout{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  function ensureButton() {
    const host = document.querySelector('#step-panel-2 .step2-sticky-header div[style*="align-items"] div');
    if (!host || document.getElementById('step2-btn-background-settings')) return;
    const btn = document.createElement('button');
    btn.id = 'step2-btn-background-settings';
    btn.type = 'button';
    btn.className = 'secondary';
    btn.textContent = '最终视频背景';
    const next = document.getElementById('step2-btn-save');
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
          <h3 class="highlight-title">Step 2：最终视频背景</h3>
          <p class="config-editor-note">这里设置的是最终 Reveal / 视频合成阶段的背景，不是 Step 3 生成图片的背景。Step 3 的 visual_draft.png 仍然强制纯白底，用于 AI Mask 和手动 Mask 的白底连通抠除。</p>
          <div class="storyboard-bg-warning"><strong>禁止混淆：</strong>不要把复杂背景写进生图提示词，也不要让 Step 3 图片生成背景图。复杂背景会破坏白底抠图和 Mask 标注。系统会在最终合成阶段单独铺背景。</div>
          <div class="storyboard-bg-flow">流程位置：Step 2 设定最终视频基调与背景；Step 3 只生成白底视觉元素；Step 5 进行 Mask 标注；Step 8 合成视频时应用这里的背景。</div>
          <div class="storyboard-bg-layout">
            <section class="storyboard-bg-panel">
              <label>背景类型</label>
              <select id="storyboard-bg-mode">
                <option value="solid">纯色背景</option>
                <option value="image">图片背景</option>
              </select>
              <label>纯色颜色</label>
              <div style="display:flex;align-items:center;gap:.8rem">
                <input id="storyboard-bg-color" type="color" value="#FFFFFF">
                <input id="storyboard-bg-color-text" type="text" value="#FFFFFF" maxlength="7" style="max-width:120px">
              </div>
              <label>图片填充方式</label>
              <select id="storyboard-bg-fit">
                <option value="cover">铺满画面，可能裁剪边缘</option>
                <option value="contain">完整显示，可能留白</option>
              </select>
              <label>上传最终视频背景图片</label>
              <input id="storyboard-bg-file" type="file" accept="image/*">
              <p class="storyboard-bg-note">建议上传 16:9 或接近 1920×1080 的图片。系统会保存为 planning/storyboard_background.png。它不会写入 visual_draft.png。</p>
            </section>
            <section class="storyboard-bg-panel">
              <h4>当前背景预览</h4>
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
    modal.querySelector('#btn-storyboard-bg-save').addEventListener('click', saveBackground);
    modal.querySelector('#storyboard-bg-color').addEventListener('input', e => { modal.querySelector('#storyboard-bg-color-text').value = e.target.value.toUpperCase(); renderPreview(); });
    modal.querySelector('#storyboard-bg-color-text').addEventListener('input', e => { const v = String(e.target.value || '').trim(); if (/^#[0-9a-fA-F]{6}$/.test(v)) modal.querySelector('#storyboard-bg-color').value = v; renderPreview(); });
    modal.querySelector('#storyboard-bg-mode').addEventListener('change', renderPreview);
    modal.querySelector('#storyboard-bg-fit').addEventListener('change', renderPreview);
    return modal;
  }

  function renderPreview(bg) {
    const modal = ensureModal();
    const mode = modal.querySelector('#storyboard-bg-mode').value;
    const color = modal.querySelector('#storyboard-bg-color-text').value || '#FFFFFF';
    const fit = modal.querySelector('#storyboard-bg-fit').value || 'cover';
    const preview = modal.querySelector('#storyboard-bg-preview');
    const status = modal.querySelector('#storyboard-bg-status');
    const imageUrl = bg?.image_url || modal.dataset.imageUrl || '';
    modal.dataset.imageUrl = imageUrl;
    preview.style.background = color;
    if (mode === 'image' && imageUrl) {
      preview.innerHTML = `<img src="${imageUrl}" alt="背景图片预览" style="object-fit:${fit}">`;
      status.textContent = '图片背景只在最终视频合成阶段使用；visual_draft.png 仍保持纯白。';
    } else {
      preview.innerHTML = '';
      preview.textContent = mode === 'image' ? '尚未上传图片，保存时会回退到纯色背景' : '纯色背景预览';
      status.textContent = '纯色背景会写入 reveal_manifest.canvas.background。';
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
      modal.querySelector('#storyboard-bg-mode').value = bg.mode || 'solid';
      modal.querySelector('#storyboard-bg-color').value = bg.solid_color || '#FFFFFF';
      modal.querySelector('#storyboard-bg-color-text').value = bg.solid_color || '#FFFFFF';
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
        mode: modal.querySelector('#storyboard-bg-mode').value,
        solid_color: modal.querySelector('#storyboard-bg-color-text').value,
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
    if (document.getElementById('step2-btn-background-settings')) clearInterval(timer);
  }, 500);
  document.addEventListener('DOMContentLoaded', boot);
})();
