// Targeted frontend patch for configuration effectiveness.
// Loaded after app.js. Keep this file small so the patch is easy to review and remove.
(function () {
  async function refreshStep3Prompts(options = {}) {
    if (!state?.currentProject?.id) return [];
    try {
      const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
      if (promptRes.success) {
        slidePrompts = promptRes.prompts || [];
      }
      if (options.updateOpenEditor) {
        const currentSlideId = document.getElementById('step3-slide-id-label')?.innerText;
        const promptInput = document.getElementById('step3-prompt-input');
        const promptInfo = slidePrompts.find(item => item.slide_id === currentSlideId);
        if (promptInput && promptInfo && currentSlideId && currentSlideId !== '--') {
          promptInput.value = promptInfo.prompt || '';
        }
      }
    } catch (error) {
      // API.fetch already displays a toast. Keep this patch silent otherwise.
    }
    return slidePrompts;
  }

  window.refreshStep3Prompts = refreshStep3Prompts;

  window.saveSettings = async function saveSettingsPatched() {
    const settings = {
      llm_provider: document.getElementById('setting-llm-provider').value,
      llm_base_url: document.getElementById('setting-llm-base-url').value.trim(),
      llm_api_key: document.getElementById('setting-llm-api-key').value.trim(),
      llm_model: document.getElementById('setting-llm-model').value.trim(),
      llm_temperature: document.getElementById('setting-llm-temp').value.trim(),
      llm_max_tokens: document.getElementById('setting-llm-max-tokens').value.trim(),

      image_base_url: document.getElementById('setting-image-base-url').value.trim(),
      image_api_key: document.getElementById('setting-image-api-key').value.trim(),
      image_model: document.getElementById('setting-image-model').value.trim(),
      image_size: document.getElementById('setting-image-size').value.trim(),

      tts_endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
      tts_api_key: document.getElementById('setting-tts-api-key').value.trim(),
      tts_model: document.getElementById('setting-tts-model').value.trim(),
      tts_voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
      tts_speed: document.getElementById('setting-tts-speed').value.trim(),
      tts_volume: document.getElementById('setting-tts-volume').value.trim(),
      tts_pitch: document.getElementById('setting-tts-pitch').value.trim()
    };

    const res = await API.put('/api/settings', { settings });
    if (res.success) {
      await loadSettings();
      closeSettingsModal();
      showToast('💾 系统全局设置保存成功，当前配置已重新加载');
    }
  };

  window.saveImageStyle = async function saveImageStylePatched() {
    const styleText = document.getElementById('image-style-input').value.trim();
    const res = await API.put('/api/image-style', { style_text: styleText });
    if (!res.success) return;
    await uploadImageStyleReference('template');
    await uploadImageStyleReference('example');
    closeImageStyleModal();
    await refreshStep3Prompts({ updateOpenEditor: state.currentStep === 3 });
    showToast('图片风格与参考图已保存，新的生图提示词已刷新');
  };

  window.saveStoryboardRules = async function saveStoryboardRulesPatched(options = {}) {
    const rules = document.getElementById('storyboard-rules-input').value.trim();
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/rules`, { rules });
    if (!res.success) return;
    closeStoryboardRulesModal();
    if (options.regenerate) {
      showToast('分镜规则已保存，正在按新规则重新规划分镜...');
      await generateStep2Contract();
      return;
    }
    showToast('分镜规则已保存。该配置将在下次“重新规划分镜”时生效，不会自动修改当前已生成分镜。');
  };

  document.addEventListener('DOMContentLoaded', () => {
    const saveBtn = document.getElementById('btn-storyboard-rules-save');
    if (saveBtn && !document.getElementById('btn-storyboard-rules-save-regenerate')) {
      const regenerateBtn = document.createElement('button');
      regenerateBtn.id = 'btn-storyboard-rules-save-regenerate';
      regenerateBtn.type = 'button';
      regenerateBtn.className = 'success';
      regenerateBtn.textContent = '保存并重新规划';
      regenerateBtn.addEventListener('click', () => window.saveStoryboardRules({ regenerate: true }));
      saveBtn.insertAdjacentElement('afterend', regenerateBtn);
    }
  });
})();
