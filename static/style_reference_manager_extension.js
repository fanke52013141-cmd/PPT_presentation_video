(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_project_style_reference_project_id') || '',
    loading: false,
  };

  function parseJsonResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(parseJsonResponse);
  }

  function apiPost(url, body) {
    return window.API?.post
      ? window.API.post(url, body || {})
      : fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {}),
        }).then(parseJsonResponse);
  }

  function apiDelete(url) {
    return window.API?.delete
      ? window.API.delete(url)
      : fetch(url, { method: 'DELETE' }).then(parseJsonResponse);
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  function rememberProjectId(projectId) {
    if (!projectId) return;
    STATE.projectId = String(projectId);
    sessionStorage.setItem('ppt_project_style_reference_project_id', STATE.projectId);
  }

  function inferProjectIdFromPage() {
    const urls = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const match = urls.match(/\/api\/projects\/([^/]+)\//);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__styleReferencePatched) {
        const originalEnter = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await originalEnter.apply(this, arguments);
          ensureStep3EntryButton();
          return result;
        };
        window.enterWorkspace.__styleReferencePatched = true;
      }
      if (window.exitWorkspace && !window.exitWorkspace.__styleReferencePatched) {
        const originalExit = window.exitWorkspace;
        window.exitWorkspace = function patchedExitWorkspace() {
          STATE.projectId = '';
          sessionStorage.removeItem('ppt_project_style_reference_project_id');
          return originalExit.apply(this, arguments);
        };
        window.exitWorkspace.__styleReferencePatched = true;
      }
    };
    patch();
    const timer = setInterval(() => {
      patch();
      if (window.enterWorkspace?.__styleReferencePatched) clearInterval(timer);
    }, 500);
  }

  function ensureStyle() {
    if (document.getElementById('style-reference-manager-style')) return;
    const style = document.createElement('style');
    style.id = 'style-reference-manager-style';
    style.textContent = `
      #step3-btn-style-reference-manager { font-size: .85rem; padding: .35rem .9rem; }
      .style-ref-modal { max-width: 1120px; width: min(1120px, 94vw); }
      .style-ref-toolbar { display: flex; gap: .6rem; flex-wrap: wrap; align-items: center; margin: .75rem 0 1rem; }
      .style-ref-note { color: #555; font-size: .88rem; line-height: 1.5; }
      .style-ref-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .9rem; }
      .style-ref-card { border: 2px solid #111; border-radius: 14px; background: #fffef9; box-shadow: 3px 3px 0 rgba(0,0,0,.12); overflow: hidden; }
      .style-ref-card img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; display: block; background: #fff; border-bottom: 1px solid #111; }
      .style-ref-card-body { padding: .75rem; }
      .style-ref-card-body strong { display: block; margin-bottom: .35rem; }
      .style-ref-card-body p { margin: .35rem 0; color: #555; font-size: .84rem; line-height: 1.45; max-height: 4.2em; overflow: auto; }
      .style-ref-empty { border: 2px dashed #111; border-radius: 14px; padding: 1rem; background: #fff; color: #555; line-height: 1.55; }
      @media (max-width: 980px) { .style-ref-grid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById('modal-style-reference-manager')) return;
    const modal = document.createElement('div');
    modal.id = 'modal-style-reference-manager';
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content style-ref-modal">
        <h3 class="highlight-title">Step 3 图片风格参考图</h3>
        <p class="style-ref-note">这些参考图只服务于 Step 3 图片生成，用于约束当前项目的生图风格。visual_draft.png 仍必须保持纯白底；最终视频背景单独合成。</p>
        <div class="style-ref-toolbar">
          <button id="btn-style-ref-refresh" class="secondary" type="button">刷新</button>
          <button id="btn-style-ref-regenerate" class="primary" type="button">生成 / 重生成 1-3 张</button>
          <button id="btn-style-ref-delete-all" class="danger" type="button">清空全部</button>
          <button id="btn-style-ref-close" class="secondary" type="button">关闭</button>
        </div>
        <div id="style-ref-list" class="style-ref-grid"></div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeManager();
    });
    document.getElementById('btn-style-ref-close')?.addEventListener('click', closeManager);
    document.getElementById('btn-style-ref-refresh')?.addEventListener('click', () => loadReferences().catch(error => toast(`刷新失败：${error.message}`, 6000)));
    document.getElementById('btn-style-ref-regenerate')?.addEventListener('click', regenerateReferences);
    document.getElementById('btn-style-ref-delete-all')?.addEventListener('click', deleteAllReferences);
  }

  function ensureStep3EntryButton() {
    ensureStyle();
    ensureModal();
    const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!toolbar || document.getElementById('step3-btn-style-reference-manager')) return;
    const button = document.createElement('button');
    button.id = 'step3-btn-style-reference-manager';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '风格参考图';
    button.addEventListener('click', () => openManager().catch(error => toast(`打开失败：${error.message}`, 6000)));
    const styleButton = document.getElementById('step3-btn-style');
    if (styleButton?.parentElement === toolbar) {
      toolbar.insertBefore(button, styleButton.nextSibling);
    } else {
      const confirmButton = document.getElementById('step3-btn-confirm');
      if (confirmButton?.parentElement === toolbar) toolbar.insertBefore(button, confirmButton);
      else toolbar.appendChild(button);
    }
  }

  function activeProjectId() {
    const inferred = inferProjectIdFromPage();
    if (inferred) rememberProjectId(inferred);
    return STATE.projectId || sessionStorage.getItem('ppt_project_style_reference_project_id') || inferred || '';
  }

  function renderReferences(references) {
    const list = document.getElementById('style-ref-list');
    if (!list) return;
    const images = references?.images || [];
    if (!images.length) {
      list.className = 'style-ref-empty';
      list.innerHTML = `
        当前项目还没有 Step 3 风格参考图。<br>
        可以点击“生成 / 重生成 1-3 张”。系统会读取当前图片风格配置生成参考图。
      `;
      return;
    }
    list.className = 'style-ref-grid';
    list.innerHTML = images.map(item => `
      <article class="style-ref-card">
        <img src="${esc(item.url)}" alt="style reference ${esc(item.index)}">
        <div class="style-ref-card-body">
          <strong>参考图 ${esc(item.index)}</strong>
          <p>${esc(item.prompt || item.filename || '')}</p>
          <button class="danger style-ref-delete-one" type="button" data-index="${esc(item.index)}">删除此图</button>
        </div>
      </article>
    `).join('');
    list.querySelectorAll('.style-ref-delete-one').forEach(button => {
      button.addEventListener('click', () => deleteReference(Number(button.dataset.index)).catch(error => toast(`删除失败：${error.message}`, 6000)));
    });
  }

  async function loadReferences() {
    const projectId = activeProjectId();
    if (!projectId) {
      toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
      return;
    }
    const result = await apiGet(`/api/projects/${projectId}/project-profile/image-style/reference-images`);
    renderReferences(result.references || {});
  }

  async function openManager() {
    ensureModal();
    const modal = document.getElementById('modal-style-reference-manager');
    if (modal) modal.style.display = 'flex';
    await loadReferences();
  }

  function closeManager() {
    const modal = document.getElementById('modal-style-reference-manager');
    if (modal) modal.style.display = 'none';
  }

  async function regenerateReferences() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const confirmed = window.confirm('将根据当前 Step 3 图片风格重新生成 1-3 张参考图，并覆盖同名参考图。继续？');
    if (!confirmed) return;
    const button = document.getElementById('btn-style-ref-regenerate');
    const original = button?.textContent || '生成 / 重生成 1-3 张';
    if (button) {
      button.disabled = true;
      button.textContent = '生成中...';
    }
    try {
      const result = await apiPost(`/api/projects/${projectId}/project-profile/image-style/reference-images/generate`, { count: 3 });
      renderReferences(result.references || {});
      toast(`已生成 ${(result.references?.images || []).length} 张风格参考图。`, 4500);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  async function deleteReference(index) {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const confirmed = window.confirm(`确定删除参考图 ${index}？`);
    if (!confirmed) return;
    const result = await apiDelete(`/api/projects/${projectId}/project-profile/image-style/reference-images/${index}`);
    renderReferences(result.references || {});
    toast('参考图已删除。', 3500);
  }

  async function deleteAllReferences() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const confirmed = window.confirm('确定清空当前项目的全部风格参考图？');
    if (!confirmed) return;
    const result = await apiDelete(`/api/projects/${projectId}/project-profile/image-style/reference-images`);
    renderReferences(result.references || {});
    toast('全部风格参考图已清空。', 3500);
  }

  function boot() {
    ensureStyle();
    ensureModal();
    patchWorkspaceNavigation();
    const timer = setInterval(() => {
      ensureStep3EntryButton();
    }, 700);
    setTimeout(() => clearInterval(timer), 15000);
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
