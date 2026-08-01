// Step 2 Prompt editor and reusable Prompt-template management.
// Shared state, API helpers, and modal utilities are provided by app.js.

async function openStoryboardRulesModal(mode = 'script') {
  if (!state.currentProject) return;
  state.activeStep2PromptMode = mode === 'visual' ? 'visual' : 'script';
  const [promptRes, templateRes] = await Promise.all([
    API.get(`/api/projects/${state.currentProject.id}/steps/2/prompts`),
    API.get('/api/step2-prompt-templates'),
  ]);
  state.step2PromptTemplates = Array.isArray(templateRes.templates) ? templateRes.templates : [];
  state.selectedStep2PromptTemplateId = '';
  state.step2PromptCreating = false;
  renderStep2PromptEditor(promptRes);
  renderStep2PromptTemplateOptions('');
  renderStep2PromptTemplateCreation();
  document.getElementById('modal-storyboard-rules').style.display = 'flex';
}

function step2PromptModeLabel(mode = state.activeStep2PromptMode) {
  return mode === 'visual' ? 'slides➡️可视化' : '文章➡️slides';
}

function composeStep2FullPrompt(systemContent, outputExample) {
  return `${String(systemContent || '').trim()}\n\n<OutputExample>\n${String(outputExample || '').trim()}\n</OutputExample>`;
}

function updateStep2FullPromptPreviews() {
  const scriptFull = document.getElementById('step2-script-full-prompt');
  const visualFull = document.getElementById('step2-visual-full-prompt');
  if (scriptFull) {
    scriptFull.value = composeStep2FullPrompt(
      document.getElementById('step2-script-system-prompt')?.value,
      document.getElementById('step2-script-output-example')?.value,
    );
  }
  if (visualFull) {
    visualFull.value = composeStep2FullPrompt(
      document.getElementById('step2-visual-system-prompt')?.value,
      document.getElementById('step2-visual-output-example')?.value,
    );
  }
}

function renderStep2PromptEditor(promptRes = {}) {
  const prompts = promptRes.prompts || {};
  const setValue = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.value = value || '';
  };
  setValue('step2-script-system-prompt', prompts.script_system);
  setValue('step2-script-output-example', prompts.script_output_example);
  setValue('step2-visual-system-prompt', prompts.visual_system);
  setValue('step2-visual-output-example', prompts.visual_output_example);
  setValue('step2-script-full-prompt', promptRes.composed?.script_system_content);
  setValue('step2-visual-full-prompt', promptRes.composed?.visual_system_content);
  updateStep2FullPromptPreviews();
  const mode = state.activeStep2PromptMode === 'visual' ? 'visual' : 'script';
  const title = document.getElementById('storyboard-prompt-modal-title');
  const helpButton = document.getElementById('step2-prompt-help');
  const scriptSection = document.getElementById('step2-script-prompt-section');
  const visualSection = document.getElementById('step2-visual-prompt-section');
  if (title) title.textContent = step2PromptModeLabel(mode);
  if (helpButton) helpButton.dataset.promptHelp = mode === 'visual' ? 'step2-visual' : 'step2-script';
  if (scriptSection) scriptSection.style.display = mode === 'script' ? 'block' : 'none';
  if (visualSection) visualSection.style.display = mode === 'visual' ? 'block' : 'none';
  renderStep2PromptTemplateOptions();
}

function step2PromptFormPayloadForMode(mode = state.activeStep2PromptMode) {
  if (mode === 'visual') {
    return {
      prompt_type: 'visual',
      visual_system: document.getElementById('step2-visual-system-prompt')?.value || '',
      visual_output_example: document.getElementById('step2-visual-output-example')?.value || '',
    };
  }
  return {
    prompt_type: 'script',
    script_system: document.getElementById('step2-script-system-prompt')?.value || '',
    script_output_example: document.getElementById('step2-script-output-example')?.value || '',
  };
}

function applyStep2PromptTemplate(template) {
  if (!template?.prompts) return;
  const prompts = template.prompts;
  if (template.prompt_type === 'visual') {
    const system = document.getElementById('step2-visual-system-prompt');
    const example = document.getElementById('step2-visual-output-example');
    if (system) system.value = prompts.visual_system || '';
    if (example) example.value = prompts.visual_output_example || '';
  } else {
    const system = document.getElementById('step2-script-system-prompt');
    const example = document.getElementById('step2-script-output-example');
    if (system) system.value = prompts.script_system || '';
    if (example) example.value = prompts.script_output_example || '';
  }
  updateStep2FullPromptPreviews();
}

function renderStep2PromptTemplateOptions(selectedId = state.selectedStep2PromptTemplateId || '') {
  const mode = state.activeStep2PromptMode === 'visual' ? 'visual' : 'script';
  const select = document.getElementById('step2-prompt-template-select');
  if (!select) return;
  const templates = (state.step2PromptTemplates || []).filter(template => template.prompt_type === mode);
  select.innerHTML = [
    `<option value="">当前 ${escHtml(step2PromptModeLabel(mode))} Prompt</option>`,
    ...templates.map(template =>
      `<option value="${escHtml(template.id)}">${escHtml(template.name)}${template.built_in ? ' · 内置' : ''}</option>`
    ),
  ].join('');
  select.value = templates.some(template => template.id === selectedId) ? selectedId : '';
  state.selectedStep2PromptTemplateId = select.value || '';
  updateStep2PromptTemplateDeleteButton();
}

function renderStep2PromptTemplateCreation() {
  const panel = document.getElementById('step2-prompt-template-create-panel');
  const modeLabel = document.getElementById('step2-prompt-create-mode-label');
  if (panel) panel.style.display = state.step2PromptCreating ? 'grid' : 'none';
  if (modeLabel) modeLabel.textContent = step2PromptModeLabel();
}

function beginStep2PromptTemplateCreation() {
  state.step2PromptCreating = true;
  state.selectedStep2PromptTemplateId = '';
  const select = document.getElementById('step2-prompt-template-select');
  const nameInput = document.getElementById('step2-prompt-template-name');
  if (select) select.value = '';
  if (nameInput) nameInput.value = '';
  updateStep2PromptTemplateDeleteButton();
  renderStep2PromptTemplateCreation();
  nameInput?.focus();
}

function cancelStep2PromptTemplateCreation() {
  state.step2PromptCreating = false;
  const nameInput = document.getElementById('step2-prompt-template-name');
  if (nameInput) nameInput.value = '';
  renderStep2PromptTemplateCreation();
}

function selectedStep2PromptTemplate() {
  const templateId = document.getElementById('step2-prompt-template-select')?.value || state.selectedStep2PromptTemplateId || '';
  return (state.step2PromptTemplates || []).find(template => template.id === templateId) || null;
}

function updateStep2PromptTemplateDeleteButton() {
  const button = document.getElementById('btn-step2-prompt-template-delete');
  if (!button) return;
  const template = selectedStep2PromptTemplate();
  button.disabled = !template || !!template.built_in;
  button.title = template?.built_in ? '内置模板不能删除' : '';
}

async function refreshStep2PromptTemplates(selectedId = '') {
  const res = await API.get('/api/step2-prompt-templates');
  state.step2PromptTemplates = Array.isArray(res.templates) ? res.templates : [];
  renderStep2PromptTemplateOptions(selectedId);
  return state.step2PromptTemplates;
}

async function loadSelectedStep2PromptTemplate() {
  const template = selectedStep2PromptTemplate();
  if (!template) {
    showToast('请选择一个 Prompt 模板。');
    return;
  }
  const res = await API.get(`/api/step2-prompt-templates/${encodeURIComponent(template.id)}`);
  if (res.success && res.template) {
    cancelStep2PromptTemplateCreation();
    applyStep2PromptTemplate(res.template);
    state.selectedStep2PromptTemplateId = res.template.id;
    renderStep2PromptTemplateOptions(res.template.id);
    showToast(`已载入 ${step2PromptModeLabel()} 模板“${res.template.name}”。`);
  }
}

async function saveStep2PromptTemplate() {
  if (!state.step2PromptCreating) {
    beginStep2PromptTemplateCreation();
    return;
  }
  const name = document.getElementById('step2-prompt-template-name')?.value.trim();
  if (!name) {
    showToast('请填写模板名称。');
    return;
  }
  const payload = {
    name,
    ...step2PromptFormPayloadForMode(),
  };
  const res = await API.post('/api/step2-prompt-templates', payload);
  if (res.success) {
    state.step2PromptTemplates = res.templates || [];
    state.step2PromptCreating = false;
    renderStep2PromptTemplateOptions(res.template?.id || '');
    renderStep2PromptTemplateCreation();
    showToast(`模板“${res.template?.name || name}”已保存。`);
  }
}

async function deleteSelectedStep2PromptTemplate() {
  const template = selectedStep2PromptTemplate();
  if (!template) {
    showToast('请选择要删除的 Prompt 模板。');
    return;
  }
  if (template.built_in) {
    showToast('内置模板不能删除。');
    return;
  }
  const confirmed = window.confirm(`确定删除模板“${template.name}”吗？`);
  if (!confirmed) return;
  const res = await API.delete(`/api/step2-prompt-templates/${encodeURIComponent(template.id)}`);
  if (res.success) {
    state.step2PromptTemplates = res.templates || [];
    state.selectedStep2PromptTemplateId = '';
    const nameInput = document.getElementById('step2-prompt-template-name');
    if (nameInput) nameInput.value = '';
    renderStep2PromptTemplateOptions();
    showToast(`模板“${template.name}”已删除。`);
  }
}

async function saveStep2Prompts() {
  if (!state.currentProject?.id) return;
  const payload = {
    script_system: document.getElementById('step2-script-system-prompt')?.value || '',
    script_output_example: document.getElementById('step2-script-output-example')?.value || '',
    visual_system: document.getElementById('step2-visual-system-prompt')?.value || '',
    visual_output_example: document.getElementById('step2-visual-output-example')?.value || '',
  };
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/prompts`, payload);
  if (res.success) {
    renderStep2PromptEditor(res);
    closeStoryboardRulesModal();
    showToast('Step 2 Prompt 已保存。');
  }
}

function closeStoryboardRulesModal() {
  cancelStep2PromptTemplateCreation();
  document.getElementById('modal-storyboard-rules').style.display = 'none';
}

