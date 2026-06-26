(function () {
  'use strict';

  const PROFILE_STATE = {
    templates: null,
    creating: false,
  };

  function apiGet(url) {
    return window.API?.get
      ? window.API.get(url)
      : fetch(url).then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
  }

  function apiPost(url, body) {
    return window.API?.post
      ? window.API.post(url, body)
      : fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
        .then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
  }

  function apiPut(url, body) {
    return window.API?.put
      ? window.API.put(url, body)
      : fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
        .then(r => r.json().then(d => { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }));
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
      const res = await apiGet('/api/project-profile/templates');
      PROFILE_STATE.templates = res;
    } catch (error) {
      PROFILE_STATE.templates = {
        storyboard_templates: [{ id: 'science_explainer', name: '科普解释型', description: '默认分镜模板', methodology: '每页只讲一个核心点。' }],
        image_style_templates: [{ id: 'handdrawn_ppt_sticker', name: '手绘 PPT 贴纸风', description: '默认图片风格', system_content: 'Use hand-drawn PPT sticker style. Keep pure-white outer canvas.' }],
        automation_modes: [
          { id: 'manual_review', name: '手动审核模式', description: '每一步由用户确认。' },
          { id: 'auto', name: '全自动模式', description: '正常路径自动跑完整链路，失败时暂停。' },
        ],
      };
    }
    return PROFILE_STATE.templates;
  }

  function ensureStyle() {
    if (document.getElementById('project-profile-extension-style')) return;
    const style = document.createElement('style');
    style.id = 'project-profile-extension-style';
    style.textContent = `
      #modal-create .project-profile-modal { max-width: 1120px; width: min(1120px, 94vw); }
      .project-profile-scroll { max-height: 76vh; overflow: auto; padding-right: .35rem; }
      .project-profile-grid { display: grid; grid-template-columns: 1.05fr .95fr; gap: 1rem; }
      .project-profile-section { border: 2px solid var(--ink-color, #111); border-radius: 16px; padding: 1rem; background: #fffef9; box-shadow: 3px 3px 0 rgba(0,0,0,.12); }
      .project-profile-section h4 { margin: 0 0 .65rem; font-size: 1rem; }
      .project-profile-section label { display: block; font-weight: 800; margin: .65rem 0 .3rem; }
      .project-profile-section textarea, .project-profile-section input, .project-profile-section select { width: 100%; }
      .project-profile-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem; }
      .project-profile-card-option { border: 2px dashed #111; border-radius: 14px; padding: .75rem; cursor: pointer; background: #fff; transition: transform .12s ease, background .12s ease; }
      .project-profile-card-option:hover { transform: translateY(-1px); }
      .project-profile-card-option.active { border-style: solid; background: #f1f3ff; box-shadow: 2px 2px 0 rgba(0,0,0,.14); }
      .project-profile-card-option strong { display: block; margin-bottom: .25rem; }
      .project-profile-card-option span { display: block; color: #555; font-size: .86rem; line-height: 1.45; }
      .project-profile-note { color: #555; font-size: .88rem; line-height: 1.55; margin: .45rem 0 0; }
      .project-profile-warning { background: #fff8dc; border-left: 4px solid #d6a100; padding: .7rem .85rem; margin: .8rem 0; font-size: .9rem; line-height: 1.5; }
      .project-profile-inline { display: flex; gap: .7rem; align-items: center; }
      .project-profile-inline > * { flex: 1; }
      .project-profile-pill { display: inline-flex; align-items: center; gap: .35rem; border: 1px solid #111; border-radius: 999px; padding: .2rem .55rem; font-size: .78rem; background: #fff; }
      @media (max-width: 980px) { .project-profile-grid, .project-profile-mode-grid { grid-template-columns: 1fr; } }
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
        <p class="config-editor-note">Project Profile 会在创建时确定生产模式、分镜风格、图片风格和最终视频背景。生成图片仍保持纯白底；最终视频背景单独合成。</p>
        <div class="project-profile-warning"><strong>生产不变量：</strong>无论选择什么风格，visual_draft.png 外背景都必须保持纯白 #FFFFFF；元素之间必须分离，不能粘连，方便 AI Mask 和手动 Mask。</div>
        <div class="project-profile-grid">
          <section class="project-profile-section">
            <h4>1. 基础信息</h4>
            <label>项目名称</label>
            <input type="text" id="input-project-name" placeholder="例如：AI 大模型原理解析">
            <label>项目描述</label>
            <textarea id="input-project-desc" rows="3" placeholder="可选：说明项目用途、受众、表达偏好。"></textarea>
            <label>可选文章内容</label>
            <textarea id="input-project-article" rows="7" placeholder="可选：创建后自动导入为 Step 1 文章；留空则稍后手动导入。"></textarea>
          </section>
          <section class="project-profile-section">
            <h4>2. 生产模式</h4>
            <div class="project-profile-mode-grid">${optionCards(templates.automation_modes || [], 'automation_mode', 'manual_review')}</div>
            <p class="project-profile-note">全自动模式在后续 Orchestrator 完成后会从内容自动跑到视频；失败或质量门不通过时暂停给用户处理。当前版本先保存该配置。</p>
          </section>
          <section class="project-profile-section">
            <h4>3. 分镜风格</h4>
            <div>${optionCards(templates.storyboard_templates || [], 'storyboard_template', 'science_explainer')}</div>
            <label>分镜补充要求</label>
            <textarea id="project-profile-storyboard-requirement" rows="4" placeholder="例如：控制在 6 页以内；先讲概念，再讲机制和应用；旁白更口语化。"></textarea>
          </section>
          <section class="project-profile-section">
            <h4>4. 图片风格</h4>
            <div>${optionCards(templates.image_style_templates || [], 'image_style_template', 'handdrawn_ppt_sticker')}</div>
            <label>图片风格来源</label>
            <select id="project-profile-image-style-source">
              <option value="template">使用所选模板</option>
              <option value="ai_text_generated">稍后用文字让 AI 生成风格</option>
              <option value="image_reverse_engineered">稍后上传 1-3 张参考图反推风格</option>
            </select>
            <label>图片风格补充要求</label>
            <textarea id="project-profile-image-style-requirement" rows="4" placeholder="例如：适合金融科普，蓝白科技感，但不要太严肃；元素之间不要粘连。"></textarea>
          </section>
          <section class="project-profile-section">
            <h4>5. 最终视频背景</h4>
            <label>背景类型</label>
            <select id="project-profile-background-mode">
              <option value="solid">纯色背景</option>
              <option value="image">图片背景（稍后上传）</option>
            </select>
            <label>纯色颜色</label>
            <div class="project-profile-inline">
              <input id="project-profile-background-color" type="color" value="#FFFFFF">
              <input id="project-profile-background-color-text" type="text" value="#FFFFFF" maxlength="7">
            </div>
            <p class="project-profile-note">这里设置最终视频底图，不改变生图白底。图片背景可以在 Step 2 背景设置里上传。</p>
          </section>
          <section class="project-profile-section">
            <h4>6. 质量门</h4>
            <label><input type="checkbox" class="project-profile-gate" data-gate="pause_on_storyboard_validation_error" checked> 分镜结构校验失败时暂停</label>
            <label><input type="checkbox" class="project-profile-gate" data-gate="pause_on_image_generation_failure" checked> 图片生成失败时暂停</label>
            <label><input type="checkbox" class="project-profile-gate" data-gate="pause_on_ai_mask_low_confidence" checked> AI Mask 低置信度时暂停</label>
            <label><input type="checkbox" class="project-profile-gate" data-gate="pause_on_tts_failure" checked> TTS 失败时暂停</label>
            <label><input type="checkbox" class="project-profile-gate" data-gate="pause_on_render_failure" checked> 渲染失败时暂停</label>
          </section>
        </div>
      </div>
      <div class="config-editor-actions">
        <span class="project-profile-pill">Project Profile v1</span>
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

  function selectedTemplate(items, id) {
    return (items || []).find(item => item.id === id) || (items || [])[0] || {};
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
    const color = document.getElementById('project-profile-background-color');
    const colorText = document.getElementById('project-profile-background-color-text');
    color?.addEventListener('input', () => { colorText.value = color.value.toUpperCase(); });
    colorText?.addEventListener('input', () => {
      const value = colorText.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(value)) color.value = value;
    });
  }

  function collectProfile() {
    const templates = PROFILE_STATE.templates || {};
    const storyboardId = selectedOption('storyboard_template', 'science_explainer');
    const imageStyleId = selectedOption('image_style_template', 'handdrawn_ppt_sticker');
    const storyboardTemplate = selectedTemplate(templates.storyboard_templates, storyboardId);
    const imageTemplate = selectedTemplate(templates.image_style_templates, imageStyleId);
    const gates = {};
    document.querySelectorAll('.project-profile-gate').forEach(input => { gates[input.dataset.gate] = !!input.checked; });
    return {
      version: 'project_profile_v1',
      automation_mode: selectedOption('automation_mode', 'manual_review'),
      storyboard_profile: {
        source: 'template',
        template_id: storyboardTemplate.id || storyboardId,
        template_name: storyboardTemplate.name || '',
        custom_requirement: document.getElementById('project-profile-storyboard-requirement')?.value || '',
        methodology: storyboardTemplate.methodology || '',
      },
      image_style_profile: {
        source: document.getElementById('project-profile-image-style-source')?.value || 'template',
        template_id: imageTemplate.id || imageStyleId,
        template_name: imageTemplate.name || '',
        custom_requirement: document.getElementById('project-profile-image-style-requirement')?.value || '',
        system_content: imageTemplate.system_content || '',
        reference_image_count_target: 0,
      },
      background_profile: {
        mode: document.getElementById('project-profile-background-mode')?.value || 'solid',
        solid_color: document.getElementById('project-profile-background-color-text')?.value || '#FFFFFF',
        image_asset: '',
        generation_policy: 'visual_draft_must_remain_pure_white',
      },
      quality_gates: gates,
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
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '创建中...';
    try {
      const projectRes = await apiPost('/api/projects', { name, description: desc });
      const project = projectRes.project;
      if (!project?.id) throw new Error('项目创建成功但未返回 project.id');
      const profile = collectProfile();
      await apiPut(`/api/projects/${project.id}/project-profile`, { profile });
      if (article) {
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${project.id}/steps/1/import`, form);
      }
      document.getElementById('modal-create').style.display = 'none';
      const modeLabel = profile.automation_mode === 'auto' ? '全自动模式' : '手动审核模式';
      toast(`🎉 项目已创建，并保存 Project Profile（${modeLabel}）。`, 4500);
      if (window.enterWorkspace) window.enterWorkspace(project.id);
      else location.reload();
    } finally {
      PROFILE_STATE.creating = false;
      button.disabled = false;
      button.textContent = original;
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
