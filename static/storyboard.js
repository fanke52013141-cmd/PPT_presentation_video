// Step 2 storyboard data, generation, editing, batch import, and persistence.
// Shared helpers and globals are provided by ui_foundation.js / workflow_state.js / api_client.js; public functions remain global for classic-script compatibility.

let step2ScriptSaveTimer = null;
let step2ScriptSavePromise = null;

let step2TaskPhases = {};
function refreshStep2TaskStates() {
  const script = step2TaskPhases.script || (state.step2ScriptPlan?.slides?.length ? 'done' : 'pending');
  const visual = step2TaskPhases.visual || (state.step2VisualExists && !state.step2VisualStale ? 'done' : 'pending');
  const labels = {running: '生成中', done: '已生成', pending: '待生成', error: '生成失败', paused: '已停止'};
  setUiTaskState(document.getElementById('step2-script-task-status'), script, labels[script]);
  setUiTaskState(document.getElementById('step2-visual-task-status'), visual, labels[visual]);
}
function setStep2TaskPhase(phase, status) {
  if (status === 'done') delete step2TaskPhases[phase];
  else step2TaskPhases[phase] = status;
  refreshStep2TaskStates();
  document.getElementById('step-panel-2')?.classList.toggle('is-generating-storyboard', Object.values(step2TaskPhases).includes('running'));
  renderPageTaskState(document.getElementById('step2-loading'), 'storyboard', Object.values(step2TaskPhases).includes('running') ? 'running' : null, phase === 'script' ? '正在生成每页演讲稿' : '正在生成画面文字与演讲片段', phase === 'script' ? 'text' : 'mapping');
  const host = document.getElementById(phase === 'script' ? 'step2-script-slides' : 'step2-script-visuals');
  const labels = {running: phase === 'script' ? '正在生成每页演讲稿' : '正在生成画面文字与演讲片段', error: '生成失败，请重试', paused: '生成已停止'};
  renderPageTaskState(host, phase, status === 'done' ? null : status, labels[status], phase === 'script' ? 'text' : 'mapping');
}

function step2CurrentProjectId() {
  return String(state.currentProject?.id || '');
}

// 工具栏生成按钮带图标：文案写入 .btn-label，避免覆盖 SVG。
function setStep2ButtonLabel(button, text) {
  if (!button) return;
  const label = button.querySelector('.btn-label');
  if (label) label.textContent = text;
  else button.textContent = text;
}

// 「内容可视化」只有全部页面演讲稿生成完毕后才可点击。
function step2VisualButtonReady() {
  return Boolean(state.step2ScriptPlan?.slides?.length)
    && state.step2ScriptPlan.slides.every(slide => String(slide.narration || '').trim());
}

function resetStep2ScriptState() {
  document.getElementById("step-panel-2")?.classList.remove("is-generating-storyboard");
  step2TaskPhases = {};
  if (step2ScriptSaveTimer) clearTimeout(step2ScriptSaveTimer);
  step2ScriptSaveTimer = null;
  state.step2ScriptPlan = null;
  state.step2VisualStale = false;
  state.step2VisualExists = false;
  state.step2WorkflowPending = false;
  state.step2Stage = 'script';
}

async function loadStep2Data() {
  const projectId = state.currentProject?.id;
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return;
  state.step2ScriptPlan = null;
  try {
    const configRes = await API.get(`/api/projects/${projectId}/steps/2/rules`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  } catch (e) {}
  const res = await API.getOptional(`/api/projects/${projectId}/steps/2/result`);
  if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
  try {
    const scriptRes = await API.getOptional(`/api/projects/${projectId}/steps/2/script/result`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    state.step2ScriptPlan = scriptRes.success ? scriptRes.script_plan : null;
  } catch (e) {
    state.step2ScriptPlan = null;
  }
  try {
    const visualPlanRes = await API.getOptional(`/api/projects/${projectId}/steps/2/visual/result`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return;
    state.step2VisualExists = visualPlanRes.success === true;
    const step2Status = state.currentProject?.step_status?.['2'];
    state.step2WorkflowPending = Boolean(step2Status && step2Status !== 'completed');
    state.step2VisualStale = visualPlanRes.stale === true
      || (state.step2WorkflowPending && state.step2VisualExists);
  } catch (e) {
    state.step2VisualExists = false;
    state.step2VisualStale = false;
    const step2Status = state.currentProject?.step_status?.['2'];
    state.step2WorkflowPending = Boolean(step2Status && step2Status !== 'completed');
  }
  if (res.success && res.contract) {
    state.slides = res.contract.slides || [];
    state.step2VisualExists = state.step2VisualExists || state.slides.length > 0;
    state.step2VisualStale = state.step2VisualStale
      || (state.step2WorkflowPending && state.step2VisualExists && !!state.step2ScriptPlan?.slides?.length);
    state.step2PresentationPolicy = res.contract.presentation_policy || {};
    state.step2ContractSha256 = res.contract_sha256 || null;
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    state.step2Stage = state.step2VisualStale ? 'script' : 'visual';
    renderStep2Workspace();
    if (!isManualMode() && state.step2ScriptPlan?.slides?.length) updateStep2AutosaveStatus('');
    void offerArtifactRepair(res, '分镜数据', loadStep2Data);
  } else {
    state.slides = [];
    state.step2PresentationPolicy = {};
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    state.step2Stage = 'script';
    state.step2WorkflowPending = true;
    renderStep2Workspace();
    updateStep2AutosaveStatus('');
  }
}


function isManualMode() {
  return document.body.classList.contains('mode-manual');
}

function step2SlideHasStructuredVisuals(slide) {
  return Array.isArray(slide?.visual_groups) && slide.visual_groups.length > 0;
}

function openStep2ScriptStage() {
  if (!state.step2ScriptPlan) {
    openStep2GenerationModal();
    return;
  }
  state.step2Stage = 'script';
  renderStep2Workspace();
}

async function generateStep2ScriptPlan(requirement = '') {
  const projectId = step2CurrentProjectId();
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return false;
  const scriptButton = document.getElementById('step2-btn-generate-script');
  const visualButton = document.getElementById('step2-btn-generate-visual');
  const loading = document.getElementById('step2-loading');
  const loadingText = document.querySelector('#step2-loading p');
  const oldLoadingText = loadingText?.textContent || '';
  if (scriptButton) scriptButton.disabled = true;
  // 生成演讲稿期间「内容可视化」保持可见但不可点击（UI 规范 §8）。
  if (visualButton) visualButton.disabled = true;
  if (loading) loading.style.display = 'block';
  setStep2TaskPhase('script', 'running');
  if (loadingText) loadingText.textContent = '第一步：AI 正在根据文章生成每页标题和演讲稿…';
  setStep2GenerationStatus('');
  try {
    if (state.step2ScriptPlan && !(await saveStep2ScriptPlan({ silent: true }))) {
      throw new Error('当前演讲稿未能保存，请检查后重试');
    }
    const payload = String(requirement || '').trim() ? { requirement: String(requirement).trim() } : {};
    const response = await API.post(
      `/api/projects/${projectId}/steps/2/script/execute`,
      payload,
      { timeoutMs: 900000 },
    );
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (response.cancelled) {
      setStep2TaskPhase('script', 'paused');
      updateStep2AutosaveStatus(response.message || '演讲稿生成已停止');
      return false;
    }
    if (!response.success || !response.script_plan) throw new Error(response.message || '演讲稿生成失败');
    state.step2ScriptPlan = response.script_plan;
    if (typeof response.visual_exists === 'boolean') state.step2VisualExists = response.visual_exists;
    if (typeof response.workflow_pending === 'boolean') state.step2WorkflowPending = response.workflow_pending;
    state.step2VisualStale = response.visual_stale === true
      || (state.step2WorkflowPending && state.step2VisualExists);
    state.step2Stage = 'script';
    renderStep2Workspace();
    if (response.workflow_changed) refreshCurrentProjectStatus(2).catch(() => {});
    setStep2TaskPhase('script', 'done');
    showToast('演讲稿已生成');
    return true;
  } catch (error) {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      setStep2TaskPhase('script', 'error');
      setStep2GenerationStatus(`演讲稿生成失败：${error?.message || error}`, 'error');
    }
    return false;
  } finally {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      if (loadingText) loadingText.textContent = oldLoadingText;
      if (loading) loading.style.display = 'none';
      if (scriptButton) scriptButton.disabled = false;
      // 全部页面演讲稿生成完毕后才恢复「内容可视化」。
      if (visualButton) visualButton.disabled = !step2VisualButtonReady();
    }
  }
}

// 二级菜单 Tab 数据源：合约分镜优先；仅有演讲稿时由演讲稿页面充当分页。
function step2TabSourceSlides() {
  if (!isManualMode() && state.step2ScriptPlan?.slides?.length) {
    return state.step2ScriptPlan.slides.map((slide, index) => ({
      slide_id: slide.slide_id || `slide_${String(index + 1).padStart(3, '0')}`,
      main_title: slide.slide_title || '',
      narration_text: slide.narration || '',
    }));
  }
  if ((state.slides || []).length) return state.slides;
  const planSlides = state.step2ScriptPlan?.slides || [];
  return planSlides.map((slide, index) => ({
    slide_id: slide.slide_id || `slide_${String(index + 1).padStart(3, '0')}`,
    main_title: slide.slide_title || '',
    narration_text: slide.narration || '',
  }));
}

// 当前激活页对应的演讲稿页（引用保持在 plan.slides 内，编辑直接写回）。
function step2ActivePlanSlide() {
  const plan = state.step2ScriptPlan;
  if (!plan?.slides?.length) return null;
  const source = step2TabSourceSlides();
  const tabSlide = source[Math.min(Math.max(state.activeSlideIndex, 0), source.length - 1)];
  const byId = plan.slides.find(item => String(item.slide_id || '') === String(tabSlide?.slide_id || ''));
  return byId || plan.slides[Math.min(state.activeSlideIndex, plan.slides.length - 1)] || null;
}

function renderStep2ScriptVisualStage(planSlide) {
  const container = document.getElementById('step2-script-visuals');
  if (!container) return;
  const stage = container.closest('.step2-stage--visual');
  if (stage) stage.style.display = state.step2VisualExists ? '' : 'none';
  if (!state.step2VisualExists) {
    container.replaceChildren();
    return;
  }
  const visualById = new Map((state.slides || []).map(slide => [String(slide.slide_id || ''), slide]));
  const visual = visualById.get(String(planSlide?.slide_id || ''));
  if (visual && !state.step2VisualStale && !state.step2WorkflowPending) {
    renderStep2VisualNarrationMap(visual, container);
  } else if (state.step2VisualStale && state.step2VisualExists) {
    container.innerHTML = '<p class="step2-visual-pending">演讲稿已修改，请点击工具栏“重新生成可视化”更新本页画面与演讲片段。</p>';
  } else {
    container.innerHTML = '<p class="step2-visual-pending">本页尚未生成。点击工具栏“内容可视化”，生成第二步画面与演讲片段。</p>';
  }
}

function renderStep2ScriptReview() {
  const section = document.getElementById('step2-script-review');
  const list = document.getElementById('step2-script-slides');
  if (!section || !list) return;
  const plan = state.step2ScriptPlan;
  const visible = !isManualMode() && !!plan?.slides?.length;
  section.style.display = visible ? 'block' : 'none';
  if (!visible) return;
  // 参考稿结构：一次只显示当前页的演讲稿（分页由上方二级菜单切换）。
  const planSlide = step2ActivePlanSlide();
  if (!planSlide) { list.innerHTML = ''; return; }
  const slideIndex = plan.slides.indexOf(planSlide);
  const pageNumber = Math.min(Math.max(state.activeSlideIndex, 0), step2TabSourceSlides().length - 1) + 1;
  const wordCount = String(planSlide.narration || '').trim().length;
  const count = document.querySelector('[data-step2-word-count]');
  if (count) count.textContent = `共 ${wordCount} 字`;
  list.innerHTML = `
    <article class="step2-script-slide" data-script-slide-index="${slideIndex}">
      <label class="step2-script-field step2-script-field--title">
        <span>标题</span>
        <input type="text" data-script-field="slide_title" aria-label="第 ${pageNumber} 页标题" value="${escHtml(planSlide.slide_title || '')}">
      </label>
      <div class="step2-script-field step2-script-field--narration">
        <div class="step2-script-field-head">
          <label><span>演讲稿</span></label>

        </div>
        <textarea rows="1" data-script-field="narration" aria-label="第 ${pageNumber} 页演讲稿">${escHtml(planSlide.narration || '')}</textarea>
      </div>
    </article>
  `;
  renderStep2ScriptVisualStage(planSlide);
  const visualButton = document.getElementById('step2-btn-generate-visual');
  if (visualButton) {
    visualButton.disabled = !step2VisualButtonReady();
    setStep2ButtonLabel(visualButton, state.step2VisualStale ? '重新生成可视化' : '内容可视化');
  }
  list.querySelectorAll('[data-script-field]').forEach(input => {
    input.addEventListener('input', () => {
      const card = input.closest('[data-script-slide-index]');
      const slide = plan.slides[Number(card?.dataset.scriptSlideIndex)];
      if (!slide) return;
      slide[input.dataset.scriptField] = input.value;
      if (visualButton) visualButton.disabled = !step2VisualButtonReady();
      state.step2VisualStale = state.step2VisualExists;
      if (state.step2VisualStale) {
        renderStep2ScriptVisualStage(slide);
        const nextButton = document.getElementById('step2-btn-next');
        if (nextButton) nextButton.disabled = true;
      }
      if (input.dataset.scriptField === 'narration') {
        autoResizeNarrationTextarea(input);
        const count = document.querySelector('[data-step2-word-count]');
        if (count) count.textContent = `共 ${String(input.value || '').trim().length} 字`;
      }
      updateStep2AutosaveStatus('演讲稿有未保存修改');
      if (step2ScriptSaveTimer) clearTimeout(step2ScriptSaveTimer);
      step2ScriptSaveTimer = setTimeout(() => saveStep2ScriptPlan({ silent: true }), 700);
    });
    if (input.tagName === 'TEXTAREA') autoResizeNarrationTextarea(input);
  });
}

async function saveStep2ScriptPlan(options = {}) {
  const projectId = step2CurrentProjectId();
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId || !state.step2ScriptPlan) return false;
  if (!step2VisualButtonReady()) {
    updateStep2AutosaveStatus('请填写新幻灯片的演讲稿');
    return false;
  }
  if (step2ScriptSaveTimer) {
    clearTimeout(step2ScriptSaveTimer);
    step2ScriptSaveTimer = null;
  }
  while (true) {
    if (step2ScriptSavePromise) {
      try { await step2ScriptSavePromise; } catch (error) { /* retry with the newest snapshot */ }
    }
    if (!isCurrentWorkspaceProject(projectId, sessionVersion) || !state.step2ScriptPlan) return false;
    const snapshot = JSON.parse(JSON.stringify(state.step2ScriptPlan));
    const savePromise = API.put(`/api/projects/${projectId}/steps/2/script/result`, snapshot);
    step2ScriptSavePromise = savePromise;
    let response;
    try {
      response = await savePromise;
    } catch (error) {
      if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
        updateStep2AutosaveStatus('演讲稿保存失败，请重试');
        if (!options.silent) showToast(`演讲稿保存失败：${error?.message || error}`);
      }
      return false;
    } finally {
      if (step2ScriptSavePromise === savePromise) step2ScriptSavePromise = null;
    }
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (!response.success) {
      updateStep2AutosaveStatus('演讲稿保存失败，请重试');
      return false;
    }
    if (JSON.stringify(state.step2ScriptPlan) !== JSON.stringify(snapshot)) {
      updateStep2AutosaveStatus('继续保存最新修改…');
      if (step2ScriptSaveTimer) clearTimeout(step2ScriptSaveTimer);
      step2ScriptSaveTimer = null;
      continue;
    }
    state.step2ScriptPlan = response.script_plan || state.step2ScriptPlan;
    if (typeof response.visual_exists === 'boolean') state.step2VisualExists = response.visual_exists;
    if (typeof response.workflow_pending === 'boolean') state.step2WorkflowPending = response.workflow_pending;
    if (typeof response.visual_stale === 'boolean') {
      state.step2VisualStale = response.visual_stale
        || (state.step2WorkflowPending && state.step2VisualExists);
    }
    if (!state.step2VisualStale && state.step2VisualExists) {
      renderStep2ScriptVisualStage(step2ActivePlanSlide());
      const nextButton = document.getElementById('step2-btn-next');
      if (nextButton) nextButton.disabled = false;
    }
    const visualButton = document.getElementById('step2-btn-generate-visual');
    if (visualButton) setStep2ButtonLabel(visualButton, state.step2VisualStale ? '重新生成可视化' : '内容可视化');
    updateStep2AutosaveStatus('');
    if (response.workflow_changed) refreshCurrentProjectStatus(2).catch(() => {});
    if (!options.silent) showToast('演讲稿已保存。');
    return true;
  }
}

async function generateStep2VisualPlan() {
  const projectId = step2CurrentProjectId();
  const sessionVersion = workspaceNavigationVersion;
  if (!projectId) return false;
  if (!state.step2ScriptPlan?.slides?.length) {
    showToast('请先生成演讲稿，再执行内容可视化。');
    return false;
  }
  if (!(await saveStep2ScriptPlan({ silent: true }))) return false;
  const button = document.getElementById('step2-btn-generate-visual');
  const loading = document.getElementById('step2-loading');
  const loadingText = document.querySelector('#step2-loading p');
  const oldLoadingText = loadingText?.textContent || '';
  if (button) button.disabled = true;
  if (loading) loading.style.display = 'block';
  try {
    setStep2TaskPhase('visual', 'running');
    if (loadingText) loadingText.textContent = '第二步：AI 正在根据已保存的演讲稿规划可视化…';
    const visual = await API.post(`/api/projects/${projectId}/steps/2/visual/execute`, undefined, { timeoutMs: 900000 });
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (visual.cancelled) {
      setStep2TaskPhase('visual', 'paused');
      updateStep2AutosaveStatus(visual.message || '内容可视化已停止');
      return false;
    }
    if (!visual.success) throw new Error(visual.message || '可视化生成失败');
    const composed = await API.post(`/api/projects/${projectId}/steps/2/compose`);
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return false;
    if (!composed.success || !composed.contract) throw new Error(composed.message || '分镜合成失败');
    state.slides = composed.contract.slides || [];
    state.step2PresentationPolicy = composed.contract.presentation_policy || {};
    state.step2Stage = 'visual';
    state.step2VisualStale = false;
    state.step2VisualExists = true;
    state.step2WorkflowPending = false;
    renderStep2Workspace();
    refreshCurrentProjectStatus(2).catch(() => {});
    setStep2TaskPhase('visual', 'done');
    showToast('可视化已根据当前演讲稿生成。');
    return true;
  } catch (error) {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      setStep2TaskPhase('visual', 'error');
      setStep2GenerationStatus(`可视化生成失败：${error?.message || error}`, 'error');
    }
    return false;
  } finally {
    if (isCurrentWorkspaceProject(projectId, sessionVersion)) {
      if (loadingText) loadingText.textContent = oldLoadingText;
      if (loading) loading.style.display = 'none';
      if (button) button.disabled = !step2VisualButtonReady();
    }
  }
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
  const usedIds = new Set(state.slides.map(slide => String(slide.slide_id || '')));
  let number = 1;
  while (usedIds.has(`slide_${String(number).padStart(3, '0')}`)) number += 1;
  const newSlideId = `slide_${String(number).padStart(3, '0')}`;
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

function addStep2Slide() {
  if (isManualMode()) return addManualSlide();
  const plan = state.step2ScriptPlan ||= {
    title: state.currentProject?.name || '演讲稿',
    slides: [],
  };
  const usedIds = new Set([...plan.slides, ...(state.slides || [])].map(slide => String(slide.slide_id || '')));
  let number = 1;
  while (usedIds.has(`slide_${String(number).padStart(3, '0')}`)) number += 1;
  plan.slides.push({ slide_id: `slide_${String(number).padStart(3, '0')}`, slide_title: `第 ${plan.slides.length + 1} 页`, narration: '' });
  state.activeSlideIndex = plan.slides.length - 1;
  state.step2VisualStale = state.step2VisualExists;
  state.step2WorkflowPending = state.step2VisualExists;
  renderStep2Workspace();
  updateStep2AutosaveStatus('请填写新幻灯片的演讲稿');
  document.querySelector('#step2-script-slides textarea[data-script-field="narration"]')?.focus();
}

// 提交手动分镜到后端（手动模式下点击"进入图片生成"时调用）
async function submitManualSkeletonIfNeeded() {
  if (!state.currentProject || !isManualMode()) return true;
  const slides = collectManualSlidesFromState();
  if (!slides.length) {
    showStep2ValidationError('请至少添加一页幻灯片');
    return false;
  }
  for (let i = 0; i < slides.length; i++) {
    if (!slides[i].main_title) {
      showStep2ValidationError(`第 ${i + 1} 页标题不能为空`, i, 'title');
      return false;
    }
    if (!slides[i].narration) {
      showStep2ValidationError(`第 ${i + 1} 页演讲稿不能为空`, i, 'narration');
      return false;
    }
  }
  try {
    const res = await saveStep2Contract({ silent: true });
    if (res && res.success && res.validation?.valid !== false) {
      await loadStep2Data();
      return true;
    }
    showStep2ValidationError('分镜结构尚未通过校验，请检查当前页内容');
    return false;
  } catch (e) {
    showToast('⚠️ 保存失败：' + (e && e.message ? e.message : String(e)));
    return false;
  }
}

function showStep2ValidationError(message, index = null, field = null) {
  if (index !== null) {
    saveCurrentSlideInputToState();
    state.activeSlideIndex = index;
    renderStep2Workspace();
  }
  updateStep2AutosaveStatus(message);
  if (field) showFieldError(document.getElementById(field === 'title'
    ? 'step2-slide-title-input' : 'step2-slide-narration-input'), message);
}

// ==================== 批量导入弹窗 ====================

const STEP2_BATCH_TEMPLATE = `[
  {
    "main_title": "第一页标题",
    "segments": [
      { "screen_text": "画面文字 1", "speech_segment": "这一段对应的演讲片段" },
      { "screen_text": "画面元素 2", "speech_segment": "这一段对应的演讲片段" }
    ]
  },
  {
    "main_title": "第二页标题",
    "narration": "第二页完整演讲稿（无 segments 时必填）"
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
      const segments = Array.isArray(item.segments) ? item.segments : null;
      let narration = String(item.narration || '').trim();
      if (segments) {
        for (let s = 0; s < segments.length; s++) {
          const seg = segments[s] || {};
          if (!String(seg.screen_text || '').trim() || !String(seg.speech_segment || '').trim()) {
            previewEl.style.display = 'block';
            previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 第 ${i + 1} 项第 ${s + 1} 个片段缺少 screen_text 或 speech_segment</div>`;
            return;
          }
        }
        if (!narration) narration = segments.map(seg => String(seg.speech_segment || '').trim()).filter(Boolean).join('');
      }
      if (!title || !narration) {
        previewEl.style.display = 'block';
        previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 第 ${i + 1} 项缺少 main_title 或 narration 字段</div>`;
        return;
      }
      slides.push({ main_title: title, narration, segments: segments ? segments.map(seg => ({
        screen_text: String(seg.screen_text || '').trim(),
        speech_segment: String(seg.speech_segment || '').trim(),
      })) : null });
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
    const segments = Array.isArray(item.segments) ? item.segments.filter(seg => seg && seg.screen_text) : [];
    const pad = (n) => String(n).padStart(3, '0');
    const visualGroups = [{
      id: `${slideId}_group_001`,
      role: 'title',
      visual_type: 'text',
      visible_text: item.main_title,
      display_text: item.main_title,
      visual_anchor: item.main_title,
      mask_target: item.main_title,
      reveal_order: 0,
    }];
    const beats = [];
    segments.forEach((seg, index) => {
      const groupId = `${slideId}_group_${pad(index + 2)}`;
      visualGroups.push({
        id: groupId,
        role: 'content_body',
        visual_type: 'text',
        visible_text: seg.screen_text,
        display_text: seg.screen_text,
        visual_anchor: seg.screen_text,
        mask_target: seg.screen_text,
        reveal_order: index + 1,
      });
      beats.push({
        id: `${slideId}_beat_${pad(index + 1)}`,
        group_id: groupId,
        content_unit_id: `${slideId}_unit_${pad(index + 1)}`,
        visible_anchor: seg.screen_text,
        spoken_intent: seg.screen_text,
        spoken_text: seg.speech_segment,
      });
    });
    if (!beats.length) {
      beats.push({
        id: `${slideId}_beat_001`,
        group_id: null,
        content_unit_id: `${slideId}_unit_001`,
        visible_anchor: '',
        spoken_intent: item.main_title,
        spoken_text: item.narration,
      });
    }
    return {
      slide_id: slideId,
      main_title: item.main_title,
      subtitle: '',
      core_message: item.narration,
      body_content: [item.narration],
      visual_groups: visualGroups,
      narration_beats: beats,
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

function closeStep2GenerationModal() {
  document.getElementById('modal-step2-generate').style.display = 'none';
}

function openStep2GenerationModal() {
  const modal = document.getElementById('modal-step2-generate');
  const title = modal?.querySelector('h3');
  const confirm = document.getElementById('btn-step2-generation-confirm');
  const requirement = document.getElementById('step2-generation-requirement');
  if (title) title.textContent = '生成演讲稿';
  if (confirm) confirm.textContent = '生成演讲稿';
  if (requirement) requirement.value = '';
  if (modal) modal.style.display = 'flex';
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
  closeStep2GenerationModal();
  await generateStep2ScriptPlan(userRequirement);
}

function renderStep2Workspace() {
  refreshStep2TaskStates();
  if (state.activeSlideIndex >= step2TabSourceSlides().length) {
    state.activeSlideIndex = Math.max(0, step2TabSourceSlides().length - 1);
  }
  const manual = isManualMode();
  const hasSlides = state.slides.length > 0;
  const showInlinePlan = !manual && !!state.step2ScriptPlan?.slides?.length;
  document.getElementById('step2-editor-area').style.display = hasSlides && !showInlinePlan ? 'block' : 'none';
  // 自动模式明确分开文章到演讲稿与演讲稿到可视化两个阶段。
  const scriptGenerateBtn = document.getElementById('step2-btn-generate-script');
  const visualGenerateBtn = document.getElementById('step2-btn-generate-visual');
  const scriptPromptBtn = document.getElementById('step2-btn-script-prompt');
  const visualPromptBtn = document.getElementById('step2-btn-visual-prompt');
  const addSlideBtn = document.getElementById('step2-btn-add-slide');
  const batchImportBtn = document.getElementById('step2-btn-batch-import');
  if (manual) {
    if (scriptGenerateBtn) scriptGenerateBtn.style.display = 'none';
    if (visualGenerateBtn) visualGenerateBtn.style.display = 'none';
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'none';
    if (visualPromptBtn) visualPromptBtn.style.display = 'none';
    if (addSlideBtn) addSlideBtn.style.display = 'inline-flex';
    if (batchImportBtn) batchImportBtn.style.display = 'inline-flex';
  } else {
    if (scriptGenerateBtn) {
      scriptGenerateBtn.style.display = 'inline-flex';
      scriptGenerateBtn.classList.toggle('is-active', state.step2Stage === 'script');
      setStep2ButtonLabel(scriptGenerateBtn, '生成演讲稿');
    }
    if (visualGenerateBtn) {
      // 自动模式常驻展示：演讲稿未生成/生成中禁用，全部生成完毕后可点（UI 规范 §8）。
      visualGenerateBtn.style.display = 'inline-flex';
      setDisabledReason(visualGenerateBtn, !step2VisualButtonReady());
      visualGenerateBtn.classList.toggle('is-active', state.step2VisualExists && !state.step2VisualStale);
      setStep2ButtonLabel(visualGenerateBtn, state.step2VisualStale ? '重新生成可视化' : '内容可视化');
      visualGenerateBtn.removeAttribute('title');
    }
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'inline-flex';
    if (visualPromptBtn) visualPromptBtn.style.display = 'inline-flex';
    if (addSlideBtn) addSlideBtn.style.display = 'inline-flex';
    if (batchImportBtn) batchImportBtn.style.display = 'none';
  }
  if (addSlideBtn) addSlideBtn.disabled = state.step2BatchDeleteMode;
  renderStep2ScriptReview();
  // 批量删除/保存按钮在工具栏中（批量导入右侧）常显，方便随时进入删除模式
  document.getElementById('step2-btn-save').style.display = step2TabSourceSlides().length ? 'inline-flex' : 'none';
  const step2NextButton = document.getElementById('step2-btn-next');
  step2NextButton.style.display = hasSlides ? 'inline-flex' : 'none';
  const visualizationNeedsRefresh = !manual && (state.step2WorkflowPending || state.step2VisualStale);
  setDisabledReason(step2NextButton, !hasSlides || visualizationNeedsRefresh);
  step2NextButton.removeAttribute('title');
  updateStep2BatchDeleteButton();

  // 渲染二级菜单 Tab（分页）：自动模式与手动模式共用同一数据源。
  const thumbsContainer = document.getElementById('step2-thumbs');
  const tabSource = step2TabSourceSlides();
  thumbsContainer.style.display = tabSource.length ? 'flex' : 'none';
  if (!thumbsContainer.dataset.horizontalWheelBound) {
    thumbsContainer.dataset.horizontalWheelBound = 'true';
    thumbsContainer.addEventListener('wheel', event => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      thumbsContainer.scrollLeft += event.deltaY;
    }, { passive: false });
  }
  thumbsContainer.classList.toggle('step2-batch-delete-mode', state.step2BatchDeleteMode);
  thumbsContainer.innerHTML = '';

  if (!tabSource.length) {
    thumbsContainer.style.display = 'flex';
    thumbsContainer.style.display = 'none';
  }

  tabSource.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card step2-slide-thumb tab-item ${idx === state.activeSlideIndex ? 'active' : ''}`;
    // 二级菜单 Tab（UI 规范 §5）：胶囊样式与动效由样式层接管；
    // 页码常显，主标题放悬停提示。
    const pageLabel = `第 ${idx + 1} 页`;
    thumb.tabIndex = 0;
    thumb.setAttribute('role', 'button');
    thumb.setAttribute('aria-label', `${pageLabel}，${slide.main_title || slide.slide_title || '未命名'}。Alt 加左右方向键调整顺序`);
    thumb.setAttribute('aria-pressed', String(idx === state.activeSlideIndex));
    thumb.addEventListener('keydown', event => {
      if (event.target !== thumb) return;
      if (event.altKey && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
        event.preventDefault();
        const target = idx + (event.key === 'ArrowLeft' ? -1 : 1);
        if (target < 0 || target >= tabSource.length || state.step2BatchDeleteMode) return;
        moveStep2Thumb(idx, target);
        document.querySelectorAll('#step2-thumbs .step2-slide-thumb')[target]?.focus();
        updateStep2AutosaveStatus(`已移至第 ${target + 1} 页，正在保存排序`);
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        thumb.click();
        document.querySelectorAll('#step2-thumbs .step2-slide-thumb')[idx]?.focus();
      }
    });
    thumb.innerHTML = `
      <span class="step2-thumb-handle" aria-hidden="true">⠿</span>
      <span class="step2-thumb-label">${escHtml(pageLabel)}</span>
      ${state.step2BatchDeleteMode ? `
        <button class="step2-thumb-delete" type="button" aria-label="删除此分镜"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3L3 9"/></svg></button>
      ` : ''}
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
    bindStep2ThumbDrag(thumb);
    thumbsContainer.appendChild(thumb);
  });

  // 加载当前 Slide 详情
  const slide = state.slides[state.activeSlideIndex];
  if (slide && !showInlinePlan) {
    const structuredManualSlide = manual && step2SlideHasStructuredVisuals(slide);
    if (!manual) {
      syncStep2SimpleFieldsToInternalGroups(slide);
    }
    // 同步隐藏字段
    document.getElementById('step2-main-title').value = slide.main_title || '';
    document.getElementById('step2-core-message').value = slide.core_message || '';

    const titleInput = document.getElementById('step2-slide-title-input');
    const narrationInput = document.getElementById('step2-slide-narration-input');
    if (titleInput) {
      titleInput.readOnly = !manual;
      titleInput.setAttribute('aria-readonly', titleInput.readOnly ? 'true' : 'false');
      titleInput.value = slide.main_title || '';
    }
    if (narrationInput) {
      // 只有纯手动分镜可直接编辑该字段；AI 映射中的旁白是演讲稿的只读引用。
      narrationInput.readOnly = !manual || structuredManualSlide;
      narrationInput.setAttribute('aria-readonly', narrationInput.readOnly ? 'true' : 'false');
      narrationInput.value = step2NarrationText(slide);
    }
    const narrationHint = document.getElementById('step2-narration-source-hint');
    if (narrationHint) narrationHint.textContent = narrationInput?.readOnly
      ? '演讲稿以第一步生成的版本为准。需要修改时请返回该阶段编辑并重新执行内容可视化。'
      : '手动模式：直接在此输入本页要朗读的演讲稿，可多行。';
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

// Only the handle starts sorting. Pointer capture supports mouse dragging and touch hold.
function moveStep2Thumb(from, to) {
  if (from < 0 || to < 0 || from === to || state.step2BatchDeleteMode) return;
  saveCurrentSlideInputToState();
  if (!isManualMode() && Array.isArray(state.step2ScriptPlan?.slides)) {
    const plan = state.step2ScriptPlan.slides;
    const activeId = String(plan[state.activeSlideIndex]?.slide_id || '');
    const [moved] = plan.splice(from, 1);
    plan.splice(to, 0, moved);
    const order = new Map(plan.map((slide, index) => [String(slide.slide_id || ''), index]));
    state.slides.sort((a, b) => (order.get(String(a.slide_id || '')) ?? Infinity)
      - (order.get(String(b.slide_id || '')) ?? Infinity));
    state.activeSlideIndex = Math.max(0, plan.findIndex(slide => String(slide.slide_id || '') === activeId));
    state.step2VisualStale = state.step2VisualExists;
    renderStep2Workspace();
    updateStep2AutosaveStatus('排序保存中…');
    if (step2ScriptSaveTimer) clearTimeout(step2ScriptSaveTimer);
    step2ScriptSaveTimer = setTimeout(async () => {
      if (await saveStep2ScriptPlan({ silent: true }) && state.slides.length) {
        const result = await saveStep2Contract({ silent: true, skipCurrentSlideSync: true });
        updateStep2AutosaveStatus(result.success ? '' : '排序保存失败，请重试');
      }
    }, 700);
  } else if (state.slides?.length) {
    const activeId = String(state.slides[state.activeSlideIndex]?.slide_id || '');
    const [moved] = state.slides.splice(from, 1);
    state.slides.splice(to, 0, moved);
    state.activeSlideIndex = Math.max(0, state.slides.findIndex(slide => String(slide.slide_id || '') === activeId));
    renderStep2Workspace();
    scheduleStep2AutoSave();
  }
}

function bindStep2ThumbDrag(thumb) {
  const handle = thumb.querySelector('.step2-thumb-handle');
  if (!handle) return;
  let pointerId = null;
  let startX = 0;
  let startY = 0;
  let active = false;
  let holdTimer = null;
  const container = document.getElementById('step2-thumbs');
  const clearHighlight = () => {
    if (holdTimer) clearTimeout(holdTimer);
    holdTimer = null;
    thumb.classList.remove('dragging');
    container.querySelectorAll('.drag-over').forEach(item => item.classList.remove('drag-over'));
    active = false;
    pointerId = null;
  };
  handle.addEventListener('click', event => event.stopPropagation());
  handle.addEventListener('pointerdown', event => {
    if (state.step2BatchDeleteMode || (event.pointerType === 'mouse' && event.button !== 0)) return;
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    handle.setPointerCapture(event.pointerId);
    if (event.pointerType === 'touch') {
      holdTimer = setTimeout(() => {
        active = true;
        thumb.classList.add('dragging');
      }, 250);
    } else {
      active = true;
      thumb.classList.add('dragging');
    }
  });
  handle.addEventListener('pointermove', event => {
    if (event.pointerId !== pointerId) return;
    if (!active && Math.hypot(event.clientX - startX, event.clientY - startY) > 8) {
      clearHighlight();
      return;
    }
    if (!active) return;
    event.preventDefault();
    container.querySelectorAll('.drag-over').forEach(item => item.classList.remove('drag-over'));
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.step2-slide-thumb');
    if (target && target !== thumb && container.contains(target)) target.classList.add('drag-over');
    const bounds = container.getBoundingClientRect();
    if (event.clientX > bounds.right - 24) container.scrollLeft += 14;
    else if (event.clientX < bounds.left + 24) container.scrollLeft -= 14;
  });
  handle.addEventListener('pointerup', event => {
    if (event.pointerId !== pointerId) return;
    const target = active ? document.elementFromPoint(event.clientX, event.clientY)?.closest('.step2-slide-thumb') : null;
    const items = [...container.querySelectorAll('.step2-slide-thumb')];
    const from = items.indexOf(thumb);
    const to = target && container.contains(target) ? items.indexOf(target) : -1;
    clearHighlight();
    if (to >= 0) moveStep2Thumb(from, to);
  });
  handle.addEventListener('pointercancel', clearHighlight);
  handle.addEventListener('lostpointercapture', clearHighlight);
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
  }
  if (input && input.id === 'step2-slide-title-input') {
    slide.main_title = input.value;
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
  if (!btn) return;
  if (state.step2BatchDeleteMode) {
    btn.className = 'success';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
      保存
    `;
  } else {
    btn.className = 'secondary';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
      批量删除
    `;
  }
}

async function handleStep2BatchDeleteButton() {
  if (!state.step2BatchDeleteMode) {
    // 只有“进入批量删除模式”需要至少一页；批量删除模式下 slides 可能被全部移除为空
    if (!step2TabSourceSlides().length) return;
    if (state.slides?.length) saveCurrentSlideInputToState();
    clearTimeout(state.step2AutoSaveTimer);
    if (step2ScriptSaveTimer) clearTimeout(step2ScriptSaveTimer);
    if (!isManualMode() && state.step2ScriptPlan?.slides?.length
      && step2VisualButtonReady() && !(await saveStep2ScriptPlan({ silent: true }))) return;
    if (isManualMode() && state.slides?.length && !(await saveStep2Contract({ silent: true })).success) return;
    state.step2BatchOriginalSlides = JSON.parse(JSON.stringify(state.slides));
    state.step2BatchOriginalScriptPlan = state.step2ScriptPlan
      ? JSON.parse(JSON.stringify(state.step2ScriptPlan)) : null;
    state.step2BatchOriginalVisualStale = state.step2VisualStale;
    state.step2BatchOriginalWorkflowPending = state.step2WorkflowPending;
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
  if (!isManualMode() && state.step2ScriptPlan?.slides?.length) {
    if (state.step2ScriptPlan.slides.length <= 1) {
      showToast('至少保留一页演讲稿');
      return;
    }
    const removedIndex = state.step2ScriptPlan.slides.findIndex(slide => slide.slide_id === slideId);
    if (removedIndex < 0) return;
    state.step2ScriptPlan.slides.splice(removedIndex, 1);
    state.step2VisualStale = state.step2VisualExists;
    state.step2WorkflowPending = state.step2VisualExists;
    state.activeSlideIndex = Math.min(state.activeSlideIndex, state.step2ScriptPlan.slides.length - 1);
    renderStep2Workspace();
    return;
  }
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
  if (state.slides?.length) saveCurrentSlideInputToState();
  clearTimeout(state.step2AutoSaveTimer);
  const scriptOnly = !isManualMode() && !!state.step2BatchOriginalScriptPlan?.slides?.length;
  const originalCount = scriptOnly
    ? state.step2BatchOriginalScriptPlan?.slides?.length || 0
    : state.step2BatchOriginalSlides.length;
  const currentCount = scriptOnly ? state.step2ScriptPlan?.slides?.length || 0 : state.slides.length;
  const removedCount = Math.max(0, originalCount - currentCount);
  if (removedCount === 0) {
    state.step2BatchDeleteMode = false;
    state.step2BatchOriginalSlides = null;
    state.step2BatchOriginalScriptPlan = null;
    state.step2VisualStale = state.step2BatchOriginalVisualStale;
    state.step2WorkflowPending = state.step2BatchOriginalWorkflowPending;
    renderStep2Workspace();
    showToast('已退出批量删除模式。');
    return;
  }
  // 保存删除会提交新合约，后端随即 shutil.rmtree 整页目录：图片、Mask 切层
  // 素材与音频物理消失且不可恢复，因此必须由用户显式确认后才发起请求。
  const confirmed = await new Promise(resolve => {
    showCustomConfirm(
      '确认删除分镜',
      scriptOnly
        ? `将从演讲稿中删除 ${removedCount} 页，确认保存吗？`
        : `将删除 ${removedCount} 个分镜页。这些页的图片、Mask、切层素材和音频将被彻底删除且不可恢复。`,
      () => resolve(true),
      () => resolve(false),
      { danger: true },
    );
  });
  if (!confirmed) {
    // 「退出批量删除」按钮已移除：确认弹窗点取消即恢复原状并退出，避免停留在一个没有出口的模式。
    exitStep2BatchDelete();
    showToast('已取消删除，分镜列表已恢复。');
    return;
  }
  const saved = scriptOnly
    ? await saveStep2ScriptPlan({ silent: true })
    : (await saveStep2Contract({ silent: true })).success;
  if (!saved) return;
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  state.step2BatchOriginalScriptPlan = null;
  renderStep2Workspace();
  showToast(`已删除 ${removedCount} 个分镜，并保存当前规划。`);
}

function exitStep2BatchDelete() {
  if (!state.step2BatchDeleteMode) return;
  if (Array.isArray(state.step2BatchOriginalSlides)) {
    state.slides = JSON.parse(JSON.stringify(state.step2BatchOriginalSlides));
    state.activeSlideIndex = Math.min(state.step2BatchOriginalActiveIndex || 0, Math.max(0, state.slides.length - 1));
  }
  if (state.step2BatchOriginalScriptPlan) {
    state.step2ScriptPlan = state.step2BatchOriginalScriptPlan;
  }
  state.step2VisualStale = state.step2BatchOriginalVisualStale;
  state.step2WorkflowPending = state.step2BatchOriginalWorkflowPending;
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  state.step2BatchOriginalScriptPlan = null;
  renderStep2Workspace();
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
  const projectId = state.currentProject.id;
  const sessionVersion = workspaceNavigationVersion;
  state.step2AutoSaveTimer = setTimeout(() => {
    if (!isCurrentWorkspaceProject(projectId, sessionVersion) || state.currentStep !== 2) return;
    saveStep2Contract({ silent: true, autosave: true, projectId, sessionVersion });
  }, 700);
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
  if (!isManualMode() && state.step2ScriptPlan?.slides?.length) return;
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

function renderStep2VisualNarrationMap(slide, container = document.getElementById('step2-visual-narration-map')) {
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
    const sourceTextLock = role === 'title' && !isManualMode()
      ? 'readonly aria-readonly="true" title="标题请在第一步“演讲稿”中修改"'
      : '';
    const mappingReady = matched.length === 1 && String(matched[0]?.spoken_text || '').trim();
    const beatsHtml = matched.length
      ? matched.map((beat, beatIndex) => renderStep2EditableBeat(beat, beatIndex, matched.length)).join('')
      : '<div class="vn-beat vn-beat-empty">缺少对应演讲片段，请重新执行内容可视化。</div>';
    const visualField = visualType === 'text'
      ? `<label class="vn-edit-field" aria-label="画面文字">
          <textarea ${sourceTextLock} data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">${escHtml(visualContent)}</textarea>
        </label>`
      : `<label class="vn-edit-field" aria-label="画面元素描述">
          <textarea data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">${escHtml(visualContent)}</textarea>
        </label>`;
    return `
      <div class="vn-group-card vn-role-${escHtml(roleValue)}" data-group-id="${escHtml(gid)}">
        <div class="vn-group-head">
          <span class="vn-group-num">${idx + 1}</span>
          <span class="vn-type-tag">${typeLabel}</span>
          ${mappingReady ? '' : '<span class="vn-beat-count is-error">需要检查</span>'}
        </div>
        <div class="vn-group-body">
          <div class="vn-visual">
            <span class="vn-column-label">${typeLabel}</span>
            ${visualField}
          </div>
          <div class="vn-narration">
            <span class="vn-column-label">对应演讲片段</span>
            ${beatsHtml}
          </div>
        </div>
      </div>`;
  }).join('');

  const orphanBeats = beats.filter(beat => !usedBeatIds.has(beat.id));
  const orphanHtml = orphanBeats.length
    ? `<div class="vn-orphan">
        <div class="vn-orphan-head">发现 ${orphanBeats.length} 段没有对应画面的演讲片段</div>
        <div class="vn-orphan-hint">当前结构不允许手动选择内部 ID，请重新执行内容可视化，让系统重新建立一对一关系。</div>
        ${orphanBeats.map((beat, index) => renderStep2EditableBeat(beat, index, orphanBeats.length)).join('')}
      </div>`
    : '';

  container.innerHTML = `
    <div class="vn-map-title">画面与演讲片段</div>
    <div class="vn-groups">${groupCards}</div>
    ${orphanHtml}`;
  document.dispatchEvent(new CustomEvent('step2WorkspaceRendered'));
  requestAnimationFrame(() => resizeStep2MapRows(container));
}

function renderStep2EditableBeat(beat, index = 0, total = 1) {
  const beatId = String(beat?.id || '');
  return `<div class="vn-beat" data-beat-id="${escHtml(beatId)}">
    <label class="vn-edit-field" aria-label="演讲片段"${total > 1 ? ` title="演讲片段 ${index + 1}（应合并为一段）"` : ''}>
      <textarea readonly aria-readonly="true" title="演讲稿请在第一步“演讲稿”中编辑" data-step2-beat-id="${escHtml(beatId)}" data-step2-beat-field="spoken_text">${escHtml(beat?.spoken_text || '')}</textarea>
    </label>
  </div>`;
}

function currentStep2EditorSlide() {
  const planSlide = !isManualMode() ? step2ActivePlanSlide() : null;
  return (planSlide && state.slides?.find(slide => slide.slide_id === planSlide.slide_id))
    || state.slides?.[state.activeSlideIndex] || null;
}

function autoResizeStep2Textarea(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = (el.scrollHeight) + 'px';
}

function bindStep2TextareaAutoResize() {
  document.querySelectorAll('#step2-editor-area textarea, .step2-inline-visual textarea').forEach(t => {
    if (t.dataset.autoResizeBound === '1') return;
    t.dataset.autoResizeBound = '1';
    if (t.closest('.step2-vn-map')) resizeStep2MapRows(t.closest('.step2-vn-map'));
    else autoResizeStep2Textarea(t);
    t.addEventListener('input', () => {
      if (t.closest('.step2-vn-map')) resizeStep2MapRows(t.closest('.step2-vn-map'));
      else autoResizeStep2Textarea(t);
    });
  });
}

function resizeStep2MapRows(root) {
  if (!root) return;
  root.querySelectorAll('.vn-group-body').forEach(row => {
    const fields = Array.from(row.querySelectorAll('textarea'));
    if (!fields.length) return;
    fields.forEach(field => {
      field.style.removeProperty('--step2-field-height');
      field.style.height = 'auto';
    });
    const height = Math.max(...fields.map(field => field.scrollHeight + 2));
    fields.forEach(field => field.style.setProperty('--step2-field-height', `${height}px`));
  });
}

document.addEventListener('step2WorkspaceRendered', bindStep2TextareaAutoResize);
window.addEventListener('load', bindStep2TextareaAutoResize);
window.addEventListener('resize', () => {
  document.querySelectorAll('.step2-script-slide textarea[data-script-field="narration"]').forEach(textarea => {
    if (typeof autoResizeNarrationTextarea === 'function') autoResizeNarrationTextarea(textarea);
    else autoResizeTextarea(textarea);
  });
  document.querySelectorAll('.step2-vn-map').forEach(resizeStep2MapRows);
});
setTimeout(bindStep2TextareaAutoResize, 500);


function handleStep2MapEditorInput(event) {
  const target = event.target;
  const scriptIndex = target?.closest?.('[data-script-slide-index]')?.dataset.scriptSlideIndex;
  const scriptSlide = scriptIndex === undefined ? null : state.step2ScriptPlan?.slides?.[Number(scriptIndex)];
  const slide = scriptSlide
    ? state.slides?.find(item => item.slide_id === scriptSlide.slide_id)
    : currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  const groupId = target.dataset.step2GroupId;
  const groupField = target.dataset.step2GroupField;
  const beatId = target.dataset.step2BeatId;
  const beatField = target.dataset.step2BeatField;
  let changed = false;

  if (groupId && groupField === 'visual_content') {
    const group = slide.visual_groups?.find(item => item?.id === groupId);
    if (group?.role === 'title' && !isManualMode()) return;
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

  if (!changed) return;
  if (!scriptSlide) syncStep2SummaryInputs(slide);
  if (target.tagName === 'TEXTAREA') resizeStep2MapRows(target.closest('.step2-vn-map'));
  scheduleStep2AutoSave();
}

function handleStep2MapEditorChange(event) {
  const target = event.target;
  const slide = currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  if (target.dataset.step2GroupField !== 'visual_content') return;
  if (target.tagName === 'TEXTAREA') resizeStep2MapRows(target.closest('.step2-vn-map'));
  if (!target.closest('[data-script-slide-index]')) syncStep2SummaryInputs(slide);
  scheduleStep2AutoSave();
}

function syncStep2SummaryInputs(slide) {
  const titleInput = document.getElementById('step2-slide-title-input');
  const narrationInput = document.getElementById('step2-slide-narration-input');
  const heading = document.getElementById('step2-current-slide-title');
  if (titleInput && document.activeElement !== titleInput) titleInput.value = slide.main_title || '';
  if (heading) heading.textContent = slide.main_title || '未命名 Slide';
  if (narrationInput) {
    narrationInput.readOnly = !isManualMode();
    narrationInput.setAttribute('aria-readonly', narrationInput.readOnly ? 'true' : 'false');
    const hint = document.getElementById('step2-narration-source-hint');
    if (hint) hint.textContent = isManualMode()
      ? '手动模式：直接在此输入本页要朗读的演讲稿，可多行。'
      : '标题和演讲稿以第一步生成的版本为准。请返回该阶段修改，自动保存后再执行内容可视化。';
  }
  if (narrationInput && document.activeElement !== narrationInput) {
    narrationInput.value = step2NarrationText(slide);
    autoResizeTextarea(narrationInput);
  }
}

async function saveStep2Contract(options = {}) {
  const projectId = options.projectId || state.currentProject?.id;
  const sessionVersion = options.sessionVersion ?? workspaceNavigationVersion;
  if (!projectId || !isCurrentWorkspaceProject(projectId, sessionVersion)) return { success: false, cancelled: true };
  if (!options.skipCurrentSlideSync) {
    saveCurrentSlideInputToState();
  }
  const pureManualContract = isManualMode()
    && state.slides.every(slide => !step2SlideHasStructuredVisuals(slide));
  const payload = {
    version: "visual_contract_v1",
    topic: state.currentProject.topic || {
      topic_id: "topic_" + projectId,
      topic_name: state.currentProject.name
    },
    presentation_policy: pureManualContract ? {
      subtitle_policy: 'forbidden',
      subtitle_decided_by: 'manual_mode',
      visual_narration_mapping: 'manual_free_v1'
    } : (state.step2PresentationPolicy || {}),
    slides: state.slides
  };
  
  if (state.step2AutoSaveInFlight && options.autosave && state.step2AutoSaveProjectId === projectId) {
    scheduleStep2AutoSave();
    return { success: false };
  }
  if (state.step2ContractSha256) {
    payload.expected_contract_sha256 = state.step2ContractSha256;
  }
  state.step2AutoSaveInFlight = true;
  state.step2AutoSaveProjectId = projectId;
  try {
    let res;
    try {
      res = await API.put(`/api/projects/${projectId}/steps/2/result`, payload);
    } catch (error) {
      if (error.status === 409 && error.body?.detail?.code === 'storyboard_conflict') {
        // Step 2 CAS: 过期快照被拒绝;服务端内容未覆盖,刷新后重进编辑
        state.step2ContractSha256 = error.body.detail.current_contract_sha256 || null;
        updateStep2AutosaveStatus('检测到并发修改，已保留服务端版本');
        showToast('分镜已在其他窗口被修改；本次保存被拒绝。请刷新分镜后重新编辑。');
        return { success: false, conflict: true };
      }
      throw error;
    }
    if (!isCurrentWorkspaceProject(projectId, sessionVersion)) return { success: false, cancelled: true };
    if (res.success) {
      state.step2ContractSha256 = res.contract_sha256 || state.step2ContractSha256;
      state.step2PresentationPolicy = res.contract?.presentation_policy || payload.presentation_policy;
      if (res.changed) refreshCurrentProjectStatus(2).catch(() => {});
      updateStep2AutosaveStatus(options.autosave ? '已自动保存' : '');
      if (!options.silent) {
        showToast('💾 分镜规划已成功保存！');
      }
    }
    return res;
  } finally {
    if (state.step2AutoSaveProjectId === projectId) state.step2AutoSaveInFlight = false;
    if (options.autosave && isCurrentWorkspaceProject(projectId, sessionVersion)) {
      setTimeout(() => updateStep2AutosaveStatus(''), 1400);
    }
  }
}


// One-click tasks share the same page-level presentation as manual generation.
let step2OneClickPresenting = false;
window.syncStoryboardGenerationState = function(status) {
  const running = status?.status === 'running' && status?.current_stage === 'storyboard';
  if (!running && !step2OneClickPresenting) return;
  step2OneClickPresenting = running;
  const loading = document.getElementById('step2-loading');
  if (loading) loading.style.display = running ? 'block' : 'none';
  if (running) {
    const text = loading?.querySelector('p');
    if (text) setUiTaskState(text, 'running', '正在生成演讲稿与画面可视化…');
    setStep2TaskPhase('script', state.step2ScriptPlan?.slides?.length ? 'done' : 'running');
    setStep2TaskPhase('visual', 'running');
  } else {
    setStep2TaskPhase("script", "done");
    setStep2TaskPhase("visual", "done");
    refreshStep2TaskStates();
  }
};
