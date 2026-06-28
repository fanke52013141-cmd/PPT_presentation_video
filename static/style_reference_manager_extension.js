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

  function apiPut(url, body) {
    return window.API?.put
      ? window.API.put(url, body || {})
      : fetch(url, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {}),
        }).then(parseJsonResponse);
  }

  function apiPostForm(url, form) {
    return fetch(url, { method: 'POST', body: form }).then(parseJsonResponse);
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

  function step3ImageStyleUrl(projectId, suffix) {
    return `/api/projects/${encodeURIComponent(projectId)}/steps/3/image-style${suffix}`;
  }

  function rememberProjectId(projectId) {
    if (!projectId) return;
    STATE.projectId = String(projectId);
    sessionStorage.setItem('ppt_project_style_reference_project_id', STATE.projectId);
    sessionStorage.setItem('ppt_image_style_reverse_project_id', STATE.projectId);
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
          sessionStorage.removeItem('ppt_image_style_reverse_project_id');
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
      #step3-btn-image-style-panel { font-size: .85rem; padding: .35rem .9rem; }
      #step3-btn-style-reference-manager, #step3-btn-image-style-reverse { display: none !important; }
      .style-ref-modal { max-width: 1120px; width: min(1120px, 94vw); }
      .style-ref-toolbar { display: flex; gap: .6rem; flex-wrap: wrap; align-items: center; margin: .75rem 0 1rem; }
      .style-ref-note { color: #555; font-size: .88rem; line-height: 1.5; }
      .style-panel-layout { display: grid; gap: 1rem; max-height: min(76vh, 820px); overflow: auto; padding-right: .25rem; }
      .style-panel-inline { border: 1px solid var(--color-border-default,#dbe2f0); border-radius: 16px; background: #fff; padding: 1rem; margin: 0; box-shadow: none; }
      .style-panel-inline h4 { margin: 0 0 .45rem; }
      .style-panel-inline label { display: block; font-weight: 800; margin-top: .75rem; }
      .style-panel-inline textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--color-border-default,#dbe2f0); border-radius: 12px; padding: .7rem; font-family: ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; line-height: 1.5; }
      .style-panel-upload-row { display:flex; align-items:center; gap:.7rem; flex-wrap:wrap; margin:.55rem 0; }
      .style-panel-upload-row input { max-width: 420px; }
      .style-template-row { display:grid; grid-template-columns:minmax(180px,1fr) auto; gap:.7rem; align-items:center; }
      .style-panel-reverse-preview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; margin: .7rem 0; }
      .style-panel-reverse-preview img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; border: 1px solid var(--color-border-default,#dbe2f0); border-radius: 12px; background: #fff; }
      .style-panel-reverse-result { white-space: pre-wrap; max-height: 180px; overflow: auto; border: 1px dashed var(--color-border-default,#dbe2f0); border-radius: 12px; padding: .7rem; background: #fafbff; font-size: .84rem; line-height: 1.45; margin-top: .65rem; }
      .style-ref-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .9rem; }
      .style-ref-card { border: 1px solid var(--color-border-default,#dbe2f0); border-radius: 16px; background: #fff; box-shadow: none; overflow: hidden; }
      .style-ref-card img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; display: block; background: #fff; border-bottom: 1px solid var(--color-border-default,#dbe2f0); }
      .style-ref-card-body { padding: .75rem; }
      .style-ref-card-body strong { display: block; margin-bottom: .35rem; }
      .style-ref-card-body p { margin: .35rem 0; color: #555; font-size: .84rem; line-height: 1.45; max-height: 4.2em; overflow: auto; }
      .style-ref-empty { border: 1px dashed var(--color-border-default,#dbe2f0); border-radius: 16px; padding: 1rem; background: #fff; color: #555; line-height: 1.55; }
      @media (max-width: 980px) { .style-ref-grid, .style-panel-reverse-preview { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById('modal-style-reference-manager')) return;
    const modal = document.createElement('div');
    modal.id = 'modal-style-reference-manager';
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content style-ref-modal">
        <h3 class="highlight-title">图片风格与参考图</h3>
        <div class="style-panel-layout">
        <section class="style-panel-inline">
          <h4>图片风格模板</h4>
          <div class="style-template-row">
            <select id="style-panel-template-select"><option value="">选择已保存模板</option></select>
            <button id="btn-style-panel-template-apply" class="secondary" type="button">应用模板</button>
          </div>
          <div class="style-panel-upload-row">
            <input id="style-panel-template-name" type="text" maxlength="120" placeholder="输入新的模板名称">
            <button id="btn-style-panel-template-save" class="success" type="button">保存为新模板</button>
            <button id="btn-style-panel-template-delete" class="danger" type="button">删除所选模板</button>
          </div>
        </section>
        <section class="style-panel-inline">
          <h4>图片生成 System Content</h4>
          <textarea id="style-panel-system-content" rows="12" spellcheck="false" placeholder="在这里写入图片生成的 System Content。保存后 Step 3 生图提示词会读取它。"></textarea>
          <div class="style-ref-toolbar">
            <button id="btn-style-panel-save-system" class="success" type="button">保存 System Content</button>
            <button id="btn-style-ref-regenerate" class="primary" type="button">按 System Content 生成参考图</button>
          </div>
        </section>
        <section class="style-panel-inline">
          <h4>模板参考图</h4>
          <div class="style-panel-upload-row">
            <input id="style-panel-upload-files" type="file" accept="image/*" multiple>
            <button id="btn-style-panel-upload-run" class="secondary" type="button">上传为参考图</button>
            <button id="btn-style-ref-refresh" class="secondary" type="button">刷新</button>
            <button id="btn-style-ref-delete-all" class="danger" type="button">清空全部</button>
          </div>
          <div id="style-ref-list" class="style-ref-grid"></div>
        </section>
        <section id="style-panel-reverse-section" class="style-panel-inline">
          <h4>由参考图反推 System Content</h4>
          <label>上传 1-3 张示例图</label>
          <input id="style-panel-reverse-files" type="file" accept="image/*" multiple>
          <div id="style-panel-reverse-preview" class="style-panel-reverse-preview"></div>
          <label>补充要求</label>
          <textarea id="style-panel-reverse-requirement" rows="3" placeholder="例如：保留圆角贴纸和柔和配色，但不要复制复杂背景；元素之间要留白。"></textarea>
          <label><input id="style-panel-reverse-generate-refs" type="checkbox" checked> 反推后生成 / 刷新模板参考图</label>
          <div class="style-ref-toolbar">
            <button id="btn-style-panel-reverse-run" class="success" type="button">反推 System Content</button>
          </div>
          <div id="style-panel-reverse-result" class="style-panel-reverse-result">尚未反推。</div>
        </section>
        </div>
        <div class="style-ref-toolbar">
          <button id="btn-style-ref-close" class="secondary" type="button">关闭</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeManager();
    });
    document.getElementById('btn-style-ref-close')?.addEventListener('click', closeManager);
    document.getElementById('btn-style-panel-template-apply')?.addEventListener('click', applySelectedTemplate);
    document.getElementById('btn-style-panel-template-save')?.addEventListener('click', saveNamedTemplate);
    document.getElementById('btn-style-panel-template-delete')?.addEventListener('click', deleteSelectedTemplate);
    document.getElementById('btn-style-ref-refresh')?.addEventListener('click', () => loadReferences().catch(error => toast(`刷新失败：${error.message}`, 6000)));
    document.getElementById('btn-style-panel-save-system')?.addEventListener('click', saveSystemContent);
    document.getElementById('btn-style-panel-upload-run')?.addEventListener('click', uploadManualReferences);
    document.getElementById('btn-style-panel-reverse-run')?.addEventListener('click', runInlineReverse);
    document.getElementById('style-panel-reverse-files')?.addEventListener('change', renderInlineReversePreview);
    document.getElementById('btn-style-ref-regenerate')?.addEventListener('click', regenerateReferences);
    document.getElementById('btn-style-ref-delete-all')?.addEventListener('click', deleteAllReferences);
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
      button.addEventListener('click', () => openManager().catch(error => toast(`打开失败：${error.message}`, 6000)));
    }
    if (button.parentElement !== toolbar) {
      const confirmButton = document.getElementById('step3-btn-confirm');
      if (confirmButton?.parentElement === toolbar) toolbar.insertBefore(button, confirmButton);
      else toolbar.appendChild(button);
    }
  }

  function activeProjectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) rememberProjectId(fromWindow);
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

  function currentSystemContent() {
    return String(document.getElementById('style-panel-system-content')?.value || '').trim();
  }

  function setSystemContent(value) {
    const input = document.getElementById('style-panel-system-content');
    if (input) input.value = String(value || '');
  }

  async function loadSystemContent() {
    const projectId = activeProjectId();
    if (!projectId) return;
    const result = await apiGet(step3ImageStyleUrl(projectId, ''));
    const style = result.style || {};
    setSystemContent(style.system_content || '');
  }

  async function saveSystemContent() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const systemContent = currentSystemContent();
    if (!systemContent) return toast('请先填写图片生成 System Content。', 4000);
    const button = document.getElementById('btn-style-panel-save-system');
    const original = button?.textContent || '保存 System Content';
    if (button) {
      button.disabled = true;
      button.textContent = '保存中...';
    }
    try {
      const result = await apiPut(step3ImageStyleUrl(projectId, ''), {
        style: {
          source: 'manual_system_content',
          style_name: '手动 System Content',
          style_summary: '由用户在 Step 3 图片风格面板手动维护。',
          system_content: systemContent,
          sample_reference_image_prompts: [systemContent],
          reference_image_count_target: 3,
        },
      });
      rememberProjectId(projectId);
      if (typeof window.refreshStep3Prompts === 'function') {
        await window.refreshStep3Prompts({ updateOpenEditor: true });
      }
      toast('System Content 已保存，Step 3 生图提示词已刷新。', 3500);
      return result;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  async function uploadManualReferences() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const input = document.getElementById('style-panel-upload-files');
    const files = Array.from(input?.files || []);
    if (!files.length) return toast('请先选择 1-3 张参考图。', 4000);
    if (files.length > 3) return toast('最多只能上传 3 张参考图。', 4000);
    const form = new FormData();
    files.slice(0, 3).forEach(file => form.append('files', file));
    const button = document.getElementById('btn-style-panel-upload-run');
    const original = button?.textContent || '上传为参考图';
    if (button) {
      button.disabled = true;
      button.textContent = '上传中...';
    }
    try {
      const result = await apiPostForm(step3ImageStyleUrl(projectId, '/reference-images'), form);
      renderReferences(result.references || {});
      if (input) input.value = '';
      toast('参考图已上传。', 3500);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  function renderInlineReversePreview() {
    const input = document.getElementById('style-panel-reverse-files');
    const preview = document.getElementById('style-panel-reverse-preview');
    if (!input || !preview) return;
    const files = Array.from(input.files || []).slice(0, 3);
    preview.innerHTML = '';
    files.forEach(file => {
      const img = document.createElement('img');
      img.src = URL.createObjectURL(file);
      img.alt = file.name;
      img.onload = () => URL.revokeObjectURL(img.src);
      preview.appendChild(img);
    });
  }

  function renderInlineReverseResult(style) {
    const el = document.getElementById('style-panel-reverse-result');
    if (!el) return;
    if (!style) {
      el.textContent = '没有返回风格结果。';
      return;
    }
    const lines = [];
    lines.push(`风格名称：${style.style_name || ''}`);
    lines.push(`风格摘要：${style.style_summary || ''}`);
    if (style.system_content) lines.push(`\n提示词规则：\n${style.system_content}`);
    if (Array.isArray(style.maskability_rules)) {
      lines.push('\nMask 友好规则：');
      style.maskability_rules.forEach(item => lines.push(`- ${item}`));
    }
    if (Array.isArray(style.negative_prompt_rules)) {
      lines.push('\n负向规则：');
      style.negative_prompt_rules.forEach(item => lines.push(`- ${item}`));
    }
    el.textContent = lines.join('\n');
  }

  function focusReverseSection() {
    const section = document.getElementById('style-panel-reverse-section');
    section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.getElementById('style-panel-reverse-files')?.focus();
  }

  async function loadReferences() {
    const projectId = activeProjectId();
    if (!projectId) {
      toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
      return;
    }
    const result = await apiGet(step3ImageStyleUrl(projectId, '/reference-images'));
    renderReferences(result.references || {});
  }

  function renderTemplates(templates) {
    const select = document.getElementById('style-panel-template-select');
    if (!select) return;
    const selected = select.value;
    select.innerHTML = '<option value="">选择已保存模板</option>' + (templates || []).map(item =>
      `<option value="${esc(item.id)}">${esc(item.name)}</option>`
    ).join('');
    if ((templates || []).some(item => String(item.id) === selected)) select.value = selected;
  }

  async function loadTemplates() {
    const result = await apiGet('/api/image-style/project-templates');
    renderTemplates(result.templates || []);
  }

  async function saveNamedTemplate() {
    const projectId = activeProjectId();
    const name = String(document.getElementById('style-panel-template-name')?.value || '').trim();
    if (!projectId) return toast('当前没有可识别的项目。', 4000);
    if (!name) return toast('请输入新的模板名称。', 4000);
    await saveSystemContent();
    const result = await apiPost(step3ImageStyleUrl(projectId, '/templates'), { name });
    renderTemplates(result.templates || []);
    const select = document.getElementById('style-panel-template-select');
    if (select && result.template?.id) select.value = result.template.id;
    document.getElementById('style-panel-template-name').value = '';
    toast('图片风格模板已保存。', 3500);
  }

  async function applySelectedTemplate() {
    const projectId = activeProjectId();
    const templateId = document.getElementById('style-panel-template-select')?.value || '';
    if (!projectId || !templateId) return toast('请先选择一个模板。', 4000);
    const result = await apiPost(step3ImageStyleUrl(projectId, `/templates/${encodeURIComponent(templateId)}/apply`), {});
    setSystemContent(result.style?.system_content || '');
    renderReferences(result.references || {});
    if (typeof window.refreshStep3Prompts === 'function') {
      await window.refreshStep3Prompts({ updateOpenEditor: true });
    }
    toast('图片风格模板已应用。', 3500);
  }

  async function deleteSelectedTemplate() {
    const templateId = document.getElementById('style-panel-template-select')?.value || '';
    if (!templateId) return toast('请先选择一个模板。', 4000);
    if (!window.confirm('确定删除所选图片风格模板？')) return;
    const result = await apiDelete(`/api/image-style/project-templates/${encodeURIComponent(templateId)}`);
    renderTemplates(result.templates || []);
    toast('图片风格模板已删除。', 3500);
  }

  async function openManager() {
    ensureModal();
    const modal = document.getElementById('modal-style-reference-manager');
    if (modal) modal.style.display = 'flex';
    await Promise.all([
      loadSystemContent().catch(error => toast(`System Content 加载失败：${error.message}`, 6000)),
      loadReferences(),
      loadTemplates(),
    ]);
  }

  function closeManager() {
    const modal = document.getElementById('modal-style-reference-manager');
    if (modal) modal.style.display = 'none';
  }

  async function runInlineReverse() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const input = document.getElementById('style-panel-reverse-files');
    const files = Array.from(input?.files || []);
    if (!files.length) return toast('请先上传 1-3 张示例图。', 5000);
    if (files.length > 3) return toast('最多只能上传 3 张示例图。', 5000);

    const form = new FormData();
    files.slice(0, 3).forEach(file => form.append('files', file));
    form.append('requirement', document.getElementById('style-panel-reverse-requirement')?.value || '');
    form.append('apply', 'true');

    const button = document.getElementById('btn-style-panel-reverse-run');
    const original = button?.textContent || '反推 System Content';
    if (button) {
      button.disabled = true;
      button.textContent = '反推中...';
    }
    try {
      const result = await apiPostForm(step3ImageStyleUrl(projectId, '/reverse'), form);
      renderInlineReverseResult(result.style);
      if (result.style?.system_content) setSystemContent(result.style.system_content);
      rememberProjectId(projectId);
      toast('已反推并应用到当前项目 Step 3 System Content。', 4500);

      if (document.getElementById('style-panel-reverse-generate-refs')?.checked) {
        if (button) button.textContent = '生成参考图...';
        const refs = await apiPost(step3ImageStyleUrl(projectId, '/reference-images/generate'), { count: 3 });
        renderReferences(refs.references || {});
        toast(`已生成 ${(refs.references?.images || []).length} 张 Step 3 风格参考图。`, 4500);
      } else {
        await loadReferences();
      }

      if (typeof window.refreshStep3Prompts === 'function') {
        await window.refreshStep3Prompts({ updateOpenEditor: true });
      }
    } catch (error) {
      toast(`反推失败：${error.message}`, 8000);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
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
      const result = await apiPost(step3ImageStyleUrl(projectId, '/reference-images/generate'), { count: 3 });
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
    const result = await apiDelete(step3ImageStyleUrl(projectId, `/reference-images/${index}`));
    renderReferences(result.references || {});
    toast('参考图已删除。', 3500);
  }

  async function deleteAllReferences() {
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const confirmed = window.confirm('确定清空当前项目的全部风格参考图？');
    if (!confirmed) return;
    const result = await apiDelete(step3ImageStyleUrl(projectId, '/reference-images'));
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
