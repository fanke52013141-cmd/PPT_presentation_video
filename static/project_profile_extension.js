(function () {
  'use strict';

  const PROFILE_STATE = {
    creationConfigs: null,
    defaultCreationConfig: null,
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

  async function loadCreationConfigs() {
    try {
      const [response, accountResponse] = await Promise.all([
        apiGet('/api/creation-configs'),
        apiGet('/api/accounts/current'),
      ]);
      const defaultConfig = accountResponse?.account?.default_creation_config;
      PROFILE_STATE.defaultCreationConfig = defaultConfig?.package_id
        ? {
            packageId: defaultConfig.package_id,
            version: Number(defaultConfig.version) || null,
          }
        : null;
      PROFILE_STATE.creationConfigs = orderCreationConfigs(
        Array.isArray(response?.packages) ? response.packages : [],
        PROFILE_STATE.defaultCreationConfig,
      );
    } catch (_) {
      // A package is optional; leaving the list empty preserves ordinary
      // project creation when the package registry is unavailable.
      PROFILE_STATE.creationConfigs = [];
      PROFILE_STATE.defaultCreationConfig = null;
    }
    return PROFILE_STATE.creationConfigs;
  }


  function optionCards(items, field, selectedId) {
    return (items || []).map(item => `
      <div class="project-profile-card-option ${item.id === selectedId ? 'active' : ''}" data-profile-option="${esc(field)}" data-value="${esc(item.id)}">
        <strong>${esc(item.name)}</strong>
        ${item.detail ? `<span>${esc(item.detail)}</span>` : ''}
      </div>
    `).join('');
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

  function orderCreationConfigs(packages, defaultConfig) {
    const defaultId = defaultConfig?.packageId;
    return [...(packages || [])].sort((left, right) => {
      if (left.id === defaultId) return -1;
      if (right.id === defaultId) return 1;
      return 0;
    });
  }

  function configVersion(item, defaultConfig) {
    if (item.id === defaultConfig?.packageId && Number.isInteger(defaultConfig?.version)) {
      return defaultConfig.version;
    }
    return Number(item.latest_version);
  }

  function creationConfigOptions(packages, defaultConfig = PROFILE_STATE.defaultCreationConfig) {
    const available = availableCreationConfigs(packages);
    if (!available.length) return '<option value="">暂无可用创作配置包</option>';
    const options = [];
    available.forEach(item => {
      const version = configVersion(item, defaultConfig);
      options.push(
        `<option value="${esc(item.id)}" data-version="${version}">${esc(item.name || '未命名配置包')} · v${version}</option>`
      );
    });
    return options.join('');
  }

  function creationConfigChoices(packages, defaultConfig = PROFILE_STATE.defaultCreationConfig) {
    const available = availableCreationConfigs(packages);
    if (!available.length) {
      return '<div class="creation-config-choice" aria-disabled="true"><strong>暂无可用创作配置包</strong><span>请先在“创作配置”中保存一套配置。</span></div>';
    }
    const choices = available.map(item => ({
      id: item.id,
      name: item.name || '未命名配置包',
      version: configVersion(item, defaultConfig),
      isDefault: item.id === defaultConfig?.packageId,
    }));
    return choices.map(item => `
      <button type="button" class="creation-config-choice${item.isDefault ? ' is-default' : ''}" data-creation-config-choice="${esc(item.id)}" role="radio" aria-checked="false">
        <span class="creation-config-choice-heading"><strong>${esc(item.name)}</strong>${item.isDefault ? '<em>当前默认</em>' : ''}</span>
        <span>v${item.version} · 提示词、模型与图片风格</span>
      </button>
    `).join('');
  }

  function refreshCreationConfigChoices(packages, { preferDefault = false } = {}) {
    const grid = document.getElementById('creation-config-choice-grid');
    const select = document.getElementById('input-creation-config');
    if (!grid || !select) return;
    const defaultConfig = PROFILE_STATE.defaultCreationConfig;
    const available = availableCreationConfigs(orderCreationConfigs(packages, defaultConfig));
    const defaultId = available.some(item => item.id === defaultConfig?.packageId)
      ? defaultConfig.packageId
      : '';
    const selected = !preferDefault && available.some(item => item.id === select.value)
      ? select.value
      : (defaultId || available[0]?.id || '');
    grid.innerHTML = creationConfigChoices(available, defaultConfig);
    select.innerHTML = creationConfigOptions(available, defaultConfig);
    select.value = selected;
    grid.querySelectorAll('[data-creation-config-choice]').forEach(choice => {
      const active = choice.dataset.creationConfigChoice === select.value;
      choice.classList.toggle('active', active);
      choice.setAttribute('aria-checked', String(active));
    });
  }

  window.refreshCreationConfigChoices = refreshCreationConfigChoices;

  function renderModal(creationConfigs) {
    const modal = document.getElementById('modal-create');
    const content = modal?.querySelector('.modal-content');
    if (!modal || !content || content.dataset.projectProfileWizard === '1') return;
    content.dataset.projectProfileWizard = '1';
    content.className = 'modal-content project-profile-modal';
    content.innerHTML = `
      <div class="project-profile-scroll">
        <h3 class="highlight-title" style="margin-bottom: .8rem;">新建视频项目</h3>
        <div id="create-running-hint" class="project-profile-running-hint" hidden></div>
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
          <p id="create-creation-config-help" class="project-profile-help">${creationConfigs?.length ? '本项目会固定所选配置包及其显示版本；模型、提示词、图片风格和参考图均以该配置包为准。' : '暂无可用创作配置包。'}</p>
        </section>
        <section class="project-profile-section" id="create-ai-mode-section">
          <h4>3. 创建方式</h4>
          <div class="project-profile-mode-grid" role="radiogroup" aria-label="创建方式">
            ${optionCards([
              { id: 'auto', name: '全自动', detail: '进入项目即自动开始并连续执行生成流程，无需手动点击。' },
              { id: 'manual', name: '手动', detail: '创建后由你按步骤编辑并触发生成。' },
            ], 'ai_mode', 'auto')}
          </div>
        </section>
        <details class="project-profile-advanced">
          <summary>画面比例</summary>
          <div class="project-profile-advanced-body">
        <section class="project-profile-section">
          <div class="project-profile-mode-grid">
            ${optionCards([
              { id: 'landscape_16_9', name: '横屏 16:9' },
              { id: 'portrait_9_16', name: '竖屏 9:16' },
            ], 'canvas_profile', 'landscape_16_9')}
          </div>
          <p class="project-profile-help">创建后比例会锁定；需要更换比例时请复制项目重新生成。</p>
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
    refreshCreationConfigChoices(creationConfigs, { preferDefault: true });
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

    document.getElementById('btn-create-cancel')?.addEventListener('click', () => {
      document.getElementById('modal-create').style.display = 'none';
    });
    document.getElementById('btn-create-submit')?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      createProjectWithProfile().catch(error => toast(`❌ 创建失败：${error.message}`, 7000));
    }, true);
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

  function collectProfile(aiMode) {
    return {
      version: 'project_profile_v1',
      canvas_profile: selectedOption('canvas_profile', 'landscape_16_9'),
      // Generation switches and pause points remain package-owned. This value
      // mirrors the project's explicit creation mode for profile consumers.
      automation_mode: aiMode === 'manual' ? 'manual_review' : 'auto',
      quality_gates: { ...DEFAULT_QUALITY_GATES },
      last_used_storyboard_template_id: '',
      notes: 'Lightweight profile only. The selected creation package owns prompts, models, image style, and reference images.',
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
      const aiMode = selectedOption('ai_mode', 'auto');
      const profile = collectProfile(aiMode);
      const creationConfig = selectedCreationConfig();
      const pendingParent = window.__pendingProjectParent || null;
      const projectRes = await apiPost('/api/projects', {
        name,
        description: desc,
        ai_mode: aiMode,
        canvas_profile: profile.canvas_profile,
        ...(creationConfig ? {
          config_package_id: creationConfig.id,
          config_package_version: creationConfig.version,
        } : {}),
        ...(pendingParent || {}),
      });
      const project = projectRes.project;
      if (!project?.id) throw new Error('项目创建成功但未返回 project.id');
      await apiPut(`/api/projects/${encodeURIComponent(project.id)}/project-profile`, { profile });

      window.__pendingProjectParent = null;

      if (article) {
        if (button) button.textContent = '导入文章...';
        const form = new FormData();
        form.append('content', article);
        await apiPost(`/api/projects/${encodeURIComponent(project.id)}/steps/1/import`, form);
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

  async function refreshRunningAutomationHint() {
    // 提示条（方案②）：打开创建弹窗时统计当前账号仍在运行的全自动任务，
    // 提前告知新任务在输出阶段会排队，避免多账号并行时互相等待的困惑。
    const hint = document.getElementById('create-running-hint');
    if (!hint) return;
    try {
      const res = await apiGet('/api/one-click-statuses');
      const items = Array.isArray(res?.items) ? res.items : [];
      const running = items.filter(item => item.status === 'running');
      if (running.length > 0) {
        const names = running.map(item => item.project_name).filter(Boolean).slice(0, 3);
        const suffix = running.length > names.length ? ' 等' : '';
        hint.textContent = `⏳ 当前有 ${running.length} 个全自动任务进行中（${names.join('、')}${suffix}）。新项目提交后会在生成与输出阶段自动排队，无需等待。`;
        hint.hidden = false;
      } else {
        hint.textContent = '';
        hint.hidden = true;
      }
    } catch {
      hint.textContent = '';
      hint.hidden = true;
    }
  }

  async function enhanceCreateModal() {
    const creationConfigs = await loadCreationConfigs();
    renderModal(creationConfigs);
    refreshCreationConfigChoices(creationConfigs, { preferDefault: true });
    // 每次打开都刷新运行中任务提示；元素在首次 renderModal 后持续存在，
    // 不受 renderModal 防重守卫影响。
    refreshRunningAutomationHint();
  }

  function boot() {
    if (!document.getElementById('modal-create')) return;
    enhanceCreateModal().catch(() => {});
    const createButton = document.getElementById('btn-create-project');
    if (createButton && !createButton.__profileConfigBound) {
      createButton.__profileConfigBound = true;
      createButton.addEventListener('click', () => enhanceCreateModal().catch(() => {}));
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
  const timer = setInterval(() => {
    if (document.getElementById('modal-create')) {
      boot();
      clearInterval(timer);
    }
  }, 500);
})();
