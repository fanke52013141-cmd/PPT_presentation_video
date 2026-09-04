// Reusable creation-package and model-connection management.
// Connection records contain only safe metadata. Credentials are submitted to
// the server-side credential boundary and are never rendered back into the UI.

(function () {
  'use strict';

  const state = {
    packages: [],
    connections: [],
    credentials: [],
    loading: false,
    editingPackageId: null,
    editingVersion: null,
  };

  const PROMPT_MODULES = [
    ['article_generation', '文章生成'],
    ['storyboard', '分镜'],
    ['visualization', '分镜可视化'],
    ['image_generation', '图片生成'],
    ['ai_mask', 'AI Mask'],
    ['narration_annotation', '旁白'],
  ];
  const MODEL_BINDINGS = [
    ['article_generation', '文章生成', 'text'],
    ['storyboard', '分镜', 'text'],
    ['visualization', '分镜可视化', 'text'],
    ['image_generation', '图片生成', 'image'],
    ['ai_mask', 'AI Mask', 'text'],
    ['narration_annotation', '旁白', 'text'],
    ['tts', '语音合成', 'tts'],
  ];

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

  function card(title, detail) {
    const item = document.createElement('article');
    item.className = 'soft-outline';
    item.style.cssText = 'padding:0.8rem; border-radius:10px; margin-bottom:0.7rem; background:rgba(255,255,255,0.72);';
    const heading = document.createElement('strong');
    heading.textContent = title;
    const copy = document.createElement('div');
    copy.textContent = detail;
    copy.style.cssText = 'font-size:0.82rem; color:var(--muted-color); margin-top:0.35rem; line-height:1.45;';
    item.append(heading, copy);
    return item;
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

  function setNumberField(id, value) {
    const field = element(id);
    if (field) field.value = typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  }

  function buildStructuredEditor() {
    const promptTarget = element('creation-config-prompt-fields');
    const bindingTarget = element('creation-config-model-binding-fields');
    if (!promptTarget || !bindingTarget || promptTarget.childElementCount || bindingTarget.childElementCount) return;

    PROMPT_MODULES.forEach(([key, label]) => {
      const section = document.createElement('section');
      section.className = 'creation-config-prompt-card';
      const heading = document.createElement('h6');
      heading.textContent = label;
      const systemLabel = document.createElement('label');
      systemLabel.textContent = '系统提示词';
      const system = document.createElement('textarea');
      system.id = `creation-config-prompt-${key}-system-content`;
      system.rows = 3;
      system.placeholder = '留空则沿用系统默认提示词';
      systemLabel.append(system);
      const exampleLabel = document.createElement('label');
      exampleLabel.textContent = '输出示例';
      const example = document.createElement('textarea');
      example.id = `creation-config-prompt-${key}-output-example`;
      example.rows = 2;
      example.placeholder = '可选，用于约束输出结构';
      exampleLabel.append(example);
      section.append(heading, systemLabel, exampleLabel);
      promptTarget.append(section);
    });

    MODEL_BINDINGS.forEach(([key, label, kind]) => {
      const labelNode = document.createElement('label');
      labelNode.className = 'creation-config-binding-field';
      const title = document.createElement('span');
      title.textContent = `${label}（${kind === 'text' ? '文本' : kind === 'image' ? '图片' : '语音'}）`;
      const select = document.createElement('select');
      select.id = `creation-config-binding-${key}`;
      select.dataset.kind = kind;
      select.dataset.binding = key;
      labelNode.append(title, select);
      bindingTarget.append(labelNode);
    });
  }

  function renderConnectionSelectors() {
    MODEL_BINDINGS.forEach(([key, , kind]) => {
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
          const revision = connectionRevision(connection);
          const revisionNumber = Number(revision.revision || connection.current_revision);
          if (!connection.id || !Number.isInteger(revisionNumber) || revisionNumber < 1) return;
          const option = document.createElement('option');
          option.value = `${connection.id}@${revisionNumber}`;
          option.textContent = `${connection.name || '未命名连接'} · ${revision.provider || '未知服务'} / ${revision.model || '未指定模型'} · v${revisionNumber}`;
          select.append(option);
        });
      if ([...select.options].some(option => option.value === selected)) select.value = selected;
    });
  }

  function connectionValue(reference) {
    if (!reference || typeof reference !== 'object') return '';
    const revision = Number(reference.revision);
    return typeof reference.connection_id === 'string' && Number.isInteger(revision) && revision > 0
      ? `${reference.connection_id}@${revision}`
      : '';
  }

  function setBindingValue(key, reference) {
    const select = element(`creation-config-binding-${key}`);
    if (select) select.value = connectionValue(reference);
  }

  function readBindingValue(key) {
    const value = element(`creation-config-binding-${key}`)?.value || '';
    const at = value.lastIndexOf('@');
    const revision = Number(value.slice(at + 1));
    if (at <= 0 || !Number.isInteger(revision) || revision < 1) return null;
    return { connection_id: value.slice(0, at), revision };
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

    const bindings = objectValue(payload.model_bindings);
    MODEL_BINDINGS.filter(([key]) => key !== 'tts').forEach(([key]) => {
      const reference = readBindingValue(key);
      if (reference) bindings[key] = reference;
      else delete bindings[key];
    });
    if (Object.keys(bindings).length) payload.model_bindings = bindings;
    else delete payload.model_bindings;

    const tts = objectValue(payload.tts);
    const ttsBinding = readBindingValue('tts');
    if (ttsBinding) tts.connection = ttsBinding;
    else delete tts.connection;
    [
      ['voice_id', 'creation-config-tts-voice-id', 'string'],
      ['clone_voice_id', 'creation-config-tts-clone-voice-id', 'string'],
      ['speed', 'creation-config-tts-speed', 'number'],
      ['volume', 'creation-config-tts-volume', 'number'],
      ['pitch', 'creation-config-tts-pitch', 'number'],
    ].forEach(([key, id, type]) => {
      const raw = element(id)?.value.trim() || '';
      if (!raw) delete tts[key];
      else if (type === 'number') {
        const value = Number(raw);
        if (Number.isFinite(value)) tts[key] = value;
        else delete tts[key];
      } else tts[key] = raw;
    });
    if (Object.keys(tts).length) payload.tts = tts;
    else delete payload.tts;

    const imageStyle = objectValue(payload.image_style);
    const imageName = element('creation-config-image-style-name')?.value.trim() || '';
    const imageSystem = element('creation-config-image-style-system-content')?.value.trim() || '';
    if (imageName) imageStyle.name = imageName;
    else delete imageStyle.name;
    if (imageSystem) imageStyle.system_content = imageSystem;
    else delete imageStyle.system_content;
    if (Object.keys(imageStyle).length) payload.image_style = imageStyle;
    else delete payload.image_style;

    payload.subtitle = { ...objectValue(payload.subtitle), enabled: !!element('creation-config-subtitle-enabled')?.checked };
    payload.mask = { ...objectValue(payload.mask), enabled: !!element('creation-config-mask-enabled')?.checked };
    const pauseSteps = [...document.querySelectorAll('[data-creation-config-pause]:checked')]
      .map(input => input.dataset.creationConfigPause)
      .filter(Boolean);
    const automation = objectValue(payload.automation);
    if (pauseSteps.length) automation.manual_pause_steps = pauseSteps;
    else delete automation.manual_pause_steps;
    if (Object.keys(automation).length) payload.automation = automation;
    else delete payload.automation;

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
    MODEL_BINDINGS.filter(([key]) => key !== 'tts').forEach(([key]) => setBindingValue(key, bindings[key]));
    const tts = objectValue(value.tts);
    setBindingValue('tts', tts.connection || bindings.tts);
    setStringField('creation-config-tts-voice-id', tts.voice_id);
    setStringField('creation-config-tts-clone-voice-id', tts.clone_voice_id);
    setNumberField('creation-config-tts-speed', tts.speed);
    setNumberField('creation-config-tts-volume', tts.volume);
    setNumberField('creation-config-tts-pitch', tts.pitch);
    const imageStyle = objectValue(value.image_style);
    setStringField('creation-config-image-style-name', imageStyle.name);
    setStringField('creation-config-image-style-system-content', imageStyle.system_content);
    const subtitle = objectValue(value.subtitle || value.subtitles);
    const mask = objectValue(value.mask);
    const subtitleToggle = element('creation-config-subtitle-enabled');
    const maskToggle = element('creation-config-mask-enabled');
    if (subtitleToggle) subtitleToggle.checked = subtitle.enabled !== false;
    if (maskToggle) maskToggle.checked = mask.enabled !== false;
    const pauseSteps = objectValue(value.automation).manual_pause_steps;
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
    toast('已从 JSON 更新结构化表单');
  }

  function resetCreationConfigEditor() {
    state.editingPackageId = null;
    state.editingVersion = null;
    const name = element('creation-config-package-name');
    const description = element('creation-config-package-description');
    const payload = element('creation-config-package-payload');
    if (name) { name.value = ''; name.readOnly = false; }
    if (description) { description.value = ''; description.readOnly = false; }
    if (payload) payload.value = '{}';
    loadPayloadIntoStructured({});
    const status = element('creation-config-editing-status');
    if (status) status.textContent = '正在新建配置包。';
    const submit = element('btn-create-creation-config');
    if (submit) submit.textContent = '新建配置包';
    const cancel = element('btn-cancel-creation-config-edit');
    if (cancel) cancel.hidden = true;
  }

  function renderPackages() {
    const target = element('creation-config-package-list');
    if (!target) return;
    target.replaceChildren();
    if (!state.packages.length) {
      const empty = document.createElement('p');
      empty.className = 'config-editor-note';
      empty.textContent = '暂无创作配置包。先完成一套默认配置后，可在这里复制出账号专属版本。';
      target.append(empty);
      return;
    }
    state.packages.forEach(packageItem => {
      const tags = Array.isArray(packageItem.tags) && packageItem.tags.length
        ? ` · ${packageItem.tags.join('、')}`
        : '';
      const item = card(
        `${packageItem.name || '未命名配置包'} · v${packageItem.latest_version || 1}`,
        `${packageItem.description || '未填写说明'}${tags}`,
      );
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex; gap:0.55rem; flex-wrap:wrap;';
      actions.append(
        button('编辑', 'secondary', () => editPackage(packageItem)),
        button('复制', 'secondary', () => copyPackage(packageItem)),
        button('归档', 'secondary', () => archivePackage(packageItem)),
      );
      item.append(actions);
      target.append(item);
    });
  }

  function renderConnections() {
    const target = element('creation-config-connection-list');
    if (!target) return;
    target.replaceChildren();
    if (!state.connections.length) {
      const empty = document.createElement('p');
      empty.className = 'config-editor-note';
      empty.textContent = '暂无模型连接。添加文本、图片或语音连接后，可在创作配置包中选择它。';
      target.append(empty);
      return;
    }
    state.connections.forEach(connection => {
      const revision = connectionRevision(connection);
      const configured = revision.credential_configured ? '已关联凭据' : '未关联凭据';
      const item = card(
        `${connection.name || '未命名连接'} · ${connection.kind || 'unknown'}`,
        `${revision.provider || '未指定服务'} / ${revision.model || '未指定模型'} · ${configured}`,
      );
      target.append(item);
    });
  }

  function renderCredentials() {
    const target = element('creation-config-credential-list');
    if (!target) return;
    target.replaceChildren();
    if (!state.credentials.length) {
      const empty = document.createElement('p');
      empty.className = 'config-editor-note';
      empty.textContent = '暂无已配置凭据。添加后会自动填入下方模型连接的凭据引用。';
      target.append(empty);
      return;
    }
    state.credentials.forEach(credential => {
      const configured = credential.configured ? '已配置' : '未配置';
      const stateLabel = credential.state === 'disabled' ? '已停用' : '可用';
      const item = card(
        credential.label || '未命名凭据',
        `${credential.provider || '未指定服务'} · ${configured} · ${stateLabel}`,
      );
      target.append(item);
    });
  }

  async function refreshCreationConfigManagement() {
    if (state.loading || !window.API) return;
    state.loading = true;
    const status = element('creation-config-management-status');
    if (status) status.textContent = '正在加载…';
    try {
      const [packagesResponse, connectionsResponse, credentialsResponse] = await Promise.all([
        window.API.get('/api/creation-configs'),
        window.API.get('/api/model-connections'),
        window.API.get('/api/credentials'),
      ]);
      state.packages = Array.isArray(packagesResponse?.packages) ? packagesResponse.packages : [];
      state.connections = Array.isArray(connectionsResponse?.connections) ? connectionsResponse.connections : [];
      state.credentials = Array.isArray(credentialsResponse?.credentials) ? credentialsResponse.credentials : [];
      buildStructuredEditor();
      renderConnectionSelectors();
      renderPackages();
      renderConnections();
      renderCredentials();
      if (status) status.textContent = `已加载 ${state.packages.length} 个配置包、${state.connections.length} 个模型连接和 ${state.credentials.length} 个凭据`;
    } catch (error) {
      if (status) status.textContent = '加载失败，请检查服务状态后重试。';
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
        version: Number(packageItem.latest_version) || undefined,
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
        throw new Error('未找到可编辑的配置包版本');
      }
      state.editingPackageId = current.id;
      state.editingVersion = Number(version.version);
      const name = element('creation-config-package-name');
      const description = element('creation-config-package-description');
      const payload = element('creation-config-package-payload');
      if (name) { name.value = current.name || ''; name.readOnly = true; }
      if (description) { description.value = current.description || ''; description.readOnly = true; }
      if (payload) payload.value = JSON.stringify(version.payload, null, 2);
      renderConnectionSelectors();
      loadPayloadIntoStructured(version.payload);
      const status = element('creation-config-editing-status');
      if (status) status.textContent = `正在编辑“${current.name || '未命名配置包'}”v${version.version}；保存会创建 v${Number(version.version) + 1}。名称和说明会保持不变。`;
      const submit = element('btn-create-creation-config');
      if (submit) submit.textContent = '保存为新版本';
      const cancel = element('btn-cancel-creation-config-edit');
      if (cancel) cancel.hidden = false;
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
    const description = element('creation-config-package-description')?.value.trim() || '';
    if (!name) {
      toast('请输入创作配置包名称');
      return;
    }
    let payload;
    try {
      payload = parseCreationConfigPayload();
    } catch (error) {
      requestError('无法创建配置包', error);
      return;
    }
    const submit = element('btn-create-creation-config');
    if (submit) submit.disabled = true;
    try {
      if (state.editingPackageId) {
        await window.API.post(`/api/creation-configs/${encodeURIComponent(state.editingPackageId)}/versions`, { payload });
        toast('已保存为配置包新版本');
      } else {
        await window.API.post('/api/creation-configs', { name, description, payload });
        toast('创作配置包已创建');
      }
      await refreshCreationConfigManagement();
      if (typeof window.loadCreationConfigs === 'function') window.loadCreationConfigs();
      resetCreationConfigEditor();
    } catch (error) {
      requestError(state.editingPackageId ? '保存配置包版本失败' : '创建配置包失败', error);
    } finally {
      if (submit) submit.disabled = false;
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

  function parsePublicConfig() {
    const field = element('creation-config-connection-public-config');
    const raw = field ? field.value.trim() : '';
    if (!raw) return {};
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_) {
      throw new Error('公开参数必须是有效 JSON 对象');
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('公开参数必须是 JSON 对象');
    }
    return parsed;
  }

  function parseCredentialSecrets() {
    const field = element('creation-config-credential-secret-values');
    const raw = field ? field.value.trim() : '';
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (_) {
      throw new Error('凭据值必须是有效 JSON 对象');
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('凭据值必须是 JSON 对象');
    }
    const valid = Object.keys(parsed).length > 0
      && Object.values(parsed).every(value => typeof value === 'string');
    if (!valid) throw new Error('凭据值必须至少包含一个字符串字段');
    return parsed;
  }

  async function createCredential() {
    const provider = element('creation-config-credential-provider')?.value.trim() || '';
    const label = element('creation-config-credential-label')?.value.trim() || '';
    if (!provider || !label) {
      toast('请填写凭据服务和名称');
      return;
    }
    let secretValues;
    try {
      secretValues = parseCredentialSecrets();
    } catch (error) {
      requestError('无法添加凭据', error);
      return;
    }
    const submit = element('btn-create-credential');
    if (submit) submit.disabled = true;
    try {
      const response = await window.API.post('/api/credentials', {
        provider,
        label,
        secret_values: secretValues,
      });
      // Support the metadata response used by both the current and planned
      // credential route contract while accepting no secret data from either.
      const credentialRef = response?.credential_ref || response?.credential?.credential_ref;
      if (!credentialRef || typeof credentialRef !== 'string') {
        throw new Error('凭据已保存，但服务未返回可用引用');
      }
      const credentialField = element('creation-config-connection-credential-ref');
      if (credentialField) credentialField.value = credentialRef;
      const secretField = element('creation-config-credential-secret-values');
      const labelField = element('creation-config-credential-label');
      if (secretField) secretField.value = '';
      if (labelField) labelField.value = '';
      toast('凭据已添加，已填入模型连接的凭据引用');
      await refreshCreationConfigManagement();
    } catch (error) {
      requestError('添加凭据失败', error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function createModelConnection() {
    const name = element('creation-config-connection-name')?.value.trim() || '';
    const kind = element('creation-config-connection-kind')?.value || '';
    const provider = element('creation-config-connection-provider')?.value.trim() || '';
    const model = element('creation-config-connection-model')?.value.trim() || '';
    const endpoint = element('creation-config-connection-endpoint')?.value.trim() || '';
    const credentialRef = element('creation-config-connection-credential-ref')?.value.trim() || '';
    if (!name || !kind || !provider || !model) {
      toast('请填写连接名称、类别、服务和模型');
      return;
    }
    let publicConfig;
    try {
      publicConfig = parsePublicConfig();
    } catch (error) {
      requestError('无法创建模型连接', error);
      return;
    }
    const payload = { name, kind, provider, model, endpoint: endpoint || null, public_config: publicConfig };
    if (credentialRef) payload.credential_ref = credentialRef;
    const submit = element('btn-create-model-connection');
    if (submit) submit.disabled = true;
    try {
      await window.API.post('/api/model-connections', payload);
      toast('模型连接已添加');
      ['creation-config-connection-name', 'creation-config-connection-provider', 'creation-config-connection-model', 'creation-config-connection-endpoint', 'creation-config-connection-credential-ref', 'creation-config-connection-public-config']
        .forEach(id => { const field = element(id); if (field) field.value = ''; });
      await refreshCreationConfigManagement();
    } catch (error) {
      requestError('创建模型连接失败', error);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function openCreationConfigManagement() {
    const modal = element('modal-creation-config-management');
    if (!modal) return;
    modal.style.display = 'flex';
    refreshCreationConfigManagement();
  }

  function closeCreationConfigManagement() {
    const modal = element('modal-creation-config-management');
    if (modal) modal.style.display = 'none';
  }

  function initCreationConfigManagementEvents() {
    buildStructuredEditor();
    renderConnectionSelectors();
    element('btn-open-creation-config-management')?.addEventListener('click', openCreationConfigManagement);
    element('btn-creation-config-management-close')?.addEventListener('click', closeCreationConfigManagement);
    element('btn-creation-config-management-refresh')?.addEventListener('click', refreshCreationConfigManagement);
    element('btn-create-creation-config')?.addEventListener('click', createCreationConfig);
    element('btn-cancel-creation-config-edit')?.addEventListener('click', resetCreationConfigEditor);
    element('btn-creation-config-load-json')?.addEventListener('click', loadJsonIntoStructured);
    element('btn-create-credential')?.addEventListener('click', createCredential);
    element('btn-create-model-connection')?.addEventListener('click', createModelConnection);
    element('creation-config-structured-editor')?.addEventListener('input', syncStructuredFieldsToJson);
    element('creation-config-structured-editor')?.addEventListener('change', syncStructuredFieldsToJson);
    element('modal-creation-config-management')?.addEventListener('click', event => {
      if (event.target?.id === 'modal-creation-config-management') closeCreationConfigManagement();
    });
    resetCreationConfigEditor();
  }

  window.openCreationConfigManagement = openCreationConfigManagement;
  window.closeCreationConfigManagement = closeCreationConfigManagement;
  window.refreshCreationConfigManagement = refreshCreationConfigManagement;
  window.initCreationConfigManagementEvents = initCreationConfigManagementEvents;
})();
