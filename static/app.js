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

// 全局状态管理
let state = {
  currentProject: null,
  currentStep: 1,
  slides: [], // 第二步及后续的分镜/图片/Mask数据
  step2PresentationPolicy: {},
  activeSlideIndex: 0, // 步骤2/3/5/6中当前激活的 slide 索引
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
    boxes: [], // 当前 slide 的标注框列表 [{group_id: '', box: [x1,y1,x2,y2], text_label: '', role: ''}]
    selectedBoxIndex: -1,
    draggedBoxIndex: -1,
    draggedHandle: null, // 'nw', 'ne', 'se', 'sw', 'move'
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

function projectFlowContext(project = state.currentProject) {
  return { audioConfirmed: project?.audio_confirmed === true };
}

// API 请求工具方法
const DEFAULT_REVEAL_DURATION_SEC = 0.25;
const MASK_ANIMATION_PRESETS = [
  { value: 'crop_fade_up', label: '柔和淡入', duration: 0.25 },
  { value: 'wipe_left_to_right', label: '从左到右显现', duration: 0.75 },
  { value: 'scratch_reveal', label: '手绘线条显现', duration: 0.9, angle: 100, feather: 18 },
  { value: 'brush_wipe_left_to_right', label: '笔刷横向显现', duration: 0.85, angle: 90, feather: 24 },
  { value: 'crop_slide_in_left', label: '从左侧滑入显现', duration: 0.65 },
  { value: 'crop_soft_zoom_in', label: '轻微放大显现', duration: 0.7 },
  { value: 'sticker_pop', label: '贴纸粘贴出现', duration: 0.7, rotation: -4 },
  { value: 'stamp_in', label: '盖章弹出出现', duration: 0.6, rotation: 2 },
  { value: 'paper_drop', label: '纸片落下出现', duration: 0.75, rotation: -3 },
];

function revealPreset(action) {
  return MASK_ANIMATION_PRESETS.find(item => item.value === action) || MASK_ANIMATION_PRESETS[0];
}

function normalizeMaskReveal(reveal) {
  const raw = reveal && typeof reveal === 'object' ? reveal : {};
  const preset = revealPreset(raw.type || raw.value || 'crop_fade_up');
  const normalized = {
    ...preset,
    ...raw,
    type: preset.value,
    duration: Number(raw.duration || preset.duration || DEFAULT_REVEAL_DURATION_SEC),
  };
  delete normalized.value;
  delete normalized.label;
  return normalized;
}

function applyRevealToSlideCollections(slide, reveal) {
  if (!slide) return;
  ['groups', 'semantic_blocks'].forEach(field => {
    if (!Array.isArray(slide[field])) return;
    slide[field].forEach(item => {
      if (item && typeof item === 'object') {
        item.reveal = normalizeMaskReveal(reveal);
      }
    });
  });
}

function applyGlobalMaskReveal(reveal, options = {}) {
  const normalized = normalizeMaskReveal(reveal);
  if (!manifestData?.slides) return normalized;
  manifestData.animation_defaults = {
    ...(manifestData.animation_defaults || {}),
    reveal: normalized,
  };
  manifestData.slides.forEach(slide => applyRevealToSlideCollections(slide, normalized));
  state.canvasState.boxes.forEach(box => {
    box.reveal = normalizeMaskReveal(normalized);
  });
  if (options.save !== false) scheduleStep5Autosave();
  return normalized;
}

function ensureGlobalMaskRevealDefault() {
  if (!manifestData?.slides) return;
  const configured = manifestData.animation_defaults?.reveal;
  const normalized = configured
    ? normalizeMaskReveal(configured)
    : normalizeMaskReveal({ type: 'crop_fade_up', duration: DEFAULT_REVEAL_DURATION_SEC });
  applyGlobalMaskReveal(normalized, { save: false });
}

const API = {
  async fetch(url, options = {}) {
    try {
      const method = String(options.method || 'GET').toUpperCase();
      const headers = new Headers(options.headers || {});
      if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        headers.set('X-PPT-Studio-Request', '1');
      }
      const response = await fetch(url, { ...options, headers });
      const contentType = response.headers.get('content-type') || '';
      const rawText = await response.text();
      let data = {};
      if (rawText) {
        if (contentType.includes('application/json')) {
          data = JSON.parse(rawText);
        } else {
          data = { detail: rawText };
        }
      }
      if (!response.ok) {
        const detail = data.detail || data.message || response.statusText || '请求失败';
        const message = typeof detail === 'string'
          ? detail
          : (detail?.message || JSON.stringify(detail));
        throw new Error(message);
      }
      return data;
    } catch (error) {
      showToast(`❌ 错误: ${error.message}`);
      throw error;
    }
  },
  
  async get(url) {
    return this.fetch(url);
  },
  
  async post(url, body) {
    const isFormData = body instanceof FormData;
    return this.fetch(url, {
      method: 'POST',
      body: isFormData ? body : JSON.stringify(body),
      headers: isFormData ? {} : { 'Content-Type': 'application/json' }
    });
  },
  
  async put(url, body) {
    return this.fetch(url, {
      method: 'PUT',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' }
    });
  },
  
  async delete(url) {
    return this.fetch(url, { method: 'DELETE' });
  }
};
window.API = API;

const artifactRepairPrompts = new Set();

async function offerArtifactRepair(result, label, onRepaired) {
  const repair = result?.repair;
  const projectId = state.currentProject?.id;
  if (!projectId || !repair?.required || !repair?.endpoint) return;
  const key = `${projectId}:${repair.endpoint}`;
  if (artifactRepairPrompts.has(key)) return;
  artifactRepairPrompts.add(key);
  const confirmed = window.confirm(`检测到${label}属于旧结构或与当前分镜不一致。是否立即执行一次显式修复？`);
  if (!confirmed) return;
  try {
    const repaired = await API.post(repair.endpoint, {});
    showToast(repaired.changed ? `✅ ${label}已修复` : `✅ ${label}无需修改`);
    if (typeof onRepaired === 'function') await onRepaired();
  } catch (error) {
    artifactRepairPrompts.delete(key);
    showToast(`⚠️ ${label}修复失败：${error.message}`, 7000);
  }
}

// Toast 提示：用状态色传达语义，不在消息前展示风格不统一的 Emoji 图标。
function getToastPresentation(message) {
  const rawMessage = String(message ?? '').trim();
  const text = rawMessage
    .replace(/^(?:[\p{Extended_Pictographic}\uFE0F\u200D]+\s*)+/u, '')
    .trim();

  let tone = 'info';
  if (/^(?:❌|⛔|🚫)/u.test(rawMessage) || /(失败|错误|异常)/.test(rawMessage)) {
    tone = 'error';
  } else if (/^(?:⚠️?|❗)/u.test(rawMessage) || /(请先|请填写|不能为空|缺少|无法|暂无)/.test(rawMessage)) {
    tone = 'warning';
  } else if (/^(?:✅|🎉|✨)/u.test(rawMessage) || /(成功|已保存|已确认|已完成|已删除|已应用|已启动)/.test(rawMessage)) {
    tone = 'success';
  }

  return { text: text || '操作已完成', tone };
}

function showToast(message, duration = 3000) {
  const container = document.getElementById('toast-container');
  while (container.children.length >= 4) {
    container.firstElementChild?.remove();
  }
  const presentation = getToastPresentation(message);
  const toast = document.createElement('div');
  toast.className = `toast toast-${presentation.tone}`;
  toast.setAttribute('role', presentation.tone === 'error' ? 'alert' : 'status');
  toast.innerText = presentation.text;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideUp 0.3s ease-in reverse';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}


// 全局手绘风格自定义确认弹窗
function showCustomConfirm(title, message, onYes, onNo = null) {
  const modal = document.getElementById('modal-confirm');
  document.getElementById('confirm-title').innerText = title;
  document.getElementById('confirm-message').innerText = message;
  
  const btnYes = document.getElementById('btn-confirm-yes');
  const btnNo = document.getElementById('btn-confirm-no');
  
  // 克隆节点清除旧事件
  const newYes = btnYes.cloneNode(true);
  const newNo = btnNo.cloneNode(true);
  btnYes.parentNode.replaceChild(newYes, btnYes);
  btnNo.parentNode.replaceChild(newNo, btnNo);
  
  modal.style.display = 'flex';
  
  newYes.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onYes) onYes();
  });
  
  newNo.addEventListener('click', () => {
    modal.style.display = 'none';
    if (onNo) onNo();
  });
}



// ==================== 跨步骤共享的文本与输入工具 ====================





function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}


function narrationDedupeKey(text) {
  return String(text || '')
    .replace(/<#\d+(?:\.\d{1,2})?#>|\([A-Za-z-]+\)/g, '')
    .toLocaleLowerCase()
    .replace(/[\s\p{P}\p{S}_]+/gu, '');
}

function uniqueNarrationLines(lines) {
  const seen = new Set();
  return (lines || []).filter(text => {
    const key = narrationDedupeKey(text);
    if (key && seen.has(key)) return false;
    if (key) seen.add(key);
    return true;
  });
}


function autoResizeTextarea(textarea) {
  if (!textarea) return;
  if (textarea.tagName === 'TEXTAREA') textarea.rows = 1;
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight + 2}px`;
}







const LLM_PROVIDER_PRESETS = {
  openai: { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  newapi: { baseUrl: '', model: '' },
  openrouter: { baseUrl: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini' },
  litellm: { baseUrl: 'http://localhost:4000/v1', model: '' },
  deepseek: { baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat' },
  volcengine: { baseUrl: 'https://ark.cn-beijing.volces.com/api/v3', model: '' },
  siliconflow: { baseUrl: 'https://api.siliconflow.cn/v1', model: 'deepseek-ai/DeepSeek-V3' },
  dashscope: { baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  zhipu: { baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  custom: { baseUrl: '', model: '' }
};

function detectLlmProvider(savedProvider, baseUrl) {
  const normalized = String(baseUrl || '').replace(/\/+$/, '').toLowerCase();
  const known = Object.entries(LLM_PROVIDER_PRESETS).find(([, preset]) =>
    preset.baseUrl && preset.baseUrl.replace(/\/+$/, '').toLowerCase() === normalized
  );
  if (known) return known[0];
  if (savedProvider === 'newapi' || savedProvider === 'litellm' || savedProvider === 'custom') {
    return savedProvider;
  }
  return normalized ? 'custom' : (savedProvider || 'openai');
}

function applyLlmProviderPreset(provider) {
  const preset = LLM_PROVIDER_PRESETS[provider];
  if (!preset) return;
  if (preset.baseUrl) document.getElementById('setting-llm-base-url').value = preset.baseUrl;
  if (preset.model) document.getElementById('setting-llm-model').value = preset.model;
}
