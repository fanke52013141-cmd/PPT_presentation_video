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
  getDownstreamEditImpact,
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
    step2ScriptPlan: null,
    step2VisualStale: false,
    step2VisualExists: false,
    step2WorkflowPending: false,
    step2Stage: 'script',
    // 当前合约的服务端 sha(CAS 保存用);项目切换时由 resetProjectScopedAsyncUi 复位,
    // 在此显式声明防止模块外动态挂载导致复位遗漏。
    step2ContractSha256: null,
    step3PromptSettings: null,
    storyboardAiRequirement: '',
    pendingStoryboardAiDraft: null,
    articleInputMode: 'article',
    step2BatchDeleteMode: false,
    step2DeleteSelection: new Set(),
    step2BatchOriginalSlides: null,
    step2BatchOriginalActiveIndex: 0,
    step2AutoSaveTimer: null,
    step2AutoSaveInFlight: false,
    step2AutoSaveProjectId: '',
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

// Canvas geometry is carried by the project API. Existing projects did not
// persist it, so retain the proven 1920×1080 landscape fallback.
function getProjectCanvasGeometry(project = state.currentProject) {
  const canvas = project?.canvas || {};
  const width = Math.max(1, Number(canvas.width) || 1920);
  const height = Math.max(1, Number(canvas.height) || 1080);
  return {
    width,
    height,
    aspectRatio: `${width} / ${height}`,
    orientation: canvas.orientation || (height > width ? 'portrait' : 'landscape'),
  };
}

function projectFlowContext(project = state.currentProject) {
  return {
    audioConfirmed: project?.audio_confirmed === true,
    digitalHumanEnabled: window.__dhEnabled === true,
    // 勾画标注(模块六)决策态与输出开关;由 annotations 模块维护
    annotationsEnabled: window.__annotationsEnabled === true,
    annotationModuleState: window.__annotationModuleState || 'not_started',
  };
}

const PPTStudioRuntime = Object.freeze({
  state,
  projectFlowContext,
  getProjectCanvasGeometry,
  flow: Object.freeze({
    VISIBLE_FLOW,
    normalizeVisibleStep,
    resolveProjectVisibleStep,
    visibleStepNumber,
    visibleStepLabel,
    getVisibleStepState,
    calculateVisibleProgress,
    isVisibleStepUnlocked,
    getDownstreamEditImpact,
    moveStep3ImageAssignment,
  }),
});

window.PPTStudio = Object.assign(window.PPTStudio || {}, { runtime: PPTStudioRuntime });
