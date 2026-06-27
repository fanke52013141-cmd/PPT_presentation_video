(function () {
  'use strict';

  const MODAL_ID = 'modal-step3-image-style-reverse';
  const STATE = {
    projectId: sessionStorage.getItem('ppt_image_style_reverse_project_id') || sessionStorage.getItem('ppt_project_style_reference_project_id') || '',
  };

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function parseJsonResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiPost(url, body) {
    if (window.API?.post) return window.API.post(url, body);
    return fetch(url, { method: 'POST', body }).then(parseJsonResponse);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  function step3ImageStyleUrl(projectId, suffix) {
    return `/api/projects/${encodeURIComponent(projectId)}/steps/3/image-style${suffix}`;
  }

  function rememberProjectId(id) {
    if (!id) return;
    STATE.projectId = String(id);
    sessionStorage.setItem('ppt_image_style_reverse_project_id', STATE.projectId);
    sessionStorage.setItem('ppt_project_style_reference_project_id', STATE.projectId);
  }

  function inferProjectIdFromPage() {
    const urls = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const match = urls.match(/\/api\/projects\/([^/]+)\//);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function projectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) {
      rememberProjectId(fromWindow);
      return fromWindow;
    }
    const inferred = inferProjectIdFromPage();
    if (inferred) {
      rememberProjectId(inferred);
      return inferred;
    }
    return STATE.projectId || sessionStorage.getItem('ppt_image_style_reverse_project_id') || sessionStorage.getItem('ppt_project_style_reference_project_id') || '';
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__imageStyleReversePatched) {
        const originalEnter = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await originalEnter.apply(this, arguments);
          ensureStep3Button();
          return result;
        };
        window.enterWorkspace.__imageStyleReversePatched = true;
      }
      if (window.exitWorkspace && !window.exitWorkspace.__imageStyleReversePatched) {
        const originalExit = window.exitWorkspace;
        window.exitWorkspace = function patchedExitWorkspace() {
          STATE.projectId = '';
          sessionStorage.removeItem('ppt_image_style_reverse_project_id');
          return originalExit.apply(this, arguments);
        };
        window.exitWorkspace.__imageStyleReversePatched = true;
      }
    };
    patch();
    const timer = setInterval(() => {
      patch();
      if (window.enterWorkspace?.__imageStyleReversePatched) clearInterval(timer);
    }, 500);
  }

  function ensureStyle() {
    if (document.getElementById('step3-image-style-reverse-style')) return;
    const style = document.createElement('style');
    style.id = 'step3-image-style-reverse-style';
    style.textContent = `
      #step3-btn-image-style-reverse { font-size: .85rem; padding: .35rem .9rem; }
      .step3-style-reverse-modal { width: min(840px, 94vw); max-width: 840px; }
      .step3-style-reverse-note { color: #555; font-size: .88rem; line-height: 1.5; }
      .step3-style-reverse-preview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; margin: .7rem 0; }
      .step3-style-reverse-preview img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; border: 1.5px solid #111; border-radius: 9px; background: #fff; }
      .step3-style-reverse-result { white-space: pre-wrap; max-height: 260px; overflow: auto; border: 1.5px dashed #111; border-radius: 9px; padding: .7rem; background: #fff; font-size: .84rem; line-height: 1.45; }
      .step3-style-reverse-actions { display: flex; justify-content: flex-end; gap: .7rem; margin-top: .9rem; }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById(MODAL_ID)) return;
    const modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content step3-style-reverse-modal">
        <h3 class="highlight-title">Step 3：上传示例图反推图片风格</h3>
        <p class="step3-style-reverse-note">这个入口只服务于图片生成阶段。上传 1-3 张示例图后，系统会抽取线条、色板、构图密度和 Mask 友好规则，并应用到当前项目的 Step 3 生图风格。生图仍保持纯白背景。</p>
        <label style="font-weight:800;display:block;margin-top:.8rem">上传 1-3 张示例图</label>
        <input id="step3-style-reverse-files" type="file" accept="image/*" multiple>
        <div id="step3-style-reverse-preview" class="step3-style-reverse-preview"></div>
        <label style="font-weight:800;display:block;margin-top:.8rem">补充要求</label>
        <textarea id="step3-style-reverse-requirement" rows="4" style="width:100%;box-sizing:border-box" placeholder="例如：保留圆角贴纸和柔和配色，但不要复制复杂背景；元素之间要留白。"></textarea>
        <label style="font-weight:800;display:block;margin-top:.8rem"><input id="step3-style-reverse-generate-refs" type="checkbox" checked> 反推后生成当前项目 Step 3 风格参考图</label>
        <h4>反推结果</h4>
        <div id="step3-style-reverse-result" class="step3-style-reverse-result">尚未反推。</div>
        <div class="step3-style-reverse-actions">
          <button id="btn-step3-style-reverse-close" class="secondary" type="button">关闭</button>
          <button id="btn-step3-style-reverse-run" class="success" type="button">反推并应用到 Step 3</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-step3-style-reverse-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-step3-style-reverse-run')?.addEventListener('click', runReverse);
    document.getElementById('step3-style-reverse-files')?.addEventListener('change', renderPreview);
  }

  function renderPreview() {
    const input = document.getElementById('step3-style-reverse-files');
    const preview = document.getElementById('step3-style-reverse-preview');
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

  function renderResult(style) {
    const el = document.getElementById('step3-style-reverse-result');
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

  function openModal() {
    ensureModal();
    document.getElementById(MODAL_ID).style.display = 'flex';
  }

  function closeModal() {
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.style.display = 'none';
  }

  async function runReverse() {
    const id = projectId();
    if (!id) return toast('当前没有可识别的项目，请先进入项目并打开 Step 3。', 6000);
    const input = document.getElementById('step3-style-reverse-files');
    const files = Array.from(input?.files || []);
    if (!files.length) return toast('请先上传 1-3 张示例图。', 5000);
    if (files.length > 3) return toast('最多只能上传 3 张示例图。', 5000);
    const form = new FormData();
    files.slice(0, 3).forEach(file => form.append('files', file));
    form.append('requirement', document.getElementById('step3-style-reverse-requirement')?.value || '');
    form.append('apply', 'true');
    const button = document.getElementById('btn-step3-style-reverse-run');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '反推中...';
    try {
      const result = await apiPost(step3ImageStyleUrl(id, '/reverse'), form);
      renderResult(result.style);
      rememberProjectId(id);
      toast('已反推并应用到当前项目 Step 3 图片风格。', 4500);
      if (document.getElementById('step3-style-reverse-generate-refs')?.checked) {
        button.textContent = '生成参考图...';
        const refs = await fetch(step3ImageStyleUrl(id, '/reference-images/generate'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ count: 3 })
        }).then(parseJsonResponse);
        toast(`已生成 ${(refs.references?.images || []).length} 张 Step 3 风格参考图。`, 4500);
      }
      if (typeof window.refreshStep3Prompts === 'function') {
        await window.refreshStep3Prompts({ updateOpenEditor: true });
      }
    } catch (error) {
      toast(`反推失败：${error.message}`, 8000);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function ensureStep3Button() {
    ensureStyle();
    ensureModal();
    const toolbar = document.querySelector('#step-panel-3 .step3-toolbar-row');
    if (!toolbar || document.getElementById('step3-btn-image-style-reverse')) return;
    const button = document.createElement('button');
    button.id = 'step3-btn-image-style-reverse';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '上传示例图反推风格';
    button.addEventListener('click', openModal);
    const refButton = document.getElementById('step3-btn-style-reference-manager');
    const styleButton = document.getElementById('step3-btn-style');
    if (refButton?.parentElement === toolbar) toolbar.insertBefore(button, refButton.nextSibling);
    else if (styleButton?.parentElement === toolbar) toolbar.insertBefore(button, styleButton.nextSibling);
    else toolbar.appendChild(button);
  }

  function removeLegacyHeaderButton() {
    document.getElementById('btn-image-style-reverse')?.remove();
  }

  function boot() {
    removeLegacyHeaderButton();
    patchWorkspaceNavigation();
    ensureStep3Button();
    const timer = setInterval(() => {
      removeLegacyHeaderButton();
      ensureStep3Button();
    }, 700);
    setTimeout(() => clearInterval(timer), 15000);
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
