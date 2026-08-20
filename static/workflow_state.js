// Shared workflow state and the explicit runtime bridge for classic scripts.

const {
  VISIBLE_FLOW,
  normalizeVisibleStep,
  resolveProjectVisibleStep,
  visibleStepNumber,
  visibleStepLabel,
  getVisibleStepState,
  calculateVisibleProgress,
  isVisibleStepUnlocked,
  moveStep3ImageAssignment
} = PPTFlow;

function createWorkflowState() {
  return {
    currentProject: null,
    currentStep: 1,
    slides: [],
    step2PresentationPolicy: {},
    activeSlideIndex: 0,
    settings: {},
    subtitleSettings: null,
    subtitleFonts: [],
    storyboardTemplates: [],
    step2PromptTemplates: [],
    selectedStoryboardTemplateId: '',
    selectedStep2PromptTemplateId: '',
    step2PromptCreating: false,
    activeStep2PromptMode: 'script',
    step2GenerationRequirement: '',
    step3PromptSettings: null,
    storyboardAiRequirement: '',
    pendingStoryboardAiDraft: null,
    articleInputMode: 'article',
    storyboardRoles: {
      title: { label: '主标题' },
      subtitle: { label: '副标题' },
      content_body: { label: '正文内容' },
      diagram: { label: '图示/流程图' },
      quote: { label: '引用/金句' },
      data_point: { label: '数据/数字' },
      process_step: { label: '步骤' },
      callout: { label: '强调提示' },
      annotation: { label: '注释' },
      summary: { label: '总结' },
      decoration: { label: '装饰' },
    },
    step2BatchDeleteMode: false,
    step2DeleteSelection: new Set(),
    step2BatchOriginalSlides: null,
    step2BatchOriginalActiveIndex: 0,
    step2AutoSaveTimer: null,
    step2AutoSaveInFlight: false,
    step5AutoSaveTimer: null,
    step5AutoSaveInFlight: false,
    step5AutoSavePromise: null,
    step6AutoSaveTimer: null,
    step6AutoSavePromise: null,
    canvasState: {
      boxes: [],
      selectedBoxIndex: -1,
      draggedBoxIndex: -1,
      draggedHandle: null,
      paintMode: false,
      paintingBoxIndex: -1,
      eraserMode: false,
      isPainting: false,
      currentStroke: null,
      brushSize: 140,
      eraserSize: 100,
      maskZoom: 1,
      maskZoomOriginX: 50,
      maskZoomOriginY: 50,
      maskFullscreen: false,
      semanticLoading: false,
      confirmingMasks: false,
      animationPreview: null,
      animationModalPreviewRaf: null,
      maskPreviewMode: 'mask',
      exactPreviewImage: null,
      exactPreviewSlideId: '',
      startX: 0,
      startY: 0
    }
  };
}

const state = createWorkflowState();

function projectFlowContext(project = state.currentProject) {
  return {
    audioConfirmed: project?.audio_confirmed === true,
    digitalHumanEnabled: window.__dhEnabled === true,
  };
}

const PPTStudioRuntime = Object.freeze({
  state,
  projectFlowContext,
  flow: Object.freeze({
    VISIBLE_FLOW,
    normalizeVisibleStep,
    resolveProjectVisibleStep,
    visibleStepNumber,
    visibleStepLabel,
    getVisibleStepState,
    calculateVisibleProgress,
    isVisibleStepUnlocked,
    moveStep3ImageAssignment,
  }),
});

window.PPTStudio = Object.assign(window.PPTStudio || {}, { runtime: PPTStudioRuntime });
