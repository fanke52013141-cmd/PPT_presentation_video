(function attachVisibleFlow(root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.PPTFlow = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createVisibleFlow() {
  const VISIBLE_FLOW = Object.freeze([
    Object.freeze({
      step: 1,
      label: '导入文章',
      relevantSteps: Object.freeze([1]),
      completionSteps: Object.freeze([1])
    }),
    Object.freeze({
      step: 2,
      label: '分镜规划',
      relevantSteps: Object.freeze([2]),
      completionSteps: Object.freeze([2])
    }),
    Object.freeze({
      step: 3,
      label: '图片生成',
      relevantSteps: Object.freeze([3, 4]),
      completionSteps: Object.freeze([4])
    }),
    Object.freeze({
      step: 5,
      label: 'AI Mask 标注',
      relevantSteps: Object.freeze([5]),
      completionSteps: Object.freeze([5])
    }),
    Object.freeze({
      step: 6,
      label: '旁白与音频',
      relevantSteps: Object.freeze([6, 7]),
      completionSteps: Object.freeze([6, 7]),
      requiresAudioConfirmation: true
    }),
    // 勾画标注(显示编号 6):决策型模块。完成状态来自模块决策
    // (confirmed / no_annotations),enabled 只决定输出是否携带笔迹。
    // 内部 data-step=10 为兼容键,显示序号一律来自 displayFlow。
    Object.freeze({
      step: 10,
      label: '勾画标注',
      relevantSteps: Object.freeze([10]),
      completionSteps: Object.freeze([10]),
      isDecisionModule: true
    }),
    Object.freeze({
      step: 9,
      label: '数字人讲解',
      relevantSteps: Object.freeze([9]),
      completionSteps: Object.freeze([9]),
      optional: true
    }),
    Object.freeze({
      step: 8,
      label: '作品输出',
      relevantSteps: Object.freeze([8]),
      completionSteps: Object.freeze([8])
    })
  ]);

  const VISIBLE_FLOW_STEPS = Object.freeze(VISIBLE_FLOW.map(item => item.step));

  function normalizeVisibleStep(step) {
    const numericStep = Number(step);
    if (numericStep === 4) return 5;
    if (numericStep === 7) return 6;
    return numericStep;
  }

  function mapClientPointToCanvas(clientX, clientY, rect, width = 1920, height = 1080) {
    const rectWidth = Math.max(1, Number(rect?.width) || 0);
    const rectHeight = Math.max(1, Number(rect?.height) || 0);
    return {
      x: Math.max(0, Math.min(width, (Number(clientX) - Number(rect?.left || 0)) * width / rectWidth)),
      y: Math.max(0, Math.min(height, (Number(clientY) - Number(rect?.top || 0)) * height / rectHeight)),
    };
  }

  function resolveProjectVisibleStep(project = {}) {
    const internalStep = Number(project.current_step || 1);
    if (internalStep === 7 && project.audio_confirmed === true) {
      return 10;
    }
    return normalizeVisibleStep(internalStep);
  }

  function getFlowItem(step) {
    const normalized = normalizeVisibleStep(step);
    return VISIBLE_FLOW.find(item => item.step === normalized) || null;
  }

  function visibleStepNumber(step) {
    const normalized = normalizeVisibleStep(step);
    const index = VISIBLE_FLOW_STEPS.indexOf(normalized);
    return index >= 0 ? index + 1 : normalized;
  }

  function visibleStepLabel(step) {
    return getFlowItem(step)?.label || `步骤 ${Number(step)}`;
  }

  function getVisibleStepState(step, status = {}, context = {}) {
    const item = getFlowItem(step);
    if (!item) return 'pending';

    // 数字人讲解:启用即完成;未启用始终 pending(不阻塞任何步骤)。
    if (item.optional) {
      return context.digitalHumanEnabled === true ? 'completed' : 'pending';
    }
    // 勾画标注(模块六):决策态驱动,与 enabled 解耦。
    if (item.isDecisionModule) {
      switch (context.annotationModuleState) {
        case 'confirmed':
        case 'no_annotations':
          return 'completed';
        case 'editing':
          return 'in_progress';
        case 'stale':
          return 'pending_reconfirmation';
        default:
          return 'pending';
      }
    }

    const relevantStates = item.relevantSteps.map(id => status[String(id)] || 'pending');
    if (relevantStates.includes('pending_reconfirmation')) {
      return 'pending_reconfirmation';
    }

    const completed = item.completionSteps.every(id => status[String(id)] === 'completed');
    if (completed && (!item.requiresAudioConfirmation || context.audioConfirmed === true)) {
      return 'completed';
    }

    if (relevantStates.includes('in_progress')) {
      return 'in_progress';
    }
    return 'pending';
  }

  // 数字人虽为可选步骤，仍保留固定的第 7 步编号。
  function displayFlow(context = {}) {
    const ordered = VISIBLE_FLOW;
    return Object.freeze(ordered.map((item, index) => Object.freeze({
      step: item.step,
      label: item.label,
      displayNumber: index + 1,
      item
    })));
  }

  function calculateVisibleProgress(status = {}, context = {}) {
    // A successfully published output completes this workflow, including
    // static slides that legitimately did not need automatic Masks.
    // Downstream invalidation resets Step 8 when an input changes.
    if (status['8'] === 'completed'
        && !VISIBLE_FLOW.some(item => !item.optional
          && item.relevantSteps.some(id => status[String(id)] === 'pending_reconfirmation'))) {
      return 100;
    }
    const required = VISIBLE_FLOW.filter(item => {
      if (item.optional) return false;
      if (item.isDecisionModule) {
        // 未进入决策的项目不进分母(旧项目兼容);一旦编辑/启用即计入
        const state = context.annotationModuleState;
        return state === 'editing' || state === 'confirmed' || state === 'no_annotations' || state === 'stale';
      }
      return true;
    });
    // 只统计必选步骤的完成数，可选步骤（数字人讲解）不得抬高总进度
    const completed = required.filter(
      item => getVisibleStepState(item.step, status, context) === 'completed'
    ).length;
    return Math.round((Math.min(completed, required.length) / required.length) * 100);
  }

  function getPreviousVisibleStep(step) {
    const normalized = normalizeVisibleStep(step);
    const index = VISIBLE_FLOW_STEPS.indexOf(normalized);
    return index > 0 ? VISIBLE_FLOW_STEPS[index - 1] : null;
  }

  function isVisibleStepUnlocked(step, status = {}, currentStep = 1, context = {}) {
    const normalized = normalizeVisibleStep(step);
    const targetIndex = VISIBLE_FLOW_STEPS.indexOf(normalized);
    if (targetIndex < 0) return false;
    if (targetIndex === 0) return true;

    const activeIndex = VISIBLE_FLOW_STEPS.indexOf(normalizeVisibleStep(currentStep));
    if (activeIndex >= targetIndex) return true;

    const targetState = getVisibleStepState(normalized, status, context);
    if (targetState === 'completed' || targetState === 'pending_reconfirmation') {
      return true;
    }

    if (normalized === 8) {
      return status['7'] === 'completed' && context.audioConfirmed === true;
    }

    // 勾画标注:有当前页图片即可进入编辑(图片已确认),不要求 AI Mask
    // 或音频;讲稿缺失在工作区内以缺失原因提示,不在导航层拦截。
    if (normalized === 10) {
      return status['4'] === 'completed' || status['4'] === 'pending_reconfirmation';
    }

    // 回退链跳过可选步骤:可选模块未启用时不得锁死其后的必选/可选步骤
    // (否则数字人讲解会被未启用的勾画标注挡住)。
    let previousStep = getPreviousVisibleStep(normalized);
    let previousItem = getFlowItem(previousStep);
    while (
      previousItem
      && (previousItem.optional
        || (previousItem.isDecisionModule
          && getVisibleStepState(previousStep, status, context) !== 'completed'
          && getVisibleStepState(previousStep, status, context) !== 'pending_reconfirmation'))
    ) {
      previousStep = getPreviousVisibleStep(previousStep);
      previousItem = getFlowItem(previousStep);
    }
    if (!previousItem) return true;
    const previousState = getVisibleStepState(previousStep, status, context);
    return previousState === 'completed' || previousState === 'pending_reconfirmation';
  }

  const DOWNSTREAM_EDIT_IMPACT = Object.freeze({
    1: '修改文章后，分镜、图片、Mask、旁白与音频、勾画标注和已输出视频可能需要重做。',
    2: '修改分镜后，图片、Mask、旁白与音频、勾画标注和已输出视频可能需要重做。',
    3: '替换图片后，对应页面的 Mask、文字定位与勾画会失效，音频确认及已输出视频可能需要重做。',
    5: '修改 Mask 后，对应页面的揭示效果和已输出视频需要重新生成。',
    6: '修改旁白或重新生成音频后，需要重新确认音频；勾画时间轴、数字人讲解素材和已输出视频可能需要更新。',
    10: '修改勾画标注后，已输出的视频需要重新生成；图片和音频不会被改动。',
    9: '修改数字人视频或布局后，已输出的视频需要重新生成；图片和音频不会被改动。'
  });

  function getDownstreamEditImpact(targetStep, currentStep, status = {}, context = {}) {
    const target = normalizeVisibleStep(targetStep);
    const currentIndex = VISIBLE_FLOW_STEPS.indexOf(normalizeVisibleStep(currentStep));
    const targetIndex = VISIBLE_FLOW_STEPS.indexOf(target);
    if (targetIndex < 0 || currentIndex <= targetIndex) return null;
    const hasDownstreamWork = VISIBLE_FLOW.slice(targetIndex + 1).some(item =>
      getVisibleStepState(item.step, status, context) !== 'pending'
    );
    return hasDownstreamWork ? DOWNSTREAM_EDIT_IMPACT[target] || null : null;
  }

  function moveStep3ImageAssignment(slots = [], fromIndex, toIndex) {
    const fixedSlots = slots.map(slot => ({ ...slot }));
    if (
      !Number.isInteger(fromIndex)
      || !Number.isInteger(toIndex)
      || fromIndex < 0
      || toIndex < 0
      || fromIndex >= fixedSlots.length
      || toIndex >= fixedSlots.length
      || fromIndex === toIndex
    ) {
      return fixedSlots;
    }

    const slideIds = fixedSlots.map(slot => slot.slide_id);
    const assignments = fixedSlots.map(({ slide_id, ...image }) => image);
    const [moved] = assignments.splice(fromIndex, 1);
    assignments.splice(toIndex, 0, moved);
    return slideIds.map((slideId, index) => ({
      slide_id: slideId,
      ...assignments[index]
    }));
  }

  return Object.freeze({
    VISIBLE_FLOW,
    VISIBLE_FLOW_STEPS,
    normalizeVisibleStep,
    mapClientPointToCanvas,
    resolveProjectVisibleStep,
    visibleStepNumber,
    visibleStepLabel,
    displayFlow,
    getVisibleStepState,
    calculateVisibleProgress,
    getPreviousVisibleStep,
    isVisibleStepUnlocked,
    getDownstreamEditImpact,
    moveStep3ImageAssignment
  });
});

(function installStep3ConfirmBeforeMaskHotfix(root) {
  if (!root || typeof root.document === 'undefined' || typeof root.window === 'undefined') {
    return;
  }

  const MARKER = '__ppt_step3_confirm_before_mask_hotfix__';
  if (root[MARKER]) return;
  root[MARKER] = true;

  let confirmingStep3 = false;

  function normalizeStep(step) {
    if (root.PPTFlow && typeof root.PPTFlow.normalizeVisibleStep === 'function') {
      return root.PPTFlow.normalizeVisibleStep(step);
    }
    return Number(step);
  }

  function isStep3PanelActive() {
    const panel = document.getElementById('step-panel-3');
    if (!panel) return false;
    return window.getComputedStyle(panel).display !== 'none';
  }

  function shouldConfirmBeforeEnteringMask() {
    const project = (root.PPTStudio && typeof root.PPTStudio.getCurrentProject === 'function')
      ? root.PPTStudio.getCurrentProject()
      : null;
    const status = project?.step_status || {};
    const imageConfirmed = ['completed', 'pending_reconfirmation'].includes(status['4'])
      || ['completed', 'pending_reconfirmation'].includes(status['5']);
    return !imageConfirmed;
  }

  async function confirmBeforeEnteringMask() {
    if (confirmingStep3) return undefined;
    if (typeof root.confirmStep3Images !== 'function') return undefined;
    confirmingStep3 = true;
    try {
      return await root.confirmStep3Images();
    } finally {
      confirmingStep3 = false;
    }
  }

  function install() {
    if (typeof root.navigateToStep !== 'function' || typeof root.confirmStep3Images !== 'function') {
      return false;
    }

    if (!root.navigateToStep.__ppt_step3_confirm_before_mask_wrapped__) {
      const originalNavigateToStep = root.navigateToStep;
      const wrappedNavigateToStep = async function wrappedNavigateToStep(step, ...rest) {
        if (normalizeStep(step) === 5 && isStep3PanelActive() && !confirmingStep3 && shouldConfirmBeforeEnteringMask()) {
          return confirmBeforeEnteringMask();
        }
        return originalNavigateToStep.call(this, step, ...rest);
      };
      wrappedNavigateToStep.__ppt_step3_confirm_before_mask_wrapped__ = true;
      root.navigateToStep = wrappedNavigateToStep;
    }

    if (!document.__ppt_step3_confirm_before_mask_click_guard__) {
      document.addEventListener('click', event => {
        if (!isStep3PanelActive() || confirmingStep3 || !shouldConfirmBeforeEnteringMask()) return;
        const target = event.target instanceof Element ? event.target : null;
        if (!target) return;
        if (target.closest('#step3-btn-confirm')) return;

        const stepperMaskTarget = target.closest('.step-item[data-step="5"]');
        const genericNextButton = target.closest('.btn-next-step');
        if (!stepperMaskTarget && !genericNextButton) return;

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        confirmBeforeEnteringMask();
      }, true);
      document.__ppt_step3_confirm_before_mask_click_guard__ = true;
    }

    return true;
  }

  function installWithRetry() {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (install() || attempts >= 50) {
        window.clearInterval(timer);
      }
    }, 100);
  }

  if (document.readyState === 'complete') {
    installWithRetry();
  } else {
    window.addEventListener('load', installWithRetry, { once: true });
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
