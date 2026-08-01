// Step 3 image-generation Prompt loading, preview, editing, reset, and persistence.
// Image grid state lives in images.js; shared modal and API utilities live in app.js.

async function refreshStep3Prompts(options = {}) {
  if (!state.currentProject?.id) return [];
  const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
  if (promptRes.success) {
    slidePrompts = promptRes.prompts || [];
    step3BatchPrompt = promptRes.batch_prompt || '';
  }
  if (options.updateOpenEditor) {
    const currentSlideId = document.getElementById('step3-slide-id-label')?.innerText;
    const promptInput = document.getElementById('step3-prompt-input');
    const promptInfo = slidePrompts.find(item => item.slide_id === currentSlideId);
    if (promptInput && promptInfo && currentSlideId && currentSlideId !== '--') {
      promptInput.value = promptInfo.prompt || '';
    }
  }
  return slidePrompts;
}

function currentStep3PromptInfo() {
  const openSlideId = document.getElementById('step3-slide-id-label')?.innerText;
  const fallbackSlideId = state.slides?.[state.activeSlideIndex]?.slide_id || step3ImageOrder?.[0]?.slide_id;
  const slideId = openSlideId && openSlideId !== '--' ? openSlideId : fallbackSlideId;
  return slidePrompts.find(item => item.slide_id === slideId) || slidePrompts[0] || null;
}

function updateStep3PromptFullPreview() {
  const settings = state.step3PromptSettings || {};
  const systemContent = document.getElementById('step3-image-system-prompt')?.value || '';
  const promptInfo = currentStep3PromptInfo();
  const inputPreview = document.getElementById('step3-image-input-preview');
  const fullPreview = document.getElementById('step3-image-full-prompt');
  const slidePrompt = String(promptInfo?.slide_prompt || '').trim();
  if (inputPreview) {
    const jsonStart = slidePrompt.indexOf('{');
    inputPreview.value = jsonStart >= 0
      ? slidePrompt.slice(jsonStart)
      : JSON.stringify(settings.current_input || settings.input_example || {}, null, 2);
  }
  if (fullPreview) {
    fullPreview.value = [
      '=== 图片生成 System Content ===',
      systemContent.trim(),
      '=== 当前生效的图片风格 ===',
      String(settings.style_content || '').trim(),
      '=== 当前 Slide 输入 ===',
      slidePrompt || `最小单页输入：\n${JSON.stringify(settings.current_input || settings.input_example || {}, null, 2)}`,
      String(settings.protected_rules || '').trim(),
    ].filter(Boolean).join('\n\n');
  }
}

async function openStep3PromptSettingsModal() {
  if (!state.currentProject?.id) return;
  const modal = document.getElementById('modal-step3-prompt-settings');
  const systemInput = document.getElementById('step3-image-system-prompt');
  const inputPreview = document.getElementById('step3-image-input-preview');
  const fullPreview = document.getElementById('step3-image-full-prompt');
  modal.style.display = 'flex';
  systemInput.value = '加载中...';
  inputPreview.value = '';
  fullPreview.value = '';
  try {
    const [result] = await Promise.all([
      API.get(`/api/projects/${state.currentProject.id}/steps/3/prompt-settings`),
      refreshStep3Prompts(),
    ]);
    state.step3PromptSettings = result.prompts || {};
    systemInput.value = state.step3PromptSettings.system_content || '';
    updateStep3PromptFullPreview();
  } catch (error) {
    modal.style.display = 'none';
  }
}

function closeStep3PromptSettingsModal() {
  const modal = document.getElementById('modal-step3-prompt-settings');
  if (modal) modal.style.display = 'none';
}

function resetStep3PromptSettings() {
  const input = document.getElementById('step3-image-system-prompt');
  if (!input) return;
  input.value = state.step3PromptSettings?.default_system_content || '';
  updateStep3PromptFullPreview();
  showToast('已恢复默认内容，保存后生效');
}

async function saveStep3PromptSettings() {
  const systemContent = document.getElementById('step3-image-system-prompt')?.value.trim() || '';
  if (!systemContent) return showToast('图片生成 System Content 不能为空');
  const button = document.getElementById('btn-step3-prompt-save');
  button.disabled = true;
  try {
    const result = await API.put(
      `/api/projects/${state.currentProject.id}/steps/3/prompt-settings`,
      { prompts: { system_content: systemContent } },
    );
    state.step3PromptSettings = result.prompts || {};
    await refreshStep3Prompts({ updateOpenEditor: true });
    closeStep3PromptSettingsModal();
    showToast('图片生成 Prompt 已保存');
  } finally {
    button.disabled = false;
  }
}

window.refreshStep3Prompts = refreshStep3Prompts;

