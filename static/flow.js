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
