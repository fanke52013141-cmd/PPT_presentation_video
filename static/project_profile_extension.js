(function () {
  'use strict';

  const PROFILE_STATE = {
    templates: null,
    creating: false,
    generatedImageStyle: null,
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
      PROFILE_STATE.templates = response;
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
      .project-profile-ai-actions { display: flex; gap: .6rem; align-items: center; margin-top: .6rem; }
      .project-profile-ai-actions button { flex: 0 0 auto; }
      .project-profile-ai-style-preview { display: none; margin-top: .65rem; padding: .7rem; border: 1.5px dashed #111; border-radius: 12px; background: #f9fbff; font-size: .86rem; line-height: 1.5; }
      .project-profile-ai-style-preview strong { display: block; margin-bottom: .25rem; }
      .project-profile-ai-style-preview code { white-space: pre-wrap; display: block; max-height: 150px; overflow: auto; background: #fff; padding: .45rem; border-radius: 8px; margin-top: .45rem; }
      .project-profile-ref-toggle { margin-top: .55rem; padding: .55rem .65rem; border: 1px solid #111; border-radius: 12px; background: #fff; font-weight: 700; }
      .project-profile-ref-toggle input { width: auto; margin-right: .4rem; }
      @media (max-width: 980px) { .project-profile-grid, .project-profile-mode-grid { grid-template-columns: 1fr; } .project-profile-ai-actions { align-items: stretch; flex-direction: column; } }
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
            <p class="project-profile-note">全自动模式会配合一键生成入口运行完整链路；失败或质量门不通过时暂停给用户处理。</p>
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
              <option value="ai_text_generated">用文字让 AI 生成风格</option>
              <option value="image_reverse_engineered">稍后上传 1-3 张参考图反推风格</option>
            </select>
            <label>图片风格补充要求</label>
            <textarea id="project-profile-image-style-requirement" rows="4" placeholder="例如：适合金融科普，蓝白科技感，但不要太严肃；元素之间不要粘连。"></textarea>
            <div class="project-profile-ai-actions">
              <button id="btn-project-profile-generate-image-style" class="secondary" type="button">AI 生成图片风格草案</button>
              <span class="project-profile-note">生成后会保存为结构化 image_style_profile。</span>
            </div>
            <label class="project-profile-ref-toggle">
              <input id="project-profile-generate-style-references" type="checkbox" checked>
              创建项目后自动生成 1-3 张风格参考图
            </label>
            <p class="project-profile-note">参考图只在 AI 文字生成风格时自动生成，保存在当前项目 planning/style_references/，不覆盖全局图片风格参考图。</p>
            <div id="project-profile-ai-style-preview" class="project-profile-ai-style-preview"></div>
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

  function renderGeneratedImageStyle(style) {
    const preview = document.getElementById('project-profile-ai-style-preview');
    if (!preview || !style) return;
    const visualLanguage = style.visual_language || {};
    const palette = Array.isArray(visualLanguage.color_palette) ? visualLanguage.color_palette.join(' / ') : '';
    const samples = Array.isArray(style.sample_reference_image_prompts) ? style.sample_reference_image_prompts.length : 0;
    preview.style.display = 'block';
    preview.innerHTML = `
      <strong>${esc(style.style_name || 'AI 生成图片风格')}</strong>
      <div>${esc(style.style_summary || '')}</div>
      ${palette ? `<div>Palette: ${esc(palette)}</div>` : ''}
      ${samples ? `<div>参考图 Prompt：${samples} 条</div>` : ''}
      <code>${esc(style.system_content || '')}</code>
    `;
  }

  async function generateImageStyleDraft() {
    const requirementEl = document.getElementById('project-profile-image-style-requirement');
    const sourceEl = document.getElementById('project-profile-image-style-source');
    const button = document.getElementById('btn-project-profile-generate-image-style');
    const requirement = requirementEl?.value.trim() || '';
    if (!requirement) {
      toast('请先填写图片风格补充要求，例如受众、行业、颜色、线条、质感和禁用项。', 5000);
      return;
    }
    const templates = PROFILE_STATE.templates || {};
    const imageStyleId = selectedOption('image_style_template', 'handdrawn_ppt_sticker');
    const imageTemplate = selectedTemplate(templates.image_style_templates, imageStyleId);
    const projectContext = [
      document.getElementById('input-project-name')?.value || '',
      document.getElementById('input-project-desc')?.value || '',
    ].filter(Boolean).join('\n');
    const originalText = button?.textContent || 'AI 生成图片风格草案';
    if (button) {
      button.disabled = true;
      button.textContent = '生成中...';
    }
    try {
      const result = await apiPost('/api/project-profile/image-style/generate', {
        requirement,
        project_context: projectContext,
        base_template: imageTemplate,
      });
      PROFILE_STATE.generatedImageStyle = result.style;
      if (sourceEl) sourceEl.value = 'ai_text_generated';
      renderGeneratedImageStyle(result.style);
      toast('✅ 图片风格草案已生成，将随项目一起保存。', 4500);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
    }
  }

  function shouldGenerateStyleReferences(profile) {
    const checkbox = document.getElementById('project-profile-generate-style-references');
    if (!checkbox?.checked) return false;
    const imageStyle = profile?.image_style_profile || {};
    return imageStyle.source === 'ai_text_generated';
  }

  async function generateProjectStyleReferences(projectId, profile) {
    if (!shouldGenerateStyleReferences(profile)) return null;
    const targetCount = Math.max(1, Math.min(3, Number(profile.image_style_profile?.reference_image_count_target || 3)));
    return apiPost(`/api/projects/${projectId}/project-profile/image-style/reference-images/generate`, { count: targetCount });
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
    document.getElementById('btn-project-profile-generate-image-style')?.addEventListener('click', event => {
      event.preventDefault();
      generateImageStyleDraft().catch(error => toast(`❌ AI 生成图片风格失败：${error.message}`, 7000));
    });
    document.getElementById('project-profile-image-style-source')?.addEventListener('change', event => {
      if (event.target.value !== 'ai_text_generated') {
        PROFILE_STATE.generatedImageStyle = null;
        const preview = document.getElementById('project-profile-ai-style-preview');
        if (preview) preview.style.display = 'none';
      }
    });
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
    const imageSource = document.getElementById('project-profile-image-style-source')?.value || 'template';
    const generatedStyle = imageSource === 'ai_text_generated' ? (PROFILE_STATE.generatedImageStyle || {}) : {};
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
        source: imageSource,
        template_id: generatedStyle.template_id || imageTemplate.id || imageStyleId,
        template_name: generatedStyle.template_name || generatedStyle.style_name || imageTemplate.name || '',
        style_name: generatedStyle.style_name || imageTemplate.name || '',
        style_summary: generatedStyle.style_summary || imageTemplate.description || '',
        custom_requirement: document.getElementById('project-profile-image-style-requirement')?.value || '',
        system_content: generatedStyle.system_content || imageTemplate.system_content || '',
        visual_language: generatedStyle.visual_language || {},
        maskability_rules: generatedStyle.maskability_rules || [],
        negative_prompt_rules: generatedStyle.negative_prompt_rules || [],
        sample_reference_image_prompts: generatedStyle.sample_reference_image_prompts || [],
        reference_image_count_target: generatedStyle.reference_image_count_target || 0,
        generated_at: generatedStyle.generated_at || '',
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
      await apiPut(`/api/projects/${project.id}/project-profile`, { profile });
      let referenceCount = 0;
      if (shouldGenerateStyleReferences(profile)) {
        if (button) button.textContent = '生成风格参考图...';
        try {
          const referenceResult = await generateProjectStyleReferences(project.id, profile);
          referenceCount = referenceResult?.references?.images?.length || 0;
        } catch (error) {
          toast(`⚠️ 项目已创建，但风格参考图生成失败：${error.message}`, 7000);
        }
      }
      if (article) {
        if (button) button.textContent = '导入文章...';
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${project.id}/steps/1/import`, form);
      }
      document.getElementById('modal-create').style.display = 'none';
      const modeLabel = profile.automation_mode === 'auto' ? '全自动模式' : '手动审核模式';
      const refText = referenceCount ? `，并生成 ${referenceCount} 张风格参考图` : '';
      toast(`🎉 项目已创建，并保存 Project Profile（${modeLabel}）${refText}。`, 4500);
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
