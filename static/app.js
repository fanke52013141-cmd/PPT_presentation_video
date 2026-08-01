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

const PROMPT_IO_HELP = {
  article: {
    title: '话题生成文章',
    inputSummary: '系统只把用户填写的话题作为 User Content；项目名称不会重复发送。',
    inputFields: ['topic：话题、方向和必要背景（最多 500 字）'],
    inputExample: '{\n  "topic": "面向职场新人解释为什么大模型需要 Token，并说明它对成本的影响"\n}',
    outputSummary: '一篇可继续用于分镜规划的 Markdown 正文。',
    outputExample: '# 为什么大模型需要 Token？\n\n## 从文字到计算\n大模型不会直接读取文字……',
  },
  'step2-script': {
    title: '文章➡️slides',
    inputSummary: '只输入完整 article.md、项目标题和用户实际填写的本次补充需求；补充需求为空时不发送该字段。',
    inputFields: ['project_title', 'article_content', 'generation_requirement（可选）'],
    inputExample: '{\n  "project_title": "Token 科普",\n  "article_content": "# Token……",\n  "generation_requirement": "控制在 6 页以内"\n}',
    outputSummary: '严格 JSON；每页只确定 slide_id、slide_title 和完整 narration。',
    outputExample: '{\n  "title": "Token 科普",\n  "slides": [{\n    "slide_id": "slide_001",\n    "slide_title": "Token 是什么？",\n    "narration": "先从最基础的定义说起……"\n  }]\n}',
  },
  'step2-visual': {
    title: 'slides➡️可视化',
    inputSummary: '只输入 Step 2A 已确认的 slide_script_plan，不重复输入文章或项目规则。',
    inputFields: ['slide_script_plan.title', 'slide_script_plan.slides[].slide_id', 'slide_script_plan.slides[].slide_title', 'slide_script_plan.slides[].narration'],
    inputExample: '{\n  "slide_script_plan": {\n    "title": "Token 科普",\n    "slides": [{\n      "slide_id": "slide_001",\n      "slide_title": "Token 是什么？",\n      "narration": "先从最基础的定义说起……"\n    }]\n  }\n}',
    outputSummary: '严格 JSON；把演讲稿原子化为可视化元素，并逐项绑定旁白片段。',
    outputExample: '{\n  "slides": [{\n    "slide_id": "slide_001",\n    "visual_elements": [{\n      "element_id": "el_001",\n      "role": "title",\n      "visual_type": "text",\n      "visual_description": "Token 是什么？",\n      "narration": "先从最基础的定义说起"\n    }]\n  }]\n}',
  },
  'step3-image': {
    title: '图片生成',
    inputSummary: '每页只发送一次主标题和 Step 2B 已确认的正文视觉元素；文章、完整旁白、核心信息和内部 ID 不重复发送。',
    inputFields: ['slide_id（仅任务识别）', 'main_title', 'body_elements[].type', 'body_elements[].content', '当前图片风格与参考图'],
    inputExample: '{\n  "slide_id": "slide_003",\n  "main_title": "为什么要拆分 Token？",\n  "body_elements": [\n    {"type": "picture", "content": "左侧展示一句中文被切分成彩色 Token 积木"},\n    {"type": "text", "content": "模型按 Token 计算，而不是直接读取文字"}\n  ]\n}',
    outputSummary: '一张完整的 1920×1080、16:9 PPT 位图。',
    outputExample: 'PNG/JPEG 位图：纯白外围画布；上方一个主标题；正文元素边界清楚；y=930..1080 完全留空。',
  },
  'step3-style': {
    title: '图片风格设置',
    inputSummary: '可手写 System Content，或上传最多 3 张参考图并填写可选风格要求。',
    inputFields: ['system_content，或 reference_images[]', 'custom_requirement（可选）'],
    inputExample: '参考图：2 张\n补充要求：柔和蓝紫配色、扁平线性图标、留白充足，不复制参考图内容。',
    outputSummary: '当前项目的图片风格 System Content，以及最多 3 张实际参与后续生图的风格参考图。',
    outputExample: 'System Content：柔和蓝紫教育信息图风格；线条简洁；标题层级清楚；使用圆角几何与统一线性图标。',
  },
  'style-reverse': {
    title: '参考图反推图片风格',
    inputSummary: '以 1–3 张参考图为主要证据；只有用户填写时才额外发送 requirement，不重复发送生产规则或输出 Schema。',
    inputFields: ['reference_images[]（1–3 张）', 'requirement（可选）'],
    inputExample: '参考图：2 张\n{\n  "requirement": "保留柔和蓝紫色和圆角线性图标，降低装饰密度"\n}',
    outputSummary: '严格 JSON 的可复用视觉语言；程序再确定性生成图片风格 System Content，并追加白底与 Mask 生产规则。',
    outputExample: '{\n  "style_name": "柔和蓝紫线性信息图",\n  "style_summary": "适合知识讲解的轻盈扁平风格。",\n  "visual_language": {\n    "line_style": "rounded outlines",\n    "shape_language": "rounded panels",\n    "color_palette": ["#6C63FF", "#DCE7FF"],\n    "texture": "flat fills",\n    "lighting": "soft and even",\n    "layout_density": "moderate",\n    "typography": "bold concise headings",\n    "composition": "one focal structure",\n    "iconography": "rounded line icons"\n  },\n  "negative_prompt_rules": ["avoid ornate frames"],\n  "sample_reference_image_prompts": ["A concise cause-and-effect explainer."],\n  "warnings": []\n}',
  },
  'style-reference-generation': {
    title: '风格预览图生成',
    inputSummary: '运行时只组合一份当前风格 System Content、一条内容中立场景简述和不可覆盖的生产规则。',
    inputFields: ['style_system_content', 'scene_brief', 'production_constraints（程序追加）'],
    inputExample: 'style_system_content：柔和蓝紫线性信息图\nscene_brief：A concise process explanation using clear symbols.\nproduction_constraints：16:9、纯白外围画布、元素不粘连',
    outputSummary: '一张用于判断视觉风格的 16:9 预览位图；不输出文字说明或 JSON。',
    outputExample: 'PNG/JPEG 位图：内容中立、风格清晰、纯白外围画布。',
  },
  'ai-mask': {
    title: 'AI Mask 自动标注',
    inputSummary: '系统提交当前 Slide 原图、自动检测后的语义对象，以及 Step 2 的旁白—视觉绑定关系。',
    inputFields: ['image_full', 'semantic_objects[]', 'visual_groups[]', 'narration_beats[]'],
    inputExample: '{\n  "slide_id": "slide_003",\n  "semantic_objects": [{"object_id": "obj_01", "type": "text_block", "bbox": [120, 220, 760, 420]}],\n  "visual_groups": [{"id": "slide_003_el_002"}],\n  "narration_beats": [{"id": "beat_002", "spoken_text": "模型会先切分文本"}]\n}',
    outputSummary: '严格 JSON 的语义对象归属；服务端再生成精确 RLE Mask，并验证覆盖率和零交叉。',
    outputExample: '{\n  "matches": [{\n    "group_id": "slide_003_el_002",\n    "narration_beat_id": "beat_002",\n    "object_ids": ["obj_01"],\n    "element_ids": [],\n    "confidence": 0.97,\n    "reason": "正文语义与对象文字一致"\n  }],\n  "unmatched_objects": [],\n  "unmatched_elements": [],\n  "unmatched_groups": [],\n  "warnings": []\n}',
  },
  'narration-annotation': {
    title: '旁白 AI 标注',
    inputSummary: '输入每页语块 ID 和原始旁白，仅添加 MiniMax 停顿与轻量语气标记。',
    inputFields: ['slides[].slide_id', 'beats[].id', 'beats[].source_text'],
    inputExample: '{\n  "slides": [{\n    "slide_id": "slide_001",\n    "beats": [{"id": "beat_001", "source_text": "首先看核心概念，再理解实际作用。"}]\n  }]\n}',
    outputSummary: '严格 JSON；保留原词，只在 tts_text 中加入合法标记。',
    outputExample: '{\n  "slides": [{\n    "slide_id": "slide_001",\n    "beats": [{"id": "beat_001", "tts_text": "首先看核心概念，<#0.35#>再理解实际作用。"}]\n  }]\n}',
  },
};

function ensurePromptIOHelpModal() {
  let modal = document.getElementById('modal-prompt-io-help');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'modal-prompt-io-help';
  modal.className = 'modal-overlay';
  modal.style.display = 'none';
  modal.innerHTML = `
    <div class="modal-content prompt-io-help-modal" role="dialog" aria-modal="true" aria-labelledby="prompt-io-help-title">
      <header class="prompt-io-help-header">
        <div><span class="prompt-io-help-kicker">INPUT / OUTPUT</span><h3 id="prompt-io-help-title">Prompt 输入输出</h3></div>
        <button id="btn-prompt-io-help-close" class="secondary" type="button">关闭</button>
      </header>
      <div class="prompt-io-help-grid">
        <section><h4>输入是什么</h4><p id="prompt-io-input-summary"></p><ul id="prompt-io-input-fields"></ul><pre id="prompt-io-input-example"></pre></section>
        <section><h4>输出是什么</h4><p id="prompt-io-output-summary"></p><pre id="prompt-io-output-example"></pre></section>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', event => {
    if (event.target === modal) modal.style.display = 'none';
  });
  modal.querySelector('#btn-prompt-io-help-close').addEventListener('click', () => {
    modal.style.display = 'none';
  });
  return modal;
}

function openPromptIOHelp(kind) {
  const help = PROMPT_IO_HELP[kind];
  if (!help) return;
  const modal = ensurePromptIOHelpModal();
  modal.querySelector('#prompt-io-help-title').textContent = `${help.title} · 输入与输出示例`;
  modal.querySelector('#prompt-io-input-summary').textContent = help.inputSummary;
  modal.querySelector('#prompt-io-input-fields').innerHTML = help.inputFields.map(item => `<li>${escHtml(item)}</li>`).join('');
  modal.querySelector('#prompt-io-input-example').textContent = help.inputExample;
  modal.querySelector('#prompt-io-output-summary').textContent = help.outputSummary;
  modal.querySelector('#prompt-io-output-example').textContent = help.outputExample;
  modal.style.display = 'flex';
}

window.openPromptIOHelp = openPromptIOHelp;

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

// 首次加载初始化
document.addEventListener('DOMContentLoaded', () => {
  initGlobalEvents();
  loadProjects();
  loadSettings();
});

// 初始化全局页面级事件监听
function initGlobalEvents() {
  document.addEventListener('click', event => {
    const helpButton = event.target.closest('[data-prompt-help]');
    if (helpButton) openPromptIOHelp(helpButton.dataset.promptHelp);
  });

  // 顶栏按钮
  document.getElementById('btn-open-settings')?.addEventListener('click', () => openSettingsModal());
  document.getElementById('btn-settings-cancel')?.addEventListener('click', () => closeSettingsModal());
  document.getElementById('btn-settings-save')?.addEventListener('click', () => saveSettings());
  document.getElementById('btn-settings-export')?.addEventListener('click', () => exportGlobalSettings());
  document.getElementById('btn-settings-import')?.addEventListener('click', () => {
    document.getElementById('settings-import-file')?.click();
  });
  document.getElementById('btn-config-export')?.addEventListener('click', () => exportGlobalSettings());
  document.getElementById('btn-config-import')?.addEventListener('click', () => {
    document.getElementById('settings-import-file')?.click();
  });
  document.getElementById('settings-import-file')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) importGlobalSettings(file);
  });
  document.getElementById('btn-back-home')?.addEventListener('click', () => exitWorkspace());
  document.getElementById('btn-toggle-ai-mode')?.addEventListener('click', () => toggleProjectAiMode());
  // 绑定设置测试连通性按钮
  document.getElementById('btn-test-llm')?.addEventListener('click', () => testLlmConnection());
  document.getElementById('btn-test-image')?.addEventListener('click', () => testImageConnection());
  document.getElementById('btn-test-tts')?.addEventListener('click', () => testTtsConnection());
  
  // 新建项目 Modal
  document.getElementById('btn-create-project')?.addEventListener('click', () => {
    document.getElementById('input-project-name').value = '';
    document.getElementById('input-project-desc').value = '';
    document.getElementById('modal-create').style.display = 'flex';
  });
  document.getElementById('btn-create-cancel')?.addEventListener('click', () => {
    document.getElementById('modal-create').style.display = 'none';
  });
  document.getElementById('btn-create-submit')?.addEventListener('click', () => createProject());

  // 设置面板 Tab 切换
  const tabs = document.querySelectorAll('#modal-settings .tab-item');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('#modal-settings .tab-pane').forEach(p => p.style.display = 'none');
      document.getElementById(tab.dataset.tab).style.display = 'block';
    });
  });

  // 步骤条点击导航
  const stepItems = document.querySelectorAll('.step-item');
  stepItems.forEach(item => {
    item.addEventListener('click', () => {
      const step = parseInt(item.dataset.step);
      const stepStatus = state.currentProject.step_status;
      const currentStep = state.currentProject.current_step;
      const isUnlocked = isVisibleStepUnlocked(
        step,
        stepStatus,
        currentStep,
        projectFlowContext()
      );
      if (isUnlocked) {
        navigateToStep(step);
      } else {
        showToast(`⚠️ 请先完成前序步骤再进入“${visibleStepLabel(step)}”`);
      }
    });
  });

  // 流水线中所有的“下一步”按钮
  document.querySelectorAll('.btn-next-step').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (state.currentStep === 2) {
        if (!Array.isArray(state.slides) || state.slides.length === 0) {
          showToast('请先添加至少一个分镜，再进入图片生成。');
          return;
        }
        // 手动模式下，跳到 Step 3 前先提交手动分镜到后端
        if (isManualMode()) {
          const ok = await submitManualSkeletonIfNeeded();
          if (!ok) return;
        }
        navigateToStep(3);
      } else if (state.currentStep === 3) {
        navigateToStep(5);
      } else if (state.currentStep === 5) {
        const saved = await saveStep5Masks();
        if (saved) navigateToStep(6);
      } else if (state.currentStep < 8) {
        navigateToStep(state.currentStep + 1);
      }
    });
  });

  // ================= 步骤 1 事件 =================
  document.getElementById('step1-btn-submit')?.addEventListener('click', () => submitStep1());
  document.getElementById('step1-btn-save-edit')?.addEventListener('click', () => saveStep1Edit());
  document.querySelectorAll('[data-step1-mode]').forEach(button => {
    button.addEventListener('click', () => setStep1Mode(button.dataset.step1Mode));
  });
  document.getElementById('step1-btn-generate-article')?.addEventListener('click', () => generateStep1Article());
  document.getElementById('step1-btn-system-content')?.addEventListener('click', () => openArticleSystemContentModal());
  document.getElementById('step1-article-input')?.addEventListener('input', event => autoResizeTextarea(event.currentTarget));

  // ================= 步骤 2 事件 =================
  document.getElementById('step2-btn-generate')?.addEventListener('click', () => generateStep2Contract());
  document.getElementById('btn-step2-generation-cancel')?.addEventListener('click', () => closeStep2GenerationModal());
  document.getElementById('btn-step2-generation-confirm')?.addEventListener('click', () => confirmStep2Generation());
  document.getElementById('step2-btn-script-prompt')?.addEventListener('click', () => openStoryboardRulesModal('script'));
  document.getElementById('step2-btn-visual-prompt')?.addEventListener('click', () => openStoryboardRulesModal('visual'));
  document.getElementById('step2-btn-save')?.addEventListener('click', () => handleStep2BatchDeleteButton());
  document.getElementById('step2-btn-cancel-delete')?.addEventListener('click', () => cancelStep2BatchDelete());
  // 手动模式：添加幻灯片 + 批量导入
  document.getElementById('step2-btn-add-slide')?.addEventListener('click', () => addManualSlide());
  document.getElementById('step2-btn-batch-import')?.addEventListener('click', () => openStep2BatchImportModal());
  document.getElementById('step2-batch-import-download')?.addEventListener('click', () => downloadStep2BatchTemplate());
  document.getElementById('step2-batch-import-file')?.addEventListener('change', e => handleStep2BatchImportFile(e));
  document.getElementById('btn-step2-batch-import-cancel')?.addEventListener('click', closeStep2BatchImportModal);
  document.getElementById('btn-step2-batch-import-append')?.addEventListener('click', () => submitStep2BatchImport('append'));
  document.getElementById('btn-step2-batch-import-overwrite')?.addEventListener('click', () => submitStep2BatchImport('overwrite'));

  // ================= 步骤 3 事件 =================
  document.getElementById('step3-btn-generate')?.addEventListener('click', () => generateStep3Image());
  document.getElementById('step3-btn-close-editor')?.addEventListener('click', () => closeStep3AIModal());
  document.getElementById('step3-btn-apply-candidate')?.addEventListener('click', () => applyStep3Candidate());
  document.getElementById('modal-step3-ai')?.addEventListener('click', (event) => {
    if (event.target.id === 'modal-step3-ai') closeStep3AIModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.getElementById('modal-step3-ai').style.display === 'flex') {
      closeStep3AIModal();
    }
  });
  document.getElementById('step3-batch-upload')?.addEventListener('change', (e) => handleStep3BatchUpload(e));
  document.getElementById('step3-btn-batch-generate')?.addEventListener('click', () => generateAllStep3Images());
  document.getElementById('step3-btn-copy-prompts')?.addEventListener('click', () => copyStep2Prompts());
  document.getElementById('step3-btn-prompt-settings')?.addEventListener('click', () => openStep3PromptSettingsModal());
  document.getElementById('btn-step3-prompt-cancel')?.addEventListener('click', () => closeStep3PromptSettingsModal());
  document.getElementById('btn-step3-prompt-save')?.addEventListener('click', () => saveStep3PromptSettings());
  document.getElementById('btn-step3-prompt-reset')?.addEventListener('click', () => resetStep3PromptSettings());
  document.getElementById('step3-image-system-prompt')?.addEventListener('input', () => updateStep3PromptFullPreview());
  document.getElementById('step3-btn-confirm')?.addEventListener('click', () => confirmStep3Images());

  // ================= 步骤 5 事件 =================
  document.getElementById('step5-btn-new-block')?.addEventListener('click', () => createCurrentSlideBlock());
  document.getElementById('step5-btn-clear-current')?.addEventListener('click', () => clearCurrentSlideMaskAnnotations());
  document.getElementById('step5-btn-subtitle-settings')?.addEventListener('click', () => openSubtitleSettingsModal());
  document.getElementById('step5-btn-animation-settings')?.addEventListener('click', () => openAnimationSettingsModal());
  document.getElementById('step5-btn-fullscreen')?.addEventListener('click', () => toggleStep5Fullscreen());
  document.getElementById('step5-brush-size')?.addEventListener('input', (e) => updateBrushSize(e.target.value));
  document.getElementById('step5-eraser-size')?.addEventListener('input', (e) => updateEraserSize(e.target.value));

  // ================= 步骤 6 事件 =================
  document.getElementById('step6-btn-init')?.addEventListener('click', () => initStep6Narration());
  document.getElementById('step6-btn-ai-annotate')?.addEventListener('click', () => annotateStep6Narration());
  document.getElementById('step6-btn-ai-prompt')?.addEventListener('click', () => openStep6AnnotationPromptModal());
  document.getElementById('btn-step6-ai-prompt-cancel')?.addEventListener('click', () => closeStep6AnnotationPromptModal());
  document.getElementById('btn-step6-ai-prompt-save')?.addEventListener('click', () => saveStep6AnnotationPrompts());
  document.getElementById('step6-ai-system-prompt')?.addEventListener('input', () => updateStep6AnnotationFullPrompt());
  document.getElementById('step6-ai-output-example')?.addEventListener('input', () => updateStep6AnnotationFullPrompt());
  document.getElementById('step6-btn-save-and-tts')?.addEventListener('click', () => saveNarrationAndRunTTS());
  document.getElementById('step6-btn-audio-confirm-next')?.addEventListener('click', async () => {
    const confirmed = await confirmStep7Audio();
    if (confirmed) navigateToStep(8);
  });

  // 步骤 7 后端能力已合并到可见步骤 6
  document.getElementById('step7-btn-synthesize')?.addEventListener('click', () => runStep7TTS());

  // ================= 步骤 8 事件 =================
  document.getElementById('step8-btn-render')?.addEventListener('click', () => runStep8Render());
  document.getElementById('step8-btn-pptx')?.addEventListener('click', () => runStep8PptxExport());
  document.getElementById('step8-btn-finish')?.addEventListener('click', () => exitWorkspace());
  document.getElementById('btn-storyboard-rules-cancel')?.addEventListener('click', () => closeStoryboardRulesModal());
  document.getElementById('btn-step2-prompts-save')?.addEventListener('click', () => saveStep2Prompts());
  document.getElementById('btn-step2-prompt-template-load')?.addEventListener('click', () => loadSelectedStep2PromptTemplate());
  document.getElementById('btn-step2-prompt-template-new')?.addEventListener('click', () => beginStep2PromptTemplateCreation());
  document.getElementById('btn-step2-prompt-template-save')?.addEventListener('click', () => saveStep2PromptTemplate());
  document.getElementById('btn-step2-prompt-template-create-cancel')?.addEventListener('click', () => cancelStep2PromptTemplateCreation());
  document.getElementById('btn-step2-prompt-template-delete')?.addEventListener('click', () => deleteSelectedStep2PromptTemplate());
  document.getElementById('step2-prompt-template-select')?.addEventListener('change', event => {
    cancelStep2PromptTemplateCreation();
    state.selectedStep2PromptTemplateId = event.target.value || '';
    updateStep2PromptTemplateDeleteButton();
  });
  document.getElementById('step2-visual-narration-map')?.addEventListener('input', event => handleStep2MapEditorInput(event));
  document.getElementById('step2-visual-narration-map')?.addEventListener('change', event => handleStep2MapEditorChange(event));
  [
    'step2-script-system-prompt',
    'step2-script-output-example',
    'step2-visual-system-prompt',
    'step2-visual-output-example'
  ].forEach(id => {
    document.getElementById(id)?.addEventListener('input', () => updateStep2FullPromptPreviews());
  });
  document.getElementById('btn-subtitle-settings-close')?.addEventListener('click', () => closeSubtitleSettingsModal());
  document.getElementById('btn-subtitle-settings-save')?.addEventListener('click', () => saveSubtitleSettings());
  document.getElementById('btn-subtitle-settings-reset')?.addEventListener('click', () => resetSubtitleSettings());
  ['subtitle-sample-text', 'subtitle-font-key', 'subtitle-font-size', 'subtitle-font-weight', 'subtitle-bottom', 'subtitle-horizontal-margin', 'subtitle-color', 'subtitle-highlight-color', 'subtitle-paging-window', 'subtitle-max-lines', 'subtitle-token-highlight']
    .forEach(id => document.getElementById(id)?.addEventListener('input', () => updateSubtitlePreview()));
  document.getElementById('btn-animation-settings-close')?.addEventListener('click', () => closeAnimationSettingsModal());
  document.getElementById('btn-animation-settings-preview')?.addEventListener('click', () => previewGlobalAnimationSettings());
  document.getElementById('btn-animation-settings-save')?.addEventListener('click', () => saveGlobalAnimationSettings());
  document.getElementById('btn-animation-settings-reset')?.addEventListener('click', () => resetGlobalAnimationSettings());
  document.getElementById('animation-setting-duration')?.addEventListener('input', (event) => {
    document.getElementById('animation-setting-duration-value').textContent = Number(event.target.value).toFixed(2);
  });
  document.getElementById('setting-llm-provider')?.addEventListener('change', (event) => applyLlmProviderPreset(event.target.value));
  document.addEventListener('wheel', handleGlobalMaskWheel, { passive: false, capture: true });

  // 窗口尺寸变化时重新校准 Step 6 旁白输入框高度（文本换行会随宽度变化）。
  let _step6ResizeTimer = null;
  window.addEventListener('resize', () => {
    if (_step6ResizeTimer) clearTimeout(_step6ResizeTimer);
    _step6ResizeTimer = setTimeout(() => {
      document.querySelectorAll('.step6-tts-input').forEach(ta => _resizeNarrationTextarea(ta));
    }, 150);
  });
}

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






// ==================== 步骤 5: Mask 可视化标注 ====================

let manifestData = null;
let manifestProjectId = '';
let step5SourceCanvas = null;

let step2Contract = null; // 用于缓存步骤 2 分镜规划数据

function resetStep5ProjectState() {
  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  state.step5AutoSavePromise = null;
  state.step5AutoSaveInFlight = false;
  manifestData = null;
  manifestProjectId = '';
  step2Contract = null;
  step5SourceCanvas = null;
  state.canvasState.boxes = [];
  state.canvasState.selectedBoxIndex = -1;
}

const MASK_COLORS = [
  '#E84A5F',
  '#1B998B',
  '#F6AE2D',
  '#3D5A80',
  '#7B2CBF',
  '#2F80ED',
  '#D45113',
  '#4C956C',
  '#C9184A',
  '#0077B6'
];
function getMaskColor(idx) {
  return MASK_COLORS[idx % MASK_COLORS.length];
}

function isValidMaskColor(color) {
  return /^#[0-9a-f]{6}$/i.test(String(color || '').trim());
}

function getBoxColor(maskBox, idx) {
  const storedColor = maskBox?.manual_mask?.color || maskBox?.color;
  return isValidMaskColor(storedColor) ? String(storedColor).trim() : getMaskColor(idx);
}

function claimUniqueMaskColor(preferredColor, idx, usedColors) {
  const preferred = isValidMaskColor(preferredColor) ? String(preferredColor).trim() : getMaskColor(idx);
  if (!usedColors.has(preferred.toUpperCase())) {
    usedColors.add(preferred.toUpperCase());
    return preferred;
  }
  for (let offset = 0; offset < MASK_COLORS.length; offset += 1) {
    const candidate = getMaskColor(idx + offset);
    if (!usedColors.has(candidate.toUpperCase())) {
      usedColors.add(candidate.toUpperCase());
      return candidate;
    }
  }
  usedColors.add(preferred.toUpperCase());
  return preferred;
}

function hexToRgba(hex, alpha) {
  const clean = String(hex || '#111111').replace('#', '');
  const full = clean.length === 3 ? clean.split('').map(ch => ch + ch).join('') : clean;
  const num = parseInt(full, 16);
  if (Number.isNaN(num)) return `rgba(17, 17, 17, ${alpha})`;
  const r = (num >> 16) & 255;
  const g = (num >> 8) & 255;
  const b = num & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function cloneManualMask(mask) {
  if (!mask || typeof mask !== 'object') return { strokes: [] };
  return {
    source: mask.source || '',
    color: mask.color || '',
    bounds: mask.bounds ? { ...mask.bounds } : null,
    rle: mask.rle && mask.rle.encoding === 'row_runs_v1'
      ? {
          encoding: 'row_runs_v1',
          width: Number(mask.rle.width || 1920),
          height: Number(mask.rle.height || 1080),
          runs: Array.isArray(mask.rle.runs)
            ? mask.rle.runs.map(run => [Number(run[0]), Number(run[1]), Number(run[2])])
            : []
        }
      : null,
    strokes: Array.isArray(mask.strokes)
      ? mask.strokes.map(stroke => ({
          color: stroke.color || '',
          size: Number(stroke.size || 42),
          mode: stroke.mode || (stroke.eraser ? 'erase' : 'paint'),
          eraser: !!stroke.eraser,
          points: Array.isArray(stroke.points)
            ? stroke.points.map(point => ({
                x: Number(point.x || 0),
                y: Number(point.y || 0)
              }))
            : []
        }))
      : []
  };
}

function ensureManualMask(maskBox, idx = 0) {
  if (!maskBox.manual_mask || typeof maskBox.manual_mask !== 'object') {
    maskBox.manual_mask = { color: getMaskColor(idx), strokes: [] };
  }
  if (!Array.isArray(maskBox.manual_mask.strokes)) {
    maskBox.manual_mask.strokes = [];
  }
  if (!isValidMaskColor(maskBox.manual_mask.color)) {
    maskBox.manual_mask.color = getMaskColor(idx);
  }
  return maskBox.manual_mask;
}

function getCurrentManifestSlide() {
  return manifestData?.slides?.[state.activeSlideIndex] || null;
}

function getStep2SlideForManifestSlide(manifestSlide = getCurrentManifestSlide()) {
  if (!manifestSlide || !step2Contract?.slides) return null;
  return step2Contract.slides.find(s => s.slide_id === manifestSlide.slide_id) || null;
}

function splitNarrationText(text) {
  const value = String(text || '').trim();
  if (!value) return [];
  const delimiters = new Set(['，', ',', '。', '.', '!', '！', '；', ';', '？', '?']);
  const quotePairs = {
    '“': '”',
    '‘': '’',
    '「': '」',
    '『': '』',
    '《': '》',
    '（': '）',
    '(': ')',
    '[': ']',
    '【': '】',
    '{': '}'
  };
  const inlineQuoteMarks = new Set(['`', '"']);
  const parts = [];
  const stack = [];
  let start = 0;

  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (inlineQuoteMarks.has(ch)) {
      if (stack.length && stack[stack.length - 1] === ch) {
        stack.pop();
      } else {
        stack.push(ch);
      }
    } else if (quotePairs[ch]) {
      stack.push(quotePairs[ch]);
    } else if (stack.length && ch === stack[stack.length - 1]) {
      stack.pop();
    }

    const isDecimalPoint = ch === '.' && /\d/.test(value[i - 1] || '') && /\d/.test(value[i + 1] || '');
    const shouldSplit = ch === '\n' || (delimiters.has(ch) && stack.length === 0 && !isDecimalPoint);
    if (shouldSplit) {
      parts.push(value.slice(start, i + 1).trim());
      start = i + 1;
    }
  }

  if (start < value.length) {
    parts.push(value.slice(start).trim());
  }
  return parts.filter(Boolean);
}

function getNarrationFragments(step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  const fragments = [];
  beats.forEach((beat, beatIdx) => {
    splitNarrationText(beat.spoken_text || '').forEach((text, fragIdx) => {
      fragments.push({
        id: `${beat.id || `beat_${beatIdx + 1}`}::${fragIdx + 1}`,
        beat_id: beat.id || '',
        group_id: beat.group_id || '',
        beat_index: beatIdx,
        fragment_index: fragIdx,
        order: fragments.length + 1,
        text
      });
    });
  });
  return fragments;
}

function getSelectedFragmentIds(maskBox) {
  if (!maskBox) return [];
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.id).filter(Boolean);
  }
  return [];
}

function getSelectedFragmentText(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  if (!maskBox) return '';
  if (Array.isArray(maskBox.narration_fragments) && maskBox.narration_fragments.length > 0) {
    return maskBox.narration_fragments.map(fragment => fragment.text).filter(Boolean).join('');
  }
  const beat = getNarrationBeatForBox(maskBox, step2Slide);
  return maskBox.spoken_text || beat?.spoken_text || '';
}

function normalizeMaskBoxNarrationFragments(maskBox, step2Slide) {
  if (!maskBox || !step2Slide) return;
  const fragments = getNarrationFragments(step2Slide);
  if (!fragments.length) return;

  const beatIds = Array.isArray(maskBox.narration_beat_ids)
    ? maskBox.narration_beat_ids.filter(Boolean)
    : [];
  if (maskBox.narration_beat_id && !beatIds.includes(maskBox.narration_beat_id)) {
    beatIds.push(maskBox.narration_beat_id);
  }

  let selected = [];
  if (beatIds.length) {
    selected = fragments.filter(fragment => beatIds.includes(fragment.beat_id));
  } else if (maskBox.narration_group_id) {
    selected = fragments.filter(fragment => fragment.group_id === maskBox.narration_group_id);
  } else if (maskBox.visual_group_id) {
    selected = fragments.filter(fragment => fragment.group_id === maskBox.visual_group_id);
  }

  if (!selected.length) return;
  const normalized = selected.map(fragment => ({
    id: fragment.id,
    beat_id: fragment.beat_id,
    group_id: fragment.group_id,
    text: fragment.text
  }));
  maskBox.narration_fragments = normalized;
  maskBox.narration_beat_ids = [...new Set(normalized.map(item => item.beat_id).filter(Boolean))];
  maskBox.narration_beat_id = maskBox.narration_beat_ids[0] || '';
  const groupIds = [...new Set(normalized.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_group_id = groupIds[0] || maskBox.narration_group_id || maskBox.visual_group_id || '';
  maskBox.spoken_text = normalized.map(item => item.text).join('');
}

function normalizeManifestNarrationFragments() {
  if (!manifestData?.slides || !step2Contract?.slides) return;
  manifestData.slides.forEach(slide => {
    const step2Slide = getStep2SlideForManifestSlide(slide);
    if (!step2Slide) return;
    ['semantic_blocks', 'groups'].forEach(field => {
      if (!Array.isArray(slide[field])) return;
      slide[field].forEach(box => normalizeMaskBoxNarrationFragments(box, step2Slide));
    });
  });
}

function getNarrationBeatForBox(maskBox, step2Slide = getStep2SlideForManifestSlide()) {
  const beats = step2Slide?.narration_beats || [];
  if (!beats.length || !maskBox) return null;
  if (Array.isArray(maskBox.narration_beat_ids) && maskBox.narration_beat_ids.length > 0) {
    const byFirstId = beats.find(beat => beat.id === maskBox.narration_beat_ids[0]);
    if (byFirstId) return byFirstId;
  }
  if (maskBox.narration_beat_id) {
    const byId = beats.find(beat => beat.id === maskBox.narration_beat_id);
    if (byId) return byId;
  }
  if (maskBox.narration_group_id) {
    const byLinkedGroup = beats.find(beat => beat.group_id === maskBox.narration_group_id);
    if (byLinkedGroup) return byLinkedGroup;
  }
  return beats.find(beat => beat.group_id === maskBox.group_id) || null;
}

function isEraseStroke(stroke) {
  return !!stroke?.eraser || String(stroke?.mode || '').toLowerCase() === 'erase';
}

function hasPaintStroke(maskBox) {
  const exactRuns = maskBox?.manual_mask?.rle?.runs;
  if (Array.isArray(exactRuns) && exactRuns.length > 0) return true;
  return (maskBox?.manual_mask?.strokes || []).some(stroke => !isEraseStroke(stroke) && (stroke.points || []).length > 0);
}

function hasVisibleMaskPixels(maskBox) {
  if (!hasPaintStroke(maskBox)) return false;
  return !!maskPixelBounds(maskBox);
}

function isManualEmptyBox(maskBox) {
  return String(maskBox?.group_id || '').startsWith('manual_group_') && !hasVisibleMaskPixels(maskBox);
}

function isSemanticDraftBox(maskBox) {
  return String(maskBox?.source || '') === 'ai_semantic' && !hasVisibleMaskPixels(maskBox);
}

function isDraftMaskBox(maskBox) {
  return isManualEmptyBox(maskBox) || isSemanticDraftBox(maskBox);
}

function copySemanticFields(target, source) {
  if (!target || !source) return target;
  [
    'source',
    'visual_group_id',
    'element_id',
    'visual_type',
    'semantic_element_type',
    'visual_description',
    'semantic_note',
    'semantic_confidence'
  ].forEach(field => {
    if (source[field] !== undefined && source[field] !== null && source[field] !== '') {
      target[field] = source[field];
    }
  });
  return target;
}

function groupToMaskBox(group) {
  const box = group.box || {};
  const x = Number(box.x || 0);
  const y = Number(box.y || 0);
  const w = Number(box.w || 1);
  const h = Number(box.h || 1);
  return copySemanticFields({
    group_id: group.id || group.group_id || '',
    role: group.role || 'content_body',
    text_label: group.visible_text || group.text_label || '',
    visual_anchor: group.visual_anchor || '',
    narration_beat_id: group.narration_beat_id || group.linked_segment_id || '',
    narration_beat_ids: Array.isArray(group.narration_beat_ids) ? [...group.narration_beat_ids] : [],
    narration_group_id: group.narration_group_id || '',
    narration_fragments: Array.isArray(group.narration_fragments) ? JSON.parse(JSON.stringify(group.narration_fragments)) : [],
    spoken_text: group.spoken_text || '',
    reveal: normalizeMaskReveal(group.reveal),
    manual_mask: cloneManualMask(group.manual_mask),
    box: [x, y, x + w, y + h]
  }, group);
}

function normalizeRevealBox(box, idx) {
  return copySemanticFields({
    ...box,
    visual_anchor: box.visual_anchor || '',
    narration_beat_id: box.narration_beat_id || '',
    narration_beat_ids: Array.isArray(box.narration_beat_ids) ? [...box.narration_beat_ids] : [],
    narration_group_id: box.narration_group_id || '',
    narration_fragments: Array.isArray(box.narration_fragments) ? JSON.parse(JSON.stringify(box.narration_fragments)) : [],
    reveal: normalizeMaskReveal(box.reveal),
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, box);
}

function semanticBlockToMaskBox(box, idx) {
  return normalizeRevealBox({
    role: "content_body",
    text_label: `语块 ${idx + 1}`,
    visual_anchor: "",
    spoken_text: "",
    reveal: normalizeMaskReveal(box.reveal),
    box: [860, 460, 1060, 620],
    ...box,
    source: "ai_semantic",
    manual_mask: cloneManualMask(box.manual_mask || { color: getMaskColor(idx), strokes: [] })
  }, idx);
}

function isManualUserMaskBox(box) {
  return String(box?.group_id || box?.id || '').startsWith('manual_group_');
}

function hasLinkedNarration(box) {
  if (String(box?.spoken_text || '').trim()) return true;
  if (String(box?.narration_beat_id || '').trim()) return true;
  if (Array.isArray(box?.narration_beat_ids) && box.narration_beat_ids.some(Boolean)) return true;
  return Array.isArray(box?.narration_fragments)
    && box.narration_fragments.some(fragment => String(fragment?.text || fragment?.id || '').trim());
}

function isDisplayableMaskBox(box) {
  return isManualUserMaskBox(box) || hasLinkedNarration(box);
}

function clearMaskBoxNarration(maskBox) {
  maskBox.narration_fragments = [];
  maskBox.narration_beat_ids = [];
  maskBox.narration_beat_id = '';
  maskBox.narration_group_id = '';
  maskBox.spoken_text = '';
}

function setMaskBoxNarrationFragments(maskBox, fragments) {
  const normalized = Array.isArray(fragments) ? fragments : [];
  maskBox.narration_fragments = normalized;
  maskBox.narration_beat_ids = [...new Set(normalized.map(item => item.beat_id).filter(Boolean))];
  maskBox.narration_beat_id = maskBox.narration_beat_ids[0] || '';
  const groupIds = [...new Set(normalized.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_group_id = groupIds[0] || '';
  maskBox.spoken_text = normalized.map(item => item.text).filter(Boolean).join('');
}

function dedupeMaskBoxNarrationAssignments(boxes) {
  const usedFragmentIds = new Set();
  return boxes.map(box => {
    if (!Array.isArray(box?.narration_fragments) || box.narration_fragments.length === 0) {
      return box;
    }
    const kept = [];
    box.narration_fragments.forEach(fragment => {
      const fragmentId = String(fragment?.id || '').trim();
      if (fragmentId && usedFragmentIds.has(fragmentId)) return;
      kept.push(fragment);
      if (fragmentId) usedFragmentIds.add(fragmentId);
    });
    if (kept.length === box.narration_fragments.length) return box;
    if (kept.length === 0) {
      clearMaskBoxNarration(box);
      return box;
    }
    setMaskBoxNarrationFragments(box, kept);
    return box;
  }).filter(isDisplayableMaskBox);
}

function getSlideMaskBoxes(slide) {
  if (!slide) return [];
  const semanticBoxes = Array.isArray(slide.semantic_blocks)
    ? slide.semantic_blocks.map(semanticBlockToMaskBox)
    : [];
  const semanticIds = new Set(semanticBoxes.map(box => box.group_id).filter(Boolean));

  let baseBoxes = [];
  if (Array.isArray(slide.groups) && slide.groups.length > 0) {
    baseBoxes = slide.groups.map(groupToMaskBox);
  }

  const baseById = new Map(baseBoxes.map(box => [box.group_id, box]));
  const merged = semanticBoxes.map((semanticBox, idx) => {
    const existing = baseById.get(semanticBox.group_id);
    if (!existing) return semanticBlockToMaskBox(semanticBox, idx);
    return {
      ...semanticBox,
      ...existing,
      source: existing.source || semanticBox.source,
      visual_group_id: existing.visual_group_id || semanticBox.visual_group_id,
      semantic_element_type: existing.semantic_element_type || semanticBox.semantic_element_type,
      visual_description: existing.visual_description || semanticBox.visual_description,
      semantic_note: existing.semantic_note || semanticBox.semantic_note,
      semantic_confidence: existing.semantic_confidence || semanticBox.semantic_confidence,
      manual_mask: cloneManualMask(existing.manual_mask || semanticBox.manual_mask)
    };
  });
  baseBoxes.forEach(box => {
    if (!semanticIds.has(box.group_id)) merged.push(box);
  });
  const usedColors = new Set();
  return dedupeMaskBoxNarrationAssignments(merged.filter(isDisplayableMaskBox))
    .map((box, idx) => {
      const manualMask = cloneManualMask(box.manual_mask || { strokes: [] });
      const color = claimUniqueMaskColor(getBoxColor(box, idx), idx, usedColors);
      return {
        ...box,
        manual_mask: {
          ...manualMask,
          color
        }
      };
    });
}

function syncMaskBoxesToSlide(slide, boxes) {
  if (!slide) return;
  boxes = Array.isArray(boxes) ? boxes : [];
  boxes.forEach((maskBox, idx) => {
    if (maskBox?.manual_mask?.strokes?.length || maskBox?.manual_mask?.rle?.runs?.length) {
      updateMaskBoxFromManualMask(idx);
    }
  });
  const readyBoxes = boxes.filter(maskBox => !isDraftMaskBox(maskBox));
  const semanticBoxes = boxes
    .filter(maskBox => String(maskBox?.source || '') === 'ai_semantic')
    .filter(hasLinkedNarration)
    .map((maskBox, idx) => ({
      ...maskBox,
      manual_mask: {
        ...cloneManualMask(maskBox.manual_mask || { strokes: [] }),
        color: getMaskColor(idx)
      }
    }));
  slide.semantic_blocks = JSON.parse(JSON.stringify(semanticBoxes));

  if (!Array.isArray(slide.groups)) {
    slide.groups = [];
  }
  const visibleGroupIds = new Set(readyBoxes.map(maskBox => maskBox.group_id).filter(Boolean));
  slide.groups = slide.groups.filter(group => (
    group?.is_static === true
    || group?.is_static_header === true
    || String(group?.source || '') === 'ai_static_header'
    || visibleGroupIds.has(group.id || group.group_id)
  ));
  readyBoxes.forEach((maskBox, idx) => {
    ensureManualMask(maskBox, idx);
    const [rawX1, rawY1, rawX2, rawY2] = maskBox.box || [0, 0, 1, 1];
    const x1 = Math.max(0, Math.round(Math.min(rawX1, rawX2)));
    const y1 = Math.max(0, Math.round(Math.min(rawY1, rawY2)));
    const x2 = Math.min(1920, Math.round(Math.max(rawX1, rawX2)));
    const y2 = Math.min(1080, Math.round(Math.max(rawY1, rawY2)));
    let group = slide.groups.find(g => g.id === maskBox.group_id);
    if (!group) {
      group = {
        id: maskBox.group_id || `custom_group_${idx + 1}`,
        role: maskBox.role || 'content_body',
        visible_text: maskBox.text_label || '',
        reveal: normalizeMaskReveal(maskBox.reveal),
        padding_px: 32,
        z_index: 40 + idx
      };
      slide.groups.push(group);
    }
    group.reveal = normalizeMaskReveal(maskBox.reveal || group.reveal);
    group.role = maskBox.role || group.role || 'content_body';
    group.source = maskBox.source || group.source || '';
    if (maskBox.text_label) group.visible_text = maskBox.text_label;
    if (maskBox.visual_anchor) group.visual_anchor = maskBox.visual_anchor;
    if (maskBox.visual_group_id) group.visual_group_id = maskBox.visual_group_id;
    if (maskBox.element_id) group.element_id = maskBox.element_id;
    if (maskBox.visual_type) group.visual_type = maskBox.visual_type;
    if (maskBox.semantic_element_type) group.semantic_element_type = maskBox.semantic_element_type;
    if (maskBox.visual_description) group.visual_description = maskBox.visual_description;
    if (maskBox.semantic_note) group.semantic_note = maskBox.semantic_note;
    if (maskBox.semantic_confidence) group.semantic_confidence = maskBox.semantic_confidence;
    if (maskBox.narration_beat_id) group.narration_beat_id = maskBox.narration_beat_id;
    group.narration_beat_ids = Array.isArray(maskBox.narration_beat_ids) ? [...maskBox.narration_beat_ids] : [];
    if (maskBox.narration_group_id) group.narration_group_id = maskBox.narration_group_id;
    group.narration_fragments = Array.isArray(maskBox.narration_fragments) ? JSON.parse(JSON.stringify(maskBox.narration_fragments)) : [];
    if (maskBox.spoken_text) group.spoken_text = maskBox.spoken_text;
    group.manual_mask = cloneManualMask(maskBox.manual_mask || { strokes: [] });
    group.manual_mask.color = getBoxColor(maskBox, idx);
    if (group.manual_mask.strokes.length > 0) {
      group.review_status = "manual_painted";
    }
    group.box = {
      x: x1,
      y: y1,
      w: Math.max(1, x2 - x1),
      h: Math.max(1, y2 - y1)
    };
  });
}

async function loadStep5Data() {
  const projectId = state.currentProject?.id;
  if (!projectId) return;
  await loadStep3VisualSettings();
  try {
    const contractRes = await API.get(`/api/projects/${projectId}/steps/2/result`);
    if (state.currentProject?.id !== projectId) return;
    if (contractRes.success && contractRes.contract) {
      step2Contract = contractRes.contract;
    }
  } catch (e) {}

  const res = await API.get(`/api/projects/${projectId}/steps/5/result`);
  if (state.currentProject?.id !== projectId) return;
  if (res.success && res.manifest) {
    manifestData = res.manifest;
    manifestProjectId = projectId;
    // 智能初始化每一页 slide 的状态并向下兼容
    manifestData.slides.forEach(s => {
      if (!s.status) {
        // 如果存在标注块尚未审核完成，则设为 pending，否则设为 completed
        const needsAdjustment = (s.groups || []).some(g => 
          g.review_status === "needs_manual_adjustment_after_image_gen" || 
          g.review_status === "auto_fitted_needs_review"
        );
        s.status = needsAdjustment ? "pending" : "completed";
      }
    });
    ensureGlobalMaskRevealDefault();
    normalizeManifestNarrationFragments();
    renderStep5Workspace();
    void offerArtifactRepair(res, 'Mask 数据', loadStep5Data);
  }
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


const DEFAULT_SUBTITLE_SETTINGS = {
  font_key: 'noto_sans_sc',
  font_family: 'Noto Sans SC',
  font_size: 38,
  font_weight: 500,
  bottom: 18,
  horizontal_margin: 180,
  color: '#111111',
  // 方案 B：TikTok 式整页分页 + 逐字高亮
  highlight_color: '#1E3A8A',
  paging_window_ms: 1300,
  token_highlight: true,
  max_lines: 2,
  line_height: 1.4,
};

function subtitleFontByKey(key) {
  return state.subtitleFonts.find(font => font.key === key) || {
    key: DEFAULT_SUBTITLE_SETTINGS.font_key,
    family: DEFAULT_SUBTITLE_SETTINGS.font_family,
  };
}

function readSubtitleSettingsForm() {
  const fontKey = document.getElementById('subtitle-font-key').value || DEFAULT_SUBTITLE_SETTINGS.font_key;
  const font = subtitleFontByKey(fontKey);
  const maxLines = Number(document.getElementById('subtitle-max-lines').value || 2);
  return {
    font_key: fontKey,
    font_family: font.family,
    font_size: Number(document.getElementById('subtitle-font-size').value || 38),
    font_weight: Number(document.getElementById('subtitle-font-weight').value || 500),
    bottom: Number(document.getElementById('subtitle-bottom').value || 18),
    horizontal_margin: Number(document.getElementById('subtitle-horizontal-margin').value || 180),
    color: document.getElementById('subtitle-color').value || '#111111',
    highlight_color: document.getElementById('subtitle-highlight-color').value || '#1E3A8A',
    paging_window_ms: Number(document.getElementById('subtitle-paging-window').value || 1300),
    token_highlight: document.getElementById('subtitle-token-highlight').checked,
    max_lines: Math.min(3, Math.max(1, maxLines)),
    line_height: 1.4,
  };
}

function populateSubtitleSettingsForm(settings) {
  const value = { ...DEFAULT_SUBTITLE_SETTINGS, ...(settings || {}) };
  document.getElementById('subtitle-font-key').value = value.font_key;
  document.getElementById('subtitle-font-size').value = String(value.font_size);
  document.getElementById('subtitle-font-weight').value = String(value.font_weight);
  document.getElementById('subtitle-bottom').value = String(value.bottom);
  document.getElementById('subtitle-horizontal-margin').value = String(value.horizontal_margin);
  document.getElementById('subtitle-color').value = String(value.color || '#111111');
  document.getElementById('subtitle-highlight-color').value = String(value.highlight_color || '#1E3A8A');
  document.getElementById('subtitle-paging-window').value = String(value.paging_window_ms || 1300);
  document.getElementById('subtitle-max-lines').value = String(value.max_lines || 2);
  document.getElementById('subtitle-token-highlight').checked = value.token_highlight !== false;
  updateSubtitlePreview();
}

function updateSubtitlePreview() {
  const stage = document.querySelector('.subtitle-preview-stage');
  const text = document.getElementById('subtitle-preview-text');
  if (!stage || !text) return;
  const settings = readSubtitleSettingsForm();
  const font = subtitleFontByKey(settings.font_key);
  const scale = Math.max(0.2, stage.clientWidth / 1920);
  const sample = document.getElementById('subtitle-sample-text').value.trim();
  const sampleText = sample || '这是一段视频字幕效果预览';
  text.style.fontFamily = `${font.family}, "Microsoft YaHei", sans-serif`;
  text.style.fontSize = `${settings.font_size * scale}px`;
  text.style.fontWeight = String(settings.font_weight);
  text.style.bottom = `${settings.bottom * scale}px`;
  text.style.left = `${settings.horizontal_margin * scale}px`;
  text.style.right = `${settings.horizontal_margin * scale}px`;
  text.style.color = settings.color;
  // 预览中加入逐字高亮示意：已播放部分高亮，未播放部分保持字幕颜色。
  const enableHighlight = settings.token_highlight !== false;
  if (enableHighlight) {
    const splitAt = Math.max(1, Math.floor(sampleText.length / 3));
    const highlighted = document.createElement('span');
    const pending = document.createElement('span');
    highlighted.textContent = sampleText.slice(0, splitAt);
    highlighted.style.color = settings.highlight_color;
    pending.textContent = sampleText.slice(splitAt);
    pending.style.color = settings.color;
    text.replaceChildren(highlighted, pending);
  } else {
    text.textContent = sampleText;
    text.style.color = settings.color;
  }
  text.style.lineHeight = String(settings.line_height || 1.4);
  text.style.whiteSpace = 'pre-wrap';
  text.style.wordBreak = 'keep-all';
  text.style.display = '-webkit-box';
  text.style.WebkitBoxOrient = 'vertical';
  text.style.WebkitLineClamp = String(settings.max_lines || 2);
  text.style.overflow = 'hidden';
  const marginWidth = settings.horizontal_margin * scale;
  const leftShade = document.getElementById('subtitle-margin-left-shade');
  const rightShade = document.getElementById('subtitle-margin-right-shade');
  const safeGuide = document.getElementById('subtitle-safe-width-guide');
  if (leftShade) leftShade.style.width = `${marginWidth}px`;
  if (rightShade) rightShade.style.width = `${marginWidth}px`;
  if (safeGuide) {
    safeGuide.style.left = `${marginWidth}px`;
    safeGuide.style.right = `${marginWidth}px`;
    const label = safeGuide.querySelector('span');
    if (label) label.textContent = `字幕可用宽度 ${Math.max(0, 1920 - settings.horizontal_margin * 2)} px`;
  }
  document.getElementById('subtitle-font-size-value').textContent = String(settings.font_size);
  document.getElementById('subtitle-font-weight-value').textContent = String(settings.font_weight);
  document.getElementById('subtitle-bottom-value').textContent = String(settings.bottom);
  document.getElementById('subtitle-margin-value').textContent = String(settings.horizontal_margin);
  document.getElementById('subtitle-color-value').textContent = String(settings.color);
  document.getElementById('subtitle-highlight-color-value').textContent = String(settings.highlight_color);
  document.getElementById('subtitle-paging-window-value').textContent = String(settings.paging_window_ms);
  document.getElementById('subtitle-max-lines-value').textContent = String(settings.max_lines);
}

async function openSubtitleSettingsModal() {
  if (!state.currentProject?.id) return;
  const res = await API.get(`/api/projects/${state.currentProject.id}/subtitle-settings`);
  state.subtitleSettings = res.subtitle_style || { ...DEFAULT_SUBTITLE_SETTINGS };
  state.subtitleFonts = res.fonts || [];
  const fontSelect = document.getElementById('subtitle-font-key');
  fontSelect.innerHTML = state.subtitleFonts.map(font =>
    `<option value="${escHtml(font.key)}">${escHtml(font.label)}</option>`
  ).join('');
  const preview = document.getElementById('subtitle-preview-image');
  preview.src = res.preview_url || '';
  preview.style.display = res.preview_url ? 'block' : 'none';
  populateSubtitleSettingsForm(state.subtitleSettings);
  document.getElementById('modal-subtitle-settings').style.display = 'flex';
  requestAnimationFrame(updateSubtitlePreview);
}

function closeSubtitleSettingsModal() {
  document.getElementById('modal-subtitle-settings').style.display = 'none';
}

function resetSubtitleSettings() {
  populateSubtitleSettingsForm(DEFAULT_SUBTITLE_SETTINGS);
  showToast('字幕样式已恢复为默认值，点击保存后生效。');
}

async function saveSubtitleSettings() {
  const subtitle_style = readSubtitleSettingsForm();
  const res = await API.put(
    `/api/projects/${state.currentProject.id}/subtitle-settings`,
    { subtitle_style },
  );
  state.subtitleSettings = res.subtitle_style;
  populateSubtitleSettingsForm(state.subtitleSettings);
  closeSubtitleSettingsModal();
  showToast('字幕样式已保存，下一次视频渲染将使用当前字体、字号和位置。');
  refreshCurrentProjectStatus().catch(() => {});
}


function renderStep5Workspace() {
  updateStep5SemanticButton();
  updateStep5ConfirmButton();
  document.body.classList.toggle('step5-fullscreen-mode', !!state.canvasState.maskFullscreen);
  const fullscreenLabel = document.getElementById('step5-fullscreen-label');
  if (fullscreenLabel) fullscreenLabel.textContent = state.canvasState.maskFullscreen ? '退出全屏' : '放大标注';
  const thumbsContainer = document.getElementById('step5-thumbs');
  thumbsContainer.className = 'step5-slides-grid'; // 改用平铺换行类名
  thumbsContainer.innerHTML = '';
  
  manifestData.slides.forEach((slide, idx) => {
    const btn = document.createElement('div');
    const isCurrent = idx === state.activeSlideIndex;
    btn.className = `step5-slide-btn${isCurrent ? ' active' : ''}`;
    btn.innerHTML = `
      <div style="font-size: 0.85rem; font-weight: bold; color: var(--ink-color);">${slide.slide_id}</div>
    `;
    
    btn.addEventListener('click', () => {
      stopMaskAnimationPreview();
      saveStep5CurrentState();
      state.activeSlideIndex = idx;
      renderStep5Workspace();
    });
    thumbsContainer.appendChild(btn);
  });
  
  // 加载当前 Slide 详情
  const slide = manifestData.slides[state.activeSlideIndex];
  if (slide) {
    // 设置 Canvas 背景图
    const imgUrl = `/api/projects/${state.currentProject.id}/slides/${slide.slide_id}/image?t=${uuid()}`;
    const backgroundImage = document.getElementById('step5-bg-img');
    step5SourceCanvas = null;
    backgroundImage.onload = () => {
      rebuildStep5SourceCache(backgroundImage);
      redrawCanvas();
    };
    backgroundImage.onerror = () => {
      showToast('当前页原图加载失败，请刷新页面后重试。', 5000);
    };
    backgroundImage.src = imgUrl;
    
    // 初始化 canvas 标注框数据并重绘
    state.canvasState.boxes = getSlideMaskBoxes(slide);
    state.canvasState.selectedBoxIndex = -1;
    state.canvasState.draggedBoxIndex = -1;
    state.canvasState.draggedHandle = null;
    state.canvasState.paintMode = false;
    state.canvasState.eraserMode = false;
    state.canvasState.paintingBoxIndex = -1;
    state.canvasState.isPainting = false;
    state.canvasState.currentStroke = null;
    updateBrushSize(state.canvasState.brushSize, false);
    updateEraserSize(state.canvasState.eraserSize, false);
    initCanvasEvents();
    redrawCanvas();
    
    // 渲染右侧属性列表
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
  }
}

function switchStep5Slide(direction) {
  if (!manifestData?.slides?.length) return;
  stopMaskAnimationPreview();
  saveStep5CurrentState();
  const total = manifestData.slides.length;
  state.activeSlideIndex = (state.activeSlideIndex + direction + total) % total;
  invalidateStep5ExactPreview();
  renderStep5Workspace();
  scheduleStep5Autosave();
}

function toggleStep5Fullscreen(force) {
  state.canvasState.maskFullscreen = typeof force === 'boolean'
    ? force
    : !state.canvasState.maskFullscreen;
  document.body.classList.toggle('step5-fullscreen-mode', !!state.canvasState.maskFullscreen);
  const canvas = document.getElementById('step5-canvas');
  setTimeout(() => {
    applyMaskCanvasZoom(canvas);
    redrawCanvas({ updateDiagnostics: false });
  }, 0);
  renderStep5Workspace();
}

function uuid() {
  return Math.random().toString(36).substring(2, 6);
}

function aiMaskIssuesForBox(box, slideId) {
  const issues = Array.isArray(window.__aiMaskReviewIssues) ? window.__aiMaskReviewIssues : [];
  const identifiers = new Set([
    box?.id,
    box?.group_id,
    box?.visual_group_id,
    box?.element_id,
  ].map(value => String(value || '')).filter(Boolean));
  return issues.filter(issue => (
    String(issue?.slide_id || '') === String(slideId || '')
    && identifiers.has(String(issue?.group_id || ''))
  ));
}

// 渲染右侧的 box 编辑表单列表
function renderStep5BoxesForm() {
  const container = document.getElementById('step5-boxes-list');
  container.innerHTML = '';
  const currentSlide = getCurrentManifestSlide();
  const step2Slide = getStep2SlideForManifestSlide(currentSlide);
  
  if (!state.canvasState.boxes.length) {
    container.innerHTML = `
      <div class="soft-outline mask-empty-state">
        当前页还没有 Mask 语块。可运行 AI 标注，或点击“添加语块”后直接涂抹。
      </div>
    `;
    return;
  }

  state.canvasState.boxes.forEach((box, idx) => {
    const isSelected = idx === state.canvasState.selectedBoxIndex;
    const isPaintTarget = state.canvasState.paintMode && !state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const isEraseTarget = state.canvasState.paintMode && state.canvasState.eraserMode && idx === state.canvasState.paintingBoxIndex;
    const item = document.createElement('div');
    const reviewIssues = aiMaskIssuesForBox(box, currentSlide?.slide_id);
    const hasBlockingIssue = reviewIssues.some(issue => issue?.severity === 'blocking');
    item.className = `mask-block-card soft-outline${isSelected ? ' highlight-glow' : ''}${isPaintTarget ? ' paint-active' : ''}${isEraseTarget ? ' erase-active' : ''}${reviewIssues.length ? ' ai-review-needed' : ''}${hasBlockingIssue ? ' ai-review-blocking' : ''}`;
    const maskColor = getBoxColor(box, idx);
    item.style.setProperty('--mask-color', maskColor);

    const spokenText = getSelectedFragmentText(box, step2Slide);
    const slidePrefix = currentSlide?.slide_id ? `${currentSlide.slide_id}_` : '';
    const elementId = box.element_id || (
      slidePrefix && String(box.visual_group_id || '').startsWith(slidePrefix)
        ? String(box.visual_group_id).slice(slidePrefix.length)
        : (box.visual_group_id || box.group_id || `el_${String(idx + 1).padStart(3, '0')}`)
    );
    const visualType = box.visual_type || (box.text_label ? 'text' : 'illustration');
    const visualDescription = box.visual_description || box.visual_anchor || box.text_label || '请根据当前图像补充这个语义块的画面描述';
    box.reveal = normalizeMaskReveal(box.reveal);
    item.innerHTML = `
      <div class="mask-block-head">
        <span class="mask-block-number">${idx + 1}</span>
        <span class="mask-block-caption">语块 ${idx + 1}</span>
        ${reviewIssues.length ? `<span class="ai-mask-card-issue-badge" title="${escHtml(reviewIssues.map(issue => issue.message || issue.type).join('\n'))}">${hasBlockingIssue ? '需修正' : '待检查'} · ${reviewIssues.length}</span>` : ''}
        <div class="mask-block-actions">
          <button class="mask-icon-btn${isPaintTarget ? ' active' : ''}" type="button" data-action="paint" title="画笔补充当前语块" aria-label="画笔补充">
            <svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg>
          </button>
          <button class="mask-icon-btn${isEraseTarget ? ' active' : ''}" type="button" data-action="erase" title="橡皮擦除当前语块" aria-label="橡皮擦除">
            <svg class="icon" viewBox="0 0 24 24"><path d="m7 21-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21"></path><path d="M22 21H7"></path></svg>
          </button>
          <button class="mask-icon-btn mask-delete-btn" type="button" data-action="delete" title="删除语块" aria-label="删除语块">
            <svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
          </button>
        </div>
      </div>
      <div class="mask-visual-card">
        <span class="mask-visual-label">画面描述 · ${escHtml(elementId)} · ${escHtml(box.role || 'content_body')} · ${escHtml(visualType)}</span>
        <span class="mask-visual-desc">${escHtml(visualDescription)}</span>
      </div>
      <div class="mask-narration-card">
        <span class="mask-narration-label">关联旁白</span>
        <span class="mask-narration-text">${spokenText ? escHtml(spokenText) : '请在下方旁白中选择片段'}</span>
      </div>
    `;
    
    item.addEventListener('click', () => {
      selectStep5MaskBox(idx);
    });

    item.querySelector('[data-action="paint"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      startMaskPaint(idx);
    });
    item.querySelector('[data-action="erase"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      startMaskErase(idx);
    });
    item.querySelector('[data-action="delete"]')?.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteMaskBox(idx);
    });

    container.appendChild(item);
    
  });
}

function renderStep5NarrationPanel() {
  const panel = document.getElementById('step5-narration-panel');
  if (!panel) return;
  const fragments = getNarrationFragments();
  if (!fragments.length) {
    panel.innerHTML = '<div class="step5-narration-empty">当前页暂无演讲旁白。</div>';
    return;
  }
  const selectedByFragment = new Map();
  state.canvasState.boxes.forEach((box, idx) => {
    getSelectedFragmentIds(box).forEach(fragmentId => {
      if (!selectedByFragment.has(fragmentId)) {
        selectedByFragment.set(fragmentId, idx);
      }
    });
  });
  const currentBoxIdx = state.canvasState.selectedBoxIndex;
  const hasCurrentBox = currentBoxIdx >= 0 && currentBoxIdx < state.canvasState.boxes.length;
  panel.innerHTML = `
    <div class="step5-narration-fragments">
      ${fragments.map(fragment => {
        const ownerIdx = selectedByFragment.get(fragment.id);
        const owned = ownerIdx !== undefined;
        const current = owned && ownerIdx === currentBoxIdx;
        const color = owned ? getBoxColor(state.canvasState.boxes[ownerIdx], ownerIdx) : '#777777';
        const title = owned
          ? (current ? '点击取消当前语块与该旁白片段的关联' : `该片段已关联到语块 ${ownerIdx + 1}，点击切换到当前语块`)
          : (hasCurrentBox ? '点击将此旁白片段关联到当前语块' : '请先选中或新建一个语块，再点击关联');
        return `
          <button class="step5-narration-fragment${owned ? ' linked' : ''}${current ? ' current' : ''}${!hasCurrentBox ? ' no-target' : ''}" type="button" data-fragment-id="${escHtml(fragment.id)}" style="--fragment-color:${color};" title="${escHtml(title)}">
            <span class="step5-narration-fragment-index">${fragment.order}</span>
            ${escHtml(fragment.text)}
          </button>
        `;
      }).join('')}
    </div>
  `;
  panel.querySelectorAll('.step5-narration-fragment').forEach(btn => {
    btn.addEventListener('click', () => {
      const fragmentId = btn.getAttribute('data-fragment-id');
      if (fragmentId) toggleStep5FragmentLink(fragmentId);
    });
  });
}

// 手动关联/取消关联/切换关联：演讲稿片段 <-> 当前选中语块
// 一个片段同一时间只能被一个语块关联；点击已关联到当前语块的片段则取消关联
function toggleStep5FragmentLink(fragmentId) {
  if (!fragmentId) return;
  const boxes = state.canvasState.boxes;
  const currentIdx = state.canvasState.selectedBoxIndex;
  if (currentIdx < 0 || currentIdx >= boxes.length) {
    showToast('请先在右侧选中一个语块，或点击"添加语块"新建后再关联旁白。');
    return;
  }
  const currentBox = boxes[currentIdx];
  const fragments = getNarrationFragments();
  const fragment = fragments.find(item => item.id === fragmentId);
  if (!fragment) return;

  invalidateStep5ExactPreview();

  // 找到当前片段的归属
  const ownerIdx = boxes.findIndex(box =>
    Array.isArray(box.narration_fragments) && box.narration_fragments.some(item => item.id === fragmentId)
  );

  // 情况 1：片段已关联到当前语块 → 取消关联
  if (ownerIdx === currentIdx) {
    currentBox.narration_fragments = (currentBox.narration_fragments || []).filter(item => item.id !== fragmentId);
    recomputeMaskBoxNarrationLinks(currentBox);
    renderStep5BoxesForm();
    renderStep5NarrationPanel();
    scheduleStep5Autosave();
    return;
  }

  // 情况 2：片段已关联到其他语块 → 从原语块移除
  if (ownerIdx >= 0) {
    const ownerBox = boxes[ownerIdx];
    ownerBox.narration_fragments = (ownerBox.narration_fragments || []).filter(item => item.id !== fragmentId);
    recomputeMaskBoxNarrationLinks(ownerBox);
  }

  // 情况 3：添加到当前语块（无论之前是否被关联）
  if (!Array.isArray(currentBox.narration_fragments)) currentBox.narration_fragments = [];
  if (!currentBox.narration_fragments.some(item => item.id === fragmentId)) {
    currentBox.narration_fragments.push({
      id: fragment.id,
      beat_id: fragment.beat_id,
      group_id: fragment.group_id,
      text: fragment.text
    });
  }
  recomputeMaskBoxNarrationLinks(currentBox);
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  scheduleStep5Autosave();
}

// 根据 narration_fragments 重算 box 的 narration_beat_ids / narration_beat_id /
// narration_group_id / spoken_text，保持字段一致性
function recomputeMaskBoxNarrationLinks(maskBox) {
  if (!maskBox) return;
  const frags = Array.isArray(maskBox.narration_fragments) ? maskBox.narration_fragments : [];
  const beatIds = [...new Set(frags.map(item => item.beat_id).filter(Boolean))];
  const groupIds = [...new Set(frags.map(item => item.group_id).filter(Boolean))];
  maskBox.narration_beat_ids = beatIds;
  maskBox.narration_beat_id = beatIds[0] || '';
  maskBox.narration_group_id = groupIds[0] || maskBox.narration_group_id || maskBox.visual_group_id || '';
  maskBox.spoken_text = frags.map(item => item.text).join('');
}

function updateStep5SemanticButton() {
  const btn = document.getElementById('step5-btn-semantic-blocks');
  if (!btn) return;
  btn.disabled = !!state.canvasState.semanticLoading || !!state.canvasState.confirmingMasks;
  btn.classList.toggle('loading', !!state.canvasState.semanticLoading);
  btn.innerHTML = state.canvasState.semanticLoading
    ? `<span class="button-spinner"></span><span class="btn-label">AI 分块中...</span>`
    : `<svg class="icon" viewBox="0 0 24 24"><path d="M4 5h16"></path><path d="M4 12h10"></path><path d="M4 19h16"></path><circle cx="18" cy="12" r="2"></circle></svg><span class="btn-label">AI 语义分块</span>`;
}

function updateStep5ConfirmButton(message = '') {
  const btn = document.getElementById('step5-btn-confirm-next');
  const status = document.getElementById('step5-confirm-status');
  if (!btn) return;

  const confirming = !!state.canvasState.confirmingMasks;
  const aiBusy = !!state.canvasState.semanticLoading;

  btn.classList.toggle('loading', confirming);
  btn.disabled = confirming || aiBusy;

  if (confirming) {
    btn.innerHTML = `<span class="button-spinner"></span><span class="btn-label">正在确认并构建切层...</span>`;
    btn.title = '正在保存标注并构建后续视频所需的 Mask 切层，请稍候';
    if (status) {
      status.style.display = 'flex';
      status.classList.remove('error');
      status.innerHTML = `<span class="button-spinner"></span><span>${message || '处理中：正在保存标注并构建切层，请不要重复点击。'}</span>`;
    }
    return;
  }

  btn.innerHTML = `确认标注，进入下一步 <svg class="icon" viewBox="0 0 24 24" style="width:14px; height:14px; stroke-width:2.5;"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
  btn.title = aiBusy
    ? 'AI 标注相关任务正在处理中，请稍候'
    : '确认全部 Mask 标注并构建切层';

  if (status) {
    const isMessageError = !!message && /失败|不能确认|漏标/.test(message);
    status.style.display = message ? 'flex' : 'none';
    status.classList.toggle('error', isMessageError);
    status.textContent = message || '';
  }
}

function selectStep5MaskBox(idx, shouldScroll = true) {
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5NarrationPanel();
  document.querySelectorAll('#step5-boxes-list > div').forEach((el, elIdx) => {
    const isSelected = elIdx === idx;
    el.classList.toggle('highlight-glow', isSelected);
    if (isSelected && shouldScroll) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

function focusAiMaskIssue(issue) {
  if (!issue || !manifestData?.slides?.length) return false;
  const slideIndex = manifestData.slides.findIndex(slide => (
    String(slide?.slide_id || '') === String(issue.slide_id || '')
  ));
  if (slideIndex < 0) return false;
  state.activeSlideIndex = slideIndex;
  renderStep5Workspace();
  const groupId = String(issue.group_id || '');
  if (!groupId) return true;
  setTimeout(() => {
    const boxIndex = state.canvasState.boxes.findIndex(box => [
      box?.id,
      box?.group_id,
      box?.visual_group_id,
      box?.element_id,
    ].some(value => String(value || '') === groupId));
    if (boxIndex >= 0) {
      selectStep5MaskBox(boxIndex, true);
    }
  }, 80);
  return true;
}

function updateBrushSize(value, shouldRedraw = true) {
  const size = Math.max(100, Math.min(200, Number(value) || 140));
  state.canvasState.brushSize = size;
  const input = document.getElementById('step5-brush-size');
  const label = document.getElementById('step5-brush-size-value');
  if (input) input.value = String(size);
  if (label) label.textContent = String(size);
  refreshMaskToolCursor();
  if (shouldRedraw) redrawCanvas();
}

function updateEraserSize(value, shouldRedraw = true) {
  const size = Math.max(100, Math.min(200, Number(value) || 100));
  state.canvasState.eraserSize = size;
  const input = document.getElementById('step5-eraser-size');
  const label = document.getElementById('step5-eraser-size-value');
  if (input) input.value = String(size);
  if (label) label.textContent = String(size);
  refreshMaskToolCursor();
  if (shouldRedraw) redrawCanvas();
}

function startMaskTool(idx, eraser) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  ensureManualMask(maskBox, idx);
  state.canvasState.paintMode = true;
  state.canvasState.eraserMode = !!eraser;
  state.canvasState.paintingBoxIndex = idx;
  state.canvasState.selectedBoxIndex = idx;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  showToast(eraser ? '橡皮已启用，在画面中拖动可擦除当前语块。' : '画笔已启用，在画面中拖动可补充当前语块。');
}

function startMaskPaint(idx) {
  startMaskTool(idx, false);
}

function startMaskErase(idx) {
  startMaskTool(idx, true);
}

function stopMaskPaint() {
  state.canvasState.paintMode = false;
  state.canvasState.eraserMode = false;
  state.canvasState.paintingBoxIndex = -1;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
  hideMaskToolCursor();
  redrawCanvas();
  renderStep5BoxesForm();
}

function createCurrentSlideBlock() {
  invalidateStep5ExactPreview();
  const idx = state.canvasState.boxes.length;
  state.canvasState.boxes.push({
    group_id: `manual_group_${Date.now().toString(36)}_${idx + 1}`,
    role: 'content_body',
    text_label: `语块 ${idx + 1}`,
    narration_beat_id: '',
    narration_beat_ids: [],
    narration_fragments: [],
    spoken_text: '',
    manual_mask: { source: 'manual', color: getMaskColor(idx), strokes: [] },
    reveal: normalizeMaskReveal({ type: 'crop_fade_up' }),
    box: [860, 460, 1060, 620]
  });
  startMaskPaint(idx);
  scheduleStep5Autosave();
}

function clearCurrentSlideMaskAnnotations() {
  if (!state.canvasState.boxes.length) return;
  showCustomConfirm(
    '清除当前页标注',
    '将清除当前 Slide 的 AI Mask 与手动修正，其他页面不受影响。',
    () => {
      invalidateStep5ExactPreview();
      state.canvasState.boxes = [];
      stopMaskPaint();
      saveStep5CurrentState();
      renderStep5BoxesForm();
      renderStep5NarrationPanel();
      scheduleStep5Autosave();
    }
  );
}

window.deleteMaskBox = function(idx) {
  invalidateStep5ExactPreview();
  state.canvasState.boxes.splice(idx, 1);
  if (state.canvasState.paintingBoxIndex === idx) {
    stopMaskPaint();
  } else if (state.canvasState.paintingBoxIndex > idx) {
    state.canvasState.paintingBoxIndex -= 1;
  }
  state.canvasState.selectedBoxIndex = -1;
  redrawCanvas();
  renderStep5BoxesForm();
  renderStep5NarrationPanel();
  scheduleStep5Autosave();
};

function updateMaskBoxFromManualMask(idx) {
  const maskBox = state.canvasState.boxes[idx];
  if (!maskBox) return;
  const manualMask = ensureManualMask(maskBox, idx);
  const bounds = maskPixelBounds(maskBox);
  if (!bounds) {
    manualMask.bounds = null;
    return;
  }
  const x1 = bounds.x;
  const y1 = bounds.y;
  const x2 = bounds.x + bounds.w;
  const y2 = bounds.y + bounds.h;
  if (x2 - x1 < 4 || y2 - y1 < 4) return;
  maskBox.box = [x1, y1, x2, y2];
  manualMask.bounds = {
    x: Math.round(x1),
    y: Math.round(y1),
    w: Math.round(x2 - x1),
    h: Math.round(y2 - y1)
  };
}

function getCanvasCoords(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return window.PPTFlow?.mapClientPointToCanvas
    ? window.PPTFlow.mapClientPointToCanvas(event.clientX, event.clientY, rect, 1920, 1080)
    : {
        x: Math.max(0, Math.min(1920, (event.clientX - rect.left) * 1920 / Math.max(1, rect.width))),
        y: Math.max(0, Math.min(1080, (event.clientY - rect.top) * 1080 / Math.max(1, rect.height))),
      };
}

function hideMaskToolCursor() {
  const cursor = document.getElementById('step5-tool-cursor');
  if (cursor) cursor.classList.remove('visible');
}

function refreshMaskToolCursor() {
  const cursor = document.getElementById('step5-tool-cursor');
  const canvas = document.getElementById('step5-canvas');
  const wrapper = document.getElementById('canvas-container');
  if (!cursor || !canvas || !wrapper || !state.canvasState.paintMode) {
    hideMaskToolCursor();
    return;
  }
  const clientX = Number(cursor.dataset.clientX);
  const clientY = Number(cursor.dataset.clientY);
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
  const canvasRect = canvas.getBoundingClientRect();
  const wrapperRect = wrapper.getBoundingClientRect();
  const toolSize = state.canvasState.eraserMode ? state.canvasState.eraserSize : state.canvasState.brushSize;
  const displayScale = Math.min(canvasRect.width / 1920, canvasRect.height / 1080);
  const displaySize = Math.max(8, toolSize * displayScale);
  cursor.style.width = `${displaySize}px`;
  cursor.style.height = `${displaySize}px`;
  cursor.style.left = `${clientX - wrapperRect.left}px`;
  cursor.style.top = `${clientY - wrapperRect.top}px`;
  cursor.classList.add('visible');
}

function updateMaskToolCursor(event) {
  const cursor = document.getElementById('step5-tool-cursor');
  if (!cursor) return;
  cursor.dataset.clientX = String(event.clientX);
  cursor.dataset.clientY = String(event.clientY);
  refreshMaskToolCursor();
}

function beginMaskStroke(event, canvas) {
  if (!state.canvasState.paintMode || state.canvasState.paintingBoxIndex < 0) return;
  if (event.button !== undefined && event.button !== 0) return;
  event.preventDefault();
  updateMaskToolCursor(event);
  const idx = state.canvasState.paintingBoxIndex;
  const box = state.canvasState.boxes[idx];
  if (!box) return;
  const point = getCanvasCoords(event, canvas);
  const stroke = {
    color: getBoxColor(box, idx),
    size: state.canvasState.eraserMode ? state.canvasState.eraserSize : state.canvasState.brushSize,
    mode: state.canvasState.eraserMode ? 'erase' : 'paint',
    eraser: !!state.canvasState.eraserMode,
    points: [{ x: Math.round(point.x), y: Math.round(point.y) }]
  };
  ensureManualMask(box, idx).strokes.push(stroke);
  state.canvasState.isPainting = true;
  state.canvasState.currentStroke = stroke;
  canvas.setPointerCapture?.(event.pointerId);
  scheduleLiveMaskRedraw();
}

let pendingMaskRedrawFrame = 0;

function scheduleLiveMaskRedraw() {
  if (pendingMaskRedrawFrame) return;
  pendingMaskRedrawFrame = requestAnimationFrame(() => {
    pendingMaskRedrawFrame = 0;
    redrawCanvas({ liveStroke: true, updateDiagnostics: false });
  });
}

function continueMaskStroke(event, canvas) {
  updateMaskToolCursor(event);
  if (!state.canvasState.isPainting || !state.canvasState.currentStroke) return;
  event.preventDefault();
  const points = state.canvasState.currentStroke.points;
  const samples = typeof event.getCoalescedEvents === 'function'
    ? event.getCoalescedEvents()
    : [event];
  let changed = false;
  samples.forEach(sample => {
    const point = getCanvasCoords(sample, canvas);
    const last = points[points.length - 1];
    if (!last || Math.hypot(point.x - last.x, point.y - last.y) >= 2) {
      points.push({ x: Math.round(point.x), y: Math.round(point.y) });
      changed = true;
    }
  });
  if (changed) scheduleLiveMaskRedraw();
}

function finishMaskStroke(event, canvas) {
  if (!state.canvasState.isPainting) return;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
  if (pendingMaskRedrawFrame) {
    cancelAnimationFrame(pendingMaskRedrawFrame);
    pendingMaskRedrawFrame = 0;
  }
  invalidateStep5ExactPreview();
  if (canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture?.(event.pointerId);
  updateMaskBoxFromManualMask(state.canvasState.paintingBoxIndex);
  redrawCanvas();
  renderStep5BoxesForm();
  scheduleStep5Autosave();
  updateMaskToolCursor(event);
}

// AI provides the base mask; pointer tools add reversible manual corrections.
function initCanvasEvents() {
  const canvas = document.getElementById('step5-canvas');
  const wrapper = document.getElementById('canvas-container');

  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  newCanvas.addEventListener('pointerdown', (event) => beginMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointermove', (event) => continueMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointerup', (event) => finishMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointercancel', (event) => finishMaskStroke(event, newCanvas));
  newCanvas.addEventListener('pointerenter', updateMaskToolCursor);
  newCanvas.addEventListener('pointerleave', () => {
    if (!state.canvasState.isPainting) hideMaskToolCursor();
  });
  newCanvas.addEventListener('wheel', (e) => handleMaskCanvasWheel(e, newCanvas), { passive: false });
  if (wrapper) {
    wrapper.onwheel = (e) => handleMaskCanvasWheel(e, newCanvas);
  }
  applyMaskCanvasZoom(newCanvas);
}

function applyMaskCanvasZoom(canvas = document.getElementById('step5-canvas')) {
  const bg = document.getElementById('step5-bg-img');
  if (!canvas || !bg) return;
  const zoom = Math.max(1, Math.min(4, Number(state.canvasState.maskZoom || 1)));
  state.canvasState.maskZoom = zoom;
  const originX = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginX || 50)));
  const originY = Math.max(0, Math.min(100, Number(state.canvasState.maskZoomOriginY || 50)));
  const transform = `scale(${zoom})`;
  const origin = `${originX}% ${originY}%`;
  [bg, canvas].forEach(el => {
    el.style.transform = transform;
    el.style.transformOrigin = origin;
  });
  const indicator = document.getElementById('step5-zoom-indicator');
  if (indicator) indicator.innerText = `${Math.round(zoom * 100)}%`;
}

function handleMaskCanvasWheel(e, canvas) {
  if (!e.ctrlKey) return;
  e.preventDefault();
  e.stopPropagation();
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  state.canvasState.maskZoomOriginX = ((e.clientX - rect.left) / rect.width) * 100;
  state.canvasState.maskZoomOriginY = ((e.clientY - rect.top) / rect.height) * 100;
  const current = Number(state.canvasState.maskZoom || 1);
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  state.canvasState.maskZoom = Math.max(1, Math.min(4, current * factor));
  applyMaskCanvasZoom(canvas);
}

function handleGlobalMaskWheel(e) {
  if (state.currentStep !== 5 || !e.ctrlKey) return;
  const wrapper = document.getElementById('canvas-container');
  const canvas = document.getElementById('step5-canvas');
  if (!wrapper || !canvas) return;
  const rect = wrapper.getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
    return;
  }
  handleMaskCanvasWheel(e, canvas);
}

function createStep5OffscreenCanvas() {
  const canvas = document.createElement('canvas');
  canvas.width = 1920;
  canvas.height = 1080;
  return canvas;
}

const MASK_PREVIEW_OUTLINE_PX = 5;
const maskDisplayLayerCache = new WeakMap();

function maskDisplaySignature(item) {
  const runs = item.manual_mask?.rle?.runs || [];
  const firstRun = runs[0] || [];
  const lastRun = runs[runs.length - 1] || [];
  const strokes = item.manual_mask?.strokes || [];
  const strokeSignature = strokes.map(stroke => {
    const points = stroke?.points || [];
    const last = points[points.length - 1] || {};
    return `${stroke?.mode || ''}:${stroke?.eraser ? 1 : 0}:${stroke?.size || 0}:${points.length}:${last.x || 0}:${last.y || 0}`;
  }).join('|');
  return `${runs.length}:${firstRun.join(',')}:${lastRun.join(',')}:${strokeSignature}`;
}

function buildMaskDisplayLayer(item, idx, options = {}) {
  const isSelected = idx === state.canvasState.selectedBoxIndex;
  const color = getBoxColor(item, idx);
  const liveStroke = options.liveStroke === true && isSelected;
  const signature = `${maskDisplaySignature(item)}:${color}:${isSelected ? 1 : 0}:${liveStroke ? 1 : 0}`;
  const cached = maskDisplayLayerCache.get(item);
  if (cached?.signature === signature) return cached.layer;

  const maskLayer = rasterizeManualMask(item);
  const displayLayer = createStep5OffscreenCanvas();
  const displayCtx = displayLayer.getContext('2d');
  displayCtx.fillStyle = hexToRgba(color, isSelected ? 0.68 : 0.55);
  displayCtx.fillRect(0, 0, 1920, 1080);
  displayCtx.globalCompositeOperation = 'destination-in';
  displayCtx.drawImage(maskLayer, 0, 0);
  displayCtx.globalCompositeOperation = 'source-over';

  if (!liveStroke) {
    const outlineMask = createStep5OffscreenCanvas();
    const outlineMaskCtx = outlineMask.getContext('2d');
    for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 8) {
      const offsetX = Math.round(Math.cos(angle) * MASK_PREVIEW_OUTLINE_PX);
      const offsetY = Math.round(Math.sin(angle) * MASK_PREVIEW_OUTLINE_PX);
      outlineMaskCtx.drawImage(maskLayer, offsetX, offsetY);
    }
    outlineMaskCtx.globalCompositeOperation = 'destination-out';
    outlineMaskCtx.drawImage(maskLayer, 0, 0);
    const outlineColorLayer = createStep5OffscreenCanvas();
    const outlineColorCtx = outlineColorLayer.getContext('2d');
    outlineColorCtx.fillStyle = hexToRgba(color, isSelected ? 1 : 0.9);
    outlineColorCtx.fillRect(0, 0, 1920, 1080);
    outlineColorCtx.globalCompositeOperation = 'destination-in';
    outlineColorCtx.drawImage(outlineMask, 0, 0);
    displayCtx.drawImage(outlineColorLayer, 0, 0);
  }

  maskDisplayLayerCache.set(item, { signature, layer: displayLayer });
  return displayLayer;
}

function rasterizeManualMask(item) {
  const maskLayer = createStep5OffscreenCanvas();
  const maskCtx = maskLayer.getContext('2d');
  const exactRuns = item.manual_mask?.rle?.runs || [];
  if (exactRuns.length) {
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
    exactRuns.forEach(run => {
      const [y, x1, x2] = run.map(Number);
      if (Number.isFinite(y) && Number.isFinite(x1) && Number.isFinite(x2) && x2 > x1) {
        maskCtx.fillRect(x1, y, x2 - x1, 1);
      }
    });
  }
  const strokes = item.manual_mask?.strokes || [];
  maskCtx.lineCap = 'round';
  maskCtx.lineJoin = 'round';

  strokes.forEach(stroke => {
    const points = stroke.points || [];
    if (!points.length) return;
    const erase = isEraseStroke(stroke);
    const width = Number(stroke.size || (erase ? state.canvasState.eraserSize : state.canvasState.brushSize));
    const radius = Math.max(1, width / 2);

    maskCtx.save();
    maskCtx.globalCompositeOperation = erase ? 'destination-out' : 'source-over';
    maskCtx.strokeStyle = 'rgba(0,0,0,1)';
    maskCtx.fillStyle = 'rgba(0,0,0,1)';
    maskCtx.lineWidth = width;
    maskCtx.beginPath();
    maskCtx.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach(point => maskCtx.lineTo(point.x, point.y));
    if (points.length === 1) {
      const point = points[0];
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
      maskCtx.restore();
      return;
    }
    maskCtx.stroke();
    points.forEach(point => {
      maskCtx.beginPath();
      maskCtx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      maskCtx.fill();
    });
    maskCtx.restore();
  });
  return maskLayer;
}

function maskPixelBounds(item) {
  const maskLayer = rasterizeManualMask(item);
  const ctx = maskLayer.getContext('2d', { willReadFrequently: true });
  const { data, width, height } = ctx.getImageData(0, 0, maskLayer.width, maskLayer.height);
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (data[(y * width + x) * 4 + 3] === 0) continue;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  if (maxX < minX || maxY < minY) return null;
  return {
    x: Math.max(0, minX),
    y: Math.max(0, minY),
    w: Math.min(1920, maxX + 1) - Math.max(0, minX),
    h: Math.min(1080, maxY + 1) - Math.max(0, minY),
  };
}

function maskBoxBounds(item) {
  const values = Array.isArray(item?.box) ? item.box.map(Number) : [0, 0, 1920, 1080];
  const x1 = Math.max(0, Math.min(values[0] || 0, values[2] || 0));
  const y1 = Math.max(0, Math.min(values[1] || 0, values[3] || 0));
  const x2 = Math.min(1920, Math.max(values[0] || 0, values[2] || 0));
  const y2 = Math.min(1080, Math.max(values[1] || 0, values[3] || 0));
  return { x: x1, y: y1, w: Math.max(1, x2 - x1), h: Math.max(1, y2 - y1) };
}

function buildMaskAnimationLayers(item) {
  const maskLayer = rasterizeManualMask(item);
  const contentLayer = createStep5OffscreenCanvas();
  const contentCtx = contentLayer.getContext('2d');
  contentCtx.drawImage(step5SourceCanvas, 0, 0);
  contentCtx.globalCompositeOperation = 'destination-in';
  contentCtx.drawImage(maskLayer, 0, 0);

  const coverLayer = createStep5OffscreenCanvas();
  const coverCtx = coverLayer.getContext('2d');
  coverCtx.fillStyle = step3VideoBackground || '#FEFDF9';
  coverCtx.fillRect(0, 0, 1920, 1080);
  coverCtx.globalCompositeOperation = 'destination-in';
  coverCtx.drawImage(maskLayer, 0, 0);
  return { contentLayer, coverLayer };
}

function easeOutBack(progress) {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const value = Math.max(0, Math.min(1, progress)) - 1;
  return 1 + c3 * value * value * value + c1 * value * value;
}

function drawMaskAnimationPreview(ctx, preview) {
  const { item, reveal, progress, contentLayer, coverLayer } = preview;
  const box = maskBoxBounds(item);
  const action = reveal.type;
  const eased = Math.max(0, Math.min(1, progress));

  ctx.drawImage(coverLayer, 0, 0);
  ctx.save();

  if (action === 'wipe_left_to_right') {
    ctx.beginPath();
    ctx.rect(box.x, box.y, box.w * eased, box.h);
    ctx.clip();
    ctx.drawImage(contentLayer, 0, 0);
  } else if (action === 'scratch_reveal' || action === 'brush_wipe_left_to_right') {
    const edgeX = box.x + box.w * eased;
    const roughness = action === 'scratch_reveal' ? 24 : 12;
    ctx.beginPath();
    ctx.moveTo(box.x, box.y);
    for (let y = box.y; y <= box.y + box.h; y += 18) {
      const wave = Math.sin(y * 0.075) * roughness + Math.sin(y * 0.19) * roughness * 0.35;
      ctx.lineTo(Math.min(box.x + box.w, edgeX + wave), y);
    }
    ctx.lineTo(box.x, box.y + box.h);
    ctx.closePath();
    ctx.clip();
    ctx.drawImage(contentLayer, 0, 0);
  } else if (action === 'crop_fade_up') {
    ctx.globalAlpha = eased;
    ctx.drawImage(contentLayer, 0, 0);
  } else {
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let rotation = 0;
    let alpha = eased;
    if (action === 'crop_slide_in_left') {
      translateX = -(1 - eased) * Math.min(90, box.w * 0.25);
    } else if (action === 'crop_soft_zoom_in') {
      scale = 0.82 + eased * 0.18;
    } else if (action === 'sticker_pop') {
      const springProgress = easeOutBack(eased);
      scale = 0.65 + springProgress * 0.35;
      rotation = Number(reveal.rotation ?? -4) * (1 - eased);
    } else if (action === 'stamp_in') {
      const springProgress = easeOutBack(eased);
      scale = 1.55 - springProgress * 0.55;
      rotation = Number(reveal.rotation ?? 2) * (1 - eased);
    } else if (action === 'paper_drop') {
      translateY = -(1 - easeOutBack(eased)) * 80;
      rotation = Number(reveal.rotation ?? -3) * (1 - eased);
    }
    ctx.globalAlpha = alpha;
    ctx.translate(cx + translateX, cy + translateY);
    ctx.rotate(rotation * Math.PI / 180);
    ctx.scale(scale, scale);
    ctx.translate(-cx, -cy);
    ctx.drawImage(contentLayer, 0, 0);
  }
  ctx.restore();
}

function stopMaskAnimationPreview() {
  const preview = state.canvasState.animationPreview;
  if (preview?.rafId) {
    cancelAnimationFrame(preview.rafId);
    clearTimeout(preview.rafId);
  }
  state.canvasState.animationPreview = null;
}

function readGlobalAnimationSettingsForm() {
  const type = document.getElementById('animation-setting-type').value || 'wipe_left_to_right';
  return normalizeMaskReveal({
    ...revealPreset(type),
    duration: Math.max(
      0.2,
      Math.min(3, Number(document.getElementById('animation-setting-duration').value) || DEFAULT_REVEAL_DURATION_SEC),
    ),
  });
}

function populateGlobalAnimationSettingsForm(reveal) {
  const normalized = normalizeMaskReveal(reveal);
  document.getElementById('animation-setting-type').value = normalized.type;
  document.getElementById('animation-setting-duration').value = String(normalized.duration);
  document.getElementById('animation-setting-duration-value').textContent = Number(normalized.duration).toFixed(2);
}

function stopAnimationModalPreview() {
  if (state.canvasState.animationModalPreviewRaf) {
    cancelAnimationFrame(state.canvasState.animationModalPreviewRaf);
    clearTimeout(state.canvasState.animationModalPreviewRaf);
  }
  state.canvasState.animationModalPreviewRaf = null;
}

function drawAnimationModalBase() {
  const canvas = document.getElementById('animation-preview-canvas');
  const empty = document.getElementById('animation-preview-empty');
  if (!canvas) return false;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  ctx.fillStyle = step3VideoBackground || '#FEFDF9';
  ctx.fillRect(0, 0, 1920, 1080);
  if (!step5SourceCanvas) {
    if (empty) empty.style.display = 'flex';
    return false;
  }
  ctx.drawImage(step5SourceCanvas, 0, 0);
  const hasMasks = state.canvasState.boxes.some(hasPaintStroke);
  if (empty) empty.style.display = hasMasks ? 'none' : 'flex';
  return hasMasks;
}

function openAnimationSettingsModal() {
  if (!manifestData?.slides?.length) return;
  const select = document.getElementById('animation-setting-type');
  select.innerHTML = MASK_ANIMATION_PRESETS.map(preset =>
    `<option value="${preset.value}">${preset.label}</option>`
  ).join('');
  const reveal = manifestData.animation_defaults?.reveal
    || state.canvasState.boxes.find(Boolean)?.reveal
    || revealPreset('crop_fade_up');
  populateGlobalAnimationSettingsForm(reveal);
  document.getElementById('modal-animation-settings').style.display = 'flex';
  requestAnimationFrame(() => drawAnimationModalBase());
}

function closeAnimationSettingsModal() {
  stopAnimationModalPreview();
  document.getElementById('modal-animation-settings').style.display = 'none';
}

function previewGlobalAnimationSettings() {
  const canvas = document.getElementById('animation-preview-canvas');
  if (!canvas || !drawAnimationModalBase()) {
    showToast('请先在当前页为至少一个语块涂抹 Mask。');
    return;
  }
  stopAnimationModalPreview();
  const ctx = canvas.getContext('2d');
  const reveal = readGlobalAnimationSettingsForm();
  const items = state.canvasState.boxes.filter(hasPaintStroke);
  const previews = items.map(item => ({
    item,
    reveal,
    ...buildMaskAnimationLayers(item),
  }));
  const startedAt = performance.now();
  const staggerMs = Math.min(280, Math.max(110, reveal.duration * 240));
  const durationMs = Math.max(400, reveal.duration * 1000);
  const totalMs = durationMs + staggerMs * Math.max(0, previews.length - 1);
  const tick = now => {
    ctx.clearRect(0, 0, 1920, 1080);
    ctx.fillStyle = step3VideoBackground || '#FEFDF9';
    ctx.fillRect(0, 0, 1920, 1080);
    ctx.drawImage(step5SourceCanvas, 0, 0);
    previews.forEach((preview, index) => {
      const localElapsed = now - startedAt - index * staggerMs;
      preview.progress = Math.max(0, Math.min(1, localElapsed / durationMs));
      drawMaskAnimationPreview(ctx, preview);
    });
    if (now - startedAt < totalMs) {
      state.canvasState.animationModalPreviewRaf = requestAnimationFrame(tick);
    } else {
      state.canvasState.animationModalPreviewRaf = setTimeout(() => drawAnimationModalBase(), 650);
    }
  };
  state.canvasState.animationModalPreviewRaf = requestAnimationFrame(tick);
}

function resetGlobalAnimationSettings() {
  populateGlobalAnimationSettingsForm(revealPreset('crop_fade_up'));
  previewGlobalAnimationSettings();
}

async function saveGlobalAnimationSettings() {
  const reveal = applyGlobalMaskReveal(readGlobalAnimationSettingsForm(), { save: false });
  saveStep5CurrentState();
  await saveStep5Draft();
  closeAnimationSettingsModal();
  showToast(`已将“${revealPreset(reveal.type).label}”应用到全部 Slide 的全部语块。`);
}

function rebuildStep5SourceCache(image) {
  const source = createStep5OffscreenCanvas();
  const sourceCtx = source.getContext('2d');
  sourceCtx.drawImage(image, 0, 0, 1920, 1080);
  step5SourceCanvas = source;

}

function invalidateStep5ExactPreview() {
  state.canvasState.exactPreviewImage = null;
  state.canvasState.exactPreviewSlideId = '';
  if (state.canvasState.maskPreviewMode === 'final') {
    state.canvasState.maskPreviewMode = 'mask';
  }
  window.dispatchEvent(new CustomEvent('step5-mask-preview-invalidated'));
}

function setStep5MaskPreviewMode(mode, previewUrl = '', slideId = '') {
  const normalized = ['source', 'mask', 'final'].includes(mode) ? mode : 'mask';
  if (normalized !== 'final') {
    state.canvasState.maskPreviewMode = normalized;
    redrawCanvas();
    window.dispatchEvent(new CustomEvent('step5-mask-preview-mode', { detail: { mode: normalized } }));
    return Promise.resolve(true);
  }
  if (!previewUrl) return Promise.resolve(false);
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => {
      state.canvasState.exactPreviewImage = image;
      state.canvasState.exactPreviewSlideId = String(slideId || '');
      state.canvasState.maskPreviewMode = 'final';
      redrawCanvas();
      window.dispatchEvent(new CustomEvent('step5-mask-preview-mode', { detail: { mode: 'final' } }));
      resolve(true);
    };
    image.onerror = () => {
      showToast('精确 Mask 预览图片加载失败，请重试。', 5000);
      resolve(false);
    };
    image.src = previewUrl;
  });
}

function drawManualMaskStrokes(ctx, item, idx, options = {}) {
  const strokes = item.manual_mask?.strokes || [];
  const exactRuns = item.manual_mask?.rle?.runs || [];
  if (!strokes.length && !exactRuns.length) return;
  ctx.drawImage(buildMaskDisplayLayer(item, idx, options), 0, 0);
}

function redrawCanvas(options = {}) {
  const canvas = document.getElementById('step5-canvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 1920, 1080);
  ctx.fillStyle = step3VideoBackground;
  ctx.fillRect(0, 0, 1920, 1080);
  canvas.classList.toggle('painting', state.canvasState.paintMode && !state.canvasState.eraserMode);
  canvas.classList.toggle('erasing', state.canvasState.paintMode && state.canvasState.eraserMode);

  if (!step5SourceCanvas) {
    return;
  }

  const currentSlideId = String(getCurrentManifestSlide()?.slide_id || '');
  if (
    state.canvasState.maskPreviewMode === 'final'
    && state.canvasState.exactPreviewImage
    && state.canvasState.exactPreviewSlideId === currentSlideId
  ) {
    ctx.drawImage(state.canvasState.exactPreviewImage, 0, 0, 1920, 1080);
    return;
  }
  ctx.drawImage(step5SourceCanvas, 0, 0);
  if (state.canvasState.maskPreviewMode === 'source') {
    return;
  }
  const preview = options.animationPreview || state.canvasState.animationPreview;
  if (preview) {
    drawMaskAnimationPreview(ctx, preview);
  } else {
    state.canvasState.boxes.forEach((item, idx) => {
      drawManualMaskStrokes(ctx, item, idx, options);
    });
  }

}

function saveStep5CurrentState() {
  const slide = manifestData.slides[state.activeSlideIndex];
  syncMaskBoxesToSlide(slide, state.canvasState.boxes);
}

function boxHasAiPaint(box) {
  const manualMask = box?.manual_mask;
  const strokes = Array.isArray(manualMask?.strokes) ? manualMask.strokes : [];
  const hasExactMask = Array.isArray(manualMask?.rle?.runs) && manualMask.rle.runs.length > 0;
  if (!hasExactMask && !strokes.some(stroke => stroke && !stroke.eraser && stroke.mode !== 'erase' && Array.isArray(stroke.points) && stroke.points.length)) return false;
  return String(manualMask?.source || '').startsWith('ai_auto_mask')
    || ['ai_matched_needs_review', 'ai_review_required'].includes(String(box?.review_status || ''))
    || !!box?.auto_mask
    || !!box?.ai_match;
}

function focusFirstAiMaskResult() {
  if (!manifestData?.slides?.length) return false;
  for (let slideIndex = 0; slideIndex < manifestData.slides.length; slideIndex += 1) {
    const boxes = getSlideMaskBoxes(manifestData.slides[slideIndex]);
    const boxIndex = boxes.findIndex(boxHasAiPaint);
    if (boxIndex < 0) continue;
    state.activeSlideIndex = slideIndex;
    renderStep5Workspace();
    setTimeout(() => {
      state.canvasState.selectedBoxIndex = boxIndex;
      selectStep5MaskBox(boxIndex, false);
      redrawCanvas({ updateDiagnostics: false });
    }, 80);
    return true;
  }
  redrawCanvas({ updateDiagnostics: false });
  return false;
}

function updateStep5DraftStatus(text) {
  const el = document.getElementById('step5-draft-status');
  if (el) el.innerText = text || '';
}

function scheduleStep5Autosave() {
  if (!manifestData?.slides?.length || state.canvasState.semanticLoading) return;
  updateStep5DraftStatus('自动保存中...');
  clearTimeout(state.step5AutoSaveTimer);
  state.step5AutoSaveTimer = setTimeout(() => {
    saveStep5Draft();
  }, 700);
}

async function saveStep5Draft() {
  const projectId = state.currentProject?.id;
  if (!projectId || manifestProjectId !== projectId || !manifestData?.slides?.length) {
    return { success: false, reason: 'stale_or_empty_step5_manifest' };
  }
  saveStep5CurrentState();
  if (state.step5AutoSavePromise) {
    try {
      await state.step5AutoSavePromise;
    } catch (error) {
      // The save below retries with the latest manifest state.
    }
    saveStep5CurrentState();
  }
  const payload = JSON.parse(JSON.stringify(manifestData));
  state.step5AutoSaveInFlight = true;
  const savePromise = API.put(`/api/projects/${projectId}/steps/5/draft`, payload);
  state.step5AutoSavePromise = savePromise;
  try {
    const res = await savePromise;
    if (res.success) {
      updateStep5DraftStatus('已自动保存');
      setTimeout(() => updateStep5DraftStatus(''), 1200);
    }
    return res;
  } finally {
    state.step5AutoSaveInFlight = false;
    if (state.step5AutoSavePromise === savePromise) {
      state.step5AutoSavePromise = null;
    }
  }
}

async function flushStep5Draft() {
  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  if (state.step5AutoSavePromise) {
    try {
      await state.step5AutoSavePromise;
    } catch (error) {
      // Save the newest editor state below.
    }
  }
  if (!manifestData?.slides?.length) return { success: false, reason: 'no_step5_manifest' };
  saveStep5CurrentState();
  return saveStep5Draft();
}

async function runStep5SemanticBlocks() {
  if (state.canvasState.semanticLoading) return;
  if (!manifestData?.slides?.length) return;
  saveStep5CurrentState();
  const currentSlide = getCurrentManifestSlide();
  if (!currentSlide?.slide_id) return;
  state.canvasState.semanticLoading = true;
  updateStep5SemanticButton();
  renderStep5Workspace();
  showToast(`🤖 正在为 ${currentSlide.slide_id} 预识别语义块、旁白和画面内容，不会自动绘制 Mask...`);

  try {
    await API.put(`/api/projects/${state.currentProject.id}/steps/5/draft`, manifestData);
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/5/semantic-blocks`, { slide_id: currentSlide.slide_id });
    if (res.success) {
      showToast(`✅ ${res.message || '已用分镜合约生成语义分块'}`);
      await loadStep5Data();
    }
  } finally {
    state.canvasState.semanticLoading = false;
    updateStep5SemanticButton();
    renderStep5Workspace();
  }
}

async function saveStep5Masks() {
  if (state.canvasState.confirmingMasks) {
    return false;
  }
  if (state.canvasState.semanticLoading) {
    showToast('AI 标注相关任务仍在处理中，请稍候再确认。', 3000);
    updateStep5ConfirmButton('AI 标注相关任务仍在处理中，请稍候。');
    return false;
  }
  state.canvasState.confirmingMasks = true;
  updateStep5ConfirmButton('处理中：正在保存当前标注草稿...');
  updateStep5SemanticButton();

  const previousStatuses = (manifestData?.slides || []).map(slide => slide.status);
  let failureMessage = '';

  if (state.step5AutoSaveTimer) {
    clearTimeout(state.step5AutoSaveTimer);
    state.step5AutoSaveTimer = null;
  }
  try {
    await saveStep5Draft();
    saveStep5CurrentState();

    // 点击下一步时统一确认全部 Slide，并一次性构建所有切层。
    manifestData.slides.forEach(slide => {
      slide.status = "completed";
    });

    updateStep5ConfirmButton('处理中：正在确认全部标注并构建切层...');
    showToast('正在确认全部标注并构建切层...');
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/5/result`, manifestData);
    if (res.success) {
      showToast('全部标注已确认，切层构建完成');
      renderStep5Workspace(); // 重新绘制切换栏以更新已标注绿色状态
      refreshCurrentProjectStatus(5).catch(() => {});
      return true;
    }
  } catch (e) {
    manifestData.slides.forEach((slide, index) => {
      slide.status = previousStatuses[index] || 'pending';
    });
    failureMessage = `确认失败：${e.message || '请检查 Mask 数据后重试'}`;
    showToast(failureMessage, 7000);
    renderStep5Workspace();
  } finally {
    state.canvasState.confirmingMasks = false;
    updateStep5SemanticButton();
    updateStep5ConfirmButton(failureMessage);
  }
  return false;
}

// ==================== 步骤 6: 演讲稿编辑 ====================

let narrationData = null;

async function loadStep6Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/6/result`);
  if (res.success && res.beats) {
    narrationData = res.beats;
    normalizeStep6Data();
    renderStep6Workspace();
    void offerArtifactRepair(res, '演讲稿数据', loadStep6Data);
  } else {
    // 首次进入没有演讲稿，提示同步初始化
    await initStep6Narration();
  }
}

async function initStep6Narration() {
  showToast('📝 正在根据视觉合约自动初始化演讲稿旁白文本...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/init`);
  if (res.success) {
    narrationData = res.beats;
    normalizeStep6Data();
    updateStep6AutosaveStatus('已同步模板');
    renderStep6Workspace();
  }
}

function composeStep6AnnotationPrompt(systemContent, outputExample) {
  return `${String(systemContent || '').trim()}\n\n<OutputExample>\n${String(outputExample || '').trim()}\n</OutputExample>`;
}

function updateStep6AnnotationFullPrompt() {
  const systemInput = document.getElementById('step6-ai-system-prompt');
  const exampleInput = document.getElementById('step6-ai-output-example');
  const fullInput = document.getElementById('step6-ai-full-prompt');
  if (!systemInput || !exampleInput || !fullInput) return;
  fullInput.value = composeStep6AnnotationPrompt(systemInput.value, exampleInput.value);
}

async function openStep6AnnotationPromptModal() {
  const modal = document.getElementById('modal-step6-ai-prompt');
  const systemInput = document.getElementById('step6-ai-system-prompt');
  const exampleInput = document.getElementById('step6-ai-output-example');
  const fullInput = document.getElementById('step6-ai-full-prompt');
  if (!modal || !systemInput || !exampleInput || !fullInput) return;

  modal.style.display = 'flex';
  systemInput.value = '加载中...';
  exampleInput.value = '';
  fullInput.value = '';
  try {
    const res = await API.get('/api/settings/narration-annotation');
    const prompts = res.prompts || {};
    systemInput.value = prompts.system_content || '';
    exampleInput.value = prompts.output_example || '';
    fullInput.value = prompts.full_prompt || '';
    updateStep6AnnotationFullPrompt();
  } catch (error) {
    closeStep6AnnotationPromptModal();
  }
}

function closeStep6AnnotationPromptModal() {
  const modal = document.getElementById('modal-step6-ai-prompt');
  if (modal) modal.style.display = 'none';
}

async function saveStep6AnnotationPrompts() {
  const systemContent = document.getElementById('step6-ai-system-prompt')?.value.trim() || '';
  const outputExample = document.getElementById('step6-ai-output-example')?.value.trim() || '';
  if (!systemContent || !outputExample) {
    showToast('System Content 和 Output Example 不能为空');
    return;
  }
  const button = document.getElementById('btn-step6-ai-prompt-save');
  if (button) button.disabled = true;
  try {
    await API.put('/api/settings/narration-annotation', {
      prompts: {
        system_content: systemContent,
        output_example: outputExample,
      },
    });
    showToast('旁白 AI 标注 Prompt 已保存');
    closeStep6AnnotationPromptModal();
  } finally {
    if (button) button.disabled = false;
  }
}

async function annotateStep6Narration() {
  if (!state.currentProject) return;
  if (!narrationData) {
    await initStep6Narration();
  }
  if (!narrationData) return;
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  if (state.step6AutoSavePromise) {
    try {
      await state.step6AutoSavePromise;
    } catch (error) {
      // The annotation request below contains the latest editor state.
    }
  }
  saveStep6CurrentState();
  normalizeStep6Data();
  const btn = document.getElementById('step6-btn-ai-annotate');
  try {
    if (btn) btn.disabled = true;
    updateStep6AutosaveStatus('AI 标注中...');
    showToast('AI 正在标注停顿和语气...');
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/6/annotate`, narrationData);
    if (res.success && res.beats) {
      narrationData = res.beats;
      normalizeStep6Data();
      renderStep6Workspace();
      updateStep6AutosaveStatus('AI 标注已保存');
      showToast(`AI 标注完成：${res.annotated_count || 0} 个句段`);
      refreshCurrentProjectStatus(6).catch(() => {});
    }
  } catch (e) {
    updateStep6AutosaveStatus('AI 标注失败');
  } finally {
    if (btn) btn.disabled = false;
  }
}

const STEP6_ALLOWED_TTS_EXPRESSION_TAGS = new Set([
  '(applause)', '(breath)', '(burps)', '(chuckle)', '(clear-throat)', '(coughs)',
  '(crying)', '(emm)', '(exhale)', '(gasps)', '(groans)', '(hissing)', '(humming)',
  '(inhale)', '(laughs)', '(lip-smacking)', '(pant)', '(sneezes)', '(sniffs)',
  '(snorts)', '(sighs)', '(whistles)',
]);

function stripStep6TtsMarkup(value) {
  return String(value || '')
    .replace(/<#\d+(?:\.\d{1,2})?#>/g, '')
    .replace(/\([A-Za-z-]+\)/g, tag => STEP6_ALLOWED_TTS_EXPRESSION_TAGS.has(tag) ? '' : tag)
    .replace(/\s+/g, ' ')
    .trim();
}

function syncStep6BeatText(beat, value) {
  if (!beat || typeof beat !== 'object') return;
  const ttsText = String(value || '').trim();
  const plainText = stripStep6TtsMarkup(ttsText);
  beat.tts_text = ttsText;
  beat.source_text = plainText;
  beat.spoken_text = plainText;
}

function normalizeStep6Beat(beat, idx) {
  if (!beat || typeof beat !== 'object') return null;
  const visibleText = String(beat.tts_text || beat.spoken_text || beat.source_text || '').trim();
  syncStep6BeatText(beat, visibleText);
  beat.id = beat.id || `sentence_${idx + 1}`;
  return beat;
}

function normalizeStep6Data() {
  if (!narrationData || !Array.isArray(narrationData.slides)) {
    narrationData = { slides: [] };
  }
  narrationData.slides.forEach(slide => {
    if (!Array.isArray(slide.beats)) slide.beats = [];
    const seen = new Set();
    slide.beats = slide.beats.map(normalizeStep6Beat).filter(Boolean).filter(beat => {
      const key = narrationDedupeKey(beat.spoken_text || beat.tts_text || beat.source_text || '');
      if (key && seen.has(key)) return false;
      if (key) seen.add(key);
      return true;
    });
  });
  if (state.activeSlideIndex >= narrationData.slides.length) {
    state.activeSlideIndex = Math.max(0, narrationData.slides.length - 1);
  }
}

function renderStep6Workspace() {
  const container = document.getElementById('step6-beats-list');
  if (!container) return;
  container.innerHTML = '';

  if (!narrationData?.slides?.length) {
    container.innerHTML = '<div class="soft-outline step6-empty-state">暂无演讲稿，请先同步演讲稿模板。</div>';
    return;
  }

  narrationData.slides.forEach((slide, slideIndex) => {
    const slideRow = document.createElement('section');
    slideRow.className = 'step6-slide-row';
    slideRow.dataset.slideId = slide.slide_id;
    slideRow.innerHTML = `
      <div class="step6-slide-row-head">
        <h3>${escHtml(slide.slide_id)}</h3>
        <span class="step6-slide-status">${slide.beats.length ? `${slide.beats.length} 条旁白` : '暂无旁白'}</span>
      </div>
      <div class="step6-slide-beats"></div>
      <div class="step6-slide-audio" data-audio-slide-id="${escHtml(slide.slide_id)}"></div>
    `;
    const beatsContainer = slideRow.querySelector('.step6-slide-beats');
    if (!slide.beats.length) {
      beatsContainer.innerHTML = '<div class="step6-empty-state">当前 Slide 暂无旁白。可返回 Mask 标注页建立语块，或重新同步旁白。</div>';
    }
    slide.beats.forEach((beat, beatIndex) => {
      normalizeStep6Beat(beat, beatIndex);
      const row = document.createElement('div');
      row.className = 'step6-beat-row';
      row.innerHTML = `
        <span class="step6-beat-number">${beatIndex + 1}</span>
        <textarea class="step6-tts-input" rows="1" data-slide-index="${slideIndex}" data-beat-index="${beatIndex}" aria-label="${escHtml(slide.slide_id)} 第 ${beatIndex + 1} 条旁白" placeholder="输入旁白文本，可保留停顿和语气标记">${escHtml(beat.tts_text || beat.spoken_text || '')}</textarea>
      `;
      const textarea = row.querySelector('textarea');
      textarea.addEventListener('input', (event) => {
        autoResizeNarrationTextarea(event.target);
        updateNarrationBeatText(slideIndex, beatIndex, event.target.value);
      });
      beatsContainer.appendChild(row);
      autoResizeNarrationTextarea(textarea);
    });
    container.appendChild(slideRow);
  });
}

function autoResizeNarrationTextarea(textarea) {
  if (!textarea) return;
  _resizeNarrationTextarea(textarea);
  // 布局可能尚未稳定（如步骤面板刚切换显示），下一帧再校准一次。
  requestAnimationFrame(() => _resizeNarrationTextarea(textarea));
}

function _resizeNarrationTextarea(textarea) {
  textarea.style.height = 'auto';
  // box-sizing: border-box 下，height 含 border 而 scrollHeight 不含，
  // 需补上边框厚度（约 2px）+ 子像素舍入余量（2px），避免长句末行被裁。
  const newHeight = Math.max(28, textarea.scrollHeight + 4);
  textarea.style.height = `${newHeight}px`;
}

function updateNarrationBeatText(slideIndex, beatIndex, val) {
  const slide = narrationData.slides[slideIndex];
  if (slide && slide.beats[beatIndex]) {
    syncStep6BeatText(slide.beats[beatIndex], val);
    scheduleStep6Autosave();
  }
}

function saveStep6CurrentState() {
  const list = document.getElementById('step6-beats-list');
  if (!list || !narrationData?.slides) return;
  list.querySelectorAll('.step6-tts-input').forEach(ta => {
    const slideIdx = Number(ta.dataset.slideIndex);
    const beatIdx = Number(ta.dataset.beatIndex);
    const beat = narrationData.slides?.[slideIdx]?.beats?.[beatIdx];
    if (beat) {
      syncStep6BeatText(beat, ta.value);
    }
  });
}

function updateStep6AutosaveStatus(text) {
  const el = document.getElementById('step6-autosave-status');
  if (el) el.innerText = text || '';
}

function scheduleStep6Autosave() {
  if (state.step6AutoSaveTimer) clearTimeout(state.step6AutoSaveTimer);
  updateStep6AutosaveStatus('自动保存中...');
  state.step6AutoSaveTimer = setTimeout(() => {
    saveStep6Narration({ silent: true });
  }, 700);
}

async function flushStep6Autosave() {
  if (state.step6AutoSaveTimer) {
    clearTimeout(state.step6AutoSaveTimer);
    state.step6AutoSaveTimer = null;
  }
  return saveStep6Narration({ silent: true });
}

async function putStep6NarrationWithRetry(payload) {
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(`/api/projects/${state.currentProject.id}/steps/6/result`, {
        method: 'PUT',
        body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json', 'X-PPT-Studio-Request': '1' }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(data.detail || '保存演讲稿失败');
        error.isHttpError = true;
        throw error;
      }
      return data;
    } catch (error) {
      lastError = error;
      if (error.isHttpError || attempt === 1) break;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }
  throw lastError || new Error('保存演讲稿失败');
}

async function saveStep6Narration(options = {}) {
  const silent = !!options.silent;
  if (!narrationData) return true;
  if (state.step6AutoSavePromise) {
    try {
      await state.step6AutoSavePromise;
    } catch (error) {
      // Retry below with the newest editor snapshot.
    }
  }
  saveStep6CurrentState();
  normalizeStep6Data();
  const payload = JSON.parse(JSON.stringify(narrationData));
  if (!silent) showToast('💾 正在保存并校验台词信息...');
  const savePromise = putStep6NarrationWithRetry(payload);
  state.step6AutoSavePromise = savePromise;
  try {
    const res = await savePromise;
    if (res.success) {
      updateStep6AutosaveStatus('已自动保存');
      if (!silent) showToast('🎉 演讲稿修改保存成功！');
      refreshCurrentProjectStatus(6).catch(() => {});
      return true;
    }
  } catch (e) {
    updateStep6AutosaveStatus('保存失败，请重试');
    showToast(`❌ 演讲稿保存失败：${e.message || '网络连接中断'}`);
    return false;
  } finally {
    if (state.step6AutoSavePromise === savePromise) {
      state.step6AutoSavePromise = null;
    }
  }
  return false;
}

// ==================== 可见步骤 6 的音频阶段（内部步骤 7） ====================

async function loadStep7Data() {
  const emptyState = document.getElementById('step7-empty-state');
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  const synthButton = document.getElementById('step7-btn-synthesize');
  const step7Status = state.currentProject?.step_status?.['7'] || 'pending';
  const stepAllowsAudio = ['in_progress', 'completed', 'pending_reconfirmation'].includes(step7Status);

  confirmButton.disabled = true;
  synthButton.style.display = stepAllowsAudio ? 'inline-flex' : 'none';
  emptyState.style.display = 'block';
  document.querySelectorAll('.step6-slide-audio').forEach(slot => {
    slot.innerHTML = '';
    slot.classList.remove('has-audio');
  });

  const [res, audioStatus] = await Promise.all([
    API.get(`/api/projects/${state.currentProject.id}/steps/3/images`),
    API.get(`/api/projects/${state.currentProject.id}/steps/7/audio-status`)
  ]);
  const hasExistingAudio = (audioStatus.slides || []).some(item => item?.audio_exists);
  const canLoadAudio = stepAllowsAudio || hasExistingAudio;
  synthButton.style.display = canLoadAudio ? 'inline-flex' : 'none';
  if (!canLoadAudio) {
    emptyState.innerText = '尚未生成音频。确认旁白后，点击“生成音频”。';
    return;
  }
  if (res.success) {
    const audioBySlide = new Map((audioStatus.slides || []).map(item => [item.slide_id, item]));
    res.images.forEach(img => {
      const slot = Array.from(document.querySelectorAll('.step6-slide-audio'))
        .find(item => item.dataset.audioSlideId === img.slide_id);
      if (!slot) return;
      const audio = audioBySlide.get(img.slide_id);
      slot.classList.add('has-audio');
      if (audio?.audio_exists && !audio?.stale) {
        const audioUrl = `/api/projects/${state.currentProject.id}/slides/${img.slide_id}/audio?t=${Date.now()}`;
        slot.innerHTML = `<audio controls preload="metadata" src="${audioUrl}" class="step7-audio-player" aria-label="${escHtml(img.slide_id)} 音频"></audio>`;
      } else {
        const reason = audio?.stale ? '音频已过期，请重新生成' : '音频尚未生成';
        slot.innerHTML = `<div class="step7-audio-missing">${escHtml(reason)}</div>`;
      }
    });

    const allAudioComplete = audioStatus.complete === true;
    const missingSlides = Array.isArray(audioStatus.missing) ? audioStatus.missing : [];
    if (!allAudioComplete) {
      emptyState.style.display = 'block';
      emptyState.innerText = `部分页面音频尚未生成或已过期：${missingSlides.join('、')}。点击“生成音频”会自动跳过已有音频，只补缺失页面。`;
      confirmButton.disabled = true;
    } else if (step7Status === 'pending_reconfirmation') {
      emptyState.style.display = 'block';
      emptyState.innerText = '旁白或上游内容已变更，请重新生成音频后再确认。';
      confirmButton.disabled = true;
    } else {
      emptyState.style.display = 'none';
      confirmButton.disabled = false;
      document.getElementById('step6-audio-confirm-label').innerText = state.currentProject.audio_confirmed
        ? '进入作品输出'
        : '确认并进入作品输出';
    }
  }
}

async function runStep7TTS() {
  const loading = document.getElementById('step7-loading');
  const synthButton = document.getElementById('step7-btn-synthesize');
  const saveAndTtsButton = document.getElementById('step6-btn-save-and-tts');
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  loading.style.display = 'inline-flex';
  synthButton.disabled = true;
  saveAndTtsButton.disabled = true;
  confirmButton.disabled = true;
  showToast('🔊 正在生成音频；已有且未过期的页面会自动跳过，只补缺失页面...');

  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/synthesize`);
    if (res.success) {
      const skipped = Array.isArray(res.skipped) ? res.skipped.length : 0;
      const generated = Array.isArray(res.generated) ? res.generated.length : 0;
      const suffix = skipped ? `（新生成 ${generated} 页，跳过已有 ${skipped} 页）` : '';
      showToast(`🎀 音频生成完成${suffix}，请逐页试听并确认。`);
      await refreshCurrentProjectStatus(6);
      await loadStep7Data();
      return true;
    }

    const failed = Array.isArray(res.failed) ? res.failed.map(item => item.slide_id).filter(Boolean) : [];
    const message = res.message || (failed.length ? `音频部分生成失败：${failed.join('、')}` : '音频生成未完成，请稍后重试。');
    showToast(`⚠️ ${message}`, 7000);
    await refreshCurrentProjectStatus(6);
    await loadStep7Data();
    return false;
  } catch (e) {
    showToast(`音频生成失败：${e.message}`, 7000);
    return false;
  } finally {
    loading.style.display = 'none';
    synthButton.disabled = false;
    saveAndTtsButton.disabled = false;
  }
}

async function saveNarrationAndRunTTS() {
  const saved = await flushStep6Autosave();
  if (!saved) return false;
  showToast('旁白已保存，开始生成音频...');
  return runStep7TTS();
}

async function confirmStep7Audio() {
  const confirmButton = document.getElementById('step6-btn-audio-confirm-next');
  confirmButton.disabled = true;
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/7/confirm`, {});
    if (res.success) {
      showToast('✅ 音频已确认，准备进入作品输出。');
      await refreshCurrentProjectStatus(6);
      return true;
    }
  } catch (e) {
    showToast(`音频确认失败：${e.message}`, 7000);
    return false;
  } finally {
    confirmButton.disabled = false;
  }
  return false;
}

// ==================== 步骤 8: 视频合成与渲染 ====================

// 渲染任务轮询状态。渲染耗时较长（5-60 分钟），后端用后台线程跑，
// 前端通过 render-status 路由轮询，避免长连接被浏览器超时断开报 "Failed to fetch"。
let _step8RenderPollTimer = null;
let _step8RenderTaskId = null;

function updateStep8LoadingText(stageLabel, elapsedSec) {
  const text = document.getElementById('step8-loading-text');
  if (!text) return;
  const stage = stageLabel ? stageLabel : '视频渲染中';
  const elapsed = (elapsedSec != null && elapsedSec > 0)
    ? `（已用 ${Math.round(elapsedSec)} 秒）`
    : '';
  text.innerText = `${stage}${elapsed}...`;
}

function stopStep8RenderPolling() {
  if (_step8RenderPollTimer) {
    clearInterval(_step8RenderPollTimer);
    _step8RenderPollTimer = null;
  }
  _step8RenderTaskId = null;
}

function startStep8RenderPolling(taskId) {
  // 防止重复启动
  if (_step8RenderPollTimer) clearInterval(_step8RenderPollTimer);
  _step8RenderTaskId = taskId;

  const poll = async () => {
    try {
      const url = `/api/projects/${state.currentProject.id}/steps/8/render-status?task_id=${encodeURIComponent(taskId)}`;
      const res = await API.get(url);
      if (!res.success) return;

      if (res.status === 'rendering') {
        updateStep8LoadingText(res.stage_label, res.elapsed_sec);
        return;
      }

      // 终态：success / error / idle
      stopStep8RenderPolling();
      document.getElementById('step8-loading').style.display = 'none';
      const renderBtn = document.getElementById('step8-btn-render');
      if (renderBtn) renderBtn.disabled = false;

      if (res.status === 'success') {
        showToast('🎉 视频渲染成功！');
        showStep8VideoResult(res.videos || (res.video ? [res.video] : []));
        refreshCurrentProjectStatus(8).catch(() => {});
      } else if (res.status === 'error') {
        const message = res.error || '视频渲染失败，请查看 logs/pipeline.log。';
        setStep8OutputError('视频渲染失败', message, { showLog: true });
        showToast(`❌ 渲染失败: ${message}`, 7000);
      } else if (res.status === 'interrupted') {
        const message = res.error || '应用上次运行时退出，视频任务已中断，请重新生成。';
        setStep8OutputError('视频任务已中断', message);
        showToast(message, 7000);
      } else if (res.status === 'idle') {
        // 任务记录丢失（可能服务器重启），刷新视频列表
        if (res.videos && res.videos.length > 0) {
          showStep8VideoResult(res.videos);
        }
      }
    } catch (e) {
      console.error('Step 8 status poll failed:', e);
      // 网络错误不停止轮询，下一轮重试
    }
  };

  // 立即轮询一次
  poll();
  // 每 3 秒轮询
  _step8RenderPollTimer = setInterval(poll, 3000);
}

async function loadStep8Data() {
  await loadStep8PptxData();
  try {
    // 先检查是否有进行中的渲染任务（页面刷新后恢复轮询）
    const statusRes = await API.get(`/api/projects/${state.currentProject.id}/steps/8/render-status`);
    if (statusRes.success && statusRes.status === 'rendering') {
      document.getElementById('step8-loading').style.display = 'inline-flex';
      updateStep8LoadingText(statusRes.stage_label, statusRes.elapsed_sec);
      const renderBtn = document.getElementById('step8-btn-render');
      if (renderBtn) renderBtn.disabled = true;
      startStep8RenderPolling(statusRes.task_id);
      // 同时显示已有视频
      if (statusRes.videos && statusRes.videos.length > 0) {
        showStep8VideoResult(statusRes.videos);
      }
      return;
    }
    if (statusRes.success && (statusRes.status === 'interrupted' || statusRes.status === 'error')) {
      setStep8OutputError(
        statusRes.status === 'interrupted' ? '视频任务已中断' : '上次视频生成失败',
        statusRes.error || '请重新生成视频。',
      );
    }

    const res = await API.get(`/api/projects/${state.currentProject.id}/videos`);
    if (res.success && Array.isArray(res.videos) && res.videos.length > 0) {
      showStep8VideoResult(res.videos);
    } else {
      document.getElementById('step8-result-box').style.display = 'none';
      document.getElementById('step8-btn-render').style.display = 'inline-flex';
    }
  } catch (e) {
    document.getElementById('step8-result-box').style.display = 'none';
    document.getElementById('step8-btn-render').style.display = 'inline-flex';
  }
}

async function runStep8Render() {
  const renderBtn = document.getElementById('step8-btn-render');
  document.getElementById('step8-loading').style.display = 'inline-flex';
  document.getElementById('step8-loading-text').innerText = '视频渲染中...';
  document.getElementById('step8-error-box').style.display = 'none';
  if (renderBtn) renderBtn.disabled = true;
  showToast('🎬 Remotion 渲染进程已启动，请稍候片刻...');

  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/8/render`);
    if (res.success && res.task_id) {
      // 异步任务已启动，开始轮询
      updateStep8LoadingText(res.stage_label, res.elapsed_sec);
      startStep8RenderPolling(res.task_id);
    } else if (res.success && res.videos) {
      // 已有渲染任务在进行中，直接显示当前视频列表
      showStep8VideoResult(res.videos);
      document.getElementById('step8-loading').style.display = 'none';
      if (renderBtn) renderBtn.disabled = false;
    }
  } catch(e) {
    console.error('Step 8 render start failed:', e);
    const message = e?.message || '视频渲染启动失败，请查看项目 logs/pipeline.log。';
    setStep8OutputError('视频渲染失败', message, { showLog: true });
    document.getElementById('step8-loading').style.display = 'none';
    if (renderBtn) renderBtn.disabled = false;
    showToast(`❌ 渲染失败: ${message}`, 7000);
  }
}

let _step8PptxPollTimer = null;
let _step8PptxJobId = null;

function stopStep8PptxPolling() {
  if (_step8PptxPollTimer) {
    clearInterval(_step8PptxPollTimer);
    _step8PptxPollTimer = null;
  }
  _step8PptxJobId = null;
}

function formatArtifactBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '未知大小';
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function pptxStageLabel(stage) {
  return ({
    queued: '等待生成',
    validating: '检查页面',
    composing: '写入幻灯片',
    verifying: '校验 PPTX',
    completed: '生成完成',
  })[stage] || '生成 PPTX';
}

function setStep8OutputError(title, message, options = {}) {
  const titleNode = document.getElementById('step8-error-title');
  const messageNode = document.getElementById('step8-error-message');
  const logHint = document.getElementById('step8-error-log-hint');
  const box = document.getElementById('step8-error-box');
  if (titleNode) titleNode.innerText = title || '输出失败';
  if (messageNode) messageNode.innerText = message || '输出失败，请重试。';
  if (logHint) logHint.style.display = options.showLog ? 'block' : 'none';
  if (box) box.style.display = 'block';
}

function updateStep8PptxLoading(job) {
  const loading = document.getElementById('step8-pptx-loading');
  const text = document.getElementById('step8-pptx-loading-text');
  const button = document.getElementById('step8-btn-pptx');
  if (loading) loading.style.display = 'inline-flex';
  if (button) button.disabled = true;
  if (text) {
    const progress = Number(job?.progress || 0);
    text.innerText = `${pptxStageLabel(job?.stage)}${progress > 0 ? ` · ${progress}%` : ''}...`;
  }
}

function startStep8PptxPolling(jobId) {
  stopStep8PptxPolling();
  _step8PptxJobId = jobId;
  const poll = async () => {
    if (!state.currentProject || _step8PptxJobId !== jobId) return;
    try {
      const res = await API.get(
        `/api/projects/${state.currentProject.id}/jobs/${encodeURIComponent(jobId)}`,
      );
      const job = res.job || {};
      if (job.status === 'queued' || job.status === 'running') {
        updateStep8PptxLoading(job);
        return;
      }
      stopStep8PptxPolling();
      document.getElementById('step8-pptx-loading').style.display = 'none';
      if (job.status === 'succeeded') {
        showToast('PPTX 已生成，可以下载。');
        await loadStep8PptxData();
        refreshCurrentProjectStatus(8).catch(() => {});
      } else {
        setStep8OutputError(
          job.status === 'interrupted' ? 'PPTX 任务已中断' : 'PPTX 生成失败',
          job.error || '生成失败，请重新生成。',
        );
        await refreshStep8PptxReadiness();
      }
    } catch (error) {
      console.error('PPTX job polling failed:', error);
    }
  };
  poll();
  _step8PptxPollTimer = setInterval(poll, 1200);
}

async function refreshStep8PptxReadiness() {
  const button = document.getElementById('step8-btn-pptx');
  const label = document.getElementById('step8-pptx-readiness');
  if (!state.currentProject || !button || !label) return null;
  const readiness = await API.get(
    `/api/projects/${state.currentProject.id}/exports/pptx/readiness`,
  );
  label.classList.toggle('ready', readiness.ready === true);
  label.classList.toggle('blocked', readiness.ready !== true);
  if (readiness.ready) {
    label.innerText = `${readiness.slide_count} 页图片已就绪`;
    label.title = '可以生成图片型 PPTX';
    button.disabled = Boolean(_step8PptxJobId);
  } else {
    const issues = Array.isArray(readiness.issues) ? readiness.issues : [];
    label.innerText = issues[0]?.message || 'PPTX 尚未就绪';
    label.title = issues.map(item => item.message).filter(Boolean).join('\n');
    button.disabled = true;
  }
  return readiness;
}

async function loadStep8PptxData() {
  if (!state.currentProject) return;
  try {
    const [readiness, exportsResult, jobsResult] = await Promise.all([
      refreshStep8PptxReadiness(),
      API.get(`/api/projects/${state.currentProject.id}/exports`),
      API.get(`/api/projects/${state.currentProject.id}/jobs?job_type=pptx_export`),
    ]);
    showStep8PptxResults(exportsResult.artifacts || []);
    const active = (jobsResult.jobs || []).find(job => (
      job.status === 'queued' || job.status === 'running'
    ));
    if (active) {
      updateStep8PptxLoading(active);
      startStep8PptxPolling(active.id);
    } else {
      stopStep8PptxPolling();
      const loading = document.getElementById('step8-pptx-loading');
      if (loading) loading.style.display = 'none';
      const button = document.getElementById('step8-btn-pptx');
      if (button) button.disabled = !readiness?.ready;
    }
  } catch (error) {
    console.error('Load PPTX exports failed:', error);
    const label = document.getElementById('step8-pptx-readiness');
    if (label) {
      label.className = 'step8-readiness blocked';
      label.innerText = 'PPTX 状态读取失败';
    }
  }
}

async function runStep8PptxExport() {
  const button = document.getElementById('step8-btn-pptx');
  if (!state.currentProject || button?.disabled) return;
  if (button) button.disabled = true;
  document.getElementById('step8-error-box').style.display = 'none';
  updateStep8PptxLoading({ status: 'queued', stage: 'queued', progress: 0 });
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/exports/pptx`, {});
    if (!res.job?.id) throw new Error('服务器没有返回 PPTX 任务编号');
    showToast(res.reused ? '已有 PPTX 任务正在进行。' : 'PPTX 生成任务已启动。');
    startStep8PptxPolling(res.job.id);
  } catch (error) {
    document.getElementById('step8-pptx-loading').style.display = 'none';
    setStep8OutputError('PPTX 无法生成', error.message);
    await refreshStep8PptxReadiness().catch(() => {});
  }
}

function showStep8PptxResults(artifacts) {
  const box = document.getElementById('step8-pptx-result-box');
  const list = document.getElementById('step8-pptx-list');
  if (!box || !list) return;
  const items = Array.isArray(artifacts) ? artifacts : [];
  if (!items.length) {
    box.style.display = 'none';
    list.innerHTML = '';
    return;
  }
  list.innerHTML = items.map((item, index) => {
    const created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
    const stateBadge = item.artifact_state === 'current'
      ? '<span class="step8-current-badge">当前内容</span>'
      : item.artifact_state === 'stale'
        ? '<span class="step8-legacy-badge">输入已变化</span>'
        : '<span class="step8-legacy-badge">文件已缺失</span>';
    return `
      <article class="step8-pptx-card">
        <div class="step8-pptx-icon" aria-hidden="true">
          <svg class="icon" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 13h8M8 17h5"></path></svg>
        </div>
        <div class="step8-pptx-main">
          <div class="step8-pptx-name">
            <strong>${index === 0 ? '最新 PPTX' : `历史 PPTX ${index + 1}`}</strong>
            ${stateBadge}
          </div>
          <div class="step8-pptx-meta">
            <span>${Number(item.slide_count || 0)} 页</span>
            <span>${formatArtifactBytes(item.size_bytes)}</span>
            <span>${escHtml(created || item.filename || '')}</span>
          </div>
        </div>
        <div class="step8-pptx-actions">
          ${item.exists ? `
            <a href="${item.download_url}" download class="btn success">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 3v12"></path></svg>
              下载 PPTX
            </a>
          ` : ''}
          <button class="danger compact-action-btn step8-pptx-delete" type="button" data-artifact-id="${escHtml(item.id || '')}">
            删除
          </button>
        </div>
      </article>
    `;
  }).join('');
  list.querySelectorAll('.step8-pptx-delete').forEach(button => {
    button.addEventListener('click', () => deleteStep8Pptx(button.dataset.artifactId || ''));
  });
  box.style.display = 'block';
}

function deleteStep8Pptx(artifactId) {
  if (!artifactId) return;
  showCustomConfirm(
    '删除 PPTX',
    '确定删除这个本地 PPTX 文件吗？删除后无法恢复。',
    async () => {
      const res = await API.delete(
        `/api/projects/${state.currentProject.id}/exports/${encodeURIComponent(artifactId)}`,
      );
      showStep8PptxResults(res.artifacts || []);
      showToast('PPTX 已删除。');
    },
  );
}

function showStep8VideoResult(videos) {
  document.getElementById('step8-btn-render').style.display = 'inline-flex';
  const list = document.getElementById('step8-video-list');
  if (!list) return;
  const items = Array.isArray(videos) ? videos : [];
  if (!items.length) {
    list.innerHTML = '<div class="soft-outline step6-empty-state">暂无渲染记录。</div>';
  } else {
    list.innerHTML = items.map((item, idx) => {
      const url = `${item.url}?t=${Date.now()}`;
      const created = item.created_at ? new Date(item.created_at).toLocaleString() : '';
      const playbackRate = Number(item.playback_rate || 1);
      const speedLabel = `${playbackRate.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')}×`;
      const artifactBadge = item.artifact_state === 'current'
        ? '<span class="step8-current-badge">精确 RLE Mask v5 · 当前</span>'
        : item.artifact_state === 'stale'
          ? '<span class="step8-legacy-badge">输入已变化 · 需重渲染</span>'
          : item.artifact_state === 'invalid'
            ? '<span class="step8-legacy-badge">元数据损坏</span>'
            : '<span class="step8-legacy-badge">历史版本 · 状态未知</span>';
      return `
        <div class="step8-video-card">
          <div class="step8-video-card-head">
            <strong>
              ${idx === 0 ? '最新渲染' : `历史版本 ${idx + 1}`}
              ${item.is_speed_variant ? `<span class="step8-speed-badge">${escHtml(speedLabel)} 调速版</span>` : ''}
              ${artifactBadge}
            </strong>
            <span>${escHtml(created || item.filename || '')}</span>
          </div>
          <div class="video-preview-box">
            <video controls src="${url}" data-video-filename="${escHtml(item.filename || '')}"></video>
          </div>
          <div class="step8-video-actions">
            ${item.is_speed_variant ? `
              <span class="step8-speed-source">已按 ${escHtml(speedLabel)} 生成，可直接下载</span>
            ` : `
              <label class="step8-speed-control">
                <span>视频语速</span>
                <select class="step8-speed-select" data-filename="${escHtml(item.filename || '')}">
                  ${[0.75, 1, 1.25, 1.5, 2].map(rate => `<option value="${rate}" ${rate === 1 ? 'selected' : ''}>${rate}×</option>`).join('')}
                </select>
              </label>
              <button class="secondary compact-action-btn step8-speed-generate" type="button" data-filename="${escHtml(item.filename || '')}">
                应用语速并生成 MP4
              </button>
            `}
            <a href="${item.url}" download class="btn success" style="text-decoration: none;">
              <svg class="icon" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 3v12"></path></svg>
              下载 MP4
            </a>
            <button class="danger compact-action-btn" type="button" onclick="deleteStep8Video('${escHtml(item.filename || '')}')">
              删除视频
            </button>
          </div>
        </div>
      `;
    }).join('');
    list.querySelectorAll('.step8-speed-select').forEach(select => {
      select.addEventListener('change', () => {
        const card = select.closest('.step8-video-card');
        const video = card?.querySelector('video');
        if (video) video.playbackRate = Number(select.value || 1);
      });
    });
    list.querySelectorAll('.step8-speed-generate').forEach(button => {
      button.addEventListener('click', () => {
        const card = button.closest('.step8-video-card');
        const select = card?.querySelector('.step8-speed-select');
        generateStep8SpeedVideo(button.dataset.filename || '', Number(select?.value || 1), button);
      });
    });
  }
  document.getElementById('step8-result-box').style.display = 'block';
}

async function generateStep8SpeedVideo(filename, speed, button) {
  if (!filename || !Number.isFinite(speed)) return;
  if (Math.abs(speed - 1) < 0.001) {
    showToast('当前是 1× 原速，直接点击“下载 MP4”即可。');
    return;
  }
  const originalText = button?.textContent || '应用语速并生成 MP4';
  if (button) {
    button.disabled = true;
    button.innerHTML = '<span class="button-spinner"></span> 正在生成调速版...';
  }
  try {
    const res = await API.post(
      `/api/projects/${state.currentProject.id}/videos/${encodeURIComponent(filename)}/speed`,
      { speed },
    );
    if (res.success) {
      showStep8VideoResult(res.videos || (res.video ? [res.video] : []));
      showToast(`已生成 ${speed}× 调速版，下载按钮会下载调速后的 MP4。`);
    }
  } catch (error) {
    showToast(`调速视频生成失败：${error.message}`, 7000);
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function deleteStep8Video(filename) {
  if (!filename) return;
  showCustomConfirm(
    '删除渲染视频',
    `确定删除本地视频 ${filename} 吗？删除后无法恢复。`,
    async () => {
      const res = await API.delete(`/api/projects/${state.currentProject.id}/videos/${encodeURIComponent(filename)}`);
      if (res.success) {
        showStep8VideoResult(res.videos || []);
        showToast('本地视频已删除。');
      }
    }
  );
}

window.deleteStep8Video = deleteStep8Video;
window.deleteStep8Pptx = deleteStep8Pptx;
window.loadStep5Data = loadStep5Data;
window.renderStep5Workspace = renderStep5Workspace;
window.saveStep5Draft = saveStep5Draft;
window.saveStep5CurrentState = saveStep5CurrentState;
window.focusFirstAiMaskResult = focusFirstAiMaskResult;
window.focusAiMaskIssue = focusAiMaskIssue;
window.setStep5MaskPreviewMode = setStep5MaskPreviewMode;
window.getCurrentStep5SlideId = () => String(getCurrentManifestSlide()?.slide_id || '');
window.PPTStudio = Object.assign(window.PPTStudio || {}, {
  getCurrentProject: () => state.currentProject,
  flushStep5Draft,
});
