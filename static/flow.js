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
      label: 'Mask 标注',
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
    Object.freeze({
      step: 8,
      label: '视频合成',
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

  function resolveProjectVisibleStep(project = {}) {
    const internalStep = Number(project.current_step || 1);
    if (internalStep === 7 && project.audio_confirmed === true) {
      return 8;
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

  function calculateVisibleProgress(status = {}, context = {}) {
    const completed = VISIBLE_FLOW.filter(
      item => getVisibleStepState(item.step, status, context) === 'completed'
    ).length;
    return Math.round((completed / VISIBLE_FLOW.length) * 100);
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

    const previousStep = getPreviousVisibleStep(normalized);
    const previousState = getVisibleStepState(previousStep, status, context);
    return previousState === 'completed' || previousState === 'pending_reconfirmation';
  }

  return Object.freeze({
    VISIBLE_FLOW,
    VISIBLE_FLOW_STEPS,
    normalizeVisibleStep,
    resolveProjectVisibleStep,
    visibleStepNumber,
    visibleStepLabel,
    getVisibleStepState,
    calculateVisibleProgress,
    getPreviousVisibleStep,
    isVisibleStepUnlocked
  });
});

(function installStep3ConfirmBeforeMaskHotfix(root) {
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
        if (normalizeStep(step) === 5 && isStep3PanelActive() && !confirmingStep3) {
          return confirmBeforeEnteringMask();
        }
        return originalNavigateToStep.call(this, step, ...rest);
      };
      wrappedNavigateToStep.__ppt_step3_confirm_before_mask_wrapped__ = true;
      root.navigateToStep = wrappedNavigateToStep;
    }

    if (!document.__ppt_step3_confirm_before_mask_click_guard__) {
      document.addEventListener('click', event => {
        if (!isStep3PanelActive() || confirmingStep3) return;
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
