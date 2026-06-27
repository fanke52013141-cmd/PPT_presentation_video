(function () {
  'use strict';

  const PROFILE_STATE = {
    templates: null,
    creating: false,
  };

  const DEFAULT_AUTOMATION_MODES = [
    { id: 'manual_review', name: '手动审核模式', description: '按原流程逐步生成、检查和确认。' },
    { id: 'auto', name: '全自动模式', description: '配合“一键生成”运行完整链路；失败时暂停给用户处理。' },
  ];

  const DEFAULT_QUALITY_GATES = {
    pause_on_storyboard_validation_error: true,
    pause_on_image_generation_failure: true,
    pause_on_ai_mask_low_confidence: true,
    pause_on_tts_failure: true,
    pause_on_render_failure: true,
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
    if (window.API?.post) return window.API.post(url, body);
    const isFormData = body instanceof FormData;
    return fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body || {}),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    }).then(parseJsonResponse);
  }

  function apiPut(url, body) {
    return window.API?.put
      ? window.API.put(url, body)
      : fetch(url, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {}),
        }).then(parseJsonResponse);
  }

  function toast(message, duration) {
    if (window.showToast) window.showToast(message, duration || 3000);
    else console.log(message);
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
  }

  async function loadTemplates() {
    if (PROFILE_STATE.templates) return PROFILE_STATE.templates;
    try {
      const response = await apiGet('/api/project-profile/templates');
      PROFILE_STATE.templates = {
        automation_modes: Array.isArray(response.automation_modes) && response.automation_modes.length
          ? response.automation_modes
          : DEFAULT_AUTOMATION_MODES,
      };
    } catch (_) {
      PROFILE_STATE.templates = { automation_modes: DEFAULT_AUTOMATION_MODES };
    }
    return PROFILE_STATE.templates;
  }

  function ensureStyle() {
    if (document.getElementById('project-profile-extension-style')) return;
    const style = document.createElement('style');
    style.id = 'project-profile-extension-style';
    style.textContent = `
      #modal-create .project-profile-modal { max-width: 780px; width: min(780px, 94vw); }
      .project-profile-scroll { max-height: 76vh; overflow: auto; padding-right: .35rem; }
      .project-profile-section { border: 2px solid var(--ink-color, #111); border-radius: 16px; padding: 1rem; background: #fffef9; box-shadow: 3px 3px 0 rgba(0,0,0,.12); margin-bottom: .9rem; }
      .project-profile-section h4 { margin: 0 0 .65rem; font-size: 1rem; }
      .project-profile-section label { display: block; font-weight: 800; margin: .65rem 0 .3rem; }
      .project-profile-section textarea, .project-profile-section input { width: 100%; box-sizing: border-box; }
      .project-profile-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem; }
      .project-profile-card-option { border: 2px dashed #111; border-radius: 14px; padding: .75rem; cursor: pointer; background: #fff; transition: transform .12s ease, background .12s ease; }
      .project-profile-card-option:hover { transform: translateY(-1px); }
      .project-profile-card-option.active { border-style: solid; background: #f1f3ff; box-shadow: 2px 2px 0 rgba(0,0,0,.14); }
      .project-profile-card-option strong { display: block; margin-bottom: .25rem; }
      .project-profile-card-option span { display: block; color: #555; font-size: .86rem; line-height: 1.45; }
      .project-profile-note { color: #555; font-size: .88rem; line-height: 1.55; margin: .45rem 0 0; }
      .project-profile-warning { background: #fff8dc; border-left: 4px solid #d6a100; padding: .7rem .85rem; margin: .8rem 0; font-size: .9rem; line-height: 1.5; }
      .project-profile-pill { display: inline-flex; align-items: center; gap: .35rem; border: 1px solid #111; border-radius: 999px; padding: .2rem .55rem; font-size: .78rem; background: #fff; }
      @media (max-width: 760px) { .project-profile-mode-grid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function optionCards(items, field, selectedId) {
    return (items || []).map(item => `
      <div class="project-profile-card-option ${item.id === selectedId ? 'active' : ''}" data-profile-option="${esc(field)}" data-value="${esc(item.id)}">
        <strong>${esc(item.name)}</strong>
        <span>${esc(item.description || '')}</span>
      </div>
    `).join('');
  }

  function renderModal(templates) {
    const modal = document.getElementById('modal-create');
    const content = modal?.querySelector('.modal-content');
    if (!modal || !content || content.dataset.projectProfileWizard === '1') return;
    content.dataset.projectProfileWizard = '1';
    content.className = 'modal-content project-profile-modal';
    content.innerHTML = `
      <div class="project-profile-scroll">
        <h3 class="highlight-title" style="margin-bottom: .8rem;">新建视频项目</h3>
        <p class="config-editor-note">这里只创建项目并选择生产模式。分镜风格在 Step 2 设置，图片风格、参考图和“以图定风格”在 Step 3 图片生成阶段设置。</p>
        <div class="project-profile-warning"><strong>流程边界：</strong>创建项目不再配置分镜风格或图片风格，避免和 Step 2 / Step 3 的模板系统重复。</div>
        <section class="project-profile-section">
          <h4>1. 基础信息</h4>
          <label>项目名称</label>
          <input type="text" id="input-project-name" placeholder="例如：AI 大模型原理解析">
          <label>项目描述</label>
          <textarea id="input-project-desc" rows="3" placeholder="可选：说明项目用途、受众或备注。"></textarea>
          <label>可选文章内容</label>
          <textarea id="input-project-article" rows="8" placeholder="可选：创建后自动导入为 Step 1 文章；留空则稍后手动导入。"></textarea>
        </section>
        <section class="project-profile-section">
          <h4>2. 生产模式</h4>
          <div class="project-profile-mode-grid">${optionCards(templates.automation_modes || DEFAULT_AUTOMATION_MODES, 'automation_mode', 'manual_review')}</div>
          <p class="project-profile-note">全自动模式只影响“一键生成”的调度偏好；实际分镜和图片风格仍由对应步骤的当前配置决定。</p>
        </section>
      </div>
      <div class="config-editor-actions">
        <span class="project-profile-pill">轻量项目创建</span>
        <button id="btn-create-cancel" class="secondary" type="button">取消</button>
        <button id="btn-create-submit" class="success" type="button">创建项目</button>
      </div>
    `;
    bindModalEvents();
  }

  function activateOption(field, value) {
    document.querySelectorAll(`[data-profile-option="${field}"]`).forEach(card => {
      card.classList.toggle('active', card.dataset.value === value);
    });
  }

  function selectedOption(field, fallback) {
    return document.querySelector(`[data-profile-option="${field}"].active`)?.dataset.value || fallback;
  }

  function bindModalEvents() {
    document.querySelectorAll('[data-profile-option]').forEach(card => {
      card.addEventListener('click', () => activateOption(card.getAttribute('data-profile-option'), card.dataset.value));
    });
    document.getElementById('btn-create-cancel')?.addEventListener('click', () => {
      document.getElementById('modal-create').style.display = 'none';
    });
    document.getElementById('btn-create-submit')?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      createProjectWithProfile().catch(error => toast(`❌ 创建失败：${error.message}`, 7000));
    }, true);
  }

  function collectProfile() {
    return {
      version: 'project_profile_v1',
      automation_mode: selectedOption('automation_mode', 'manual_review'),
      quality_gates: { ...DEFAULT_QUALITY_GATES },
      last_used_storyboard_template_id: '',
      last_used_image_style_template_id: '',
      notes: 'Lightweight profile only. Step 2 owns storyboard style; Step 3 owns image style and references.',
    };
  }

  async function createProjectWithProfile() {
    if (PROFILE_STATE.creating) return;
    const name = document.getElementById('input-project-name')?.value.trim() || '';
    const desc = document.getElementById('input-project-desc')?.value.trim() || '';
    const article = document.getElementById('input-project-article')?.value.trim() || '';
    if (!name) {
      toast('⚠️ 请输入项目名称');
      return;
    }
    PROFILE_STATE.creating = true;
    const button = document.getElementById('btn-create-submit');
    const original = button?.textContent || '创建项目';
    if (button) {
      button.disabled = true;
      button.textContent = '创建中...';
    }
    try {
      const projectRes = await apiPost('/api/projects', { name, description: desc });
      const project = projectRes.project;
      if (!project?.id) throw new Error('项目创建成功但未返回 project.id');
      const profile = collectProfile();
      await apiPut(`/api/projects/${encodeURIComponent(project.id)}/project-profile`, { profile });
      if (article) {
        if (button) button.textContent = '导入文章...';
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/1/import`, form);
      }
      document.getElementById('modal-create').style.display = 'none';
      const modeLabel = profile.automation_mode === 'auto' ? '全自动模式' : '手动审核模式';
      toast(`🎉 项目已创建（${modeLabel}）。分镜风格请到 Step 2 设置，图片风格请到 Step 3 设置。`, 4500);
      if (window.enterWorkspace) window.enterWorkspace(project.id);
      else location.reload();
    } finally {
      PROFILE_STATE.creating = false;
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  async function enhanceCreateModal() {
    ensureStyle();
    const templates = await loadTemplates();
    renderModal(templates);
  }

  function boot() {
    if (!document.getElementById('modal-create')) return;
    enhanceCreateModal().catch(() => {});
  }

  document.addEventListener('DOMContentLoaded', boot);
  const timer = setInterval(() => {
    if (document.getElementById('modal-create')) {
      boot();
      clearInterval(timer);
    }
  }, 500);
})();
