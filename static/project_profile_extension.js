(function () {
  'use strict';

  const PROFILE_STATE = {
    imageStyles: null,
    creationConfigs: null,
    selectedStyleTemplate: 'default',
    creating: false,
  };

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

  function availableCreationConfigs(packages) {
    return (packages || []).filter(item => (
      item
      && !item.archived
      && typeof item.id === 'string'
      && item.id
      && Number.isInteger(Number(item.latest_version))
      && Number(item.latest_version) > 0
    ));
  }

  function creationConfigOptions(packages) {
    const available = availableCreationConfigs(packages);
    if (!available.length) return '<option value="">暂无可用创作配置包</option>';
    const options = [];
    available.forEach(item => {
      const version = Number(item.latest_version);
      options.push(
        `<option value="${esc(item.id)}" data-version="${version}">${esc(item.name || '未命名配置包')} · v${version}</option>`
      );
    });
    return options.join('');
  }

  function creationConfigChoices(packages) {
    const available = availableCreationConfigs(packages);
    if (!available.length) {
      return '<div class="creation-config-choice" aria-disabled="true"><strong>暂无可用创作配置包</strong><span>请先在“创作配置”中保存一套配置。</span></div>';
    }
    const choices = available.map(item => ({
      id: item.id,
      name: item.name || '未命名配置包',
      detail: `最新版本 v${Number(item.latest_version)} · 提示词与模型关联`
    }));
    return choices.map(item => `
      <button type="button" class="creation-config-choice" data-creation-config-choice="${esc(item.id)}" role="radio" aria-checked="false">
        <strong>${esc(item.name)}</strong>
        <span>${esc(item.detail)}</span>
      </button>
    `).join('');
  }

  function refreshCreationConfigChoices(packages) {
    const grid = document.getElementById('creation-config-choice-grid');
    const select = document.getElementById('input-creation-config');
    if (!grid || !select) return;
    const available = availableCreationConfigs(packages);
    const selected = available.some(item => item.id === select.value)
      ? select.value
      : (available[0]?.id || '');
    grid.innerHTML = creationConfigChoices(packages);
    select.value = selected;
    grid.querySelectorAll('[data-creation-config-choice]').forEach(choice => {
      const active = choice.dataset.creationConfigChoice === select.value;
      choice.classList.toggle('active', active);
      choice.setAttribute('aria-checked', String(active));
    });
  }

  window.refreshCreationConfigChoices = refreshCreationConfigChoices;

  function renderModal(imageStyles, creationConfigs) {
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
        <section class="project-profile-section" id="create-creation-config-section">
          <h4>2. 创作配置包</h4>
          <span class="project-profile-field-label">选择创作配置包</span>
          <div id="creation-config-choice-grid" class="creation-config-choice-grid" role="radiogroup" aria-label="创作配置包">
            ${creationConfigChoices(creationConfigs)}
          </div>
          <select id="input-creation-config" class="creation-config-native-select" aria-hidden="true" tabindex="-1">${creationConfigOptions(creationConfigs)}</select>
          <p id="create-creation-config-help" class="project-profile-help">${creationConfigs?.length ? '本项目会保存所选配置包的版本。' : '暂无可用创作配置包。'}</p>
        </section>
        <details class="project-profile-advanced">
          <summary>高级设置 <span>画布、图片风格与参考图</span></summary>
          <div class="project-profile-advanced-body">
        <section class="project-profile-section">
          <h4>3. 画布比例</h4>
          <div class="project-profile-mode-grid">
            ${optionCards([
              { id: 'landscape_16_9', name: '横屏 16:9' },
              { id: 'portrait_9_16', name: '竖屏 9:16' },
            ], 'canvas_profile', 'landscape_16_9')}
          </div>
          <p class="project-profile-help">创建后比例会锁定；需要更换比例时请复制项目重新生成。</p>
        </section>
        <section class="project-profile-section">
          <h4>4. 图片风格</h4>
          <div class="profile-style-grid">${styleTiles(imageStyles)}</div>
          <p class="project-profile-help">选择模板作为基础风格；本项目还可以单独上传参考图。</p>
        </section>
        <section class="project-profile-section">
          <h4>5. 本项目参考图片</h4>
          <label class="profile-upload-box" for="input-project-reference-images">
            <strong>添加 1–3 张参考图</strong>
            <span>只作用于当前项目；支持 PNG、JPG、WEBP，单张不超过 12MB。</span>
            <input id="input-project-reference-images" type="file" accept="image/*" multiple>
          </label>
          <div id="project-reference-preview" class="project-reference-preview"></div>
        </section>
          </div>
        </details>
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
    document.querySelectorAll('[data-profile-option]').forEach(card => {
      card.addEventListener('click', () => {
        activateOption(card.getAttribute('data-profile-option'), card.dataset.value);
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

    document.getElementById('btn-create-cancel')?.addEventListener('click', () => {
      document.getElementById('modal-create').style.display = 'none';
    });
    document.getElementById('btn-create-submit')?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      createProjectWithProfile().catch(error => toast(`❌ 创建失败：${error.message}`, 7000));
    }, true);
    document.getElementById('input-project-reference-images')?.addEventListener('change', event => {
      const files = Array.from(event.target.files || []).slice(0, 3);
      if (event.target.files?.length > 3) toast('最多选择 3 张参考图');
      const preview = document.getElementById('project-reference-preview');
      if (!preview) return;
      preview.replaceChildren();
      files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'project-reference-preview-item';
        const image = document.createElement('img');
        image.alt = file.name;
        image.src = URL.createObjectURL(file);
        const name = document.createElement('span');
        name.textContent = file.name;
        item.append(image, name);
        preview.append(item);
      });
    });

    const configGrid = document.getElementById('creation-config-choice-grid');
    configGrid?.addEventListener('click', event => {
      const choice = event.target.closest('[data-creation-config-choice]');
      const select = document.getElementById('input-creation-config');
      if (!choice || !select) return;
      select.value = choice.dataset.creationConfigChoice || '';
      configGrid.querySelectorAll('[data-creation-config-choice]').forEach(item => {
        const active = item === choice;
        item.classList.toggle('active', active);
        item.setAttribute('aria-checked', String(active));
      });
    });
  }

  function collectProfile() {
    return {
      version: 'project_profile_v1',
      canvas_profile: selectedOption('canvas_profile', 'landscape_16_9'),
      // Generation switches and pause points are defined by the creation package.
      automation_mode: 'auto',
      quality_gates: { ...DEFAULT_QUALITY_GATES },
      last_used_storyboard_template_id: '',
      last_used_image_style_template_id: PROFILE_STATE.selectedStyleTemplate || 'default',
      notes: 'Lightweight profile only. Step 2 owns storyboard style; Step 3 owns image style and references.',
    };
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
      const styleTemplate = PROFILE_STATE.selectedStyleTemplate || 'default';
      const creationConfig = selectedCreationConfig();
      const pendingParent = window.__pendingProjectParent || null;
      const projectRes = await apiPost('/api/projects', {
        name,
        description: desc,
        canvas_profile: profile.canvas_profile,
        image_style_template: styleTemplate,
        ...(creationConfig ? {
          config_package_id: creationConfig.id,
          config_package_version: creationConfig.version,
        } : {}),
        ...(pendingParent || {}),
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

      window.__pendingProjectParent = null;

      if (article) {
        if (button) button.textContent = '导入文章...';
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/1/import`, form);
      }
      const referenceInput = document.getElementById('input-project-reference-images');
      const referenceFiles = Array.from(referenceInput?.files || []).slice(0, 3);
      if (referenceFiles.length) {
        if (button) button.textContent = '上传参考图...';
        const form = new FormData();
        referenceFiles.forEach(file => form.append('files', file));
        await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/3/image-style/reference-images`, form);
      }
      document.getElementById('modal-create').style.display = 'none';
      toast('项目已创建。', 4500);
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
    const [imageStyles, creationConfigs] = await Promise.all([
      loadImageStyles(),
      loadCreationConfigs(),
    ]);
    renderModal(imageStyles, creationConfigs);
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
