(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_project_style_reference_project_id') || '',
    activeTab: 'template',
    style: {},
    references: { images: [] },
    templates: [],
    templateDetails: new Map(),
    selectedTemplateId: 'current',
  };

  function parseResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(parseResponse);
  }

  function apiPost(url, body) {
    return window.API?.post ? window.API.post(url, body || {}) : fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(parseResponse);
  }

  function apiPut(url, body) {
    return window.API?.put ? window.API.put(url, body || {}) : fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(parseResponse);
  }

  function apiPostForm(url, form) {
    return fetch(url, { method: 'POST', body: form }).then(parseResponse);
  }

  function apiDelete(url) {
    return window.API?.delete ? window.API.delete(url) : fetch(url, { method: 'DELETE' }).then(parseResponse);
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }

  function step3ImageStyleUrl(projectId, suffix) {
    return `/api/projects/${encodeURIComponent(projectId)}/steps/3/image-style${suffix || ''}`;
  }

  function rememberProjectId(projectId) {
    if (!projectId) return;
    STATE.projectId = String(projectId);
    sessionStorage.setItem('ppt_project_style_reference_project_id', STATE.projectId);
    sessionStorage.setItem('ppt_image_style_reverse_project_id', STATE.projectId);
  }

  function activeProjectId() {
    const current = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (current) rememberProjectId(current);
    return STATE.projectId || '';
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__styleReferencePatched) {
        const original = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await original.apply(this, arguments);
          ensureStep3EntryButton();
          return result;
        };
        window.enterWorkspace.__styleReferencePatched = true;
      }
      if (window.exitWorkspace && !window.exitWorkspace.__styleReferencePatched) {
        const original = window.exitWorkspace;
        window.exitWorkspace = function patchedExitWorkspace() {
          STATE.projectId = '';
          sessionStorage.removeItem('ppt_project_style_reference_project_id');
          sessionStorage.removeItem('ppt_image_style_reverse_project_id');
          return original.apply(this, arguments);
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
      #step3-btn-image-style-panel{font-size:.85rem;padding:.35rem .9rem}
      #step3-btn-style-reference-manager,#step3-btn-image-style-reverse{display:none!important}
      .style-ref-modal [hidden]{display:none!important}
      .style-ref-modal{width:min(1380px,96vw);max-width:1380px;padding:0!important;overflow:hidden;border-radius:20px;background:#fff}
      .style-ref-header{height:72px;padding:0 30px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e6eaf2}
      .style-ref-header h3{margin:0;color:#172033;font-size:1.35rem}
      .style-ref-x{border:0!important;background:transparent!important;color:#172033!important;font-size:2rem!important;line-height:1!important;padding:.25rem!important;box-shadow:none!important}
      .style-ref-tabs{display:flex;width:560px;margin:18px 30px 14px;border:1px solid #dfe4ee;border-radius:10px;overflow:hidden;background:#f8f9fc}
      .style-ref-tab{flex:1;border:0!important;border-radius:0!important;background:transparent!important;color:#344054!important;padding:.72rem .9rem!important;box-shadow:none!important;font-weight:700}
      .style-ref-tab+.style-ref-tab{border-left:1px solid #e4e8f0!important}
      .style-ref-tab.active{color:#5940ed!important;background:#fff!important;box-shadow:inset 0 -2px 0 #684cff!important}
      .style-ref-workbench{height:min(710px,68vh);overflow:auto;padding:0 24px 20px}
      .style-ref-view{display:grid;grid-template-columns:minmax(360px,.9fr) minmax(520px,1.1fr);gap:22px;min-height:100%}
      .style-ref-view[hidden]{display:none!important}
      .style-workbench-panel{border:1px solid #e0e5ef;border-radius:14px;background:#fff;padding:20px;min-width:0}
      .style-workbench-panel h4{margin:0 0 14px;color:#172033;font-size:1.05rem}
      .style-panel-label{display:block;font-weight:800;color:#263044;font-size:.9rem;margin:0 0 8px}
      .style-system-textarea,.style-reverse-result{width:100%;box-sizing:border-box;resize:vertical;border:1px solid #d8deea;border-radius:11px;padding:14px;line-height:1.65;color:#263044;background:#fff;font-family:inherit;min-height:210px}
      .style-system-textarea:focus,.style-reverse-result:focus{outline:0;border-color:#7761ff;box-shadow:0 0 0 3px rgba(105,76,255,.1)}
      .style-template-catalog{display:grid;gap:10px;align-content:start;max-height:570px;overflow:auto;padding-right:4px}
      .style-template-card{position:relative;display:grid;grid-template-columns:164px minmax(0,1fr) 28px;gap:14px;align-items:center;min-height:88px;border:1.5px solid #dfe4ed;border-radius:12px;padding:9px;background:#fff;cursor:pointer;text-align:left;transition:.16s}
      .style-template-card:hover{border-color:#a89cff;transform:translateY(-1px)}
      .style-template-card.active{border-color:#684cff;box-shadow:0 0 0 2px rgba(104,76,255,.08)}
      .style-template-thumb{width:164px;aspect-ratio:16 / 9;border-radius:8px;object-fit:cover;background:linear-gradient(135deg,#f1edff,#dcd4ff);display:block;overflow:hidden}
      .style-template-thumb img{width:100%;height:100%;object-fit:cover;display:block}
      .style-template-thumb-placeholder{width:100%;height:100%;display:grid;place-items:center;color:#6b55ed;font-weight:800;font-size:.75rem}
      .style-template-name{font-weight:800;color:#283247;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .style-template-meta{display:block;color:#7b8496;font-size:.78rem;margin-top:6px}
      .style-template-check{width:24px;height:24px;border:1.5px solid #c6ccda;border-radius:50%;display:grid;place-items:center;color:transparent;font-size:.75rem}
      .style-template-card.active .style-template-check{background:#684cff;border-color:#684cff;color:#fff}
      .style-template-delete{position:absolute;right:8px;bottom:6px;border:0!important;background:transparent!important;color:#9a4b55!important;padding:2px!important;font-size:.72rem!important;box-shadow:none!important;opacity:.72}
      #style-panel-template-select{display:none}
      .style-ref-output-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 10px}
      .style-ref-output-head h4{margin:0}
      .style-ref-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
      .style-ref-actions button{border-radius:9px!important}
      .style-ref-primary{background:linear-gradient(135deg,#735aff,#5231e8)!important;color:#fff!important;border:0!important}
      .style-ref-preview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
      .style-ref-card{position:relative;min-width:0;border-radius:11px;overflow:hidden;background:#f5f6fa;border:1px solid #e0e5ef;aspect-ratio:16 / 9}
      .style-ref-card img{width:100%;height:100%;aspect-ratio:16 / 9;object-fit:cover;display:block;background:#fff}
      .style-ref-card-overlay{position:absolute;right:8px;top:8px;display:flex;gap:6px}
      .style-ref-card-overlay button{width:30px;height:30px;min-width:0;padding:0!important;display:grid;place-items:center;border:0!important;border-radius:8px!important;background:rgba(255,255,255,.94)!important;color:#344054!important;box-shadow:0 3px 10px rgba(20,27,44,.14)!important}
      .style-ref-empty-slot{width:100%;height:100%;display:grid;place-items:center;color:#8a93a4;background:linear-gradient(145deg,#fafbfe,#f1f3f8);font-size:.82rem;text-align:center;padding:10px;box-sizing:border-box}
      .style-ref-product-note{margin:10px 0 0;color:#768094;font-size:.8rem;line-height:1.5}
      .style-ref-field{margin-bottom:18px}
      .style-ref-input{width:100%;height:44px;box-sizing:border-box;border:1px solid #d8deea;border-radius:10px;padding:0 12px}
      .style-ref-two-actions{display:flex;justify-content:flex-end;gap:12px;margin-top:14px}
      .style-ref-upload-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid #cfc7ff;border-radius:9px;padding:.56rem .85rem;color:#5d43ea;background:#faf9ff;font-weight:700;cursor:pointer;font-size:.84rem}
      #style-panel-upload-files,#style-panel-reverse-files{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
      .style-reverse-upload-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:18px}
      .style-reverse-input-card{position:relative;aspect-ratio:16 / 9;border:1px solid #e0e5ef;border-radius:10px;overflow:hidden;background:#f6f7fb}
      .style-reverse-input-card img{width:100%;height:100%;object-fit:cover;display:block}
      .style-reverse-upload-empty{aspect-ratio:16 / 9;border:1.5px dashed #a99bff;border-radius:10px;display:grid;place-items:center;text-align:center;color:#6550e8;background:#fbfaff;cursor:pointer;font-weight:700;font-size:.82rem}
      .style-reverse-upload-empty span{display:block;font-size:1.4rem;margin-bottom:5px}
      .style-reverse-help{color:#7a8496;font-size:.8rem;margin:-8px 0 14px}
      .style-ref-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 24px;border-top:1px solid #e4e8f0;background:#fff}
      .style-ref-footer-left,.style-ref-footer-right{display:flex;align-items:center;gap:12px}
      .style-ref-footer button{border-radius:10px!important;min-width:112px}
      .style-ref-footer .style-ref-primary{min-width:170px}
      @media(max-width:980px){.style-ref-modal{width:96vw}.style-ref-tabs{width:auto;margin-left:18px;margin-right:18px}.style-ref-workbench{padding:0 16px 16px}.style-ref-view{grid-template-columns:1fr}.style-ref-preview-grid,.style-reverse-upload-grid{grid-template-columns:1fr}.style-template-card{grid-template-columns:140px minmax(0,1fr) 26px}.style-template-thumb{width:140px}.style-ref-footer{align-items:stretch;flex-direction:column}.style-ref-footer-left,.style-ref-footer-right{justify-content:flex-end;flex-wrap:wrap}}
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    let modal = document.getElementById('modal-style-reference-manager');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'modal-style-reference-manager';
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content style-ref-modal" role="dialog" aria-modal="true" aria-labelledby="style-ref-title">
        <header class="style-ref-header"><h3 id="style-ref-title">图片风格设置</h3><button id="btn-style-ref-x" class="style-ref-x" type="button" aria-label="关闭">×</button></header>
        <nav class="style-ref-tabs" aria-label="图片风格设置方式">
          <button class="style-ref-tab active" type="button" data-style-tab="template">使用模板</button>
          <button class="style-ref-tab" type="button" data-style-tab="manual">手写 System Content</button>
          <button class="style-ref-tab" type="button" data-style-tab="reverse">图片反推</button>
        </nav>
        <main class="style-ref-workbench">
          <section class="style-ref-view" data-style-view="template">
            <div class="style-workbench-panel"><h4>选择模板</h4><select id="style-panel-template-select"><option value="current">当前图片风格</option></select><div id="style-template-catalog" class="style-template-catalog"></div></div>
            <div class="style-workbench-panel">
              <label class="style-panel-label" for="style-template-system-content">System Content</label>
              <textarea id="style-template-system-content" class="style-system-textarea" rows="8" readonly placeholder="选择模板后显示对应的 System Content"></textarea>
              <div class="style-ref-output-head"><h4>效果预览</h4><div class="style-ref-actions"><button id="btn-style-panel-template-apply" class="secondary" type="button">应用模板</button><button id="btn-style-template-generate" class="style-ref-primary" type="button">✦ 生成3张预览图</button></div></div>
              <div id="style-template-preview" class="style-ref-preview-grid" data-style-preview-list></div>
              <p class="style-ref-product-note">这 3 张效果预览会作为后续图片生成的实际参考图。</p>
            </div>
          </section>
          <section class="style-ref-view" data-style-view="manual" hidden>
            <div class="style-workbench-panel">
              <h4>System Content</h4>
              <div class="style-ref-field"><label class="style-panel-label" for="style-panel-template-name">模板名称（可选）</label><input id="style-panel-template-name" class="style-ref-input" type="text" maxlength="120" placeholder="例如：极简自然产品风格"></div>
              <textarea id="style-panel-system-content" class="style-system-textarea" rows="16" spellcheck="false" placeholder="写入图片生成的 System Content，例如风格、光线、色彩、构图、材质、氛围和适用场景。"></textarea>
              <div class="style-ref-two-actions"><button id="btn-style-panel-clear-system" class="secondary" type="button">清空内容</button><button id="btn-style-ref-regenerate" class="style-ref-primary" type="button">生成3张预览图</button></div>
              <button id="btn-style-panel-save-system" type="button" hidden>保存 System Content</button>
            </div>
            <div class="style-workbench-panel">
              <div class="style-ref-output-head"><h4>效果预览</h4><div class="style-ref-actions"><label class="style-ref-upload-button" for="style-panel-upload-files">⇧ 手动上传参考图</label><input id="style-panel-upload-files" type="file" accept="image/*" multiple><button id="btn-style-panel-upload-run" type="button" hidden>上传为参考图</button></div></div>
              <div id="style-ref-list" class="style-ref-preview-grid" data-style-preview-list></div>
              <p class="style-ref-product-note">所有图片统一保存为 1920×1080 横图；预览图会直接参与后续生图。</p>
            </div>
          </section>
          <section id="style-panel-reverse-section" class="style-ref-view" data-style-view="reverse" hidden>
            <div class="style-workbench-panel">
              <h4>上传参考图（最多3张）</h4>
              <input id="style-panel-reverse-files" type="file" accept="image/*" multiple>
              <div id="style-panel-reverse-preview" class="style-reverse-upload-grid"></div>
              <p class="style-reverse-help">上传图片会以 16:9 横图卡片展示，反推时保留画面风格而不照抄内容。</p>
              <label class="style-panel-label" for="style-panel-reverse-requirement">补充要求（可选）</label>
              <textarea id="style-panel-reverse-requirement" class="style-system-textarea" rows="5" placeholder="请输入希望保留或偏好的风格特征，例如：光线、色调、构图、材质等。"></textarea>
              <div class="style-ref-two-actions"><button id="btn-style-panel-reverse-run" class="style-ref-primary" type="button">反推 System Content</button></div>
              <label hidden><input id="style-panel-reverse-generate-refs" type="checkbox">反推后生成参考图</label>
            </div>
            <div class="style-workbench-panel">
              <div class="style-ref-output-head"><h4>System Content 结果</h4><button id="btn-style-reverse-generate" class="secondary" type="button">生成3张预览图</button></div>
              <textarea id="style-panel-reverse-result" class="style-reverse-result" rows="10" readonly placeholder="完成图片反推后显示 System Content"></textarea>
              <div class="style-ref-output-head"><h4>效果预览</h4></div>
              <div id="style-reverse-output-preview" class="style-ref-preview-grid" data-style-preview-list></div>
              <p class="style-ref-product-note">System Content 与这组效果预览共同构成新的图片风格。</p>
            </div>
          </section>
        </main>
        <footer class="style-ref-footer"><div class="style-ref-footer-left"><button id="btn-style-panel-template-save" class="secondary" type="button">保存为模板</button><button id="btn-style-panel-template-delete" type="button" hidden>删除所选模板</button><button id="btn-style-ref-refresh" type="button" hidden>刷新</button><button id="btn-style-ref-delete-all" type="button" hidden>清空全部</button></div><div class="style-ref-footer-right"><button id="btn-style-ref-close" class="secondary" type="button">取消</button><button id="btn-style-apply" class="style-ref-primary" type="button">应用到本次生成</button></div></footer>
      </div>`;
    document.body.appendChild(modal);

    modal.addEventListener('click', event => { if (event.target === modal) closeManager(); });
    modal.querySelector('#btn-style-ref-x').addEventListener('click', closeManager);
    modal.querySelector('#btn-style-ref-close').addEventListener('click', closeManager);
    modal.querySelectorAll('[data-style-tab]').forEach(button => button.addEventListener('click', () => setActiveTab(button.dataset.styleTab)));
    modal.querySelector('#btn-style-panel-template-apply').addEventListener('click', () => applySelectedTemplate().catch(showError));
    modal.querySelector('#btn-style-template-generate').addEventListener('click', event => generateTemplatePreviews(event.currentTarget).catch(showError));
    modal.querySelector('#btn-style-panel-template-save').addEventListener('click', () => saveNamedTemplate().catch(showError));
    modal.querySelector('#btn-style-panel-template-delete').addEventListener('click', () => deleteSelectedTemplate().catch(showError));
    modal.querySelector('#btn-style-panel-clear-system').addEventListener('click', () => { modal.querySelector('#style-panel-system-content').value = ''; });
    modal.querySelector('#btn-style-panel-save-system').addEventListener('click', () => saveSystemContent().catch(showError));
    modal.querySelector('#btn-style-ref-regenerate').addEventListener('click', event => generateManualPreviews(event.currentTarget).catch(showError));
    modal.querySelector('#style-panel-upload-files').addEventListener('change', () => uploadManualReferences().catch(showError));
    modal.querySelector('#btn-style-panel-upload-run').addEventListener('click', () => uploadManualReferences().catch(showError));
    modal.querySelector('#style-panel-reverse-files').addEventListener('change', renderInlineReversePreview);
    modal.querySelector('#btn-style-panel-reverse-run').addEventListener('click', event => runInlineReverse(event.currentTarget).catch(showError));
    modal.querySelector('#btn-style-reverse-generate').addEventListener('click', event => regenerateReferences(event.currentTarget).catch(showError));
    modal.querySelector('#btn-style-ref-refresh').addEventListener('click', () => loadReferences().catch(showError));
    modal.querySelector('#btn-style-ref-delete-all').addEventListener('click', () => deleteAllReferences().catch(showError));
    modal.querySelector('#btn-style-apply').addEventListener('click', event => applyCurrentMode(event.currentTarget).catch(showError));
    renderInlineReversePreview();
    return modal;
  }

  function showError(error) {
    toast(error?.message || String(error || '操作失败'), 7000);
  }

  function ensureStep3EntryButton() {
    ensureStyle();
    ensureModal();
    const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!toolbar || document.getElementById('step3-btn-image-style-panel')) return;
    const button = document.getElementById('step3-btn-style') || document.createElement('button');
    button.id = 'step3-btn-image-style-panel';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '图片风格设置';
    if (button.dataset.styleManagerBound !== '1') {
      button.dataset.styleManagerBound = '1';
      button.addEventListener('click', () => openManager().catch(showError));
    }
    if (button.parentElement !== toolbar) {
      const confirm = document.getElementById('step3-btn-confirm');
      toolbar.insertBefore(button, confirm || null);
    }
  }

  function setActiveTab(tab) {
    STATE.activeTab = ['template', 'manual', 'reverse'].includes(tab) ? tab : 'template';
    const modal = ensureModal();
    modal.querySelectorAll('[data-style-tab]').forEach(button => button.classList.toggle('active', button.dataset.styleTab === STATE.activeTab));
    modal.querySelectorAll('[data-style-view]').forEach(view => { view.hidden = view.dataset.styleView !== STATE.activeTab; });
  }

  function referenceCardsHtml(images, deletable) {
    const normalized = Array.isArray(images) ? images.slice(0, 3) : [];
    const cards = normalized.map(item => `
      <article class="style-ref-card">
        <img src="${esc(item.url)}" alt="风格参考图 ${esc(item.index)}">
        <div class="style-ref-card-overlay"><button class="style-ref-open" type="button" data-url="${esc(item.url)}" aria-label="预览大图">⌕</button>${deletable ? `<button class="style-ref-delete-one" type="button" data-index="${esc(item.index)}" aria-label="删除参考图">⌫</button>` : ''}</div>
      </article>`);
    for (let index = cards.length; index < 3; index += 1) cards.push('<article class="style-ref-card"><div class="style-ref-empty-slot">16:9 效果预览<br>等待生成</div></article>');
    return cards.join('');
  }

  function bindPreviewActions(container, deletable) {
    container.querySelectorAll('.style-ref-open').forEach(button => button.addEventListener('click', () => window.open(button.dataset.url, '_blank', 'noopener')));
    if (deletable) container.querySelectorAll('.style-ref-delete-one').forEach(button => button.addEventListener('click', () => deleteReference(Number(button.dataset.index)).catch(showError)));
  }

  function renderCurrentReferences() {
    const images = STATE.references?.images || [];
    ['style-ref-list', 'style-reverse-output-preview'].forEach(id => {
      const container = document.getElementById(id);
      if (!container) return;
      container.innerHTML = referenceCardsHtml(images, true);
      bindPreviewActions(container, true);
    });
  }

  function currentTemplateDetail() {
    if (STATE.selectedTemplateId === 'current') return { style: STATE.style, references: STATE.references };
    return STATE.templateDetails.get(STATE.selectedTemplateId) || { style: {}, references: { images: [] } };
  }

  function renderTemplateOutput() {
    const detail = currentTemplateDetail();
    const textarea = document.getElementById('style-template-system-content');
    if (textarea) textarea.value = detail.style?.system_content || '';
    const preview = document.getElementById('style-template-preview');
    if (preview) {
      preview.innerHTML = referenceCardsHtml(detail.references?.images || [], false);
      bindPreviewActions(preview, false);
    }
  }

  function renderTemplates() {
    const catalog = document.getElementById('style-template-catalog');
    const select = document.getElementById('style-panel-template-select');
    if (!catalog || !select) return;
    const entries = [{ id: 'current', name: STATE.style?.style_name || '当前图片风格', reference_count: (STATE.references?.images || []).length }, ...STATE.templates];
    select.innerHTML = entries.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
    select.value = STATE.selectedTemplateId;
    catalog.innerHTML = entries.map(item => {
      const detail = item.id === 'current' ? { references: STATE.references } : STATE.templateDetails.get(item.id);
      const image = detail?.references?.images?.[0];
      const thumb = image ? `<img src="${esc(image.url)}" alt="${esc(item.name)} 模板缩略图">` : '<span class="style-template-thumb-placeholder">16:9 风格模板</span>';
      const count = detail?.references?.images?.length ?? item.reference_count ?? 0;
      return `<article class="style-template-card ${item.id === STATE.selectedTemplateId ? 'active' : ''}" data-template-id="${esc(item.id)}"><span class="style-template-thumb">${thumb}</span><span><span class="style-template-name">${esc(item.name)}</span><span class="style-template-meta">System Content + ${count} 张参考图</span></span><span class="style-template-check">✓</span>${item.id !== 'current' && !item.built_in ? '<button class="style-template-delete" type="button">删除</button>' : ''}</article>`;
    }).join('');
    catalog.querySelectorAll('.style-template-card').forEach(card => card.addEventListener('click', event => {
      if (event.target.closest('.style-template-delete')) return;
      STATE.selectedTemplateId = card.dataset.templateId;
      renderTemplates();
      renderTemplateOutput();
    }));
    catalog.querySelectorAll('.style-template-delete').forEach(button => button.addEventListener('click', event => {
      event.stopPropagation();
      STATE.selectedTemplateId = button.closest('.style-template-card').dataset.templateId;
      deleteSelectedTemplate().catch(showError);
    }));
    renderTemplateOutput();
  }

  async function loadSystemContent() {
    const projectId = activeProjectId();
    if (!projectId) return;
    const result = await apiGet(step3ImageStyleUrl(projectId));
    STATE.style = result.style || {};
    const input = document.getElementById('style-panel-system-content');
    if (input) input.value = STATE.style.system_content || '';
    const reverse = document.getElementById('style-panel-reverse-result');
    if (reverse) reverse.value = STATE.style.system_content || '';
  }

  async function loadReferences() {
    const projectId = activeProjectId();
    if (!projectId) return;
    const result = await apiGet(step3ImageStyleUrl(projectId, '/reference-images'));
    STATE.references = result.references || { images: [] };
    renderCurrentReferences();
  }

  async function loadTemplates() {
    const result = await apiGet('/api/image-style/project-templates');
    STATE.templates = result.templates || [];
    STATE.templateDetails = new Map();
    await Promise.all(STATE.templates.map(async item => {
      try {
        const detail = await apiGet(`/api/image-style/project-templates/${encodeURIComponent(item.id)}`);
        STATE.templateDetails.set(String(item.id), detail);
      } catch (error) {
        console.warn('图片风格模板详情加载失败', item.id, error);
      }
    }));
    const currentIsEmpty = !String(STATE.style?.system_content || '').trim() && !(STATE.references?.images || []).length;
    if (currentIsEmpty && STATE.selectedTemplateId === 'current' && STATE.templates.some(item => String(item.id) === 'handdrawn')) {
      STATE.selectedTemplateId = 'handdrawn';
    }
    if (STATE.selectedTemplateId !== 'current' && !STATE.templates.some(item => String(item.id) === STATE.selectedTemplateId)) STATE.selectedTemplateId = 'current';
    renderTemplates();
  }

  async function saveSystemContent() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目，请先进入项目工作区。');
    const input = document.getElementById('style-panel-system-content');
    const systemContent = String(input?.value || '').trim();
    if (!systemContent) throw new Error('请先填写图片生成 System Content。');
    const result = await apiPut(step3ImageStyleUrl(projectId), {
      style: {
        ...STATE.style,
        source: 'manual_system_content',
        style_name: String(document.getElementById('style-panel-template-name')?.value || '').trim() || STATE.style?.style_name || '手动 System Content',
        style_summary: STATE.style?.style_summary || '由用户在 Step 3 图片风格面板手动维护。',
        system_content: systemContent,
        sample_reference_image_prompts: [systemContent],
        reference_image_count_target: 3,
      },
    });
    STATE.style = result.style || {};
    document.getElementById('style-panel-reverse-result').value = STATE.style.system_content || '';
    renderTemplates();
    return result;
  }

  async function regenerateReferences(button) {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目。');
    const original = button?.textContent || '生成3张预览图';
    if (button) { button.disabled = true; button.textContent = '生成中...'; }
    try {
      const result = await apiPost(step3ImageStyleUrl(projectId, '/reference-images/generate'), { count: 3 });
      STATE.references = result.references || { images: [] };
      renderCurrentReferences();
      renderTemplates();
      toast(`已生成 ${(STATE.references.images || []).length} 张 16:9 效果预览。`, 4000);
      return result;
    } finally {
      if (button) { button.disabled = false; button.textContent = original; }
    }
  }

  async function generateManualPreviews(button) {
    const original = button?.textContent || '生成3张预览图';
    if (button) { button.disabled = true; button.textContent = '保存 System Content...'; }
    try {
      await saveSystemContent();
      if (button) button.textContent = '生成中...';
      await regenerateReferences();
    } finally {
      if (button) { button.disabled = false; button.textContent = original; }
    }
  }

  async function generateTemplatePreviews(button) {
    if (STATE.selectedTemplateId !== 'current') await applySelectedTemplate(false);
    await regenerateReferences(button);
    STATE.selectedTemplateId = 'current';
    renderTemplates();
  }

  async function uploadManualReferences() {
    const projectId = activeProjectId();
    const input = document.getElementById('style-panel-upload-files');
    const files = Array.from(input?.files || []);
    if (!projectId) throw new Error('当前没有可识别的项目。');
    if (!files.length) return;
    if (files.length > 3) {
      input.value = '';
      throw new Error('最多只能上传 3 张参考图。');
    }
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    const result = await apiPostForm(step3ImageStyleUrl(projectId, '/reference-images'), form);
    STATE.references = result.references || { images: [] };
    input.value = '';
    renderCurrentReferences();
    renderTemplates();
    toast('参考图已上传并统一处理为 16:9 横图。', 4000);
  }

  function renderInlineReversePreview() {
    const input = document.getElementById('style-panel-reverse-files');
    const preview = document.getElementById('style-panel-reverse-preview');
    if (!input || !preview) return;
    Array.from(preview.querySelectorAll('img[data-object-url]')).forEach(img => URL.revokeObjectURL(img.dataset.objectUrl));
    const files = Array.from(input.files || []);
    if (files.length > 3) toast('最多只能上传 3 张参考图，请重新选择。', 4500);
    const selected = files.slice(0, 3);
    const cards = selected.map(file => {
      const url = URL.createObjectURL(file);
      return `<article class="style-reverse-input-card"><img src="${esc(url)}" data-object-url="${esc(url)}" alt="${esc(file.name)}"></article>`;
    });
    if (cards.length < 3) cards.push('<label class="style-reverse-upload-empty" for="style-panel-reverse-files"><span>＋</span>上传图片<br><small>继续上传（最多3张）</small></label>');
    while (cards.length < 3) cards.push('<article class="style-ref-card"><div class="style-ref-empty-slot">16:9 参考图位置</div></article>');
    preview.innerHTML = cards.join('');
  }

  async function runInlineReverse(button) {
    const projectId = activeProjectId();
    const input = document.getElementById('style-panel-reverse-files');
    const files = Array.from(input?.files || []);
    if (!projectId) throw new Error('当前没有可识别的项目。');
    if (!files.length) throw new Error('请先上传 1-3 张示例图。');
    if (files.length > 3) throw new Error('最多只能上传 3 张示例图。');
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    form.append('requirement', document.getElementById('style-panel-reverse-requirement')?.value || '');
    form.append('apply', 'true');
    const original = button?.textContent || '反推 System Content';
    if (button) { button.disabled = true; button.textContent = '反推中...'; }
    try {
      const result = await apiPostForm(step3ImageStyleUrl(projectId, '/reverse'), form);
      STATE.style = result.style || {};
      document.getElementById('style-panel-system-content').value = STATE.style.system_content || '';
      document.getElementById('style-panel-reverse-result').value = STATE.style.system_content || '';
      if (button) button.textContent = '保存效果预览...';
      const referenceForm = new FormData();
      files.forEach(file => referenceForm.append('files', file));
      const referenceResult = await apiPostForm(step3ImageStyleUrl(projectId, '/reference-images'), referenceForm);
      STATE.references = referenceResult.references || { images: [] };
      renderCurrentReferences();
      STATE.selectedTemplateId = 'current';
      renderTemplates();
      toast('System Content 已反推；上传图片已成为本次生成的实际参考图。', 4500);
      return result;
    } finally {
      if (button) { button.disabled = false; button.textContent = original; }
    }
  }

  async function applySelectedTemplate(showToast = true) {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目。');
    if (STATE.selectedTemplateId === 'current') {
      if (showToast) toast('当前图片风格已在使用中。');
      return;
    }
    const result = await apiPost(step3ImageStyleUrl(projectId, `/templates/${encodeURIComponent(STATE.selectedTemplateId)}/apply`), {});
    STATE.style = result.style || {};
    STATE.references = result.references || { images: [] };
    document.getElementById('style-panel-system-content').value = STATE.style.system_content || '';
    document.getElementById('style-panel-reverse-result').value = STATE.style.system_content || '';
    renderCurrentReferences();
    renderTemplateOutput();
    if (showToast) toast('模板的 System Content 与效果预览已应用。', 3500);
    return result;
  }

  async function saveNamedTemplate() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目。');
    if (STATE.activeTab === 'manual') await saveSystemContent();
    if (STATE.activeTab === 'template' && STATE.selectedTemplateId !== 'current') await applySelectedTemplate(false);
    if (!(STATE.references?.images || []).length) throw new Error('请先生成或上传至少 1 张效果预览，再保存模板。');
    const field = document.getElementById('style-panel-template-name');
    let name = String(field?.value || '').trim();
    if (!name) name = String(window.prompt('请输入新的模板名称', STATE.style?.style_name || '') || '').trim();
    if (!name) return;
    const result = await apiPost(step3ImageStyleUrl(projectId, '/templates'), { name });
    STATE.templates = result.templates || [];
    if (field) field.value = '';
    STATE.selectedTemplateId = result.template?.id || 'current';
    await loadTemplates();
    toast('模板已保存，包含 System Content 与当前效果预览。', 4000);
  }

  async function deleteSelectedTemplate() {
    const id = STATE.selectedTemplateId;
    if (!id || id === 'current') throw new Error('请选择一个已保存模板。');
    if (!window.confirm('确定删除所选图片风格模板？')) return;
    const result = await apiDelete(`/api/image-style/project-templates/${encodeURIComponent(id)}`);
    STATE.templates = result.templates || [];
    STATE.selectedTemplateId = 'current';
    await loadTemplates();
    toast('图片风格模板已删除。', 3500);
  }

  async function deleteReference(index) {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目。');
    const result = await apiDelete(step3ImageStyleUrl(projectId, `/reference-images/${index}`));
    STATE.references = result.references || { images: [] };
    renderCurrentReferences();
    renderTemplates();
  }

  async function deleteAllReferences() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('当前没有可识别的项目。');
    const result = await apiDelete(step3ImageStyleUrl(projectId, '/reference-images'));
    STATE.references = result.references || { images: [] };
    renderCurrentReferences();
    renderTemplates();
  }

  async function refreshPrompts() {
    if (typeof window.refreshStep3Prompts === 'function') await window.refreshStep3Prompts({ updateOpenEditor: true });
  }

  async function applyCurrentMode(button) {
    const original = button?.textContent || '应用到本次生成';
    if (button) { button.disabled = true; button.textContent = '应用中...'; }
    try {
      if (STATE.activeTab === 'template') await applySelectedTemplate(false);
      if (STATE.activeTab === 'manual') await saveSystemContent();
      if (STATE.activeTab === 'reverse' && !String(STATE.style?.system_content || '').trim()) throw new Error('请先完成图片反推。');
      await refreshPrompts();
      closeManager();
      toast('图片风格已应用：System Content 与效果预览将用于本次图片生成。', 4500);
    } finally {
      if (button) { button.disabled = false; button.textContent = original; }
    }
  }

  async function openManager() {
    const projectId = activeProjectId();
    if (!projectId) throw new Error('请先进入项目工作区。');
    ensureStyle();
    const modal = ensureModal();
    modal.style.display = 'flex';
    await Promise.all([loadSystemContent(), loadReferences()]);
    await loadTemplates();
    setActiveTab(STATE.activeTab);
  }

  function closeManager() {
    const modal = document.getElementById('modal-style-reference-manager');
    if (modal) modal.style.display = 'none';
  }

  function boot() {
    ensureStyle();
    ensureModal();
    patchWorkspaceNavigation();
    ensureStep3EntryButton();
  }

  const timer = setInterval(ensureStep3EntryButton, 700);
  setTimeout(() => clearInterval(timer), 15000);
  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
