// Global settings, configuration portability, and provider connection checks.
// This remains a classic script so existing inline handlers and ui_foundation.js / workflow_state.js calls keep
// the same global function contract while the legacy bundle is modularized.

const LLM_PROVIDER_PRESETS = {
  openai: { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  newapi: { baseUrl: '', model: '' },
  openrouter: { baseUrl: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini' },
  litellm: { baseUrl: 'http://localhost:4000/v1', model: '' },
  deepseek: { baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat' },
  volcengine: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: '' },
  siliconflow: { baseUrl: 'https://api.siliconflow.cn/v1', model: 'deepseek-ai/DeepSeek-V3' },
  dashscope: { baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  zhipu: { baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  custom: { baseUrl: '', model: '' }
};

function updateTtsProviderHint() {
  var provider = document.getElementById('setting-tts-provider');
  if (!provider) return;
  var isComfyui = provider.value === 'comfyui_tts';
  var section = document.getElementById('tts-comfyui-section');
  if (section) section.style.display = isComfyui ? 'block' : 'none';
  // ComfyUI 本地模式不使用云端 API 字段，全部隐藏
  ['tts-row-endpoint', 'tts-row-credentials', 'tts-row-model-voice', 'tts-row-clone-region', 'tts-row-provider-extra'].forEach(function (rowId) {
    var row = document.getElementById(rowId);
    if (row) row.style.display = isComfyui ? 'none' : '';
  });
  // ComfyUI 模式下所有音频参数（语速等）由工作流 JSON 自行定义，全部隐藏
  ['tts-field-speed', 'tts-field-volume', 'tts-field-pitch'].forEach(function (fieldId) {
    var field = document.getElementById(fieldId);
    if (field) field.style.display = isComfyui ? 'none' : '';
  });
  if (isComfyui) loadComfyuiTtsWorkflowStatus();
}

async function loadComfyuiTtsWorkflowStatus() {
  var statusEl = document.getElementById('tts-comfyui-workflow-status');
  if (!statusEl) return;
  try {
    const res = await API.get('/api/settings/comfyui-tts-workflow');
    if (res && res.exists) {
      statusEl.textContent = '已导入';
      statusEl.style.color = '#4CAF50';
    } else {
      statusEl.textContent = '未导入';
      statusEl.style.color = '';
    }
  } catch (error) {
    statusEl.textContent = '状态未知';
    statusEl.style.color = '';
  }
}

async function uploadComfyuiTtsWorkflow(file) {
  var button = document.getElementById('btn-tts-comfyui-workflow');
  var statusEl = document.getElementById('tts-comfyui-workflow-status');
  if (!file || !button) return;
  var originalText = button.textContent;
  button.disabled = true;
  button.textContent = '上传中...';
  try {
    const form = new FormData();
    form.append('file', file);
    await API.post('/api/settings/comfyui-tts-workflow', form);
    if (statusEl) {
      statusEl.textContent = '已导入';
      statusEl.style.color = '#4CAF50';
    }
    showToast('ComfyUI 工作流已导入，语音合成将自动使用该工作流');
  } catch (error) {
    // API transport 已展示错误详情，仅重置状态
    if (statusEl) {
      statusEl.textContent = '未导入';
      statusEl.style.color = '';
    }
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

document.addEventListener('DOMContentLoaded', function() {
  var ttsProviderSelect = document.getElementById('setting-tts-provider');
  if (ttsProviderSelect) {
    ttsProviderSelect.addEventListener('change', updateTtsProviderHint);
  }
  var wfButton = document.getElementById('btn-tts-comfyui-workflow');
  var wfInput = document.getElementById('tts-comfyui-workflow-file');
  if (wfButton && wfInput) {
    wfButton.addEventListener('click', function () { wfInput.click(); });
    wfInput.addEventListener('change', function () {
      if (wfInput.files && wfInput.files.length > 0) {
        uploadComfyuiTtsWorkflow(wfInput.files[0]);
      }
      wfInput.value = '';
    });
  }
});

function detectLlmProvider(savedProvider, baseUrl) {
  const normalized = String(baseUrl || '').replace(/\/+$/, '').toLowerCase();
  const known = Object.entries(LLM_PROVIDER_PRESETS).find(([, preset]) =>
    preset.baseUrl && preset.baseUrl.replace(/\/+$/, '').toLowerCase() === normalized
  );
  if (known) return known[0];
  if (savedProvider === 'newapi' || savedProvider === 'litellm' || savedProvider === 'custom') {
    return savedProvider;
  }
  return normalized ? 'custom' : (savedProvider || 'openai');
}

function applyLlmProviderPreset(provider) {
  const preset = LLM_PROVIDER_PRESETS[provider];
  if (!preset) return;
  if (preset.baseUrl) document.getElementById('setting-llm-base-url').value = preset.baseUrl;
  if (preset.model) document.getElementById('setting-llm-model').value = preset.model;
}

async function loadSettings() {
  state.settings = await API.get('/api/settings');

  document.getElementById('setting-llm-provider').value = detectLlmProvider(
    state.settings.llm_provider,
    state.settings.llm_base_url
  );
  document.getElementById('setting-llm-base-url').value = state.settings.llm_base_url || '';
  document.getElementById('setting-llm-api-key').value = state.settings.llm_api_key || '';
  document.getElementById('setting-llm-model').value = state.settings.llm_model || '';
  document.getElementById('setting-llm-temp').value = state.settings.llm_temperature || '0.7';
  document.getElementById('setting-llm-max-tokens').value = state.settings.llm_max_tokens || '50000';

  document.getElementById('setting-image-base-url').value = state.settings.image_base_url || '';
  document.getElementById('setting-image-api-key').value = state.settings.image_api_key || '';
  document.getElementById('setting-image-model').value = state.settings.image_model || 'gpt-image-1';
  document.getElementById('setting-image-size').value = state.settings.image_size || '1024x1024';

  document.getElementById('setting-tts-provider').value = state.settings.tts_provider || 'minimax';
  updateTtsProviderHint();
  document.getElementById('setting-tts-endpoint').value = state.settings.tts_endpoint || '';
  document.getElementById('setting-tts-api-key').value = state.settings.tts_api_key || '';
  document.getElementById('setting-tts-secret-key').value = state.settings.tts_secret_key || '';
  document.getElementById('setting-tts-region').value = state.settings.tts_region || '';
  document.getElementById('setting-tts-model').value = state.settings.tts_model || '';
  document.getElementById('setting-tts-voice-id').value = state.settings.tts_voice_id || '';
  document.getElementById('setting-tts-clone-voice-id').value = state.settings.tts_clone_voice_id || '';
  document.getElementById('setting-tts-provider-extra').value = state.settings.tts_provider_extra || '';
  document.getElementById('setting-tts-speed').value = state.settings.tts_speed || '1.2';
  document.getElementById('setting-tts-volume').value = state.settings.tts_volume || '1.0';
  document.getElementById('setting-tts-pitch').value = state.settings.tts_pitch || '0';
}

function openSettingsModal() {
  document.getElementById('modal-settings').style.display = 'flex';
}

function closeSettingsModal() {
  document.getElementById('modal-settings').style.display = 'none';
}

function readSettingsForm() {
  return {
    llm_provider: document.getElementById('setting-llm-provider').value,
    llm_base_url: document.getElementById('setting-llm-base-url').value.trim(),
    llm_api_key: document.getElementById('setting-llm-api-key').value.trim(),
    llm_model: document.getElementById('setting-llm-model').value.trim(),
    llm_temperature: document.getElementById('setting-llm-temp').value.trim(),
    llm_max_tokens: document.getElementById('setting-llm-max-tokens').value.trim(),
    vision_model: state.settings?.vision_model || document.getElementById('setting-llm-model').value.trim(),
    image_base_url: document.getElementById('setting-image-base-url').value.trim(),
    image_api_key: document.getElementById('setting-image-api-key').value.trim(),
    image_model: document.getElementById('setting-image-model').value.trim(),
    image_size: document.getElementById('setting-image-size').value.trim(),
    tts_provider: document.getElementById('setting-tts-provider').value,
    tts_endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    tts_api_key: document.getElementById('setting-tts-api-key').value.trim(),
    tts_secret_key: document.getElementById('setting-tts-secret-key').value.trim(),
    tts_region: document.getElementById('setting-tts-region').value.trim(),
    tts_model: document.getElementById('setting-tts-model').value.trim(),
    tts_voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    tts_clone_voice_id: document.getElementById('setting-tts-clone-voice-id').value.trim(),
    tts_provider_extra: document.getElementById('setting-tts-provider-extra').value.trim(),
    tts_speed: document.getElementById('setting-tts-speed').value.trim(),
    tts_volume: document.getElementById('setting-tts-volume').value.trim(),
    tts_pitch: document.getElementById('setting-tts-pitch').value.trim()
  };
}

async function saveSettings() {
  const res = await API.put('/api/settings', { settings: readSettingsForm() });
  if (!res.success) return;
  await loadSettings();
  closeSettingsModal();
  showToast('系统全局设置保存成功，当前配置已重新加载');
}

function settingsExportFileName() {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  return `ppt-studio-config-bundle-sensitive-${stamp}.json`;
}

async function exportGlobalSettings() {
  const payload = await API.get('/api/config/export');
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = settingsExportFileName();
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast('配置已导出。文件包含 API Key、Prompt 模板和参考图，请妥善保存。', 5000);
}

async function importGlobalSettings(file) {
  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch (error) {
    showToast(`导入失败：${error.message}`, 6000);
    return;
  }

  showCustomConfirm(
    '导入整体配置？',
    '将覆盖当前 API 配置、分镜模板、Step 2 Prompt 模板和图片风格模板。项目内容不会被修改。',
    () => {
      API.post('/api/config/import', payload).then(async () => {
        await loadSettings();
        showToast('配置已导入并重新加载。', 5000);
      }).catch(error => {
        showToast(`导入失败：${error.message}`, 6000);
      });
    }
  );
}

async function testLlmConnection() {
  const button = document.getElementById('btn-test-llm');
  const originalHtml = button.innerHTML;
  const payload = {
    base_url: document.getElementById('setting-llm-base-url').value.trim() || null,
    api_key: document.getElementById('setting-llm-api-key').value.trim(),
    model: document.getElementById('setting-llm-model').value.trim()
  };
  if (!payload.api_key) {
    showToast('请填写接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('请填写文本模型');
    return;
  }
  button.disabled = true;
  button.innerHTML = '测试中...';
  try {
    const result = await API.post('/api/settings/test-llm', payload);
    showToast(result.message || (result.success ? '文本模型连接成功' : '文本模型连接失败'));
  } catch (error) {
    showToast(`测试请求发送失败: ${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

async function testImageConnection() {
  const button = document.getElementById('btn-test-image');
  const originalHtml = button.innerHTML;
  const payload = {
    base_url: document.getElementById('setting-image-base-url').value.trim() || null,
    api_key: document.getElementById('setting-image-api-key').value.trim(),
    model: document.getElementById('setting-image-model').value.trim(),
    size: document.getElementById('setting-image-size').value.trim() || '1024x1024'
  };
  if (!payload.api_key) {
    showToast('请填写生图接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('请填写生图模型');
    return;
  }
  button.disabled = true;
  button.innerHTML = '测试中...';
  try {
    const result = await API.post('/api/settings/test-image', payload);
    showToast(result.message || (result.success ? '图片模型连接成功' : '图片模型连接失败'));
  } catch (error) {
    showToast(`测试请求发送失败: ${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

async function testTtsConnection() {
  const button = document.getElementById('btn-test-tts');
  const originalHtml = button.innerHTML;
  const payload = {
    provider: document.getElementById('setting-tts-provider').value,
    endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    api_key: document.getElementById('setting-tts-api-key').value.trim(),
    secret_key: document.getElementById('setting-tts-secret-key').value.trim(),
    region: document.getElementById('setting-tts-region').value.trim(),
    model: document.getElementById('setting-tts-model').value.trim(),
    voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    clone_voice_id: document.getElementById('setting-tts-clone-voice-id').value.trim(),
    provider_extra: document.getElementById('setting-tts-provider-extra').value.trim()
  };
  if (!payload.model) {
    showToast('请填写语音模型');
    return;
  }
  if (!payload.voice_id) {
    showToast('请填写音色 ID');
    return;
  }
  button.disabled = true;
  button.innerHTML = '测试中...';
  try {
    const result = await API.post('/api/settings/test-tts', payload);
    showToast(result.message || (result.success ? '语音模型连接成功' : '语音模型连接失败'));
  } catch (error) {
    showToast(`测试请求发送失败: ${error.message}`);
  } finally {
    button.disabled = false;
    button.innerHTML = originalHtml;
  }
}

function copyLlmUrlToImage() {
  const llmUrl = document.getElementById('setting-llm-base-url').value.trim();
  if (!llmUrl) {
    showToast('请先填写文本模型的接口地址');
    return;
  }
  document.getElementById('setting-image-base-url').value = llmUrl;
  showToast('已将文本模型 Base URL 同步到图片生成配置');
}
