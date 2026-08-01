// Project workspace entry/exit, AI-mode switching, stepper state, and step data routing.
// Shared state/API/flow helpers live in app.js; step implementations live in their owner modules.

// ==================== 项目管理与系统设置逻辑 ====================

// ==================== 工作区视图控制逻辑 ====================

async function enterWorkspace(projectId) {
  resetStep5ProjectState();
  const project = await API.get(`/api/projects/${projectId}`);
  state.currentProject = project;
  const visibleStep = resolveProjectVisibleStep(project);

  // 顶栏切换
  document.getElementById('project-info-header').style.display = 'flex';
  document.getElementById('current-project-name').innerText = project.name;
  document.getElementById('btn-back-home').style.display = 'block';
  applyProjectAiMode(project.ai_mode || 'auto');

  // 页面切换
  document.getElementById('page-home').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'flex';
  document.body.classList.add('workspace-open');

  // 加载步骤状态并导航至当前步骤
  updateStepperUI(visibleStep, project.step_status);
  navigateToStep(visibleStep);
}

function exitWorkspace() {
  resetStep5ProjectState();
  document.getElementById('project-info-header').style.display = 'none';
  document.getElementById('btn-back-home').style.display = 'none';
  document.getElementById('btn-toggle-ai-mode').style.display = 'none';
  document.getElementById('page-workspace').style.display = 'none';
  document.body.classList.remove('workspace-open');
  document.body.classList.remove('mode-manual');
  document.body.classList.remove('mode-auto');
  document.getElementById('page-home').style.display = 'block';

  state.currentProject = null;
  loadProjects();
}

function applyProjectAiMode(aiMode) {
  const mode = (aiMode || 'auto').toLowerCase() === 'manual' ? 'manual' : 'auto';
  document.body.classList.remove('mode-manual', 'mode-auto');
  document.body.classList.add(mode === 'manual' ? 'mode-manual' : 'mode-auto');
  const toggleBtn = document.getElementById('btn-toggle-ai-mode');
  if (toggleBtn) {
    toggleBtn.style.display = 'inline-block';
    toggleBtn.textContent = `AI 模式: ${mode === 'manual' ? '手动' : '自动'}`;
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
    ? '切换到手动模式后：\n- 第二步将只填写标题和演讲稿，不再调用 AI 生成可视化\n- 第五步进入时不会自动触发 Mask 标注，需要手动点击"运行 AI 标注"\n- 已有的分镜数据不会被清除\n\n确认切换吗？'
    : '切换到自动模式后：\n- 第二步将恢复调用 AI 生成完整分镜\n- 第五步进入时会自动触发 Mask 标注\n- 已有的手动数据不会被清除\n\n确认切换吗？';
  showCustomConfirm('切换 AI 模式', confirmMsg, async () => {
    const res = await API.put(`/api/projects/${state.currentProject.id}/ai-mode`, { ai_mode: next });
    if (res && res.success) {
      applyProjectAiMode(res.ai_mode);
      showToast(`已切换为${next === 'manual' ? '手动' : '自动'}模式`);
      // 切换模式后重置 Step 5 自动标注尝试记录，让新模式下能重新触发
      if (typeof window.__aiMaskResetAutoAttempted === 'function') {
        window.__aiMaskResetAutoAttempted();
      }
      // 重新加载当前步骤以应用模式变化（如 Step 2 UI 切换）
      if (typeof navigateToStep === 'function' && state.currentProject) {
        const visibleStep = resolveProjectVisibleStep(state.currentProject);
        navigateToStep(visibleStep);
      }
    }
  });
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
  if (!state.currentProject?.id) return;
  const project = await API.get(`/api/projects/${state.currentProject.id}`);
  state.currentProject = project;
  updateStepperUI(normalizeVisibleStep(activeStep), project.step_status);
}

// 步骤面板切换
async function navigateToStep(step) {
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
    state.currentProject = res;
  }
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
  }
}

