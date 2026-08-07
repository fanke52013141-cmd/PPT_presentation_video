// Step 2 storyboard data, generation, editing, batch import, and persistence.
// Shared helpers and globals are provided by ui_foundation.js / workflow_state.js / api_client.js; public functions remain global for classic-script compatibility.

async function loadStep2Data() {
  try {
    const configRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/rules`);
    state.storyboardRoles = configRes.roles || state.storyboardRoles;
  } catch (e) {}
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
  if (res.success && res.contract) {
    state.slides = res.contract.slides || [];
    state.step2PresentationPolicy = res.contract.presentation_policy || {};
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
    void offerArtifactRepair(res, '分镜数据', loadStep2Data);
  } else {
    state.slides = [];
    state.step2PresentationPolicy = {};
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    document.getElementById('step2-editor-area').style.display = 'none';
    document.getElementById('step2-thumbs').style.display = 'none';
    if (!isManualMode()) {
      document.getElementById('step2-btn-generate').style.display = 'inline-flex';
      document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> AI 生成分镜`;
    } else {
      // 手动模式新建项目：必须显示"添加幻灯片"和"批量导入"，否则用户无法开始
      document.getElementById('step2-btn-add-slide').style.display = 'inline-flex';
      document.getElementById('step2-btn-batch-import').style.display = 'inline-flex';
    }
    document.getElementById('step2-btn-save').style.display = 'none';
    document.getElementById('step2-btn-next').style.display = 'none';
    updateStep2AutosaveStatus('');
  }
}

function isManualMode() {
  return document.body.classList.contains('mode-manual');
}

function step2SlideHasStructuredVisuals(slide) {
  return Array.isArray(slide?.visual_groups) && slide.visual_groups.length > 0;
}

// ==================== 手动模式：添加幻灯片 + 批量导入 ====================

// 从当前 state.slides 收集手动分镜数据（用于提交 manual-skeleton 接口）
function collectManualSlidesFromState() {
  return (state.slides || []).map((slide, index) => {
    const narration = (slide.narration_beats || [])
      .map(b => b.spoken_text || b.spoken_intent || '')
      .filter(Boolean)
      .join('\n');
    return {
      slide_id: slide.slide_id || `slide_${String(index + 1).padStart(3, '0')}`,
      main_title: slide.main_title || '',
      narration,
    };
  });
}

// 添加一页空白幻灯片到 state.slides 末尾并切换过去
function addManualSlide() {
  if (!state.slides) state.slides = [];
  saveCurrentSlideInputToState();
  const newIndex = state.slides.length;
  const newSlideId = `slide_${String(newIndex + 1).padStart(3, '0')}`;
  state.slides.push({
    slide_id: newSlideId,
    main_title: '',
    core_message: '',
    visual_groups: [],
    narration_beats: [{
      id: `beat_001`,
      group_id: null,
      content_unit_id: `${newSlideId}_unit_001`,
      visible_anchor: '',
      spoken_intent: '',
      spoken_text: '',
    }],
  });
  state.activeSlideIndex = newIndex;
  renderStep2Workspace();
  updateStep2AutosaveStatus('未保存草稿');
  // 焦点放到标题输入框
  requestAnimationFrame(() => {
    document.getElementById('step2-slide-title-input')?.focus();
  });
}

// 提交手动分镜到后端（手动模式下点击"进入图片生成"时调用）
async function submitManualSkeletonIfNeeded() {
  if (!state.currentProject || !isManualMode()) return true;
  const slides = collectManualSlidesFromState();
  if (!slides.length) {
    showToast('⚠️ 请至少添加一页幻灯片');
    return false;
  }
  for (let i = 0; i < slides.length; i++) {
    if (!slides[i].main_title) {
      showToast(`⚠️ 第 ${i + 1} 页标题不能为空`);
      return false;
    }
    if (!slides[i].narration) {
      showToast(`⚠️ 第 ${i + 1} 页演讲稿不能为空`);
      return false;
    }
  }
  try {
    const res = await saveStep2Contract({ silent: true });
    if (res && res.success && res.validation?.valid !== false) {
      await loadStep2Data();
      return true;
    }
    showToast('⚠️ 分镜结构尚未通过校验，请检查当前页内容');
    return false;
  } catch (e) {
    showToast('⚠️ 保存失败：' + (e && e.message ? e.message : String(e)));
    return false;
  }
}

// ==================== 批量导入弹窗 ====================

const STEP2_BATCH_TEMPLATE = `[
  {
    "main_title": "第一页标题",
    "narration": "第一页要朗读的演讲稿，可多行。"
  },
  {
    "main_title": "第二页标题",
    "narration": "第二页要朗读的演讲稿。"
  }
]
`;

function openStep2BatchImportModal() {
  document.getElementById('step2-batch-import-preview').style.display = 'none';
  document.getElementById('step2-batch-import-preview').innerHTML = '';
  document.getElementById('step2-batch-import-file').value = '';
  document.getElementById('btn-step2-batch-import-append').disabled = true;
  document.getElementById('btn-step2-batch-import-overwrite').disabled = true;
  document.getElementById('modal-step2-batch-import').style.display = 'flex';
}

function closeStep2BatchImportModal() {
  document.getElementById('modal-step2-batch-import').style.display = 'none';
}

function downloadStep2BatchTemplate() {
  const blob = new Blob([STEP2_BATCH_TEMPLATE], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '手动分镜模板.txt';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

let step2BatchImportPending = null;

function handleStep2BatchImportFile(event) {
  const file = event.target.files && event.target.files[0];
  const previewEl = document.getElementById('step2-batch-import-preview');
  const appendBtn = document.getElementById('btn-step2-batch-import-append');
  const overwriteBtn = document.getElementById('btn-step2-batch-import-overwrite');
  step2BatchImportPending = null;
  appendBtn.disabled = true;
  overwriteBtn.disabled = true;
  previewEl.style.display = 'none';
  previewEl.innerHTML = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    let parsed = null;
    let parseError = '';
    try {
      parsed = JSON.parse(String(reader.result || ''));
    } catch (e) {
      parseError = String(e.message || e);
    }
    if (!Array.isArray(parsed)) {
      previewEl.style.display = 'block';
      previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件内容不是 JSON 数组${parseError ? '：' + escHtml(parseError) : ''}</div>`;
      return;
    }
    const slides = [];
    for (let i = 0; i < parsed.length; i++) {
      const item = parsed[i] || {};
      const title = String(item.main_title || '').trim();
      const narration = String(item.narration || '').trim();
      if (!title || !narration) {
        previewEl.style.display = 'block';
        previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 第 ${i + 1} 项缺少 main_title 或 narration 字段</div>`;
        return;
      }
      slides.push({ main_title: title, narration });
    }
    if (!slides.length) {
      previewEl.style.display = 'block';
      previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件中没有有效条目</div>`;
      return;
    }
    step2BatchImportPending = slides;
    previewEl.style.display = 'block';
    const currentCount = (state.slides || []).length;
    previewEl.innerHTML = `
      <div class="step2-batch-import-summary">
        <strong>已解析 ${slides.length} 页分镜：</strong>
        <ul>
          ${slides.slice(0, 5).map((s, i) => `<li>第 ${i + 1} 页 · ${escHtml(s.main_title)}</li>`).join('')}
          ${slides.length > 5 ? `<li>... 还有 ${slides.length - 5} 页</li>` : ''}
        </ul>
        <div class="step2-batch-import-hint">当前已有 ${currentCount} 页。追加导入后将变成 ${currentCount + slides.length} 页；覆盖导入将清空现有分镜后导入 ${slides.length} 页。</div>
      </div>
    `;
    appendBtn.disabled = false;
    overwriteBtn.disabled = false;
  };
  reader.onerror = () => {
    previewEl.style.display = 'block';
    previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件读取失败</div>`;
  };
  reader.readAsText(file, 'utf-8');
}

async function submitStep2BatchImport(mode) {
  if (!state.currentProject || !step2BatchImportPending) return;
  const importedSlides = step2BatchImportPending;
  saveCurrentSlideInputToState();
  const existingSlides = mode === 'append' ? state.slides.slice() : [];
  const usedIds = new Set(existingSlides.map(slide => String(slide.slide_id || '')));
  let nextNumber = existingSlides.length + 1;
  const newSlides = importedSlides.map(item => {
    let slideId = '';
    do {
      slideId = `slide_${String(nextNumber++).padStart(3, '0')}`;
    } while (usedIds.has(slideId));
    usedIds.add(slideId);
    return {
      slide_id: slideId,
      main_title: item.main_title,
      subtitle: '',
      core_message: item.narration,
      body_content: [item.narration],
      visual_groups: [],
      narration_beats: [{
        id: `${slideId}_beat_001`,
        group_id: null,
        content_unit_id: `${slideId}_unit_001`,
        visible_anchor: '',
        spoken_intent: item.main_title,
        spoken_text: item.narration,
      }],
    };
  });
  state.slides = existingSlides.concat(newSlides);
  state.activeSlideIndex = mode === 'append' ? existingSlides.length : 0;
  try {
    // 批量导入刚构造完 slides，不能再让 saveStep2Contract 用旧编辑框内容
    // 覆盖新导入的第一项标题/正文（skipCurrentSlideSync）。
    const res = await saveStep2Contract({ silent: true, skipCurrentSlideSync: true });
    if (res && res.success && res.validation?.valid !== false) {
      showToast(`✅ 已${mode === 'append' ? '追加' : '覆盖'}导入 ${importedSlides.length} 页分镜`);
      closeStep2BatchImportModal();
      await loadStep2Data();
    } else {
      showToast('⚠️ 导入失败');
    }
  } catch (e) {
    showToast('⚠️ 导入失败：' + (e && e.message ? e.message : String(e)));
  }
}

function openStep2GenerationModal() {
  const input = document.getElementById('step2-generation-requirement');
  input.value = state.step2GenerationRequirement || '';
  document.getElementById('modal-step2-generate').style.display = 'flex';
  input.focus();
}

function closeStep2GenerationModal() {
  document.getElementById('modal-step2-generate').style.display = 'none';
}

function setStep2GenerationStatus(message = '', type = '') {
  const status = document.getElementById('step2-generation-status');
  if (!status) return;
  status.textContent = message;
  status.className = `step2-generation-status${type ? ` ${type}` : ''}`;
  status.style.display = message ? 'block' : 'none';
}

async function confirmStep2Generation() {
  const userRequirement = document.getElementById('step2-generation-requirement').value.trim();
  state.step2GenerationRequirement = userRequirement;
  closeStep2GenerationModal();
  await generateStep2Contract(userRequirement);
}

async function generateStep2Contract(requirement = '') {
  const normalizedRequirement = String(requirement || '').trim();
  setStep2GenerationStatus('');
  document.getElementById('step2-loading').style.display = 'block';
  document.getElementById('step2-btn-generate').disabled = true;
  const loadingText = document.querySelector('#step2-loading p');
  const originalLoadingText = loadingText?.innerText || '';
  
  try {
    if (loadingText) loadingText.innerText = 'Step 2A：AI 正在规划每页标题、正文要点和演讲稿...';
    const scriptPayload = normalizedRequirement ? { requirement: normalizedRequirement } : {};
    // LLM 规划可能超过 2 分钟（后端 STEP2_LLM_TIMEOUT_SEC=240s），给足前端超时。
    const scriptRes = await API.post(
      `/api/projects/${state.currentProject.id}/steps/2/script/execute`,
      scriptPayload,
      { timeoutMs: 300000 },
    );
    if (!scriptRes.success) {
      showToast(`❌ 错误: ${scriptRes.message || 'Step 2A 生成失败'}`);
      return;
    }
    if (loadingText) loadingText.innerText = 'Step 2B：AI 正在根据演讲稿规划画面语义块...';
    const visualRes = await API.post(
      `/api/projects/${state.currentProject.id}/steps/2/visual/execute`,
      undefined,
      { timeoutMs: 300000 },
    );
    if (!visualRes.success) {
      showToast(`❌ 错误: ${visualRes.message || 'Step 2B 生成失败'}`);
      return;
    }
    if (loadingText) loadingText.innerText = 'Step 2C：正在合成可用于生图、Mask 和旁白绑定的 visual_contract...';
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/compose`);
    if (!res.success) {
      showToast(`❌ 错误: ${res.message || 'Step 2 合成失败'}`);
      return;
    }
    showToast('🎉 Narration-first 分镜规划已生成！');
    setStep2GenerationStatus('');
    state.slides = res.contract?.slides || [];
    renderStep2Workspace();
  } catch(e) {
    const message = e?.message || '分镜生成失败，请稍后重试。';
    console.error('Step 2 generation failed:', e);
    setStep2GenerationStatus(`分镜生成失败：${message}`, 'error');
  } finally {
    if (loadingText) loadingText.innerText = originalLoadingText;
    document.getElementById('step2-loading').style.display = 'none';
    document.getElementById('step2-btn-generate').disabled = false;
  }
}

function renderStep2Workspace() {
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = Math.max(0, state.slides.length - 1);
  }
  const manual = isManualMode();
  const hasSlides = state.slides.length > 0;
  document.getElementById('step2-editor-area').style.display = hasSlides ? 'block' : 'none';
  // 按钮显隐：自动模式显示 AI 生成分镜/文章slides/可视化；手动模式显示 添加幻灯片/批量导入
  const generateBtn = document.getElementById('step2-btn-generate');
  const scriptPromptBtn = document.getElementById('step2-btn-script-prompt');
  const visualPromptBtn = document.getElementById('step2-btn-visual-prompt');
  const addSlideBtn = document.getElementById('step2-btn-add-slide');
  const batchImportBtn = document.getElementById('step2-btn-batch-import');
  if (manual) {
    if (generateBtn) generateBtn.style.display = 'none';
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'none';
    if (visualPromptBtn) visualPromptBtn.style.display = 'none';
    if (addSlideBtn) addSlideBtn.style.display = 'inline-flex';
    if (batchImportBtn) batchImportBtn.style.display = 'inline-flex';
  } else {
    if (generateBtn) {
      generateBtn.style.display = 'inline-flex';
      generateBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> AI 生成分镜`;
    }
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'inline-flex';
    if (visualPromptBtn) visualPromptBtn.style.display = 'inline-flex';
    if (addSlideBtn) addSlideBtn.style.display = 'none';
    if (batchImportBtn) batchImportBtn.style.display = 'none';
  }
  document.getElementById('step2-btn-save').style.display = 'inline-flex';
  const step2NextButton = document.getElementById('step2-btn-next');
  step2NextButton.style.display = 'inline-flex';
  step2NextButton.disabled = !hasSlides;
  step2NextButton.title = hasSlides ? '' : '请先添加至少一个分镜';
  updateStep2BatchDeleteButton();

  // 渲染精简版横向缩略图（只显示 Slide 序号）
  const thumbsContainer = document.getElementById('step2-thumbs');
  thumbsContainer.style.display = 'flex'; // 显式呈现
  thumbsContainer.classList.toggle('step2-batch-delete-mode', state.step2BatchDeleteMode);
  thumbsContainer.innerHTML = '';

  if (!hasSlides) {
    thumbsContainer.innerHTML = '<div class="step2-empty-storyboard" role="status">当前没有分镜，可添加幻灯片、批量导入或重新生成。</div>';
  }

  state.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card step2-slide-thumb ${idx === state.activeSlideIndex ? 'active' : ''}`;
    thumb.style.cssText = 'min-width: 112px; max-width: 112px; min-height: 42px; padding: 0.55rem 1.75rem 0.55rem 0.65rem; cursor: pointer; display: flex; align-items: center; justify-content: center;';
    const slideTitle = (slide.main_title || '').trim() || `第 ${idx + 1} 页`;
    thumb.innerHTML = `
      ${state.step2BatchDeleteMode ? `
        <button class="step2-thumb-delete" type="button" title="删除此分镜" aria-label="删除此分镜">
          <svg class="icon" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
        </button>
      ` : ''}
      <div style="font-size: 0.78rem; font-weight: 800; color: #111; text-align: center; line-height: 1.2; word-break: break-all; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;" title="${escHtml(slideTitle)}">${escHtml(slideTitle)}</div>
    `;
    thumb.addEventListener('click', () => {
      if (state.step2BatchDeleteMode) {
        return;
      }
      saveCurrentSlideInputToState();
      state.activeSlideIndex = idx;
      renderStep2Workspace();
    });
    const deleteBtn = thumb.querySelector('.step2-thumb-delete');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        removeStep2DraftSlide(slide.slide_id);
      });
    }
    thumbsContainer.appendChild(thumb);
  });

  // 加载当前 Slide 详情
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    const structuredManualSlide = manual && step2SlideHasStructuredVisuals(slide);
    if (!manual) {
      syncStep2SimpleFieldsToInternalGroups(slide);
    }
    const slideIdEl = document.getElementById('step2-current-slide-id');
    const slideTitleEl = document.getElementById('step2-current-slide-title');
    if (slideIdEl) slideIdEl.innerText = slide.slide_id;
    if (slideTitleEl) slideTitleEl.innerText = slide.main_title || '未命名 Slide';
    // 同步隐藏字段
    document.getElementById('step2-main-title').value = slide.main_title || '';
    document.getElementById('step2-core-message').value = slide.core_message || '';

    const titleInput = document.getElementById('step2-slide-title-input');
    const narrationInput = document.getElementById('step2-slide-narration-input');
    if (titleInput) titleInput.value = slide.main_title || '';
    if (narrationInput) {
      // 纯手动分镜可直接编辑整页演讲稿；已有视觉映射时按语块编辑，避免覆盖其余语块。
      narrationInput.readOnly = !manual || structuredManualSlide;
      narrationInput.value = step2NarrationText(slide);
    }
    [titleInput, narrationInput].forEach(input => {
      if (!input || input.dataset.boundStep2SimpleEditor === '1') return;
      input.dataset.boundStep2SimpleEditor = '1';
      input.addEventListener('input', () => {
        if (input.tagName === 'TEXTAREA') autoResizeTextarea(input);
        const activeSlide = state.slides?.[state.activeSlideIndex];
        if (isManualMode() && !step2SlideHasStructuredVisuals(activeSlide)) {
          saveManualNarrationInputToState(input);
        } else {
          saveCurrentSlideInputToState();
        }
        scheduleStep2AutoSave();
      });
      input.addEventListener('blur', () => {
        if (input.tagName !== 'TEXTAREA') return;
        normalizeAndResizeStep2Textarea(input);
        const activeSlide = state.slides?.[state.activeSlideIndex];
        if (isManualMode() && !step2SlideHasStructuredVisuals(activeSlide)) {
          saveManualNarrationInputToState(input);
        } else {
          saveCurrentSlideInputToState();
        }
        scheduleStep2AutoSave();
      });
    });
    requestAnimationFrame(() => autoResizeTextarea(narrationInput));
    // 纯手动分镜没有视觉映射；已有结构化视觉时始终显示逐语块编辑器。
    const vnMap = document.getElementById('step2-visual-narration-map');
    if (manual && !structuredManualSlide) {
      if (vnMap) vnMap.style.display = 'none';
    } else {
      if (vnMap) vnMap.style.display = '';
      renderStep2VisualNarrationMap(slide);
    }
  }
}

// 手动模式下：把演讲稿输入写回当前 slide 的 narration_beats[0].spoken_text
function saveManualNarrationInputToState(input) {
  const slide = state.slides && state.slides[state.activeSlideIndex];
  if (!slide) return;
  if (step2SlideHasStructuredVisuals(slide)) return;
  if (input && input.id === 'step2-slide-narration-input') {
    if (!Array.isArray(slide.narration_beats) || !slide.narration_beats.length) {
      slide.narration_beats = [{
        id: 'beat_001',
        group_id: null,
        content_unit_id: `${slide.slide_id}_unit_001`,
        visible_anchor: '',
        spoken_intent: '',
        spoken_text: '',
      }];
    }
    slide.narration_beats[0].spoken_text = input.value;
    // 同步显示在头部
    const titleEl = document.getElementById('step2-current-slide-title');
    // 标题输入也走这个分支
  }
  if (input && input.id === 'step2-slide-title-input') {
    slide.main_title = input.value;
    const titleEl = document.getElementById('step2-current-slide-title');
    if (titleEl) titleEl.innerText = input.value || '未命名 Slide';
  }
}

// 拼接并一键复制所有 Slide 的生图提示词
async function copyStep2Prompts() {
  saveCurrentSlideInputToState();
  
  if (!state.slides || state.slides.length === 0) {
    showToast('⚠️ 暂无分镜规划数据，无法复制提示词');
    return;
  }
  
  if (!String(step3BatchPrompt || '').trim()) {
    try {
      await refreshStep3Prompts();
    } catch (error) {
      // API.fetch 已展示具体错误，这里只阻止复制空内容。
    }
  }
  const allPromptsText = String(step3BatchPrompt || '').trim();
  if (!allPromptsText) {
    showToast('批量提示词加载失败，请稍后重试');
    return;
  }
  
  navigator.clipboard.writeText(allPromptsText).then(() => {
    showToast('📋 已成功复制所有 Slide 的生图提示词到剪贴板！');
  }).catch(err => {
    console.error('复制失败:', err);
    showToast('⚠️ 复制失败，请手动选择复制');
  });
}

function updateStep2BatchDeleteButton() {
  const btn = document.getElementById('step2-btn-save');
  const cancelBtn = document.getElementById('step2-btn-cancel-delete');
  if (!btn) return;
  if (state.step2BatchDeleteMode) {
    btn.className = 'success';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
      保存
    `;
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  } else {
    btn.className = 'secondary';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
      批量删除
    `;
    if (cancelBtn) cancelBtn.style.display = 'none';
  }
}

async function handleStep2BatchDeleteButton() {
  if (!state.slides || state.slides.length === 0) return;
  if (!state.step2BatchDeleteMode) {
    saveCurrentSlideInputToState();
    clearTimeout(state.step2AutoSaveTimer);
    await saveStep2Contract({ silent: true });
    state.step2BatchOriginalSlides = JSON.parse(JSON.stringify(state.slides));
    state.step2BatchOriginalActiveIndex = state.activeSlideIndex;
    state.step2BatchDeleteMode = true;
    state.step2DeleteSelection = new Set();
    renderStep2Workspace();
    showToast('已进入批量删除模式。点卡片右上角删除，此处只临时移除，点击保存后生效。');
    return;
  }
  saveStep2BatchDelete();
}

function removeStep2DraftSlide(slideId) {
  if (!state.step2BatchDeleteMode) return;
  const removedIndex = state.slides.findIndex(slide => slide.slide_id === slideId);
  if (removedIndex < 0) return;
  state.slides.splice(removedIndex, 1);
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = Math.max(0, state.slides.length - 1);
  } else if (removedIndex < state.activeSlideIndex) {
    state.activeSlideIndex -= 1;
  }
  renderStep2Workspace();
}

async function saveStep2BatchDelete() {
  saveCurrentSlideInputToState();
  clearTimeout(state.step2AutoSaveTimer);
  const originalCount = state.step2BatchOriginalSlides?.length || state.slides.length;
  const removedCount = Math.max(0, originalCount - state.slides.length);
  if (removedCount === 0) {
    state.step2BatchDeleteMode = false;
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
    showToast('已退出批量删除模式。');
    return;
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  await saveStep2Contract({ silent: true });
  renderStep2Workspace();
  showToast(`已删除 ${removedCount} 个分镜，并保存当前规划。`);
}

function cancelStep2BatchDelete() {
  if (!state.step2BatchDeleteMode) return;
  if (Array.isArray(state.step2BatchOriginalSlides)) {
    state.slides = JSON.parse(JSON.stringify(state.step2BatchOriginalSlides));
    state.activeSlideIndex = Math.min(state.step2BatchOriginalActiveIndex || 0, Math.max(0, state.slides.length - 1));
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  renderStep2Workspace();
  showToast('已取消批量删除，分镜列表已恢复。');
}

function updateStep2AutosaveStatus(text) {
  const el = document.getElementById('step2-autosave-status');
  if (el) el.innerText = text || '';
}

function scheduleStep2AutoSave() {
  if (state.currentStep !== 2 || !state.currentProject || !state.slides?.length) return;
  if (state.step2BatchDeleteMode) return;
  updateStep2AutosaveStatus('自动保存中...');
  clearTimeout(state.step2AutoSaveTimer);
  state.step2AutoSaveTimer = setTimeout(() => {
    saveStep2Contract({ silent: true, autosave: true });
  }, 700);
}

function step2BodyContentText(slide) {
  const items = Array.isArray(slide?.body_content) ? slide.body_content : [];
  return normalizeStep2MultilineText(items.map(item => String(item || '')).filter(Boolean).join('\n'));
}

function step2NarrationText(slide) {
  const beats = Array.isArray(slide?.narration_beats) ? slide.narration_beats : [];
  const seen = new Set();
  return beats
    .map(beat => normalizeStep2NarrationText(beat?.spoken_text || ''))
    .filter(Boolean)
    .filter(text => {
      const key = narrationDedupeKey(text);
      if (key && seen.has(key)) return false;
      if (key) seen.add(key);
      return true;
    })
    .join('\n');
}

function normalizeStep2MultilineText(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function normalizeStep2NarrationText(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .join('\n');
}

function normalizeAndResizeStep2Textarea(textarea) {
  if (!textarea) return;
  const normalized = textarea.id === 'step2-slide-narration-input'
    ? normalizeStep2NarrationText(textarea.value)
    : normalizeStep2MultilineText(textarea.value);
  if (textarea.value !== normalized) textarea.value = normalized;
  autoResizeTextarea(textarea);
}

function syncStep2SimpleFieldsToInternalGroups(slide) {
  if (!slide || !Array.isArray(slide.visual_groups)) return;
  const title = String(slide.main_title || '').trim();
  const titleGroup = slide.visual_groups.find(group => group?.role === 'title');
  if (titleGroup && title) {
    titleGroup.visible_text = title;
    titleGroup.display_text = title;
    titleGroup.visual_anchor = title;
    titleGroup.mask_target = title;
    titleGroup.visual_type = 'text';
  }
  const subtitleGroupIds = new Set(
    slide.visual_groups
      .filter(group => group?.role === 'subtitle')
      .map(group => group?.id)
      .filter(Boolean),
  );
  slide.subtitle = '';
  slide.visual_groups = slide.visual_groups.filter(group => group?.role !== 'subtitle');
  if (subtitleGroupIds.size && Array.isArray(slide.narration_beats)) {
    slide.narration_beats = slide.narration_beats.filter(beat => !subtitleGroupIds.has(beat?.group_id));
  }
}

function saveCurrentSlideInputToState() {
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    slide.main_title = document.getElementById('step2-slide-title-input')?.value
      ?? document.getElementById('step2-main-title').value;
    slide.subtitle = '';
    slide.core_message = document.getElementById('step2-core-message').value;
    if (isManualMode() && !step2SlideHasStructuredVisuals(slide)) {
      // 手动模式：把演讲稿直接写回 narration_beats[0].spoken_text，不走 visual_groups 同步
      const narration = document.getElementById('step2-slide-narration-input')?.value || '';
      if (!Array.isArray(slide.narration_beats) || !slide.narration_beats.length) {
        slide.narration_beats = [{
          id: 'beat_001',
          group_id: null,
          content_unit_id: `${slide.slide_id}_unit_001`,
          visible_anchor: '',
          spoken_intent: '',
          spoken_text: narration,
        }];
      } else {
        slide.narration_beats[0].spoken_text = narration;
      }
      return;
    }
    syncStep2SimpleFieldsToInternalGroups(slide);
    renderStep2VisualNarrationMap(slide);
  }
}

function renderStep2VisualNarrationMap(slide) {
  const container = document.getElementById('step2-visual-narration-map');
  if (!container) return;
  if (!slide) { container.innerHTML = ''; return; }

  const groups = Array.isArray(slide.visual_groups) ? slide.visual_groups : [];
  const beats = Array.isArray(slide.narration_beats) ? slide.narration_beats : [];
  if (groups.length === 0 && beats.length === 0) {
    container.innerHTML = '';
    return;
  }

  groups.forEach((group, index) => {
    if (!group.id) group.id = `${slide.slide_id}_group_${String(index + 1).padStart(3, '0')}`;
  });
  beats.forEach((beat, index) => {
    if (!beat.id) beat.id = `${slide.slide_id}_beat_${String(index + 1).padStart(3, '0')}`;
  });

  const roleOrder = { title: 0, subtitle: 1, body: 2, body_content: 2, content_body: 2, decoration: 3 };
  const sortedGroups = groups.filter(group => !['subtitle', 'decoration'].includes(String(group?.role || ''))).map((g, i) => ({ g, i })).sort((a, b) => {
    const ra = Number(a.g?.reveal_order ?? roleOrder[a.g?.role] ?? a.i);
    const rb = Number(b.g?.reveal_order ?? roleOrder[b.g?.role] ?? b.i);
    return ra - rb;
  }).map(item => item.g);

  const usedBeatIds = new Set();
  const groupCards = sortedGroups.map((group, idx) => {
    const gid = String(group?.id || '');
    const matched = beats.filter(beat => {
      if (beat?.group_id !== gid) return false;
      usedBeatIds.add(beat.id);
      return true;
    });
    const role = String(group?.role || 'content_body');
    const roleValue = role === 'body' || role === 'body_content' ? 'content_body' : role;
    const visualType = group?.visual_type === 'text' ? 'text' : 'picture';
    const visualContent = visualType === 'text'
      ? String(group?.display_text || group?.visible_text || group?.visual_anchor || '')
      : String(group?.visual_anchor || group?.mask_target || '');
    const typeLabel = visualType === 'text' ? '画面文字' : '画面元素';
    const mappingReady = matched.length === 1 && String(matched[0]?.spoken_text || '').trim();
    const beatsHtml = matched.length
      ? matched.map((beat, beatIndex) => renderStep2EditableBeat(beat, beatIndex, matched.length)).join('')
      : '<div class="vn-beat vn-beat-empty">缺少对应演讲片段，请重新生成 Slides → 可视化。</div>';
    const visualField = visualType === 'text'
      ? `<label class="vn-edit-field">
          <span>画面文字</span>
          <input type="text" value="${escHtml(visualContent)}" data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">
        </label>`
      : `<label class="vn-edit-field">
          <span>画面元素描述</span>
          <textarea rows="4" data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">${escHtml(visualContent)}</textarea>
        </label>`;

    return `
      <div class="vn-group-card vn-role-${escHtml(roleValue)}" data-group-id="${escHtml(gid)}">
        <div class="vn-group-head">
          <span class="vn-group-num">${idx + 1}</span>
          <span class="vn-type-tag">${typeLabel}</span>
          <span class="vn-map-arrow" aria-hidden="true">→</span>
          <span class="vn-map-target">对应演讲片段</span>
          <span class="vn-beat-count${mappingReady ? '' : ' is-error'}">${mappingReady ? '已对应' : '需要检查'}</span>
        </div>
        <div class="vn-group-body">
          <div class="vn-visual">
            ${visualField}
          </div>
          <div class="vn-narration">
            ${beatsHtml}
          </div>
        </div>
      </div>`;
  }).join('');

  const orphanBeats = beats.filter(beat => !usedBeatIds.has(beat.id));
  const orphanHtml = orphanBeats.length
    ? `<div class="vn-orphan">
        <div class="vn-orphan-head">发现 ${orphanBeats.length} 段没有对应画面的演讲片段</div>
        <div class="vn-orphan-hint">当前结构不允许手动选择内部 ID，请重新生成 Slides → 可视化，让系统重新建立一对一关系。</div>
        ${orphanBeats.map((beat, index) => renderStep2EditableBeat(beat, index, orphanBeats.length)).join('')}
      </div>`
    : '';

  container.innerHTML = `
    <div class="vn-map-title">画面与演讲片段</div>
    <div class="vn-map-hint">每张卡片就是一个 Reveal 单元：左侧是实际画面内容，右侧是该画面出现时播放的演讲片段；两侧内容保持一一对应。</div>
    <div class="vn-groups">${groupCards}</div>
    ${orphanHtml}`;
}

function renderStep2EditableBeat(beat, index = 0, total = 1) {
  const beatId = String(beat?.id || '');
  return `<div class="vn-beat" data-beat-id="${escHtml(beatId)}">
    <label class="vn-edit-field">
      <span>${total > 1 ? `演讲片段 ${index + 1}（应合并为一段）` : '演讲片段'}</span>
      <textarea rows="3" data-step2-beat-id="${escHtml(beatId)}" data-step2-beat-field="spoken_text">${escHtml(beat?.spoken_text || '')}</textarea>
    </label>
  </div>`;
}

function currentStep2EditorSlide() {
  return state.slides?.[state.activeSlideIndex] || null;
}

function handleStep2MapEditorInput(event) {
  const target = event.target;
  const slide = currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  const groupId = target.dataset.step2GroupId;
  const groupField = target.dataset.step2GroupField;
  const beatId = target.dataset.step2BeatId;
  const beatField = target.dataset.step2BeatField;
  let changed = false;

  if (groupId && groupField === 'visual_content') {
    const group = slide.visual_groups?.find(item => item?.id === groupId);
    if (group) {
      const value = target.value;
      if (group.visual_type === 'text') {
        group.visible_text = value;
        group.display_text = value;
        group.visual_anchor = value;
        group.mask_target = value;
        group.narration_function = value;
        slide.narration_beats?.filter(beat => beat?.group_id === groupId).forEach(beat => { beat.visible_anchor = value; });
        if (group.role === 'title') slide.main_title = value;
      } else {
        group.mask_target = value;
        group.visual_anchor = value;
        group.narration_function = value || group.visible_text || '';
        slide.narration_beats?.filter(beat => beat?.group_id === groupId).forEach(beat => {
          beat.spoken_intent = group.narration_function;
        });
      }
      changed = true;
    }
  }

  if (beatId && beatField === 'spoken_text') {
    const beat = slide.narration_beats?.find(item => item?.id === beatId);
    if (beat) {
      beat.spoken_text = target.value;
      changed = true;
    }
  }

  if (!changed) return;
  syncStep2SummaryInputs(slide);
  scheduleStep2AutoSave();
}

function handleStep2MapEditorChange(event) {
  const target = event.target;
  const slide = currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  if (target.tagName === 'TEXTAREA') autoResizeTextarea(target);
  syncStep2SummaryInputs(slide);
  scheduleStep2AutoSave();
}

function syncStep2SummaryInputs(slide) {
  const titleInput = document.getElementById('step2-slide-title-input');
  const narrationInput = document.getElementById('step2-slide-narration-input');
  const heading = document.getElementById('step2-current-slide-title');
  if (titleInput && document.activeElement !== titleInput) titleInput.value = slide.main_title || '';
  if (heading) heading.textContent = slide.main_title || '未命名 Slide';
  if (narrationInput && document.activeElement !== narrationInput) {
    narrationInput.value = step2NarrationText(slide);
    autoResizeTextarea(narrationInput);
  }
}

async function saveStep2Contract(options = {}) {
  if (!options.skipCurrentSlideSync) {
    saveCurrentSlideInputToState();
  }
  const pureManualContract = isManualMode()
    && state.slides.every(slide => !step2SlideHasStructuredVisuals(slide));
  const payload = {
    version: "visual_contract_v1",
    topic: state.currentProject.topic || {
      topic_id: "topic_" + state.currentProject.id,
      topic_name: state.currentProject.name
    },
    presentation_policy: pureManualContract ? {
      subtitle_policy: 'forbidden',
      subtitle_decided_by: 'manual_mode',
      visual_narration_mapping: 'manual_free_v1'
    } : (state.step2PresentationPolicy || {}),
    slides: state.slides
  };
  
  if (state.step2AutoSaveInFlight && options.autosave) {
    scheduleStep2AutoSave();
    return { success: false };
  }
  state.step2AutoSaveInFlight = true;
  try {
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/result`, payload);
    if (res.success) {
      state.step2PresentationPolicy = res.contract?.presentation_policy || payload.presentation_policy;
      updateStep2AutosaveStatus(options.autosave ? '已自动保存' : '');
      if (!options.silent) {
        showToast('💾 分镜规划已成功保存！');
      }
    }
    return res;
  } finally {
    state.step2AutoSaveInFlight = false;
    if (options.autosave) {
      setTimeout(() => updateStep2AutosaveStatus(''), 1400);
    }
  }
}

