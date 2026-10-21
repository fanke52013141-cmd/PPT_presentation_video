// Project workspace entry/exit, AI-mode switching, stepper state, and step data routing.
// Shared state/API/flow helpers live in ui_foundation.js / workflow_state.js / api_client.js; step implementations live in their owner modules.

// ==================== 项目管理与系统设置逻辑 ====================

// ==================== 工作区视图控制逻辑 ====================

let workspaceNavigationVersion = 0;

function isCurrentWorkspaceProject(projectId, sessionVersion = workspaceNavigationVersion) {
  return Boolean(
    projectId
    && state.currentProject?.id === projectId
    && workspaceNavigationVersion === sessionVersion
    && document.body.classList.contains('workspace-open')
  );
}

// 切换/退出项目前,把各步骤防抖窗口(约 700ms)内尚未落盘的编辑冲刷到
// 服务端。必须在 workspace 复位清空 state/模块数据之前调用;各冲刷函数
// 均在入口同步捕获项目上下文,后续 await 不依赖已复位的状态。
async function flushProjectPendingEdits() {
  const flushes = [];
  if (state.step2AutoSaveTimer && typeof window.flushStep2PendingSaves === 'function') {
    flushes.push(window.flushStep2PendingSaves().catch(() => {}));
  }
  if (state.step5AutoSaveTimer && window.PPTStudio?.flushStep5Draft) {
    flushes.push(window.PPTStudio.flushStep5Draft().catch(() => {}));
  }
  if (state.step6AutoSaveTimer && typeof window.flushStep6Autosave === 'function') {
    flushes.push(window.flushStep6Autosave({ userInitiated: false }).catch(() => {}));
  }
  if (typeof window.flushAnnotationsSave === 'function') {
    flushes.push(window.flushAnnotationsSave().catch(() => {}));
  }
  if (flushes.length) await Promise.allSettled(flushes);
}

function resetProjectScopedAsyncUi() {
  clearTimeout(state.step2AutoSaveTimer);
  state.step2AutoSaveTimer = null;
  clearTimeout(state.step6AutoSaveTimer);
  state.step6AutoSaveTimer = null;
  if (typeof resetStep2ScriptState === 'function') resetStep2ScriptState();
  if (typeof stopStep8RenderPolling === 'function') stopStep8RenderPolling();
  if (typeof stopStep8PptxPolling === 'function') stopStep8PptxPolling();
  if (typeof resetStep3ProjectState === 'function') resetStep3ProjectState();
  if (typeof resetStep6ProjectState === 'function') resetStep6ProjectState();
  // 勾画标注(可选步骤 10)的项目级状态复位;在途保存由 flush 兜底
  if (typeof window.flushAnnotationsSave === 'function') {
    window.flushAnnotationsSave().catch(() => {});
  }
  if (typeof window.resetAnnotationsProjectState === 'function') resetAnnotationsProjectState();
  const scriptButton = document.getElementById('step2-btn-generate-script');
  if (scriptButton) scriptButton.disabled = false;
  const visualButton = document.getElementById('step2-btn-generate-visual');
  if (visualButton) visualButton.disabled = false;
  const articleButton = document.getElementById('step1-btn-submit');
  if (articleButton) {
    articleButton.disabled = false;
    articleButton.innerHTML = '进入分镜规划';
  }
  // TTS 轮询最长可达 30 分钟,其 finally 的按钮恢复受 ownership 守卫保护,
  // 切换项目后会被跳过;这里无条件恢复四个持久 DOM 按钮,避免跨项目永久禁用。
  for (const buttonId of ['step7-btn-synthesize', 'step6-btn-save-and-tts', 'step6-btn-audio-confirm-next', 'step7-btn-force-all']) {
    const button = document.getElementById(buttonId);
    if (button) button.disabled = false;
  }
  // 共享 state 的项目级数据必须一并复位:残留旧项目的 slides 会让新项目
  // Step 3 沿用旧 slide_id 提交生图;残留旧合约 sha 会让新项目首次保存
  // 合约带上错误的 expected_contract_sha256 而必然 409。
  state.slides = [];
  state.activeSlideIndex = 0;
  state.step2ContractSha256 = null;
}

// 画布比例以 CSS 变量下发到根节点，供 style.css 中所有跟随项目画布的
// 预览容器（Mask 画布、字幕预览、Step3 预览、视频预览等）统一继承。
function syncProjectCanvasCssVars(project = state.currentProject) {
  const root = document.documentElement;
  if (!project) {
    root.style.removeProperty('--project-aspect-ratio');
    root.style.removeProperty('--project-aspect-ratio-scale');
    return;
  }
  const geometry = typeof getProjectCanvasGeometry === 'function'
    ? getProjectCanvasGeometry(project)
    : { width: 1920, height: 1080, aspectRatio: '1920 / 1080' };
  root.style.setProperty('--project-aspect-ratio', geometry.aspectRatio);
  root.style.setProperty('--project-aspect-ratio-scale', String(geometry.width / geometry.height));
}

async function enterWorkspace(projectId) {
  // 先冲刷旧项目防抖窗口内的编辑,再切版本号与复位(冲刷依赖旧项目上下文)。
  await flushProjectPendingEdits();
  const entryVersion = ++workspaceNavigationVersion;
  resetProjectScopedAsyncUi();
  resetStep5ProjectState();
  // In-flight work from the old project must fail its ownership guard while
  // the new project's metadata is being fetched.
  state.currentProject = null;
  let project;
  try {
    project = await API.get(`/api/projects/${projectId}`);
  } catch (error) {
    // 独立视频与课程内视频使用同一项目接口。网络中断或项目已在其他
    // 窗口删除时，不让未捕获异常叠在目录上；重新拉取目录清除陈旧项。
    if (entryVersion !== workspaceNavigationVersion) return;
    if (typeof window.showToast === 'function') {
      window.showToast('无法打开该视频，已刷新项目列表。');
    }
    if (typeof window.loadProjects === 'function') window.loadProjects();
    return;
  }
  if (entryVersion !== workspaceNavigationVersion) return;
  state.currentProject = project;
  syncProjectCanvasCssVars(project);
  const visibleStep = resolveProjectVisibleStep(project);

  // 顶栏切换
  document.getElementById('project-info-header').style.display = 'flex';
  document.getElementById('current-project-name').innerText = project.name;
  const btnBackHome = document.getElementById('btn-back-home');
  if (btnBackHome) btnBackHome.hidden = false;
  applyProjectAiMode(project.ai_mode || 'auto');
  renderProductionModeSummary(project);

  // 页面切换
  document.getElementById('page-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'flex';
  document.body.classList.add('workspace-open');

  // 加载步骤状态并导航至当前步骤
  if (typeof window.loadAnnotationWorkflowState === 'function') {
    try {
      await window.loadAnnotationWorkflowState(projectId);
    } catch (error) {
      console.error('annotation workflow state restore failed:', error);
    }
    if (entryVersion !== workspaceNavigationVersion) return;
  }
  updateStepperUI(visibleStep, project.step_status);
  await navigateToStep(visibleStep);
}

async function exitWorkspace() {
  await flushProjectPendingEdits();
  ++workspaceNavigationVersion;
  resetProjectScopedAsyncUi();
  resetStep5ProjectState();
  document.getElementById('project-info-header').style.display = 'none';
  const btnBackHome = document.getElementById('btn-back-home');
  if (btnBackHome) btnBackHome.hidden = true;
  document.getElementById('ai-mode-segment').style.display = 'none';
  document.getElementById('project-production-mode')?.remove();
  document.getElementById('page-workspace').style.display = 'none';
  document.body.classList.remove('workspace-open');
  document.body.classList.remove('mode-manual');
  document.body.classList.remove('mode-auto');
  document.getElementById('page-home').style.display = 'block';

  state.currentProject = null;
  syncProjectCanvasCssVars(null);
  loadProjects();
}

function applyProjectAiMode(aiMode) {
  const mode = (aiMode || 'auto').toLowerCase() === 'manual' ? 'manual' : 'auto';
  document.body.classList.remove('mode-manual', 'mode-auto');
  document.body.classList.add(mode === 'manual' ? 'mode-manual' : 'mode-auto');
  const segment = document.getElementById('ai-mode-segment');
  if (segment) {
    segment.style.display = (document.body.classList.contains('workspace-open') && Number(state.currentStep) === 2) ? 'inline-flex' : 'none';
    const autoBtn = document.getElementById('btn-ai-mode-auto');
    const manualBtn = document.getElementById('btn-ai-mode-manual');
    if (autoBtn && manualBtn) {
      const activeCls = 'ai-mode-segment-btn-active';
      autoBtn.classList.toggle(activeCls, mode !== 'manual');
      manualBtn.classList.toggle(activeCls, mode === 'manual');
      autoBtn.setAttribute('aria-pressed', String(mode !== 'manual'));
      manualBtn.setAttribute('aria-pressed', String(mode === 'manual'));
    }
  }
  if (state.currentProject) {
    state.currentProject.ai_mode = mode;
  }
}

async function toggleProjectAiMode() {
  if (!state.currentProject) return;
  const current = (state.currentProject.ai_mode || 'auto').toLowerCase();
  const next = current === 'manual' ? 'auto' : 'manual';
  const toggleBtn = document.getElementById('btn-toggle-ai-mode');
  if (toggleBtn) toggleBtn.disabled = true;
  const segmentBtns = ['btn-ai-mode-auto', 'btn-ai-mode-manual']
    .map(id => document.getElementById(id))
    .filter(Boolean);
  segmentBtns.forEach(btn => { btn.disabled = true; });
  try {
    const res = await API.put(`/api/projects/${state.currentProject.id}/ai-mode`, { ai_mode: next });
    if (res && res.success) {
      applyProjectAiMode(res.ai_mode);
      showToast(`已切换为${next === 'manual' ? '手动' : '自动'}模式`);
      // 重新刷新可选元素动画区的状态。
      if (typeof window.__aiMaskResetAutoAttempted === 'function') {
        window.__aiMaskResetAutoAttempted();
      }
      // 重新加载当前步骤以应用模式变化（如 Step 2 UI 切换）
      if (typeof navigateToStep === 'function' && state.currentProject) {
        const visibleStep = resolveProjectVisibleStep(state.currentProject);
        await navigateToStep(visibleStep);
      }
    }
  } finally {
    if (toggleBtn) toggleBtn.disabled = false;
    ['btn-ai-mode-auto', 'btn-ai-mode-manual'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });
  }
}

// 指定模式切换（分段控件按钮入口）：复用既有 AI 模式切换 API。
async function setProjectAiMode(mode) {
  if (!state.currentProject) return;
  const target = (mode || 'auto').toLowerCase() === 'manual' ? 'manual' : 'auto';
  const current = (state.currentProject.ai_mode || 'auto').toLowerCase();
  if (current === target) return;
  const toggleBtn = document.getElementById('btn-toggle-ai-mode');
  if (toggleBtn) toggleBtn.disabled = true;
  ['btn-ai-mode-auto', 'btn-ai-mode-manual'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = true;
  });
  try {
    const res = await API.put(`/api/projects/${state.currentProject.id}/ai-mode`, { ai_mode: target });
    if (res && res.success) {
      applyProjectAiMode(res.ai_mode);
      showToast(`已切换为${target === 'manual' ? '手动' : '自动'}模式`);
      if (typeof window.__aiMaskResetAutoAttempted === 'function') {
        window.__aiMaskResetAutoAttempted();
      }
      if (typeof navigateToStep === 'function' && state.currentProject) {
        const visibleStep = resolveProjectVisibleStep(state.currentProject);
        await navigateToStep(visibleStep);
      }
    }
  } finally {
    if (toggleBtn) toggleBtn.disabled = false;
    ['btn-ai-mode-auto', 'btn-ai-mode-manual'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.disabled = false;
    });
  }
}
window.setProjectAiMode = setProjectAiMode;

function renderProductionModeSummary(project = state.currentProject) {
  // 制作方式已在创建项目时确定，工作区不再用顶部标签重复展示。
  // 清理热更新前残留的节点，避免用户看到无操作价值的状态胶囊。
  document.getElementById('project-production-mode')?.remove();
}


// [一键进度同步 20260912] 一键生成运行时，左侧步骤条实时挂"进行中"标记：
// markStepperRunningStep 由一键轮询调用；updateStepperUI 每次重建步骤条后
// 重新应用标记，保证导航/刷新不会抹掉进行中指示。
let stepperRunningStep = null;
let stepperRunningLabel = '';

function applyStepperRunningMark() {
  document.querySelectorAll('.step-item').forEach(item => {
    item.classList.remove('one-click-running');
    item.querySelectorAll('.step-running-tag').forEach(tag => tag.remove());
  });
  if (!stepperRunningStep) return;
  const item = document.querySelector(`.step-item[data-step="${stepperRunningStep}"]`);
  if (!item) return;
  item.classList.add('one-click-running');
  const badge = item.querySelector('.step-status-tag');
  if (badge) badge.textContent = '进行中';
  // The active-step color and status dot already communicate progress.  A
  // second floating stage label (for example “生成分镜”) makes the narrow
  // sidebar look like a tooltip and obscures the following row.
}

function markStepperRunningStep(step, label) {
  const normalized = Number(step) || null;
  const normalizedLabel = String(label || '').trim();
  if (normalized === stepperRunningStep && normalizedLabel === stepperRunningLabel) return;
  stepperRunningStep = normalized;
  stepperRunningLabel = normalizedLabel;
  updateStepperUI(state.currentStep, state.currentProject?.step_status || {});
}

window.markStepperRunningStep = markStepperRunningStep;

function updateStepperUI(currentStep, stepStatus) {
  const activeStep = normalizeVisibleStep(currentStep);
  const context = projectFlowContext();
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    const step = parseInt(item.dataset.step);
    item.className = 'step-item'; // 重置
    item.querySelectorAll('.step-status-tag').forEach(badge => badge.remove());
    item.querySelectorAll('.step-running-tag').forEach(badge => badge.remove());
    item.classList.remove('one-click-running');

    if (step === activeStep) {
      item.classList.add('active');
    }

    const status = getVisibleStepState(step, stepStatus, context);
    const stateLabel = status === 'completed' ? '已完成'
      : (step === activeStep || step === stepperRunningStep || status === 'in_progress') ? '进行中' : '待完成';
    const stepLabel = item.querySelector('.step-label')?.textContent?.trim() || `步骤${step}`;
    item.dataset.state = stateLabel === '已完成' ? 'completed'
      : stateLabel === '进行中' ? 'in-progress' : 'pending';
    item.setAttribute('aria-label', `${stepLabel}，${stateLabel}`);
    const unavailable = step === 9 && !document.getElementById('step-panel-9');
    item.setAttribute('aria-disabled', String(unavailable));
    item.tabIndex = unavailable ? -1 : 0;
    if (step === activeStep) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
    if (status === 'completed') {
      item.classList.add('completed');
    } else if (status === 'pending_reconfirmation') {
      item.classList.add('pending_reconfirmation');
    }
  });
  applyStepperRunningMark();
}

async function refreshCurrentProjectStatus(activeStep = state.currentStep) {
  const projectId = state.currentProject?.id;
  const navigationVersion = workspaceNavigationVersion;
  if (!projectId) return;
  const project = await API.get(`/api/projects/${projectId}`);
  if (navigationVersion !== workspaceNavigationVersion || !isCurrentWorkspaceProject(projectId)) return;
  state.currentProject = project;
  syncProjectCanvasCssVars(project);
  updateStepperUI(normalizeVisibleStep(activeStep), project.step_status);
}

// 步骤面板切换
async function navigateToStep(step) {
  const navigationVersion = ++workspaceNavigationVersion;
  step = normalizeVisibleStep(step);
  // 离开勾画标注(可选步骤 10)前等待自动保存落盘;失败保留本地编辑并提示
  if (normalizeVisibleStep(state.currentStep) === 10 && step !== 10
      && typeof window.flushAnnotationsSave === 'function') {
    try {
      await window.flushAnnotationsSave();
    } catch (error) {
      if (typeof showToast === 'function') showToast('勾画标注尚未保存成功,已保留本地编辑。');
    }
  }
  // 目标面板不存在时就近兜底：数字人未启用时没有 step-panel-9，回退到
  // 作品输出；其余异常目标保持当前面板，避免所有面板被隐藏后工作区空白。
  if (!document.getElementById(`step-panel-${step}`)) {
    const fallback = step === 9 ? 8 : normalizeVisibleStep(state.currentStep);
    if (!document.getElementById(`step-panel-${fallback}`)) return;
    step = fallback;
  }
  state.currentStep = step;
  const modeButton = document.getElementById('btn-toggle-ai-mode');
  if (modeButton) modeButton.style.display = step === 2 ? 'inline-block' : 'none';
  if (state.currentProject) applyProjectAiMode(state.currentProject.ai_mode || 'auto');
  
  // 隐藏所有面板
  document.querySelectorAll('.step-panel').forEach(panel => panel.style.display = 'none');
  
  // 显示指定步骤面板
  const panel = document.getElementById(`step-panel-${step}`);
  if (panel) panel.style.display = 'block';
  
  // 刷新左侧步骤条高亮，若当前步骤有改动则进行同步
  if (state.currentProject && state.currentProject.current_step !== step) {
    // 更新数据库步骤与后处理状态
    const res = await API.get(`/api/projects/${state.currentProject.id}`);
    if (navigationVersion !== workspaceNavigationVersion) return;
    state.currentProject = res;
    syncProjectCanvasCssVars(res);
  }
  if (navigationVersion !== workspaceNavigationVersion || !state.currentProject) return;
  updateStepperUI(step, state.currentProject.step_status);
  
  // 针对特定步骤加载结果数据
  await loadStepData(step);
}

async function loadStepData(step) {
  switch (step) {
    case 1:
      await loadStep1Data();
      break;
    case 2:
      await loadStep2Data();
      break;
    case 3:
      await loadStep3Data();
      break;
    case 5:
      await loadStep5Data();
      break;
    case 6:
      await loadStep6Data();
      await loadStep7Data();
      break;
    case 8:
      await loadStep8Data();
      break;
    case 9:
      if (typeof window.loadStep9Data === 'function') {
        await window.loadStep9Data();
      }
      break;
    case 10:
      if (typeof window.loadStep10Data === 'function') {
        await window.loadStep10Data();
      }
      break;
  }
}

