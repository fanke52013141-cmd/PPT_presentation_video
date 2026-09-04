(function () {
  'use strict';

  const PROFILE_STATE = {
    templates: null,
    imageStyles: null,
    creationConfigs: null,
    selectedStyleTemplate: 'default',
    creating: false,
  };

  const DEFAULT_AUTOMATION_MODES = [
    { id: 'manual_review', name: '手动审核模式', description: '按原流程逐步生成、检查和确认。' },
    { id: 'auto', name: '全自动模式', description: '配合"一键生成"运行完整链路；失败时暂停给用户处理。' },
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

  async function loadImageStyles() {
    if (PROFILE_STATE.imageStyles) return PROFILE_STATE.imageStyles;
    try {
      const data = await apiGet('/api/image-style/templates');
      PROFILE_STATE.imageStyles = (data && data.templates) || [];
    } catch (_) {
      PROFILE_STATE.imageStyles = [];
    }
    return PROFILE_STATE.imageStyles;
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

  async function loadCreationConfigs() {
    try {
      const response = await apiGet('/api/creation-configs');
      PROFILE_STATE.creationConfigs = Array.isArray(response?.packages)
        ? response.packages
        : [];
    } catch (_) {
      // A package is optional; leaving the list empty preserves ordinary
      // project creation when the package registry is unavailable.
      PROFILE_STATE.creationConfigs = [];
    }
    return PROFILE_STATE.creationConfigs;
  }


  function optionCards(items, field, selectedId) {
    return (items || []).map(item => `
      <div class="project-profile-card-option ${item.id === selectedId ? 'active' : ''}" data-profile-option="${esc(field)}" data-value="${esc(item.id)}">
        <strong>${esc(item.name)}</strong>
      </div>
    `).join('');
  }

  function styleTiles(styles) {
    PROFILE_STATE.selectedStyleTemplate = 'default';
    return (styles || []).map(t => {
      let thumb = '';
      if (t.references && typeof t.references === 'object') {
        for (const key of Object.keys(t.references)) {
          const ref = t.references[key];
          if (ref && ref.url) { thumb = ref.url; break; }
        }
      }
      const sel = t.id === 'default' ? 'selected' : '';
      return `<div class="profile-style-tile ${sel}" data-style-id="${esc(t.id)}">
        ${thumb
          ? `<img src="${esc(thumb)}" alt="${esc(t.name)}" style="width:100%;height:72px;object-fit:cover;display:block;">`
          : `<div style="width:100%;height:72px;background:var(--color-bg-subtle);display:flex;align-items:center;justify-content:center;color:var(--color-text-tertiary);font-size:.74rem;">无预览</div>`}
        <div style="padding:.35rem .4rem;font-size:.8rem;text-align:center;background:var(--color-bg-surface);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--color-text-secondary);">${esc(t.name)}</div>
      </div>`;
    }).join('');
  }

  function creationConfigOptions(packages) {
    const available = (packages || []).filter(item => (
      item
      && !item.archived
      && typeof item.id === 'string'
      && item.id
      && Number.isInteger(Number(item.latest_version))
      && Number(item.latest_version) > 0
    ));
    const options = ['<option value="">不使用创作配置包</option>'];
    available.forEach(item => {
      const version = Number(item.latest_version);
      options.push(
        `<option value="${esc(item.id)}" data-version="${version}">${esc(item.name || '未命名配置包')} · v${version}</option>`
      );
    });
    return options.join('');
  }

  function renderModal(templates, imageStyles, creationConfigs) {
    const modal = document.getElementById('modal-create');
    const content = modal?.querySelector('.modal-content');
    if (!modal || !content || content.dataset.projectProfileWizard === '1') return;
    content.dataset.projectProfileWizard = '1';
    content.className = 'modal-content project-profile-modal';
    content.innerHTML = `
      <div class="project-profile-scroll">
        <h3 class="highlight-title" style="margin-bottom: .8rem;">新建视频项目</h3>
        <section class="project-profile-section">
          <h4>1. 基础信息</h4>
          <label>项目名称</label>
          <input type="text" id="input-project-name" placeholder="例如：AI 大模型原理解析">
          <label>项目描述</label>
          <textarea id="input-project-desc" rows="1" placeholder="可选：说明项目用途、受众或备注。"></textarea>
          <label>可选文章内容</label>
          <textarea id="input-project-article" rows="8" placeholder="可选：创建后自动导入为 Step 1 文章；留空则稍后手动导入。"></textarea>
        </section>
        <section class="project-profile-section">
          <h4>2. 画布比例</h4>
          <div class="project-profile-mode-grid">
            ${optionCards([
              { id: 'landscape_16_9', name: '横屏 16:9' },
              { id: 'portrait_9_16', name: '竖屏 9:16' },
            ], 'canvas_profile', 'landscape_16_9')}
          </div>
          <p class="project-profile-help">创建后比例会锁定；需要更换比例时请复制项目重新生成。</p>
        </section>
        <section class="project-profile-section">
          <h4>3. 生产模式</h4>
          <div class="project-profile-mode-grid">${optionCards(templates.automation_modes || DEFAULT_AUTOMATION_MODES, 'automation_mode', 'manual_review')}</div>
        </section>
        <section class="project-profile-section" id="create-creation-config-section">
          <h4>4. 创作配置包</h4>
          <label for="input-creation-config">选择配置包</label>
          <select id="input-creation-config">${creationConfigOptions(creationConfigs)}</select>
          <p id="create-creation-config-help" class="project-profile-help">${creationConfigs?.length ? '选择后会固定使用该配置包的最新版本；不选择则沿用当前项目创建方式。' : '暂无可用创作配置包；仍可按当前项目创建方式继续。'}</p>
        </section>
        <section class="project-profile-section">
          <h4>5. 是否需要 Mask 标注</h4>
          <div class="project-profile-mode-grid">
            ${optionCards([
              { id: 'false', name: '否（整页切换）' },
              { id: 'true', name: '是（逐元素揭示动画）' },
            ], 'mask_enabled', 'false')}
          </div>
          <p class="project-profile-help">选择"否"将跳过 AI Mask 标注步骤，视频以整页切换方式呈现，速度更快。</p>
        </section>
        <section class="project-profile-section" id="profile-pause-section" style="display:none;">
          <h4>6. 手动暂停模块</h4>
          <p class="project-profile-help" style="margin-bottom:.7rem;">勾选的模块在全自动流程到达该步骤时暂停，等待您手动操作后再继续。</p>
          <div class="profile-pause-chips">
            <label class="profile-pause-chip" id="profile-pause-chip-mask"><input type="checkbox" class="profile-pause-step" value="mask">Mask 标注模块</label>
            <label class="profile-pause-chip"><input type="checkbox" class="profile-pause-step" value="narration">旁白语音模块</label>
            <label class="profile-pause-chip"><input type="checkbox" class="profile-pause-step" value="digital_human">数字人模块</label>
          </div>
        </section>
        <section class="project-profile-section">
          <h4>7. 图片风格</h4>
          <div class="profile-style-grid">${styleTiles(imageStyles)}</div>
          <p class="project-profile-help">选择图片风格模板，将在生成图片时自动应用该风格。</p>
        </section>
      </div>
      <div class="config-editor-actions">
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
    // Show/hide pause section based on automation mode
    function syncPauseVisibility() {
      const mode = selectedOption('automation_mode', 'manual_review');
      const pauseSection = document.getElementById('profile-pause-section');
      if (pauseSection) pauseSection.style.display = mode === 'auto' ? '' : 'none';
      syncMaskChipVisibility();
    }

    // Show/hide Mask pause chip based on mask_enabled selection
    function syncMaskChipVisibility() {
      const maskEnabled = selectedOption('mask_enabled', 'false');
      const maskChip = document.getElementById('profile-pause-chip-mask');
      if (maskChip) maskChip.style.display = maskEnabled === 'true' ? '' : 'none';
      if (maskEnabled === 'false') {
        const maskCb = maskChip?.querySelector('input');
        if (maskCb) maskCb.checked = false;
      }
    }

    document.querySelectorAll('[data-profile-option]').forEach(card => {
      card.addEventListener('click', () => {
        activateOption(card.getAttribute('data-profile-option'), card.dataset.value);
        if (card.getAttribute('data-profile-option') === 'automation_mode') syncPauseVisibility();
        if (card.getAttribute('data-profile-option') === 'mask_enabled') syncMaskChipVisibility();
      });
    });

    // Style tile selection
    document.querySelectorAll('.profile-style-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        document.querySelectorAll('.profile-style-tile').forEach(t => { t.classList.remove('selected'); });
        tile.classList.add('selected');
        PROFILE_STATE.selectedStyleTemplate = tile.getAttribute('data-style-id') || 'default';
      });
    });

    syncPauseVisibility();

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
      canvas_profile: selectedOption('canvas_profile', 'landscape_16_9'),
      automation_mode: selectedOption('automation_mode', 'manual_review'),
      mask_enabled: selectedOption('mask_enabled', 'false') !== 'false',
      quality_gates: { ...DEFAULT_QUALITY_GATES },
      last_used_storyboard_template_id: '',
      last_used_image_style_template_id: PROFILE_STATE.selectedStyleTemplate || 'default',
      notes: 'Lightweight profile only. Step 2 owns storyboard style; Step 3 owns image style and references.',
    };
  }

  function collectManualPauseSteps() {
    const steps = [];
    document.querySelectorAll('.profile-pause-step:checked').forEach(cb => steps.push(cb.value));
    return steps;
  }

  function selectedCreationConfig() {
    const select = document.getElementById('input-creation-config');
    const option = select?.selectedOptions?.[0];
    const version = Number(option?.dataset?.version);
    if (!select?.value || !Number.isInteger(version) || version < 1) return null;
    return { id: select.value, version };
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
      const profile = collectProfile();
      const aiMode = profile.automation_mode === 'auto' ? 'auto' : 'manual';
      const manualPauseSteps = collectManualPauseSteps();
      const styleTemplate = PROFILE_STATE.selectedStyleTemplate || 'default';
      const creationConfig = selectedCreationConfig();
      const projectRes = await apiPost('/api/projects', {
        name,
        description: desc,
        ai_mode: aiMode,
        canvas_profile: profile.canvas_profile,
        manual_pause_steps: manualPauseSteps,
        image_style_template: styleTemplate,
        mask_enabled: profile.mask_enabled !== false,
        ...(creationConfig ? {
          config_package_id: creationConfig.id,
          config_package_version: creationConfig.version,
        } : {}),
      });
      const project = projectRes.project;
      if (!project?.id) throw new Error('项目创建成功但未返回 project.id');
      await apiPut(`/api/projects/${encodeURIComponent(project.id)}/project-profile`, { profile });

      // Apply image style template if not default
      if (styleTemplate && styleTemplate !== 'default') {
        try {
          await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/3/image-style/templates/${encodeURIComponent(styleTemplate)}/apply`);
        } catch (_) { /* non-fatal */ }
      }

      // 挂载到课程/章节：若由课程/章节的"+视频"按钮触发，
      // createProjectInCourse / createProjectInChapter 会把目标父级写入
      // window.__pendingProjectParent。创建成功后调用 /move 完成挂载，
      // 使视频直接出现在对应课程/章节下。
      const pendingParent = window.__pendingProjectParent || null;
      if (pendingParent) {
        try {
          await apiPost(`/api/projects/${encodeURIComponent(project.id)}/move`, pendingParent);
        } catch (e) {
          toast('视频移动到课程/章节失败，已创建为独立项目');
        }
        window.__pendingProjectParent = null;
      }

      if (article) {
        if (button) button.textContent = '导入文章...';
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/1/import`, form);
      }
      const shouldAutoStart = profile.automation_mode === 'auto' && !!article;
      let autoStarted = false;
      if (shouldAutoStart) {
        if (button) button.textContent = '启动一键生成...';
        try {
          await apiPost(`/api/projects/${encodeURIComponent(project.id)}/one-click-generate`, {});
          autoStarted = true;
        } catch (error) {
          toast(`项目已创建，但一键生成启动失败：${error.message}`, 7000);
        }
      }
      document.getElementById('modal-create').style.display = 'none';
      const modeLabel = profile.automation_mode === 'auto' ? '全自动模式' : '手动审核模式';
      toast(autoStarted ? `项目已创建（${modeLabel}），一键生成已启动。` : `项目已创建（${modeLabel}）。`, 4500);
      // [创建后进入详情页 20260813]
      // 先刷新课程树（让新视频出现在列表中），再自动进入工作台。
      try {
        if (window.loadProjects) { await window.loadProjects(); }
        else if (window.CourseTree && window.CourseTree.load) { await window.CourseTree.load(); }
      } catch (e) { /* 刷新失败不阻断进入 */ }
      if (typeof window.enterWorkspace === 'function' && project?.id) {
        await window.enterWorkspace(project.id);
      } else if (typeof enterWorkspace === 'function' && project?.id) {
        await enterWorkspace(project.id);
      }
    } finally {
      PROFILE_STATE.creating = false;
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  async function enhanceCreateModal() {
    const [templates, imageStyles, creationConfigs] = await Promise.all([
      loadTemplates(),
      loadImageStyles(),
      loadCreationConfigs(),
    ]);
    renderModal(templates, imageStyles, creationConfigs);
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
