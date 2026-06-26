(function () {
  'use strict';

  const STATE = {
    projectId: sessionStorage.getItem('ppt_image_style_reverse_project_id') || '',
    running: false,
  };

  function parseJsonResponse(response) {
    return response.json().then(data => {
      if (!response.ok) throw new Error(data.detail || data.message || response.statusText || '请求失败');
      return data;
    });
  }

  function apiPost(url, body) {
    if (window.API?.post) return window.API.post(url, body);
    const isFormData = body instanceof FormData;
    return fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body || {}),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    }).then(parseJsonResponse);
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
    sessionStorage.setItem('ppt_image_style_reverse_project_id', STATE.projectId);
  }

  function activeProjectId() {
    return STATE.projectId || sessionStorage.getItem('ppt_image_style_reverse_project_id') || '';
  }

  function patchWorkspaceNavigation() {
    const patch = () => {
      if (window.enterWorkspace && !window.enterWorkspace.__imageStyleReversePatched) {
        const originalEnter = window.enterWorkspace;
        window.enterWorkspace = async function patchedEnterWorkspace(projectId) {
          rememberProjectId(projectId);
          const result = await originalEnter.apply(this, arguments);
          ensureEntryButton();
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
    if (document.getElementById('image-style-reverse-style')) return;
    const style = document.createElement('style');
    style.id = 'image-style-reverse-style';
    style.textContent = `
      #btn-image-style-reverse { margin-left: .5rem; }
      .image-style-reverse-modal { max-width: 1080px; width: min(1080px, 94vw); }
      .image-style-reverse-grid { display: grid; grid-template-columns: .9fr 1.1fr; gap: 1rem; }
      .image-style-reverse-section { border: 2px solid #111; border-radius: 14px; background: #fffef9; padding: 1rem; box-shadow: 3px 3px 0 rgba(0,0,0,.12); }
      .image-style-reverse-section label { display: block; font-weight: 800; margin: .65rem 0 .3rem; }
      .image-style-reverse-section input[type=file], .image-style-reverse-section textarea { width: 100%; }
      .image-style-reverse-note { color: #555; font-size: .88rem; line-height: 1.5; }
      .image-style-reverse-preview { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; margin-top: .7rem; }
      .image-style-reverse-preview img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border: 1.5px solid #111; border-radius: 10px; background: #fff; }
      .image-style-reverse-result { white-space: pre-wrap; max-height: 430px; overflow: auto; background: #fff; border: 1.5px dashed #111; border-radius: 12px; padding: .75rem; font-size: .86rem; line-height: 1.45; }
      .image-style-reverse-actions { display: flex; gap: .6rem; flex-wrap: wrap; margin-top: .9rem; }
      @media (max-width: 980px) { .image-style-reverse-grid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureModal() {
    if (document.getElementById('modal-image-style-reverse')) return;
    const modal = document.createElement('div');
    modal.id = 'modal-image-style-reverse';
    modal.className = 'modal';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content image-style-reverse-modal">
        <h3 class="highlight-title">上传参考图反推图片风格</h3>
        <p class="image-style-reverse-note">上传 1-3 张参考图，系统会抽取可复用视觉语言并写入 Project Profile。只反推线条、形状、色板、构图密度、字体感和 Mask 友好规则；不会把复杂背景画进 visual_draft.png。</p>
        <div class="image-style-reverse-grid">
          <section class="image-style-reverse-section">
            <h4>参考图输入</h4>
            <label>上传 1-3 张图片</label>
            <input id="image-style-reverse-files" type="file" accept="image/*" multiple>
            <div id="image-style-reverse-preview" class="image-style-reverse-preview"></div>
            <label>补充要求</label>
            <textarea id="image-style-reverse-requirement" rows="5" placeholder="例如：保留这种圆角贴纸和柔和配色，但不要复制复杂背景；适合金融科普，元素之间要留白。"></textarea>
            <label><input id="image-style-reverse-generate-refs" type="checkbox" checked> 反推后自动生成项目级风格参考图</label>
            <div class="image-style-reverse-actions">
              <button id="btn-image-style-reverse-run" class="primary" type="button">开始反推并应用</button>
              <button id="btn-image-style-reverse-close" class="secondary" type="button">关闭</button>
            </div>
          </section>
          <section class="image-style-reverse-section">
            <h4>反推结果</h4>
            <div id="image-style-reverse-result" class="image-style-reverse-result">尚未反推。</div>
          </section>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
      if (event.target === modal) closeModal();
    });
    document.getElementById('btn-image-style-reverse-close')?.addEventListener('click', closeModal);
    document.getElementById('btn-image-style-reverse-run')?.addEventListener('click', () => runReverse().catch(error => toast(`反推失败：${error.message}`, 8000)));
    document.getElementById('image-style-reverse-files')?.addEventListener('change', renderFilePreview);
  }

  function ensureEntryButton() {
    ensureStyle();
    ensureModal();
    const header = document.getElementById('project-info-header');
    if (!header || document.getElementById('btn-image-style-reverse')) return;
    const button = document.createElement('button');
    button.id = 'btn-image-style-reverse';
    button.className = 'secondary';
    button.type = 'button';
    button.textContent = '以图定风格';
    button.addEventListener('click', openModal);
    const styleRefButton = document.getElementById('btn-style-reference-manager');
    if (styleRefButton?.parentElement === header) {
      header.insertBefore(button, styleRefButton.nextSibling);
    } else {
      const backButton = document.getElementById('btn-back-home');
      if (backButton?.parentElement === header) header.insertBefore(button, backButton);
      else header.appendChild(button);
    }
  }

  function openModal() {
    ensureModal();
    const modal = document.getElementById('modal-image-style-reverse');
    if (modal) modal.style.display = 'flex';
  }

  function closeModal() {
    const modal = document.getElementById('modal-image-style-reverse');
    if (modal) modal.style.display = 'none';
  }

  function renderFilePreview() {
    const input = document.getElementById('image-style-reverse-files');
    const preview = document.getElementById('image-style-reverse-preview');
    if (!input || !preview) return;
    const files = Array.from(input.files || []).slice(0, 3);
    preview.innerHTML = '';
    files.forEach(file => {
      const img = document.createElement('img');
      img.src = URL.createObjectURL(file);
      img.onload = () => URL.revokeObjectURL(img.src);
      img.alt = file.name;
      preview.appendChild(img);
    });
  }

  function renderResult(style) {
    const el = document.getElementById('image-style-reverse-result');
    if (!el) return;
    if (!style) {
      el.textContent = '没有返回风格结果。';
      return;
    }
    const lines = [];
    lines.push(`风格名称：${style.style_name || ''}`);
    lines.push(`风格摘要：${style.style_summary || ''}`);
    if (style.source_notes) lines.push(`抽取说明：${style.source_notes}`);
    if (Array.isArray(style.warnings) && style.warnings.length) {
      lines.push('\n风险提示：');
      style.warnings.forEach(item => lines.push(`- ${item}`));
    }
    if (style.system_content) {
      lines.push('\nSystem Content:');
      lines.push(style.system_content);
    }
    if (style.visual_language && typeof style.visual_language === 'object') {
      lines.push('\nVisual Language:');
      Object.entries(style.visual_language).forEach(([key, value]) => {
        lines.push(`- ${key}: ${Array.isArray(value) ? value.join(' / ') : value}`);
      });
    }
    if (Array.isArray(style.maskability_rules) && style.maskability_rules.length) {
      lines.push('\nMaskability Rules:');
      style.maskability_rules.forEach(item => lines.push(`- ${item}`));
    }
    if (Array.isArray(style.negative_prompt_rules) && style.negative_prompt_rules.length) {
      lines.push('\nNegative Rules:');
      style.negative_prompt_rules.forEach(item => lines.push(`- ${item}`));
    }
    el.textContent = lines.join('\n');
  }

  async function runReverse() {
    if (STATE.running) return;
    const projectId = activeProjectId();
    if (!projectId) return toast('当前没有可识别的项目，请先进入项目工作区。', 5000);
    const input = document.getElementById('image-style-reverse-files');
    const files = Array.from(input?.files || []);
    if (!files.length) return toast('请先上传 1-3 张参考图。', 5000);
    if (files.length > 3) return toast('最多只能上传 3 张参考图。', 5000);
    const form = new FormData();
    files.slice(0, 3).forEach(file => form.append('files', file));
    form.append('requirement', document.getElementById('image-style-reverse-requirement')?.value || '');
    form.append('apply', 'true');
    const button = document.getElementById('btn-image-style-reverse-run');
    const original = button?.textContent || '开始反推并应用';
    STATE.running = true;
    if (button) {
      button.disabled = true;
      button.textContent = '反推中...';
    }
    try {
      const result = await apiPost(`/api/projects/${projectId}/project-profile/image-style/reverse`, form);
      renderResult(result.style);
      toast('已反推并应用图片风格到 Project Profile。', 4500);
      if (document.getElementById('image-style-reverse-generate-refs')?.checked) {
        if (button) button.textContent = '生成风格参考图...';
        try {
          const refs = await apiPost(`/api/projects/${projectId}/project-profile/image-style/reference-images/generate`, { count: 3 });
          toast(`已生成 ${(refs.references?.images || []).length} 张项目级风格参考图。`, 4500);
        } catch (error) {
          toast(`风格已应用，但参考图生成失败：${error.message}`, 7000);
        }
      }
    } finally {
      STATE.running = false;
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  function boot() {
    ensureStyle();
    ensureModal();
    patchWorkspaceNavigation();
    const timer = setInterval(ensureEntryButton, 700);
    setTimeout(() => clearInterval(timer), 15000);
  }

  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') boot();
})();
