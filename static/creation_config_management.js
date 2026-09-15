// Reusable creation-package and model-connection management.
// Connection records contain only safe metadata. Credentials are submitted to
// the server-side credential boundary and are never rendered back into the UI.

(function () {
  'use strict';

  const state = {
    packages: [],
    connections: [],
    credentials: [],
    styleTemplates: [],
    styleTemplateDetails: new Map(),
    defaultPayload: {},
    defaultPackageId: null,
    defaultPackageVersion: null,
    currentAccountId: null,
    loading: false,
    editingPackageId: null,
    editingVersion: null,
    editingConnectionId: null,
    activeModelKind: 'text',
  };

  const PROMPT_MODULES = [
    ['article_generation', '文章生成'],
    ['storyboard', '分镜生成'],
    ['visualization', '分镜可视化'],
    ['image_generation', '图片生成'],
    ['ai_mask', 'AI Mask'],
    ['narration_annotation', '旁白'],
  ];
  const MODEL_BINDING_GROUPS = [
    ['text', '文本模型', '文章、分镜、可视化、旁白和 AI Mask', 'text'],
    ['image', '图片模型', '图片生成及需要图片理解的阶段', 'image'],
    ['tts', '语音模型', '旁白语音合成', 'tts'],
  ];
  const TEXT_BINDING_KEYS = [
    'article_generation', 'storyboard', 'visualization', 'ai_mask', 'narration_annotation',
  ];
  const DEFAULT_SUBTITLE = {
    enabled: false,
    font_key: 'lxgw_marker_gothic',
    font_size: 40,
    font_weight: 400,
    bottom: 0,
    horizontal_margin: 110,
    color: '#000000',
    highlight_color: '#000000',
    paging_window_ms: 1300,
    token_highlight: true,
    max_lines: 1,
    line_height: 1.4,
  };

  function element(id) {
    return document.getElementById(id);
  }

  function toast(message) {
    if (typeof window.showToast === 'function') window.showToast(message);
  }

  function requestError(message, error) {
    const detail = error && error.message ? `：${error.message}` : '';
    toast(`${message}${detail}`);
  }

  function connectionRevision(connection) {
    return connection && typeof connection.revision === 'object'
      ? connection.revision
      : {};
  }

  function button(label, className, onClick) {
    const control = document.createElement('button');
    control.type = 'button';
    control.className = className || 'secondary';
    control.textContent = label;
    control.style.marginTop = '0.65rem';
    control.addEventListener('click', onClick);
    return control;
  }

  function objectValue(value) {
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  }

  function clonePayload(value) {
    return JSON.parse(JSON.stringify(objectValue(value)));
  }

  function removeEmptyObject(parent, key) {
    if (parent[key] && Object.keys(parent[key]).length === 0) delete parent[key];
  }

  function setStringField(id, value) {
    const field = element(id);
    if (field) field.value = typeof value === 'string' ? value : '';
  }

  function buildStructuredEditor() {
    const promptTarget = element('creation-config-prompt-fields');
    const bindingTarget = element('creation-config-model-binding-fields');
    if (!promptTarget || !bindingTarget || promptTarget.childElementCount || bindingTarget.childElementCount) return;

    PROMPT_MODULES.forEach(([key, label]) => {
      const section = document.createElement('details');
      section.className = 'creation-config-prompt-card';
      section.open = true;
      const summary = document.createElement('summary');
      summary.className = 'creation-config-prompt-summary';
      const summaryTitle = document.createElement('strong');
      summaryTitle.textContent = label;
      const summaryHint = document.createElement('span');
      summaryHint.textContent = key === 'image_generation'
        ? '编辑创作指引；生产合同由系统锁定'
        : '编辑提示词与输出示例';
      summary.append(summaryTitle, summaryHint);
      const headingRow = document.createElement('div');
      headingRow.className = 'creation-config-prompt-heading';
      const restore = document.createElement('button');
      restore.type = 'button';
      restore.className = 'secondary creation-config-restore-prompt';
      restore.textContent = '恢复默认';
      restore.title = `将${label}的提示词恢复为系统默认值`;
      restore.addEventListener('click', () => restorePromptModule(key, label));
      headingRow.append(restore);
      const systemLabel = document.createElement('label');
      systemLabel.textContent = key === 'image_generation' ? '创作指引（可编辑）' : '系统提示词';
      const system = document.createElement('textarea');
      system.id = `creation-config-prompt-${key}-system-content`;
      system.rows = 10;
      system.placeholder = '新建配置默认已填入；留空则沿用系统默认提示词';
      system.spellcheck = false;
      systemLabel.append(system);
      const exampleLabel = document.createElement('label');
      exampleLabel.textContent = '输出示例（JSON，可选）';
      const example = document.createElement('textarea');
      example.id = `creation-config-prompt-${key}-output-example`;
      example.rows = 8;
      example.spellcheck = false;
      example.placeholder = '没有示例可以留空；如果有，请保留完整 JSON 结构，便于后续流程校验和优化';
      exampleLabel.append(example);
      section.append(summary, headingRow, systemLabel, exampleLabel);
      if (key === 'image_generation') {
        const lockedLabel = document.createElement('label');
        lockedLabel.className = 'creation-config-locked-prompt';
        lockedLabel.textContent = '固定生产合同（系统锁定）';
        const locked = document.createElement('textarea');
        locked.rows = 8;
        locked.readOnly = true;
        locked.value = [
          '1920×1080 横屏或项目选定画布比例；外围画布保持纯白。',
          '主标题只能有一个，并完整位于标题保护区；禁止页面副标题。',
          '正文、人物、图标、箭头和装饰必须位于正文安全区。',
          '仅在开启视频字幕时，底部约 14% 为字幕安全区，必须完全留空并保持纯白。',
          '独立语义元素保持清楚边界和可见白色间距。',
          '以上规则由服务端在每次生图请求末尾强制追加，配置包无法覆盖。',
        ].join('\n');
        lockedLabel.append(locked);
        section.append(lockedLabel);
      }
      promptTarget.append(section);
    });

    MODEL_BINDING_GROUPS.forEach(([key, label, help, kind]) => {
      const labelNode = document.createElement('label');
      labelNode.className = 'creation-config-binding-field';
      const title = document.createElement('span');
      title.textContent = label;
      const select = document.createElement('select');
      select.id = `creation-config-binding-${key}`;
      select.dataset.kind = kind;
      select.dataset.binding = key;
      const hint = document.createElement('small');
      hint.textContent = help;
      labelNode.append(title, select, hint);
      bindingTarget.append(labelNode);
    });
  }

  function renderConnectionSelectors() {
    MODEL_BINDING_GROUPS.forEach(([key, , , kind]) => {
      const select = element(`creation-config-binding-${key}`);
      if (!select) return;
      const selected = select.value;
      const empty = document.createElement('option');
      empty.value = '';
      empty.textContent = '不绑定连接';
      select.replaceChildren(empty);
      state.connections
        .filter(connection => connection.kind === kind && connection.state === 'active')
        .forEach(connection => {
          if (!connection.id) return;
          const option = document.createElement('option');
          option.value = connection.id;
          // The selector is a business choice, not a diagnostic screen.  A
          // connection's display name is enough here; provider/model/version
          // remain available in its editor and must not crowd the selection.
          option.textContent = connection.name || '未命名连接';
          select.append(option);
        });
      if ([...select.options].some(option => option.value === selected)) select.value = selected;
    });
  }

  function connectionValue(reference) {
    if (!reference || typeof reference !== 'object') return '';
    return typeof reference.connection_id === 'string' ? reference.connection_id : '';
  }

  function setBindingValue(key, reference) {
    const select = element(`creation-config-binding-${key}`);
    if (!select) return;
    const value = connectionValue(reference);
    if (value && ![...select.options].some(option => option.value === value)) {
      const historical = document.createElement('option');
      historical.value = value;
      historical.textContent = `当前未启用 · ${value}`;
      select.append(historical);
    }
    select.value = value;
  }

  function currentReferencePolicy() {
    return document.querySelector('input[name="creation-config-reference-policy"]:checked')?.value || 'preferred';
  }

  function updateImageStyleSummary() {
    const minimum = element('creation-config-image-style-minimum');
    if (minimum) minimum.disabled = currentReferencePolicy() !== 'required';
  }

  function updateSubtitleControls() {
    const enabled = !!element('creation-config-subtitle-enabled')?.checked;
    const section = document.querySelector('.creation-config-subtitle-option');
    if (!section) return;
    section.hidden = !enabled;
    section.querySelectorAll('select, input').forEach(control => {
      control.disabled = !enabled;
    });
  }

  function automationModeFromForm() {
    return document.querySelector('input[name="creation-config-automation-mode"]:checked')?.value === 'auto'
      ? 'auto'
      : 'manual';
  }

  function narrationAnnotationFromForm() {
    return document.querySelector('input[name="creation-config-narration-annotation"]:checked')?.value === 'true';
  }

  function maskAnnotationFromForm() {
    return document.querySelector('input[name="creation-config-mask-annotation"]:checked')?.value === 'true';
  }

  function updateAutomationControls() {
    const automatic = automationModeFromForm() === 'auto';
    const section = document.querySelector('.creation-config-auto-options');
    if (!section) return;
    section.hidden = !automatic;
    section.querySelectorAll('input').forEach(control => {
      control.disabled = !automatic;
    });
  }

  function renderImageStyleSelector() {
    const select = element('creation-config-image-style-template');
    if (!select) return;
    const selected = select.value;
    select.replaceChildren();
    selectableStyleTemplates().forEach(item => {
      if (!item?.id) return;
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${item.built_in ? '系统内置 · ' : ''}${item.name || '未命名风格'} · ${item.reference_count || 0} 张参考图`;
      option.dataset.version = String(item.version || 1);
      select.append(option);
    });
    if ([...select.options].some(option => option.value === selected)) select.value = selected;
    else if (select.options.length) select.selectedIndex = 0;
    updateImageStyleSummary();
    renderImageStyleCards();
  }

  // The legacy hand-drawn preset depends on two bundled references. It is no
  // longer offered in creation packages, so a new package starts with a
  // maintainable built-in style instead.
  function selectableStyleTemplates() {
    return state.styleTemplates.filter(item => item?.id && item.id !== 'handdrawn');
  }

  function renderImageStyleCards() {
    const target = element('creation-config-image-style-cards');
    const select = element('creation-config-image-style-template');
    if (!target || !select) return;
    target.replaceChildren();
    selectableStyleTemplates().forEach(item => {
      if (!item?.id) return;
      const detail = state.styleTemplateDetails.get(String(item.id));
      const imageInfo = detail?.references?.images?.[0];
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'creation-config-image-style-card';
      const active = item.id === select.value;
      card.classList.toggle('active', active);
      card.setAttribute('role', 'radio');
      card.setAttribute('aria-checked', String(active));
      card.title = item.summary || item.name || '图片风格';
      const preview = document.createElement('span');
      preview.className = 'creation-config-image-style-thumb';
      if (imageInfo?.url) {
        const image = document.createElement('img');
        image.src = imageInfo.url;
        image.alt = `${item.name || '图片风格'}参考图`;
        preview.append(image);
      } else {
        preview.textContent = '加载预览中';
      }
      const copy = document.createElement('span');
      copy.className = 'creation-config-image-style-copy';
      const name = document.createElement('strong');
      name.textContent = item.name || '未命名风格';
      const meta = document.createElement('small');
      const count = detail?.references?.images?.length ?? item.reference_count ?? 0;
      meta.textContent = `${item.built_in ? '系统内置 · ' : ''}${count} 张参考图`;
      copy.append(name, meta);
      card.append(preview, copy);
      card.addEventListener('click', () => {
        select.value = item.id;
        updateImageStyleSummary();
        renderImageStyleCards();
      });
      target.append(card);
    });
  }

  function setImageStyleValue(value) {
    const style = objectValue(value);
    const select = element('creation-config-image-style-template');
    let templateId = typeof style.template_id === 'string' ? style.template_id : '';
    if (templateId === 'handdrawn') templateId = '';
    if (select && templateId && ![...select.options].some(option => option.value === templateId)) {
      const historical = document.createElement('option');
      historical.value = templateId;
      historical.dataset.version = String(Number(style.version) || 1);
      historical.textContent = `历史风格资源 · ${templateId}`;
      select.append(historical);
    }
    if (select) {
      select.value = templateId;
      if (!select.value && select.options.length) select.selectedIndex = 0;
    }
    const policy = ['required', 'preferred', 'text_only'].includes(style.reference_policy)
      ? style.reference_policy
      : 'preferred';
    const radio = document.querySelector(`input[name="creation-config-reference-policy"][value="${policy}"]`);
    if (radio) radio.checked = true;
    const minimum = element('creation-config-image-style-minimum');
    if (minimum) minimum.value = String(Math.max(1, Math.min(3, Number(style.minimum_reference_images) || 1)));
    updateImageStyleSummary();
    renderImageStyleCards();
  }

  function createStyleForCreationConfig() {
    const modal = element('modal-creation-config-style');
    if (!modal) return;
    element('creation-config-style-name').value = '';
    element('creation-config-style-summary').value = '';
    element('creation-config-style-system-content').value = '';
    const files = element('creation-config-style-reference-files');
    if (files) files.value = '';
    renderCreationConfigStyleReferencePreview();
    modal.style.display = 'flex';
    window.setTimeout(() => element('creation-config-style-name')?.focus(), 0);
  }

  function closeCreationConfigStyleDialog() {
    const modal = element('modal-creation-config-style');
    if (modal) modal.style.display = 'none';
  }

  function renderCreationConfigStyleReferencePreview() {
    const target = element('creation-config-style-reference-preview');
    const input = element('creation-config-style-reference-files');
    if (!target || !input) return;
    target.replaceChildren();
    const files = Array.from(input.files || []);
    if (!files.length) {
      target.textContent = '未上传参考图；该风格会按提示词生成。';
      return;
    }
    files.slice(0, 3).forEach(file => {
      const preview = document.createElement('img');
      const objectUrl = URL.createObjectURL(file);
      preview.src = objectUrl;
      preview.alt = file.name || '风格参考图预览';
      preview.addEventListener('load', () => URL.revokeObjectURL(objectUrl), { once: true });
      target.append(preview);
    });
  }

  async function submitCreationConfigStyle() {
    if (!window.API) return;
    const name = element('creation-config-style-name')?.value.trim() || '';
    const styleSummary = element('creation-config-style-summary')?.value.trim() || '';
    const systemContent = element('creation-config-style-system-content')?.value.trim() || '';
    const files = Array.from(element('creation-config-style-reference-files')?.files || []);
    if (!name) {
      toast('请输入风格名称');
      element('creation-config-style-name')?.focus();
      return;
    }
    if (!systemContent) {
      toast('请输入图片风格提示词');
      element('creation-config-style-system-content')?.focus();
      return;
    }
    if (files.length > 3) {
      toast('最多只能上传 3 张参考图');
      return;
    }
    const submit = element('btn-creation-config-style-submit');
    if (submit) submit.disabled = true;
    try {
      const form = new FormData();
      form.append('name', name);
      form.append('style_summary', styleSummary);
      form.append('system_content', systemContent);
      files.forEach(file => form.append('files', file));
      const response = await window.API.post('/api/image-style/project-templates/with-references', form);
      const template = response?.template;
      if (!template?.id) throw new Error('风格已创建，但没有返回 ID');
      const detail = await window.API.get(`/api/image-style/project-templates/${encodeURIComponent(template.id)}`);
      state.styleTemplates = [...state.styleTemplates, template];
      state.styleTemplateDetails.set(String(template.id), detail);
      renderImageStyleSelector();
      const selector = element('creation-config-image-style-template');
      if (selector) selector.value = template.id;
      updateImageStyleSummary();
      renderImageStyleCards();
      syncStructuredFieldsToJson();
      closeCreationConfigStyleDialog();
      toast(files.length ? '新风格及参考图已创建并选用。' : '新风格已创建并选用。');
    } catch (error) {
      requestError('新建风格失败', error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function subtitleFromForm(existingValue) {
    const subtitle = { ...DEFAULT_SUBTITLE, ...objectValue(existingValue) };
    subtitle.enabled = !!element('creation-config-subtitle-enabled')?.checked;
    document.querySelectorAll('[data-creation-config-subtitle]').forEach(field => {
      const key = field.dataset.creationConfigSubtitle;
      if (!key) return;
      subtitle[key] = field.type === 'checkbox'
        ? !!field.checked
        : (field.type === 'number' ? Number(field.value) : field.value.trim());
    });
    return subtitle;
  }

  function loadSubtitleIntoForm(value) {
    const subtitle = { ...DEFAULT_SUBTITLE, ...objectValue(value) };
    const subtitleToggle = element('creation-config-subtitle-enabled');
    if (subtitleToggle) subtitleToggle.checked = subtitle.enabled !== false;
    document.querySelectorAll('[data-creation-config-subtitle]').forEach(field => {
      const key = field.dataset.creationConfigSubtitle;
      if (!key) return;
      if (field.type === 'checkbox') field.checked = subtitle[key] !== false;
      else if (subtitle[key] !== undefined && subtitle[key] !== null) field.value = String(subtitle[key]);
    });
    updateSubtitleControls();
  }

  function firstActiveConnectionReference(kind) {
    const connection = state.connections.find(item => item.kind === kind && item.state === 'active');
    return connection?.id ? { connection_id: connection.id } : null;
  }

  function applyDefaultModelBindings() {
    setBindingValue('text', firstActiveConnectionReference('text'));
    setBindingValue('image', firstActiveConnectionReference('image'));
    setBindingValue('tts', firstActiveConnectionReference('tts'));
  }

  function restorePromptModule(key, label) {
    const defaults = objectValue(objectValue(state.defaultPayload).prompts)[key];
    const module = objectValue(defaults);
    setStringField(`creation-config-prompt-${key}-system-content`, module.system_content);
    setStringField(`creation-config-prompt-${key}-output-example`, module.output_example);
    syncStructuredFieldsToJson();
    toast(`${label}已恢复默认提示词`);
  }

  function readBindingValue(key) {
    const value = element(`creation-config-binding-${key}`)?.value || '';
    return value ? { connection_id: value } : null;
  }

  function boundedSeedAudioConcurrency(value) {
    if (value === null || value === undefined || String(value).trim() === '') return 5;
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 5;
    return Math.max(1, Math.min(5, Math.round(numeric)));
  }

  function payloadFromEditor() {
    return parseCreationConfigPayload();
  }

  function syncStructuredFieldsToJson() {
    let payload;
    try {
      payload = clonePayload(payloadFromEditor());
    } catch (_) {
      payload = {};
    }
    const prompts = objectValue(payload.prompts);
    PROMPT_MODULES.forEach(([key]) => {
      const module = objectValue(prompts[key]);
      const system = element(`creation-config-prompt-${key}-system-content`)?.value.trim() || '';
      const example = element(`creation-config-prompt-${key}-output-example`)?.value.trim() || '';
      if (system) module.system_content = system;
      else delete module.system_content;
      if (example) module.output_example = example;
      else delete module.output_example;
      if (Object.keys(module).length) prompts[key] = module;
      else delete prompts[key];
    });
    if (Object.keys(prompts).length) payload.prompts = prompts;
    else delete payload.prompts;

    // Pipeline validation remains internal.  New packages do not persist a
    // second user-authored input/output contract layer.
    delete payload.step_contracts;

    const bindings = objectValue(payload.model_bindings);
    const textBinding = readBindingValue('text');
    TEXT_BINDING_KEYS.forEach(key => {
      if (textBinding) bindings[key] = textBinding;
      else delete bindings[key];
    });
    const imageBinding = readBindingValue('image');
    if (imageBinding) bindings.image_generation = imageBinding;
    else delete bindings.image_generation;
    delete bindings.tts;
    if (Object.keys(bindings).length) payload.model_bindings = bindings;
    else delete payload.model_bindings;

    const tts = objectValue(payload.tts);
    const ttsBinding = readBindingValue('tts');
    if (ttsBinding) tts.connection = ttsBinding;
    else delete tts.connection;
    const ttsConcurrency = Math.max(1, Math.min(10, Number(element('creation-config-tts-concurrency')?.value) || 10));
    tts.concurrency = ttsConcurrency;
    const seedAudioConcurrency = boundedSeedAudioConcurrency(element('creation-config-seed-audio-concurrency')?.value);
    tts.seed_audio_concurrency = seedAudioConcurrency;
    const ttsRequestsPerMinute = Math.max(1, Math.min(600, Number(element('creation-config-tts-rpm')?.value) || 10));
    tts.requests_per_minute = ttsRequestsPerMinute;
    if (Object.keys(tts).length) payload.tts = tts;
    else delete payload.tts;

    const styleSelect = element('creation-config-image-style-template');
    if (styleSelect?.value) {
      const selectedOption = styleSelect.selectedOptions?.[0];
      const policy = currentReferencePolicy();
      payload.image_style = {
        template_id: styleSelect.value,
        version: Number(selectedOption?.dataset.version) || 1,
        reference_policy: policy,
        minimum_reference_images: policy === 'text_only'
          ? 0
          : Math.max(1, Math.min(3, Number(element('creation-config-image-style-minimum')?.value) || 1)),
      };
    } else {
      delete payload.image_style;
    }

    payload.subtitle = subtitleFromForm(payload.subtitle || payload.subtitles);
    delete payload.subtitles;
    // Keep legacy ``mask`` data untouched. It remains part of imported and
    // exported configuration packages, but no longer controls new projects.
    const pauseSteps = [...document.querySelectorAll('[data-creation-config-pause]:checked')]
      .map(input => input.dataset.creationConfigPause)
      .filter(Boolean);
    const automation = objectValue(payload.automation);
    const imageConcurrency = Math.max(1, Math.min(6, Number(element('creation-config-image-concurrency')?.value) || 5));
    automation.mode = automationModeFromForm();
    automation.image_concurrency = imageConcurrency;
    automation.ai_narration_annotation = automation.mode === 'auto' && narrationAnnotationFromForm();
    automation.ai_mask_annotation = automation.mode === 'auto' && maskAnnotationFromForm();
    if (automation.mode === 'auto' && pauseSteps.length) automation.manual_pause_steps = pauseSteps;
    else delete automation.manual_pause_steps;
    if (Object.keys(automation).length) payload.automation = automation;
    else delete payload.automation;
    const outputFormats = [...document.querySelectorAll('[data-creation-config-output]:checked')]
      .map(input => input.dataset.creationConfigOutput)
      .filter(Boolean);
    payload.render = {
      acceleration: element('creation-config-render-acceleration')?.value || 'auto',
      output_formats: outputFormats.length ? outputFormats : ['video'],
    };

    const field = element('creation-config-package-payload');
    if (field) field.value = JSON.stringify(payload, null, 2);
  }

  function loadPayloadIntoStructured(payload) {
    const value = objectValue(payload);
    const prompts = objectValue(value.prompts);
    PROMPT_MODULES.forEach(([key]) => {
      const module = objectValue(prompts[key]);
      setStringField(`creation-config-prompt-${key}-system-content`, module.system_content);
      setStringField(`creation-config-prompt-${key}-output-example`, module.output_example);
    });
    const bindings = objectValue(value.model_bindings);
    setBindingValue('text', TEXT_BINDING_KEYS.map(key => bindings[key]).find(Boolean));
    setBindingValue('image', bindings.image_generation);
    const tts = objectValue(value.tts);
    setBindingValue('tts', tts.connection || bindings.tts);
    setStringField('creation-config-tts-concurrency', String(Math.max(1, Math.min(10, Number(tts.concurrency) || 10))));
    setStringField('creation-config-seed-audio-concurrency', String(boundedSeedAudioConcurrency(tts.seed_audio_concurrency)));
    setStringField('creation-config-tts-rpm', String(Math.max(1, Math.min(600, Number(tts.requests_per_minute) || 10))));
    setImageStyleValue(value.image_style);
    loadSubtitleIntoForm(value.subtitle || value.subtitles);
    const automation = objectValue(value.automation);
    const automationMode = automation.mode === 'manual' ? 'manual' : 'auto';
    const modeControl = document.querySelector(`input[name="creation-config-automation-mode"][value="${automationMode}"]`);
    if (modeControl) modeControl.checked = true;
    const annotationControl = document.querySelector(
      `input[name="creation-config-narration-annotation"][value="${automation.ai_narration_annotation === true ? 'true' : 'false'}"]`,
    );
    if (annotationControl) annotationControl.checked = true;
    const maskAnnotationControl = document.querySelector(
      `input[name="creation-config-mask-annotation"][value="${automation.ai_mask_annotation === true ? 'true' : 'false'}"]`,
    );
    if (maskAnnotationControl) maskAnnotationControl.checked = true;
    updateAutomationControls();
    setStringField('creation-config-image-concurrency', String(Math.max(1, Math.min(6, Number(automation.image_concurrency) || 5))));
    const render = objectValue(value.render);
    setStringField('creation-config-render-acceleration', render.acceleration || 'auto');
    const outputFormats = Array.isArray(render.output_formats) && render.output_formats.length
      ? new Set(render.output_formats)
      : new Set(['video']);
    document.querySelectorAll('[data-creation-config-output]').forEach(input => {
      input.checked = outputFormats.has(input.dataset.creationConfigOutput);
    });
    const pauseSteps = automation.manual_pause_steps;
    const pauses = Array.isArray(pauseSteps) ? new Set(pauseSteps) : new Set();
    document.querySelectorAll('[data-creation-config-pause]').forEach(input => {
      input.checked = pauses.has(input.dataset.creationConfigPause);
    });
  }

  function loadJsonIntoStructured() {
    let payload;
    try {
      payload = parseCreationConfigPayload();
    } catch (error) {
      requestError('无法载入 JSON', error);
      return;
    }
    loadPayloadIntoStructured(payload);
    syncStructuredFieldsToJson();
    toast('已从 JSON 更新结构化表单');
  }

  function resetCreationConfigEditor() {
    state.editingPackageId = null;
    state.editingVersion = null;
    const name = element('creation-config-package-name');
    const payload = element('creation-config-package-payload');
    if (name) { name.value = ''; name.readOnly = false; }
    const defaultPayload = clonePayload(state.defaultPayload);
    if (payload) payload.value = JSON.stringify(defaultPayload, null, 2);
    loadPayloadIntoStructured(defaultPayload);
    // A fresh package is immediately runnable when reusable connections exist.
    // Users can still switch any of these three bindings independently.
    applyDefaultModelBindings();
    syncStructuredFieldsToJson();
    const submit = element('btn-create-creation-config');
    if (submit) submit.textContent = '保存当前修改';
    const prepareSaveAs = element('btn-prepare-save-creation-config-as');
    if (prepareSaveAs) prepareSaveAs.hidden = false;
    const cancel = element('btn-cancel-creation-config-edit');
    if (cancel) { cancel.hidden = false; cancel.textContent = '放弃修改'; }
    const status = element('creation-config-editing-status');
    if (status) { status.hidden = true; status.textContent = ''; }
  }

  function renderPackages() {
    const target = element('creation-config-package-list');
    if (!target) return;
    target.replaceChildren();
    if (!state.packages.length) {
      const empty = document.createElement('p');
      empty.className = 'config-editor-note';
      empty.textContent = '暂无创作配置包。';
      target.append(empty);
      return;
    }
    const createPackageCard = packageItem => {
      const isDefault = packageItem.id === state.defaultPackageId;
      const item = document.createElement('article');
      item.className = 'creation-config-package-card';
      const heading = document.createElement('div');
      heading.className = 'creation-config-package-card-heading';
      const title = document.createElement('strong');
      title.textContent = packageItem.name || '未命名配置包';
      heading.append(title);
      const actions = document.createElement('div');
      actions.className = 'creation-config-package-card-actions';
      actions.append(
        button('编辑', 'secondary', () => editPackage(packageItem)),
        button('复制', 'secondary', () => copyPackage(packageItem)),
        button('删除', 'danger', () => deletePackage(packageItem, { isDefault })),
      );
      item.append(heading, actions);
      return item;
    };
    const grid = document.createElement('div');
    grid.className = 'creation-config-package-grid';
    state.packages.forEach(packageItem => grid.append(createPackageCard(packageItem)));
    target.append(grid);
  }

  async function setDefaultPackage(packageItem) {
    if (!packageItem?.id || !state.currentAccountId) {
      toast('无法识别当前账号，请刷新后重试');
      return;
    }
    try {
      await window.API.put(`/api/accounts/${encodeURIComponent(state.currentAccountId)}/default-config`, {
        package_id: packageItem.id,
        version: null,
      });
      toast(`已将“${packageItem.name || '此配置包'}”设为当前账号默认配置`);
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
    } catch (error) {
      requestError('设置默认创作配置失败', error);
    }
  }

  function renderConnections() {
    const target = element('model-library-list');
    if (!target) return;
    target.replaceChildren();
    const kind = state.activeModelKind;
    const labels = { text: '文本模型', image: '图片模型', tts: '语音模型' };
    const connections = state.connections.filter(connection => connection.kind === kind);
    if (!connections.length) {
      const empty = document.createElement('p');
      empty.className = 'config-editor-note';
      empty.textContent = `暂无${labels[kind]}。在下方填写一次，即可在创作配置中关联使用。`;
      target.append(empty);
      return;
    }
    connections.forEach(connection => {
      const revision = connectionRevision(connection);
      const item = document.createElement('article');
      item.classList.add('model-library-card');
      const heading = document.createElement('div');
      heading.className = 'model-library-card-heading';
      const title = document.createElement('strong');
      title.textContent = connection.name || '未命名模型';
      heading.append(title);
      const actions = document.createElement('div');
      actions.className = 'model-library-card-actions';
      actions.append(button('编辑', 'secondary', () => editModelConnection(connection)));
      actions.append(button('删除', 'danger', () => deleteModelConnection(connection)));
      item.append(heading, actions);
      target.append(item);
    });
  }

  function renderCredentials() {
    // API keys and provider tokens are deliberately not a separate user-facing
    // concept. They are stored safely behind each model after the user saves it.
  }

  const MODEL_KIND_COPY = {
    text: {
      title: '新增文本模型',
      description: '适用于文章、分镜、可视化、旁白标注和 AI Mask。',
      action: '另存为文本模型模板',
      name: '例如：豆包写作模型',
      model: '例如：doubao-seed-2-1-turbo-260628',
    },
    image: {
      title: '新增图片模型',
      description: '适用于整页图片生成；支持 OpenAI 兼容接口或 ToAPIs 异步图片中转。',
      action: '另存为图片模型模板',
      name: '例如：GPT Image 图片模型',
      model: '例如：gpt-image-2',
    },
    tts: {
      title: '新增语音模型',
      description: '支持 MiniMax、豆包音频生成 1.0 参考音频生成，以及本地 ComfyUI / IndexTTS。',
      action: '另存为语音模型模板',
      name: '例如：自然讲解语音',
      model: '',
    },
  };

  const OPENAI_COMPATIBLE_PRESETS = {
    openai: { endpoint: 'https://api.openai.com/v1', model: '' },
    openrouter: { endpoint: 'https://openrouter.ai/api/v1', model: '' },
    newapi: { endpoint: '', model: '' },
    litellm: { endpoint: 'http://localhost:4000/v1', model: '' },
    toapis: { endpoint: 'https://toapis.cn', model: 'gpt-image-2-vip' },
    custom: { endpoint: '', model: '' },
  };

  function modelProviderLabel(provider) {
    const labels = {
      openai_compatible: 'OpenAI 兼容接口',
      toapis: 'ToAPIs',
      minimax: 'MiniMax',
      volcengine_seed_audio: '豆包音频生成 1.0',
      comfyui_tts: 'ComfyUI / IndexTTS',
    };
    return labels[provider] || provider || '未指定服务';
  }

  function setHidden(id, hidden) {
    const field = element(id);
    if (field) field.hidden = hidden;
  }

  function currentTtsProvider() {
    return element('model-form-tts-provider')?.value || 'minimax';
  }

  function updateModelProviderPanels() {
    const isTts = state.activeModelKind === 'tts';
    const isComfy = isTts && currentTtsProvider() === 'comfyui_tts';
    const isSeedAudio = isTts && currentTtsProvider() === 'volcengine_seed_audio';
    setHidden('model-form-minimax', !isTts || isComfy || isSeedAudio);
    setHidden('model-form-comfyui', !isComfy);
    setHidden('model-form-seed-audio', !isSeedAudio);
    if (isComfy) refreshComfyUiWorkflowStatus();
    const isToApis = state.activeModelKind === 'image' && element('model-form-protocol')?.value === 'toapis';
    setHidden('model-form-toapis-resolution-row', !isToApis);
    setHidden('model-form-toapis-quality-row', !isToApis);
  }

  function updateModelSetupForm() {
    const kind = state.activeModelKind;
    const copy = MODEL_KIND_COPY[kind];
    document.querySelectorAll('[data-model-kind]').forEach(tab => {
      const active = tab.dataset.modelKind === kind;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const title = element('model-setup-title');
    const description = element('model-setup-description');
    const action = element('btn-save-model');
    const editing = state.connections.find(item => item.id === state.editingConnectionId);
    const isEditing = !!editing && editing.kind === kind;
    if (title) title.textContent = isEditing ? `编辑${{ text: '文本', image: '图片', tts: '语音' }[kind]}模型` : copy.title;
    if (description) description.textContent = copy.description;
    if (action) action.textContent = isEditing ? '保存修改' : copy.action;
    const name = element('model-form-name');
    const model = element('model-form-model');
    if (name) name.placeholder = copy.name;
    if (model) model.placeholder = copy.model;
    const isTts = kind === 'tts';
    setHidden('model-form-protocol-row', isTts);
    setHidden('model-form-endpoint-row', isTts);
    setHidden('model-form-api-key-row', isTts);
    setHidden('model-form-model-row', isTts);
    setHidden('model-form-text-context-window-row', kind !== 'text');
    setHidden('model-form-text-max-tokens-row', kind !== 'text');
    setHidden('model-form-text-temperature-row', kind !== 'text');
    setHidden('model-form-image-size-row', kind !== 'image');
    setHidden('model-form-image-reference-row', kind !== 'image');
    setHidden('model-form-image-reference-count-row', kind !== 'image');
    setHidden('model-form-tts-provider-row', !isTts);
    const editingStatus = element('model-setup-editing-status');
    if (editingStatus) {
      editingStatus.hidden = !isEditing;
      editingStatus.textContent = isEditing
        ? `正在编辑“${editing.name || '未命名模型'}”；保存会直接更新当前配置。密钥已保存时可留空不改。`
        : '';
    }
    const cancel = element('btn-cancel-model-edit');
    if (cancel) cancel.hidden = !isEditing;
    updateModelProviderPanels();
    renderConnections();
  }

  function selectModelKind(kind) {
    if (!MODEL_KIND_COPY[kind]) return;
    state.activeModelKind = kind;
    if (state.editingConnectionId) clearModelForm();
    state.editingConnectionId = null;
    updateModelSetupForm();
  }

  function applyOpenAiCompatiblePreset() {
    const protocol = element('model-form-protocol')?.value;
    const preset = OPENAI_COMPATIBLE_PRESETS[protocol] || OPENAI_COMPATIBLE_PRESETS.custom;
    const endpoint = element('model-form-endpoint');
    const model = element('model-form-model');
    if (endpoint && preset.endpoint) endpoint.value = preset.endpoint;
    if (model && preset.model) model.value = preset.model;
    if (protocol === 'toapis') {
      setStringField('model-form-image-size', '16:9');
      setStringField('model-form-toapis-resolution', '1k');
      setStringField('model-form-toapis-quality', 'low');
    }
    updateModelProviderPanels();
  }

  async function refreshCreationConfigManagement() {
    if (state.loading || !window.API) return;
    state.loading = true;
    const statuses = [element('model-management-status')].filter(Boolean);
    statuses.forEach(status => { status.textContent = ''; });
    try {
      const [packagesResponse, connectionsResponse, credentialsResponse, defaultsResponse, accountResponse, stylesResponse] = await Promise.all([
        window.API.get('/api/creation-configs'),
        window.API.get('/api/model-connections'),
        window.API.get('/api/credentials'),
        window.API.get('/api/creation-configs/default-payload'),
        window.API.get('/api/accounts/current'),
        window.API.get('/api/image-style/project-templates'),
      ]);
      state.packages = Array.isArray(packagesResponse?.packages) ? packagesResponse.packages : [];
      state.connections = Array.isArray(connectionsResponse?.connections) ? connectionsResponse.connections : [];
      state.credentials = Array.isArray(credentialsResponse?.credentials) ? credentialsResponse.credentials : [];
      state.defaultPayload = objectValue(defaultsResponse?.payload);
      state.currentAccountId = typeof accountResponse?.account?.id === 'string'
        ? accountResponse.account.id
        : null;
      state.defaultPackageId = typeof accountResponse?.account?.default_creation_config?.package_id === 'string'
        ? accountResponse.account.default_creation_config.package_id
        : null;
      state.defaultPackageVersion = Number.isInteger(Number(accountResponse?.account?.default_creation_config?.version))
        ? Number(accountResponse.account.default_creation_config.version)
        : null;
      state.styleTemplates = Array.isArray(stylesResponse?.templates) ? stylesResponse.templates : [];
      state.styleTemplateDetails = new Map();
      await Promise.all(state.styleTemplates.map(async item => {
        if (!item?.id) return;
        try {
          const detail = await window.API.get(`/api/image-style/project-templates/${encodeURIComponent(item.id)}`);
          state.styleTemplateDetails.set(String(item.id), detail);
        } catch (_) {
          // A preview failure must not prevent selecting a valid style package.
        }
      }));
      buildStructuredEditor();
      renderConnectionSelectors();
      renderImageStyleSelector();
      renderPackages();
      renderConnections();
      renderCredentials();
      if (!state.editingPackageId && !element('creation-config-package-name')?.value.trim()) {
        const defaultPackage = state.packages.find(item => item.id === state.defaultPackageId);
        if (defaultPackage) await editPackage(defaultPackage);
        else resetCreationConfigEditor();
      }
      // The management screen communicates state through its lists and
      // controls; no redundant aggregate status banner is shown.
      statuses.forEach(status => { status.textContent = ''; });
    } catch (error) {
      statuses.forEach(status => { status.textContent = '加载失败，请检查服务状态后重试。'; });
      requestError('无法加载创作配置管理数据', error);
    } finally {
      state.loading = false;
    }
  }

  async function copyPackage(packageItem) {
    const fallbackName = `${packageItem.name || '创作配置'} 副本`;
    const name = window.prompt('输入复制后的配置包名称', fallbackName);
    if (name === null) return;
    if (!name.trim()) {
      toast('请输入配置包名称');
      return;
    }
    try {
      await window.API.post(`/api/creation-configs/${encodeURIComponent(packageItem.id)}/copy`, {
        name: name.trim(),
      });
      toast('已复制创作配置包');
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
    } catch (error) {
      requestError('复制配置包失败', error);
    }
  }

  async function editPackage(packageItem) {
    if (!packageItem?.id) return;
    try {
      const response = await window.API.get(`/api/creation-configs/${encodeURIComponent(packageItem.id)}`);
      const current = response?.package;
      const versions = Array.isArray(current?.versions) ? current.versions : [];
      const version = versions.find(item => Number(item.version) === Number(current.latest_version)) || versions.at(-1);
      if (!current || !version || !objectValue(version.payload)) {
        throw new Error('未找到可编辑的创作配置');
      }
      state.editingPackageId = current.id;
      state.editingVersion = Number(version.version);
      const name = element('creation-config-package-name');
      const payload = element('creation-config-package-payload');
      if (name) { name.value = current.name || ''; name.readOnly = false; }
      if (payload) payload.value = JSON.stringify(version.payload, null, 2);
      renderConnectionSelectors();
      loadPayloadIntoStructured(version.payload);
      const submit = element('btn-create-creation-config');
      if (submit) submit.textContent = '保存当前修改';
      const status = element('creation-config-editing-status');
      if (status) {
        status.hidden = false;
        status.textContent = '保存后，所有引用此创作设置的项目都会使用当前配置。';
      }
      const prepareSaveAs = element('btn-prepare-save-creation-config-as');
      if (prepareSaveAs) prepareSaveAs.hidden = false;
      const cancel = element('btn-cancel-creation-config-edit');
      if (cancel) { cancel.hidden = false; cancel.textContent = '放弃修改'; }
      element('creation-config-package-name')?.focus();
    } catch (error) {
      requestError('加载配置包失败', error);
    }
  }

  function parseCreationConfigPayload() {
    const field = element('creation-config-package-payload');
    const raw = field ? field.value.trim() : '';
    if (!raw) return {};
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_) {
      throw new Error('配置内容必须是有效 JSON 对象');
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('配置内容必须是 JSON 对象');
    }
    return parsed;
  }

  async function createCreationConfig() {
    const name = element('creation-config-package-name')?.value.trim() || '';
    if (!name) {
      toast('请输入创作配置包名称');
      return;
    }
    let payload;
    try {
      syncStructuredFieldsToJson();
      payload = parseCreationConfigPayload();
    } catch (error) {
      requestError('无法创建配置包', error);
      return;
    }
    const submit = element('btn-create-creation-config');
    if (submit) submit.disabled = true;
    try {
      if (state.editingPackageId) {
        await window.API.put(`/api/creation-configs/${encodeURIComponent(state.editingPackageId)}`, { name, payload });
        toast('当前创作配置已保存');
      } else {
        await window.API.post('/api/creation-configs', { name, payload });
        toast('创作配置包已创建');
      }
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
      resetCreationConfigEditor();
    } catch (error) {
      requestError(state.editingPackageId ? '保存当前配置失败' : '创建配置包失败', error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function discardCreationConfigChanges() {
    const current = state.packages.find(item => item.id === state.editingPackageId);
    if (current) {
      await editPackage(current);
      toast('已放弃未保存的修改');
      return;
    }
    resetCreationConfigEditor();
  }

  async function saveCreationConfigAs() {
    const name = element('creation-config-package-name')?.value.trim() || '';
    if (!name) {
      toast('请输入当前配置包名称');
      return;
    }
    let payload;
    try {
      syncStructuredFieldsToJson();
      payload = parseCreationConfigPayload();
    } catch (error) {
      requestError('无法另存配置', error);
      return;
    }
    const saveAs = element('btn-prepare-save-creation-config-as');
    if (saveAs) saveAs.disabled = true;
    try {
      await window.API.post('/api/creation-configs', { name, payload });
      toast('已按当前名称另存为新配置包');
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
      const created = state.packages.find(item => item.name === name);
      if (created) await editPackage(created);
      else resetCreationConfigEditor();
    } catch (error) {
      requestError('另存为新配置失败', error);
    } finally {
      if (saveAs) saveAs.disabled = false;
    }
  }

  async function archivePackage(packageItem) {
    const confirmed = window.confirm(`归档“${packageItem.name || '此配置包'}”后将不能用于新建项目，是否继续？`);
    if (!confirmed) return;
    try {
      await window.API.put(`/api/creation-configs/${encodeURIComponent(packageItem.id)}/archive`, { archived: true });
      toast('已归档创作配置包');
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
    } catch (error) {
      requestError('归档配置包失败', error);
    }
  }

  async function deletePackage(packageItem, { isDefault = false } = {}) {
    if (!packageItem?.id) return;
    const name = packageItem.name || '此创作包';
    const defaultNotice = isDefault
      ? '\n\n这是当前默认创作包。删除后会自动清除默认设置；你之后可以选择其他创作包作为默认。'
      : '';
    const message = `删除创作包“${name}”？\n\n删除后，它将不再用于新项目；已经创建的项目保留自己的配置快照，不受影响。${defaultNotice}`;
    const performDelete = async () => {
      try {
        const result = await window.API.delete(`/api/creation-configs/${encodeURIComponent(packageItem.id)}`);
        if (state.editingPackageId === packageItem.id) resetCreationConfigEditor();
        toast(result?.default_cleared
          ? '已删除默认创作包并清除默认设置；历史项目不受影响'
          : '已删除创作包；历史项目不受影响');
        await refreshCreationConfigManagement();
        if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
      } catch (error) {
        requestError('删除创作包失败', error);
      }
    };
    if (typeof window.showCustomConfirm === 'function') {
      window.showCustomConfirm('删除创作包', message, performDelete);
    } else {
      // The shared modal is loaded before this module in production. This
      // fallback only protects non-production fixture pages.
      if (window.confirm(message)) await performDelete();
    }
  }

  async function deleteModelConnection(connection) {
    if (!connection?.id) return;
    const name = connection.name || '此模型';
    const message = `删除模型“${name}”？\n\n删除后，它将从新建和绑定列表中移除，不能再被新的创作包关联。已使用它的创作包与历史项目会保留内部历史记录，不会中断。`;
    const performDelete = async () => {
      const status = element('model-management-status');
      if (status) status.textContent = '';
      try {
        const result = await window.API.delete(`/api/model-connections/${encodeURIComponent(connection.id)}`);
        if (state.editingConnectionId === connection.id) cancelModelEdit();
        toast(result?.retained_for_history
          ? '已删除模型；历史创作包与项目会保留内部记录'
          : '已删除模型；已有项目的配置快照不受影响');
        await refreshCreationConfigManagement();
      } catch (error) {
        requestError('删除模型失败', error);
      }
    };
    if (typeof window.showCustomConfirm === 'function') {
      window.showCustomConfirm('删除模型', message, performDelete);
    } else if (window.confirm(message)) {
      await performDelete();
    }
  }

  async function saveApiSecret(provider, label, apiKey) {
    const response = await window.API.post('/api/credentials', {
      provider,
      label,
      secret_values: { api_key: apiKey },
    });
    const reference = response?.credential_ref || response?.credential?.credential_ref;
    if (!reference || typeof reference !== 'string') {
      throw new Error('API 密钥已保存，但未能关联到模型');
    }
    return reference;
  }

  function clearModelForm() {
    ['model-form-name', 'model-form-endpoint', 'model-form-api-key', 'model-form-model', 'model-form-image-size', 'model-form-minimax-token', 'model-form-minimax-voice-id', 'model-form-text-context-window', 'model-form-text-max-tokens', 'model-form-text-temperature']
      .forEach(id => { const field = element(id); if (field) field.value = ''; });
    setStringField('model-form-protocol', 'custom');
    setStringField('model-form-image-size', '1920x1080');
    const supportsReferences = element('model-form-image-supports-references');
    if (supportsReferences) supportsReferences.checked = true;
    const maxReferences = element('model-form-image-max-references');
    if (maxReferences) maxReferences.value = '3';
    setStringField('model-form-toapis-resolution', '1k');
    setStringField('model-form-toapis-quality', 'low');
    setStringField('model-form-minimax-endpoint', 'https://api.minimaxi.com/v1/t2a_async_v2');
    setStringField('model-form-minimax-model', 'speech-2.8-hd');
    setStringField('model-form-minimax-speed', '1');
    setStringField('model-form-minimax-volume', '1');
    setStringField('model-form-minimax-pitch', '0');
    setStringField('model-form-comfyui-endpoint', 'http://127.0.0.1:8188');
    setStringField('model-form-seed-audio-endpoint', 'https://openspeech.bytedance.com/api/v3/tts/create');
    setStringField('model-form-seed-audio-model', 'seed-audio-1.0');
    setStringField('model-form-seed-audio-speed', '1');
    setStringField('model-form-seed-audio-volume', '1');
    setStringField('model-form-seed-audio-pitch', '0');
    setStringField('model-form-seed-audio-prompt-prefix', '参考此音频中的人物音色。一个人在做口播短视频，内容如下：');
    const genericSecret = element('model-form-api-key');
    const minimaxSecret = element('model-form-minimax-token');
    if (genericSecret) genericSecret.placeholder = '保存后不会再次显示';
    if (minimaxSecret) minimaxSecret.placeholder = '保存后不会再次显示';
  }

  function setNumberField(id, value) {
    const field = element(id);
    if (!field) return;
    field.value = Number.isFinite(Number(value)) ? String(value) : '';
  }

  function readOptionalNumber(id, min, max, label) {
    const raw = element(id)?.value.trim() || '';
    if (!raw) return undefined;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < min || value > max) {
      throw new Error(`${label}应在 ${min} 到 ${max} 之间`);
    }
    return value;
  }

  function editModelConnection(connection) {
    if (!connection?.id) return;
    const revision = connectionRevision(connection);
    const publicConfig = objectValue(revision.public_config);
    state.activeModelKind = connection.kind;
    state.editingConnectionId = connection.id;
    clearModelForm();
    setStringField('model-form-name', connection.name);
    setStringField('model-form-protocol', publicConfig.preset || 'custom');
    setStringField('model-form-endpoint', revision.endpoint);
    setStringField('model-form-model', revision.model);
    setNumberField('model-form-text-context-window', publicConfig.context_window_tokens);
    setNumberField('model-form-text-max-tokens', publicConfig.max_tokens);
    setNumberField('model-form-text-temperature', publicConfig.temperature);
    setStringField('model-form-image-size', publicConfig.image_size);
    const supportsReferences = element('model-form-image-supports-references');
    if (supportsReferences) supportsReferences.checked = publicConfig.supports_reference_images !== false;
    setNumberField('model-form-image-max-references', publicConfig.max_reference_images || 3);
    setStringField('model-form-toapis-resolution', publicConfig.toapis_resolution || '1k');
    setStringField('model-form-toapis-quality', publicConfig.toapis_quality || 'low');
    if (connection.kind === 'tts') {
      setStringField('model-form-tts-provider', revision.provider || 'minimax');
      setStringField('model-form-minimax-endpoint', revision.endpoint || 'https://api.minimaxi.com/v1/t2a_async_v2');
      setStringField('model-form-minimax-model', revision.model || 'speech-2.8-hd');
      setStringField('model-form-minimax-voice-id', publicConfig.voice_id);
      setNumberField('model-form-minimax-speed', publicConfig.speed ?? 1);
      setNumberField('model-form-minimax-volume', publicConfig.volume ?? 1);
      setNumberField('model-form-minimax-pitch', publicConfig.pitch ?? 0);
      setStringField('model-form-comfyui-endpoint', revision.endpoint || 'http://127.0.0.1:8188');
      setStringField('model-form-seed-audio-endpoint', revision.endpoint || 'https://openspeech.bytedance.com/api/v3/tts/create');
      setStringField('model-form-seed-audio-model', revision.model || 'seed-audio-1.0');
      setNumberField('model-form-seed-audio-speed', publicConfig.speed ?? 1);
      setNumberField('model-form-seed-audio-volume', publicConfig.volume ?? 1);
      setNumberField('model-form-seed-audio-pitch', publicConfig.pitch ?? 0);
      try {
        const providerExtra = JSON.parse(String(publicConfig.provider_extra || '{}'));
        const savedPrefix = String(providerExtra.seed_audio_prompt_prefix || '').trim();
        setStringField(
          'model-form-seed-audio-prompt-prefix',
          !savedPrefix || savedPrefix === '参考上传的音频作为人物音色。一个人在做口播短视频，内容如下：'
            ? '参考此音频中的人物音色。一个人在做口播短视频，内容如下：'
            : savedPrefix,
        );
      } catch (_) {
        setStringField('model-form-seed-audio-prompt-prefix', '参考此音频中的人物音色。一个人在做口播短视频，内容如下：');
      }
    }
    const secretField = connection.kind === 'tts' && revision.provider === 'minimax'
      ? element('model-form-minimax-token')
      : connection.kind === 'tts' && revision.provider === 'volcengine_seed_audio'
        ? element('model-form-seed-audio-key')
        : element('model-form-api-key');
    if (secretField && revision.credential_configured) secretField.placeholder = '密钥已保存；留空则不修改';
    updateModelSetupForm();
    element('model-form-name')?.focus();
  }

  function cancelModelEdit() {
    state.editingConnectionId = null;
    clearModelForm();
    updateModelSetupForm();
  }

  async function saveModel() {
    const kind = state.activeModelKind;
    const editingConnection = state.connections.find(item => item.id === state.editingConnectionId);
    const isEditing = !!editingConnection && editingConnection.kind === kind;
    const name = element('model-form-name')?.value.trim() || '';
    if (!name) {
      toast('请先填写显示名称');
      return;
    }
    let provider = isEditing
      ? (editingConnection?.revision?.provider || 'openai_compatible')
      : 'openai_compatible';
    let model = '';
    let endpoint = '';
    let apiKey = '';
    let publicConfig = isEditing ? clonePayload(editingConnection?.revision?.public_config) : {};
    if (kind === 'tts') {
      provider = currentTtsProvider();
      if (provider === 'minimax') {
        endpoint = element('model-form-minimax-endpoint')?.value.trim() || 'https://api.minimaxi.com/v1/t2a_async_v2';
        apiKey = element('model-form-minimax-token')?.value.trim() || '';
        model = element('model-form-minimax-model')?.value.trim() || 'speech-2.8-hd';
        const voiceId = element('model-form-minimax-voice-id')?.value.trim() || '';
        if ((!apiKey && !(isEditing && editingConnection?.revision?.credential_configured)) || !voiceId) {
          toast(isEditing ? 'MiniMax 需要保留已保存的 Token 或填写新的 Token，并填写音色 ID' : 'MiniMax 需要填写 API Token 和音色 ID');
          return;
        }
        publicConfig = {
          ...publicConfig,
          voice_id: voiceId,
          speed: readOptionalNumber('model-form-minimax-speed', 0.5, 2, '语速') ?? 1,
          volume: readOptionalNumber('model-form-minimax-volume', 0, 10, '音量') ?? 1,
          pitch: readOptionalNumber('model-form-minimax-pitch', -12, 12, '音调') ?? 0,
        };
      } else if (provider === 'volcengine_seed_audio') {
        endpoint = element('model-form-seed-audio-endpoint')?.value.trim() || 'https://openspeech.bytedance.com/api/v3/tts/create';
        apiKey = element('model-form-seed-audio-key')?.value.trim() || '';
        model = 'seed-audio-1.0';
        if (!apiKey && !(isEditing && editingConnection?.revision?.credential_configured)) {
          toast('豆包音频生成 1.0 需要填写或保留已保存的 API Key');
          return;
        }
        const referenceAudio = element('model-form-seed-audio-reference')?.files?.[0];
        if (!referenceAudio && !publicConfig.clone_voice_id) {
          toast('豆包音频生成 1.0 需要先上传一条参考音频');
          return;
        }
        publicConfig = {
          ...publicConfig,
          speed: readOptionalNumber('model-form-seed-audio-speed', 0.5, 2, '语速') ?? 1,
          volume: readOptionalNumber('model-form-seed-audio-volume', 0.5, 2, '音量') ?? 1,
          pitch: readOptionalNumber('model-form-seed-audio-pitch', -12, 12, '音调') ?? 0,
          provider_extra: JSON.stringify({
            seed_audio_style_instruction: element('model-form-seed-audio-prompt-prefix')?.value.trim()
              || '参考此音频中的人物音色。一个人在做口播短视频，内容如下：',
          }),
        };
      } else {
        endpoint = element('model-form-comfyui-endpoint')?.value.trim() || 'http://127.0.0.1:8188';
        model = 'IndexTTS-2.5';
        const referenceAudio = element('model-form-comfyui-reference')?.files?.[0];
        if (!referenceAudio && !publicConfig.clone_voice_id) {
          toast('ComfyUI / IndexTTS 需要先上传一条参考音频');
          return;
        }
      }
    } else {
      endpoint = element('model-form-endpoint')?.value.trim() || '';
      apiKey = element('model-form-api-key')?.value.trim() || '';
      model = element('model-form-model')?.value.trim() || '';
      if (!endpoint || (!apiKey && !(isEditing && editingConnection?.revision?.credential_configured)) || !model) {
        toast(isEditing ? '请填写接口地址和模型 ID；密钥已保存时可以留空不改' : '请填写接口地址、API 密钥和模型 ID');
        return;
      }
      publicConfig = {
        ...publicConfig,
        protocol: element('model-form-protocol')?.value === 'toapis' ? 'toapis' : 'openai_compatible',
        preset: element('model-form-protocol')?.value || 'custom',
      };
      if (kind === 'text') {
        const contextWindow = readOptionalNumber('model-form-text-context-window', 1024, 2000000, '上下文窗口');
        const maxTokens = readOptionalNumber('model-form-text-max-tokens', 256, 64000, '单次最大输出');
        const temperature = readOptionalNumber('model-form-text-temperature', 0, 2, '温度');
        if (contextWindow !== undefined) publicConfig.context_window_tokens = Math.round(contextWindow);
        if (maxTokens !== undefined) publicConfig.max_tokens = Math.round(maxTokens);
        if (temperature !== undefined) publicConfig.temperature = temperature;
      }
      if (kind === 'image') {
        const size = element('model-form-image-size')?.value.trim() || '';
        if (size) publicConfig.image_size = size;
        publicConfig.supports_reference_images = !!element('model-form-image-supports-references')?.checked;
        publicConfig.max_reference_images = Math.max(
          1,
          Math.min(6, Number(element('model-form-image-max-references')?.value) || 3),
        );
        if (publicConfig.preset === 'toapis') {
          provider = 'toapis';
          publicConfig.toapis_resolution = element('model-form-toapis-resolution')?.value || '1k';
          publicConfig.toapis_quality = element('model-form-toapis-quality')?.value || 'low';
        }
      }
    }
    const submit = element('btn-save-model');
    if (submit) submit.disabled = true;
    try {
      const credentialRef = apiKey ? await saveApiSecret(provider, `${name} API 密钥`, apiKey) : null;
      const payload = { name, provider, model, endpoint: endpoint || null, public_config: publicConfig };
      if (!isEditing) payload.kind = kind;
      if (credentialRef) payload.credential_ref = credentialRef;
      const saved = isEditing
        ? await window.API.put(`/api/model-connections/${encodeURIComponent(editingConnection.id)}`, payload)
        : await window.API.post('/api/model-connections', payload);
      if (provider === 'volcengine_seed_audio' || provider === 'comfyui_tts') {
        const reference = provider === 'comfyui_tts'
          ? element('model-form-comfyui-reference')?.files?.[0]
          : element('model-form-seed-audio-reference')?.files?.[0];
        if (reference) {
          const form = new FormData();
          form.append('file', reference);
          await window.API.post(`/api/model-connections/${encodeURIComponent(saved.id)}/reference-audio`, form);
        }
      }
      state.editingConnectionId = null;
      clearModelForm();
      toast(isEditing ? '模型修改已保存' : `${MODEL_KIND_COPY[kind].title.replace('新增', '')}模板已保存`);
      await refreshCreationConfigManagement();
      updateModelSetupForm();
    } catch (error) {
      requestError('保存模型失败', error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function refreshComfyUiWorkflowStatus() {
    const status = element('model-form-comfyui-workflow-status');
    if (!status || !window.API) return;
    try {
      const result = await window.API.get('/api/settings/comfyui-tts-workflow');
      status.textContent = result?.exists ? '已导入工作流，可直接使用。' : '尚未导入工作流。';
    } catch (_) {
      status.textContent = '无法读取工作流状态。';
    }
  }

  async function importComfyUiWorkflow() {
    const input = element('model-form-comfyui-workflow-file');
    const status = element('model-form-comfyui-workflow-status');
    const file = input?.files?.[0];
    if (!file) {
      if (input) input.click();
      return;
    }
    const form = new FormData();
    form.append('file', file);
    try {
      const result = await window.API.post('/api/settings/comfyui-tts-workflow', form);
      if (status) status.textContent = `已导入 ${result?.nodes || 0} 个节点；该连接将沿用此工作流。`;
      toast('ComfyUI 工作流已导入');
    } catch (error) {
      requestError('ComfyUI 工作流导入失败', error);
    } finally {
      if (input) input.value = '';
    }
  }

  function openCreationConfigManagement() {
    const modal = element('modal-creation-config-management');
    if (!modal) return;
    modal.style.display = 'flex';
    refreshCreationConfigManagement();
  }

  function openModelManagement() {
    const modal = element('modal-model-management');
    if (!modal) return;
    modal.style.display = 'flex';
    refreshCreationConfigManagement();
  }

  function closeCreationConfigManagement() {
    const modal = element('modal-creation-config-management');
    if (modal) modal.style.display = 'none';
  }

  function closeModelManagement() {
    const modal = element('modal-model-management');
    if (modal) modal.style.display = 'none';
  }

  function selectCreationConfigTab(tab) {
    const selected = ['models', 'visual', 'output', 'prompts'].includes(tab) ? tab : 'models';
    document.querySelectorAll('[data-creation-config-tab]').forEach(button => {
      const active = button.dataset.creationConfigTab === selected;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll('[data-creation-config-panel]').forEach(panel => {
      panel.hidden = panel.dataset.creationConfigPanel !== selected;
    });
  }

  function initCreationConfigManagementEvents() {
    buildStructuredEditor();
    renderConnectionSelectors();
    element('btn-open-creation-config-management')?.addEventListener('click', openCreationConfigManagement);
    element('btn-open-model-management')?.addEventListener('click', openModelManagement);
    element('btn-creation-config-management-close')?.addEventListener('click', closeCreationConfigManagement);
    element('btn-model-management-close-icon')?.addEventListener('click', closeModelManagement);
    element('btn-model-management-refresh')?.addEventListener('click', refreshCreationConfigManagement);
    element('btn-create-creation-config')?.addEventListener('click', createCreationConfig);
    element('btn-cancel-creation-config-edit')?.addEventListener('click', discardCreationConfigChanges);
    element('btn-prepare-save-creation-config-as')?.addEventListener('click', saveCreationConfigAs);
    document.querySelectorAll('[data-creation-config-tab]').forEach(button => {
      button.addEventListener('click', () => selectCreationConfigTab(button.dataset.creationConfigTab));
    });
    selectCreationConfigTab('models');
    element('btn-creation-config-load-json')?.addEventListener('click', loadJsonIntoStructured);
    document.querySelectorAll('[data-model-kind]').forEach(tab => {
      tab.addEventListener('click', () => selectModelKind(tab.dataset.modelKind));
    });
    element('model-form-protocol')?.addEventListener('change', applyOpenAiCompatiblePreset);
    element('model-form-tts-provider')?.addEventListener('change', updateModelProviderPanels);
    element('creation-config-image-style-template')?.addEventListener('change', () => {
      updateImageStyleSummary();
      renderImageStyleCards();
    });
    element('btn-creation-config-create-style')?.addEventListener('click', createStyleForCreationConfig);
    element('btn-creation-config-style-close')?.addEventListener('click', closeCreationConfigStyleDialog);
    element('btn-creation-config-style-cancel')?.addEventListener('click', closeCreationConfigStyleDialog);
    element('btn-creation-config-style-submit')?.addEventListener('click', submitCreationConfigStyle);
    element('creation-config-style-reference-files')?.addEventListener('change', renderCreationConfigStyleReferencePreview);
    element('creation-config-subtitle-enabled')?.addEventListener('change', updateSubtitleControls);
    document.querySelectorAll('input[name="creation-config-automation-mode"]').forEach(input => {
      input.addEventListener('change', () => {
        updateAutomationControls();
        syncStructuredFieldsToJson();
      });
    });
    document.querySelectorAll('input[name="creation-config-reference-policy"]').forEach(input => {
      input.addEventListener('change', updateImageStyleSummary);
    });
    element('btn-model-form-comfyui-workflow')?.addEventListener('click', importComfyUiWorkflow);
    element('model-form-comfyui-workflow-file')?.addEventListener('change', importComfyUiWorkflow);
    element('btn-save-model')?.addEventListener('click', saveModel);
    element('btn-cancel-model-edit')?.addEventListener('click', cancelModelEdit);
    updateModelSetupForm();
    updateAutomationControls();
    const syncEditor = () => {
      try {
        syncStructuredFieldsToJson();
        const status = element('creation-config-editing-status');
        if (status?.dataset.configError) {
          delete status.dataset.configError;
          status.textContent = state.editingPackageId ? '可以保存当前修改。' : '可以创建配置包。';
        }
      } catch (error) {
        const status = element('creation-config-editing-status');
        if (status) {
          status.dataset.configError = 'true';
          status.textContent = error?.message || '配置内容格式不正确。';
        }
      }
    };
    element('creation-config-structured-editor')?.addEventListener('input', syncEditor);
    element('creation-config-structured-editor')?.addEventListener('change', syncEditor);
    element('modal-creation-config-management')?.addEventListener('click', event => {
      if (event.target?.id === 'modal-creation-config-management') closeCreationConfigManagement();
    });
    element('modal-creation-config-style')?.addEventListener('click', event => {
      if (event.target?.id === 'modal-creation-config-style') closeCreationConfigStyleDialog();
    });
    element('modal-model-management')?.addEventListener('click', event => {
      if (event.target?.id === 'modal-model-management') closeModelManagement();
    });
    resetCreationConfigEditor();
  }

  window.openCreationConfigManagement = openCreationConfigManagement;
  window.openModelManagement = openModelManagement;
  window.closeCreationConfigManagement = closeCreationConfigManagement;
  window.refreshCreationConfigManagement = refreshCreationConfigManagement;
  window.initCreationConfigManagementEvents = initCreationConfigManagementEvents;
})();
