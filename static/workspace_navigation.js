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

function resetProjectScopedAsyncUi() {
  clearTimeout(state.step2AutoSaveTimer);
  state.step2AutoSaveTimer = null;
  if (typeof stopStep8RenderPolling === 'function') stopStep8RenderPolling();
  if (typeof stopStep8PptxPolling === 'function') stopStep8PptxPolling();
  if (typeof resetStep3ProjectState === 'function') resetStep3ProjectState();
  const generateButton = document.getElementById('step2-btn-generate');
  if (generateButton) generateButton.disabled = false;
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
  const entryVersion = ++workspaceNavigationVersion;
  resetProjectScopedAsyncUi();
  resetStep5ProjectState();
  // In-flight work from the old project must fail its ownership guard while
  // the new project's metadata is being fetched.
  state.currentProject = null;
  const project = await API.get(`/api/projects/${projectId}`);
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
  updateStepperUI(visibleStep, project.step_status);
  await navigateToStep(visibleStep);
}

function exitWorkspace() {
  ++workspaceNavigationVersion;
  resetProjectScopedAsyncUi();
  resetStep5ProjectState();
  document.getElementById('project-info-header').style.display = 'none';
  const btnBackHome = document.getElementById('btn-back-home');
  if (btnBackHome) btnBackHome.hidden = true;
  document.getElementById('btn-toggle-ai-mode').style.display = 'none';
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
  const toggleBtn = document.getElementById('btn-toggle-ai-mode');
  if (toggleBtn) {
    toggleBtn.style.display = 'inline-block';
    toggleBtn.textContent = `分镜方式：${mode === 'manual' ? '手动编排' : 'AI 辅助'}`;
    toggleBtn.classList.remove('ai-mode-auto', 'ai-mode-manual');
    toggleBtn.classList.add(mode === 'manual' ? 'ai-mode-manual' : 'ai-mode-auto');
  }
  if (state.currentProject) {
    state.currentProject.ai_mode = mode;
  }
}

async function toggleProjectAiMode() {
  if (!state.currentProject) return;
  const current = (state.currentProject.ai_mode || 'auto').toLowerCase();
  const next = current === 'manual' ? 'auto' : 'manual';
  const confirmMsg = next === 'manual'
    ? '切换到手动编排后：\n- 第二步将只填写标题和演讲稿，不再调用 AI 生成可视化\n- 元素动画仍需在第 5 步由你主动启用\n- 已有的分镜数据不会被清除\n\n确认切换吗？'
    : '切换到 AI 辅助后：\n- 第二步将恢复调用 AI 生成完整分镜\n- 元素动画仍只会在第 5 步由你主动启用\n- 已有的手动数据不会被清除\n\n确认切换吗？';
  showCustomConfirm('切换 AI 模式', confirmMsg, async () => {
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
  });
}

function renderProductionModeSummary(project = state.currentProject) {
  const header = document.getElementById('project-info-header');
  if (!header || !project) return;
  let card = document.getElementById('project-production-mode');
  if (!card) {
    card = document.createElement('button');
    card.id = 'project-production-mode';
    card.type = 'button';
    card.className = 'project-production-mode';
    card.addEventListener('click', () => selectProductionMode());
    header.appendChild(card);
  }
  const production = project.production_mode === 'one_click' ? '一键生成' : '分步制作';
  const presentation = project.presentation_mode === 'reveal' ? '逐元素讲解' : '整页展示';
  card.textContent = `${production} · ${presentation}`;
}

async function selectProductionMode() {
  if (!state.currentProject) return;
  const current = state.currentProject.production_mode === 'one_click' ? 'one_click' : 'guided';
  const chooseOneClick = window.confirm(
    '选择“确定”会进入一键生成：自动完成分镜、整页图片、旁白、语音和视频，不会做 AI Mask 标注。\n\n选择“取消”则使用分步制作，可在第 5 步主动启用元素动画。'
  );
  const next = chooseOneClick ? 'one_click' : 'guided';
  if (next === current) return;
  const result = await API.put(`/api/projects/${state.currentProject.id}`, { production_mode: next });
  if (result?.project) {
    Object.assign(state.currentProject, result.project);
    renderProductionModeSummary();
    showToast(next === 'one_click' ? '已切换为一键生成：将使用整页展示。' : '已切换为分步制作。');
  }
}

function updateStepperUI(currentStep, stepStatus) {
  const activeStep = normalizeVisibleStep(currentStep);
  const context = projectFlowContext();
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    const step = parseInt(item.dataset.step);
    item.className = 'step-item'; // 重置
    item.querySelectorAll('.step-status-tag').forEach(badge => badge.remove());
    
    if (step === activeStep) {
      item.classList.add('active');
    }
    
    const status = getVisibleStepState(step, stepStatus, context);
    if (status === 'completed') {
      item.classList.add('completed');
    } else if (status === 'pending_reconfirmation') {
      item.classList.add('pending_reconfirmation');
      const badge = document.createElement('span');
      badge.className = 'step-status-tag';
      badge.innerText = '需重做';
      item.appendChild(badge);
    }
  });
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
  state.currentStep = step;
  
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
  }
}

