const {
  VISIBLE_FLOW,
  normalizeVisibleStep,
  resolveProjectVisibleStep,
  visibleStepNumber,
  visibleStepLabel,
  getVisibleStepState,
  calculateVisibleProgress,
  isVisibleStepUnlocked
} = PPTFlow;

// 全局状态管理
let state = {
  currentProject: null,
  currentStep: 1,
  slides: [], // 第二步及后续的分镜/图片/Mask数据
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
        throw new Error(data.detail || data.message || response.statusText || '请求失败');
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
  ['subtitle-sample-text', 'subtitle-font-key', 'subtitle-font-size', 'subtitle-font-weight', 'subtitle-bottom', 'subtitle-horizontal-margin', 'subtitle-highlight-color', 'subtitle-paging-window', 'subtitle-max-lines', 'subtitle-token-highlight']
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

async function loadProjects() {
  const data = await API.get('/api/projects');
  const listEl = document.getElementById('project-list');
  listEl.innerHTML = '';
  
  if (data.length === 0) {
    listEl.innerHTML = `
      <div class="card soft-outline" style="text-align: center; padding: 4rem 2rem; grid-column: 1/-1;">
        <p style="font-size: 1.2rem; margin-bottom: 1rem;">还没有项目，快去新建一个吧！</p>
        <button onclick="document.getElementById('btn-create-project').click()">立即新建</button>
      </div>`;
    return;
  }
  
  data.forEach(p => {
    const status = p.step_status || {};
    const context = projectFlowContext(p);
    const percent = calculateVisibleProgress(status, context);
    const hasPendingReconfirm = VISIBLE_FLOW.some(
      item => getVisibleStepState(item.step, status, context) === 'pending_reconfirmation'
    );
    const currentVisibleStep = resolveProjectVisibleStep(p);
    
    const card = document.createElement('div');
    card.className = 'project-card soft-elevation';
    card.innerHTML = `
      <div>
        <div class="project-card-header">
          <h3 class="highlight-title">${p.name}</h3>
        </div>
        <p style="color: #666; font-size: 0.95rem; min-height: 40px; margin-bottom: 0.5rem;">${p.description || '无项目描述'}</p>
        <div style="font-size: 0.9rem; margin-top: 0.5rem;">
          <div>当前阶段: <strong>第 ${visibleStepNumber(currentVisibleStep)} 步 · ${visibleStepLabel(currentVisibleStep)}</strong></div>
          ${hasPendingReconfirm ? '<div style="color: #c9a002; font-weight: bold;">⚠️ 有步骤需重做</div>' : ''}
        </div>
      </div>
      <div>
        <div class="project-progress-bar">
          <div class="project-progress-fill" style="width: ${percent}%"></div>
        </div>
        <div style="text-align: right; font-size: 0.8rem; margin-top: 2px; color: #555;">完成度: ${percent}%</div>
        <div style="display: flex; gap: 0.8rem; margin-top: 1rem;">
          <button class="success" onclick="enterWorkspace('${p.id}')" style="flex: 1; justify-content: center; font-size: 0.95rem; padding: 0.4rem;">继续设计</button>
          <button class="danger" onclick="deleteProject('${p.id}')" style="font-size: 0.95rem; padding: 0.4rem 0.6rem;">
            <svg class="icon" viewBox="0 0 24 24" style="width: 16px; height: 16px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          </button>
        </div>
      </div>
    `;
    listEl.appendChild(card);
  });
}

async function createProject() {
  const name = document.getElementById('input-project-name').value.trim();
  const desc = document.getElementById('input-project-desc').value.trim();
  const aiMode = (document.getElementById('input-project-ai-mode')?.value || 'auto').trim();

  if (!name) {
    showToast('⚠️ 请输入项目名称');
    return;
  }

  const res = await API.post('/api/projects', { name, description: desc, ai_mode: aiMode });
  if (res.success) {
    document.getElementById('modal-create').style.display = 'none';
    showToast('🎉 项目新建成功！');
    enterWorkspace(res.project.id);
  }
}

async function deleteProject(id) {
  showCustomConfirm(
    '🗑️ 删除项目确认',
    '您确定要永久删除该项目及其所有的素材、视频文件吗？此操作不可逆！',
    async () => {
      const res = await API.delete(`/api/projects/${id}`);
      if (res.success) {
        showToast('🗑️ 项目删除成功');
        loadProjects();
      }
    }
  );
}

async function loadSettings() {
  state.settings = await API.get('/api/settings');
  
  // 填充设置输入框
  document.getElementById('setting-llm-provider').value = detectLlmProvider(
    state.settings.llm_provider,
    state.settings.llm_base_url
  );
  document.getElementById('setting-llm-base-url').value = state.settings.llm_base_url || '';
  document.getElementById('setting-llm-api-key').value = state.settings.llm_api_key || '';
  document.getElementById('setting-llm-model').value = state.settings.llm_model || '';
  document.getElementById('setting-llm-temp').value = state.settings.llm_temperature || '0.7';
  document.getElementById('setting-llm-max-tokens').value = state.settings.llm_max_tokens || '50000';
  
  document.getElementById('setting-image-base-url').value = state.settings.image_base_url || '';
  document.getElementById('setting-image-api-key').value = state.settings.image_api_key || '';
  document.getElementById('setting-image-model').value = state.settings.image_model || 'gpt-image-1';
  document.getElementById('setting-image-size').value = state.settings.image_size || '1024x1024';
  
  document.getElementById('setting-tts-provider').value = state.settings.tts_provider || 'minimax';
  document.getElementById('setting-tts-endpoint').value = state.settings.tts_endpoint || '';
  document.getElementById('setting-tts-api-key').value = state.settings.tts_api_key || '';
  document.getElementById('setting-tts-secret-key').value = state.settings.tts_secret_key || '';
  document.getElementById('setting-tts-region').value = state.settings.tts_region || '';
  document.getElementById('setting-tts-model').value = state.settings.tts_model || '';
  document.getElementById('setting-tts-voice-id').value = state.settings.tts_voice_id || '';
  document.getElementById('setting-tts-clone-voice-id').value = state.settings.tts_clone_voice_id || '';
  document.getElementById('setting-tts-provider-extra').value = state.settings.tts_provider_extra || '';
  document.getElementById('setting-tts-speed').value = state.settings.tts_speed || '1.2';
  document.getElementById('setting-tts-volume').value = state.settings.tts_volume || '1.0';
  document.getElementById('setting-tts-pitch').value = state.settings.tts_pitch || '0';
}

function openSettingsModal() {
  document.getElementById('modal-settings').style.display = 'flex';
}

function closeSettingsModal() {
  document.getElementById('modal-settings').style.display = 'none';
}

const GLOBAL_SETTINGS_EXPORT_KEYS = [
  'llm_provider',
  'llm_base_url',
  'llm_api_key',
  'llm_model',
  'llm_temperature',
  'llm_max_tokens',
  'vision_model',
  'image_base_url',
  'image_api_key',
  'image_model',
  'image_size',
  'tts_provider',
  'tts_endpoint',
  'tts_api_key',
  'tts_secret_key',
  'tts_region',
  'tts_model',
  'tts_voice_id',
  'tts_clone_voice_id',
  'tts_provider_extra',
  'tts_speed',
  'tts_volume',
  'tts_pitch',
];

function readSettingsForm() {
  return {
    llm_provider: document.getElementById('setting-llm-provider').value,
    llm_base_url: document.getElementById('setting-llm-base-url').value.trim(),
    llm_api_key: document.getElementById('setting-llm-api-key').value.trim(),
    llm_model: document.getElementById('setting-llm-model').value.trim(),
    llm_temperature: document.getElementById('setting-llm-temp').value.trim(),
    llm_max_tokens: document.getElementById('setting-llm-max-tokens').value.trim(),
    vision_model: state.settings?.vision_model || document.getElementById('setting-llm-model').value.trim(),
    
    image_base_url: document.getElementById('setting-image-base-url').value.trim(),
    image_api_key: document.getElementById('setting-image-api-key').value.trim(),
    image_model: document.getElementById('setting-image-model').value.trim(),
    image_size: document.getElementById('setting-image-size').value.trim(),
    
    tts_provider: document.getElementById('setting-tts-provider').value,
    tts_endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    tts_api_key: document.getElementById('setting-tts-api-key').value.trim(),
    tts_secret_key: document.getElementById('setting-tts-secret-key').value.trim(),
    tts_region: document.getElementById('setting-tts-region').value.trim(),
    tts_model: document.getElementById('setting-tts-model').value.trim(),
    tts_voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    tts_clone_voice_id: document.getElementById('setting-tts-clone-voice-id').value.trim(),
    tts_provider_extra: document.getElementById('setting-tts-provider-extra').value.trim(),
    tts_speed: document.getElementById('setting-tts-speed').value.trim(),
    tts_volume: document.getElementById('setting-tts-volume').value.trim(),
    tts_pitch: document.getElementById('setting-tts-pitch').value.trim()
  };
}

async function saveSettings() {
  const settings = readSettingsForm();
  
  const res = await API.put('/api/settings', { settings });
  if (res.success) {
    await loadSettings();
    closeSettingsModal();
    showToast('💾 系统全局设置保存成功，当前配置已重新加载');
  }
}

function settingsExportFileName() {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  return `ppt-studio-config-bundle-sensitive-${stamp}.json`;
}

async function exportGlobalSettings() {
  const configPayload = await API.get('/api/config/export');
  const configBlob = new Blob([JSON.stringify(configPayload, null, 2)], { type: 'application/json' });
  const configUrl = URL.createObjectURL(configBlob);
  const configLink = document.createElement('a');
  configLink.href = configUrl;
  configLink.download = settingsExportFileName();
  document.body.appendChild(configLink);
  configLink.click();
  configLink.remove();
  URL.revokeObjectURL(configUrl);
  showToast('配置已导出。文件包含 API Key、Prompt 模板和参考图，请妥善保存。', 5000);
  return;
  const currentFormSettings = readSettingsForm();
  const settings = {};
  GLOBAL_SETTINGS_EXPORT_KEYS.forEach(key => {
    if (Object.prototype.hasOwnProperty.call(currentFormSettings, key)) {
      settings[key] = currentFormSettings[key];
    } else if (Object.prototype.hasOwnProperty.call(state.settings || {}, key)) {
      settings[key] = String(state.settings[key] ?? '');
    }
  });
  const payload = {
    app: 'PPT Visualization Studio',
    type: 'global_settings',
    version: 1,
    exported_at: new Date().toISOString(),
    warning: 'This file may contain API keys and other secrets. Keep it private.',
    settings,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = settingsExportFileName();
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  showToast('✅ 全局配置已导出。注意：文件包含 API Key，请妥善保存。', 5000);
}

function extractImportableSettings(payload) {
  const source = payload?.settings && typeof payload.settings === 'object'
    ? payload.settings
    : payload;
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    throw new Error('配置文件格式不正确');
  }
  const settings = {};
  GLOBAL_SETTINGS_EXPORT_KEYS.forEach(key => {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      settings[key] = String(source[key] ?? '');
    }
  });
  if (!Object.keys(settings).length) {
    throw new Error('没有找到可导入的全局配置字段');
  }
  return settings;
}

async function applyImportedGlobalSettings(settings) {
  const merged = {
    ...(state.settings || {}),
    ...settings,
  };
  const res = await API.put('/api/settings', { settings: merged });
  if (res.success) {
    await loadSettings();
    showToast('✅ 全局配置已导入并重新加载。', 5000);
  }
}

async function importGlobalSettings(file) {
  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch (error) {
    showToast(`导入失败：${error.message}`, 6000);
    return;
  }

  showCustomConfirm(
    '导入整体配置？',
    '将覆盖当前 API 配置、分镜模板、Step 2 Prompt 模板和图片风格模板。项目内容不会被修改。',
    () => {
      API.post('/api/config/import', payload).then(async () => {
        await loadSettings();
        showToast('配置已导入并重新加载。', 5000);
      }).catch(error => {
        showToast(`导入失败：${error.message}`, 6000);
      });
    }
  );
  return;

  let settings;
  try {
    const text = await file.text();
    settings = extractImportableSettings(JSON.parse(text));
  } catch (error) {
    showToast(`❌ 导入失败：${error.message}`, 6000);
    return;
  }

  showCustomConfirm(
    '导入全局配置？',
    '将覆盖当前文本模型、生图模型、语音合成和 API Key 等全局配置。项目内容不会被修改。',
    () => {
      applyImportedGlobalSettings(settings).catch(error => {
        showToast(`❌ 导入失败：${error.message}`, 6000);
      });
    }
  );
}

async function testLlmConnection() {
  const btn = document.getElementById('btn-test-llm');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-llm-base-url').value.trim() || null,
    api_key: document.getElementById('setting-llm-api-key').value.trim(),
    model: document.getElementById('setting-llm-model').value.trim()
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写文本模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-llm', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testImageConnection() {
  const btn = document.getElementById('btn-test-image');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    base_url: document.getElementById('setting-image-base-url').value.trim() || null,
    api_key: document.getElementById('setting-image-api-key').value.trim(),
    model: document.getElementById('setting-image-model').value.trim(),
    size: document.getElementById('setting-image-size').value.trim() || '1024x1024'
  };
  
  if (!payload.api_key) {
    showToast('⚠️ 请填写生图接口密钥 (API Key)');
    return;
  }
  if (!payload.model) {
    showToast('⚠️ 请填写生图模型');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-image', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

async function testTtsConnection() {
  const btn = document.getElementById('btn-test-tts');
  const originalHtml = btn.innerHTML;
  
  const payload = {
    provider: document.getElementById('setting-tts-provider').value,
    endpoint: document.getElementById('setting-tts-endpoint').value.trim(),
    api_key: document.getElementById('setting-tts-api-key').value.trim(),
    secret_key: document.getElementById('setting-tts-secret-key').value.trim(),
    region: document.getElementById('setting-tts-region').value.trim(),
    model: document.getElementById('setting-tts-model').value.trim(),
    voice_id: document.getElementById('setting-tts-voice-id').value.trim(),
    clone_voice_id: document.getElementById('setting-tts-clone-voice-id').value.trim(),
    provider_extra: document.getElementById('setting-tts-provider-extra').value.trim()
  };
  
  if (!payload.model) {
    showToast('⚠️ 请填写语音模型');
    return;
  }
  if (!payload.voice_id) {
    showToast('⚠️ 请填写音色 ID');
    return;
  }
  
  btn.disabled = true;
  btn.innerHTML = '测试中...';
  
  try {
    const res = await API.post('/api/settings/test-tts', payload);
    if (res.success) {
      showToast('✅ ' + res.message);
    } else {
      showToast('❌ ' + res.message);
    }
  } catch (err) {
    showToast('❌ 测试请求发送失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
  }
}

function copyLlmUrlToImage() {
  const llmUrl = document.getElementById('setting-llm-base-url').value.trim();
  if (!llmUrl) {
    showToast('请先填写文本模型的接口地址');
    return;
  }
  document.getElementById('setting-image-base-url').value = llmUrl;
  showToast('✅ 已将文本模型 Base URL 同步到图片生成配置');
}

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

// ==================== 步骤 1: 导入文章 ====================

async function loadStep1Data() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/1/result`);
  if (res.success && res.brief) {
    document.getElementById('step1-article-input').value = res.brief.content || '';
    document.getElementById('step1-res-title').value = res.brief.title || '';
    document.getElementById('step1-res-summary').value = res.brief.summary || '';
    document.getElementById('step1-result-box').style.display = 'block';
  } else {
    document.getElementById('step1-article-input').value = '';
    document.getElementById('step1-result-box').style.display = 'none';
    const hint = document.getElementById('step1-status-hint');
    if (hint) hint.innerText = '';
    const saveEditBtn = document.getElementById('step1-btn-save-edit');
    if (saveEditBtn) saveEditBtn.style.display = 'none';
  }
  setStep1Mode('article');
  requestAnimationFrame(() => autoResizeTextarea(document.getElementById('step1-article-input')));
}

function setStep1Mode(mode) {
  const normalized = mode === 'topic' ? 'topic' : 'article';
  state.articleInputMode = normalized;
  document.querySelectorAll('[data-step1-mode]').forEach(button => {
    const active = button.dataset.step1Mode === normalized;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const topicPanel = document.getElementById('step1-topic-panel');
  if (topicPanel) topicPanel.style.display = normalized === 'topic' ? 'block' : 'none';
}

function ensureArticleSystemContentModal() {
  let modal = document.getElementById('modal-article-system-content');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'modal-article-system-content';
  modal.className = 'modal-overlay';
  modal.style.display = 'none';
  modal.innerHTML = `
    <div class="modal-content config-editor-modal" style="max-width:820px;width:min(820px,94vw)">
      <div class="config-editor-scroll">
        <div class="prompt-title-row">
          <h3 class="highlight-title">话题生成文章 · System Content</h3>
          <button class="prompt-help-button" type="button" data-prompt-help="article" aria-label="查看话题生成文章的输入输出示例">?</button>
        </div>
        <p class="config-editor-note">这里的 System Content 可直接修改；问号中展示系统实际追加的 User Content 和输出格式示例。</p>
        <textarea id="article-generation-system-content" rows="18" spellcheck="false"></textarea>
      </div>
      <div class="config-editor-actions">
        <button id="btn-article-system-cancel" class="secondary" type="button">取消</button>
        <button id="btn-article-system-save" class="success" type="button">保存</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', event => {
    if (event.target === modal) modal.style.display = 'none';
  });
  modal.querySelector('#btn-article-system-cancel').addEventListener('click', () => {
    modal.style.display = 'none';
  });
  modal.querySelector('#btn-article-system-save').addEventListener('click', async () => {
    const button = modal.querySelector('#btn-article-system-save');
    const systemContent = modal.querySelector('#article-generation-system-content').value.trim();
    if (!systemContent) return showToast('System Content 不能为空');
    button.disabled = true;
    try {
      await API.put('/api/settings/article-generation', { system_content: systemContent });
      modal.style.display = 'none';
      showToast('文章生成 System Content 已保存');
    } finally {
      button.disabled = false;
    }
  });
  return modal;
}

async function openArticleSystemContentModal() {
  const modal = ensureArticleSystemContentModal();
  modal.style.display = 'flex';
  const textarea = modal.querySelector('#article-generation-system-content');
  textarea.value = '加载中...';
  const result = await API.get('/api/settings/article-generation');
  textarea.value = result.system_content || '';
}

async function generateStep1Article() {
  const topic = document.getElementById('step1-topic-input')?.value.trim() || '';
  if (!topic) return showToast('请先输入一个话题');
  const button = document.getElementById('step1-btn-generate-article');
  const original = button.textContent;
  button.disabled = true;
  button.innerHTML = '<span class="button-spinner"></span> 生成中...';
  try {
    const result = await API.post(
      `/api/projects/${state.currentProject.id}/steps/1/generate-article`,
      { topic },
    );
    document.getElementById('step1-article-input').value = result.content || '';
    autoResizeTextarea(document.getElementById('step1-article-input'));
    document.getElementById('step1-status-hint').innerText = '文章已生成，可编辑后保存';
    showToast('AI 文章已生成');
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function submitStep1() {
  const content = document.getElementById('step1-article-input').value.trim();
  if (!content) {
    showToast('⚠️ 请输入 Markdown 文章内容');
    return;
  }
  const submitBtn = document.getElementById('step1-btn-submit');
  const origHtml = submitBtn.innerHTML;
  submitBtn.disabled = true;
  submitBtn.innerHTML = '保存中...';
  showToast('🚀 正在保存文章，请稍候...');
  const formData = new FormData();
  formData.append('content', content);
  
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/1/import`, formData);
    if (res.success) {
      showToast('✨ 文章已保存，正在进入分镜规划...');
      document.getElementById('step1-res-title').value = res.brief.title;
      document.getElementById('step1-res-summary').value = res.brief.summary || '';
      document.getElementById('step1-result-box').style.display = 'none';
      const hint = document.getElementById('step1-status-hint');
      if (hint) hint.innerText = '✅ 文章已保存，已自动进入分镜规划';
      document.getElementById('step1-btn-save-edit').style.display = 'inline-flex';
      state.currentProject.current_step = Math.max(state.currentProject.current_step, 2);
      state.currentProject.step_status['1'] = 'completed';
      updateStepperUI(1, state.currentProject.step_status);
      setTimeout(() => {
        navigateToStep(2);
      }, 500);
    }
  } finally {
    submitBtn.disabled = false;
    submitBtn.innerHTML = origHtml;
  }
}

async function saveStep1Edit() {
  const title = document.getElementById('step1-res-title').value.trim();
  const summary = document.getElementById('step1-res-summary').value.trim();
  const content = document.getElementById('step1-article-input').value.trim();
  const payload = { title: state.currentProject?.name || title, summary, content };
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/1/result`, payload);
  if (res.success) {
    showToast('💾 修改已保存');
  }
}

async function loadStep2Data() {
  try {
    const configRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/rules`);
    state.storyboardRoles = configRes.roles || state.storyboardRoles;
  } catch (e) {}
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
  if (res.success && res.contract) {
    state.slides = res.contract.slides || [];
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
    void offerArtifactRepair(res, '分镜数据', loadStep2Data);
  } else {
    state.slides = [];
    state.step2BatchDeleteMode = false;
    state.step2DeleteSelection = new Set();
    state.step2BatchOriginalSlides = null;
    document.getElementById('step2-editor-area').style.display = 'none';
    document.getElementById('step2-thumbs').style.display = 'none';
    if (!isManualMode()) {
      document.getElementById('step2-btn-generate').style.display = 'inline-flex';
      document.getElementById('step2-btn-generate').innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> AI 生成分镜`;
    } else {
      // 手动模式新建项目：必须显示"添加幻灯片"和"批量导入"，否则用户无法开始
      document.getElementById('step2-btn-add-slide').style.display = 'inline-flex';
      document.getElementById('step2-btn-batch-import').style.display = 'inline-flex';
    }
    document.getElementById('step2-btn-save').style.display = 'none';
    document.getElementById('step2-btn-next').style.display = 'none';
    updateStep2AutosaveStatus('');
  }
}

function isManualMode() {
  return document.body.classList.contains('mode-manual');
}

// ==================== 手动模式：添加幻灯片 + 批量导入 ====================

// 从当前 state.slides 收集手动分镜数据（用于提交 manual-skeleton 接口）
function collectManualSlidesFromState() {
  return (state.slides || []).map((slide, index) => {
    const narration = (slide.narration_beats || [])
      .map(b => b.spoken_text || b.spoken_intent || '')
      .filter(Boolean)
      .join('\n');
    return {
      slide_id: slide.slide_id || `slide_${String(index + 1).padStart(3, '0')}`,
      main_title: slide.main_title || '',
      narration,
    };
  });
}

// 添加一页空白幻灯片到 state.slides 末尾并切换过去
function addManualSlide() {
  if (!state.slides) state.slides = [];
  saveCurrentSlideInputToState();
  const newIndex = state.slides.length;
  const newSlideId = `slide_${String(newIndex + 1).padStart(3, '0')}`;
  state.slides.push({
    slide_id: newSlideId,
    main_title: '',
    core_message: '',
    visual_groups: [],
    narration_beats: [{
      id: `beat_001`,
      group_id: null,
      content_unit_id: `${newSlideId}_unit_001`,
      visible_anchor: '',
      spoken_intent: '',
      spoken_text: '',
    }],
  });
  state.activeSlideIndex = newIndex;
  renderStep2Workspace();
  // 自动触发保存
  scheduleStep2AutoSave();
  // 焦点放到标题输入框
  requestAnimationFrame(() => {
    document.getElementById('step2-slide-title-input')?.focus();
  });
}

// 提交手动分镜到后端（手动模式下点击"进入图片生成"时调用）
async function submitManualSkeletonIfNeeded() {
  if (!state.currentProject || !isManualMode()) return true;
  const slides = collectManualSlidesFromState();
  if (!slides.length) {
    showToast('⚠️ 请至少添加一页幻灯片');
    return false;
  }
  for (let i = 0; i < slides.length; i++) {
    if (!slides[i].main_title) {
      showToast(`⚠️ 第 ${i + 1} 页标题不能为空`);
      return false;
    }
    if (!slides[i].narration) {
      showToast(`⚠️ 第 ${i + 1} 页演讲稿不能为空`);
      return false;
    }
  }
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/manual-skeleton`, { slides });
    if (res && res.success) {
      await loadStep2Data();
      return true;
    }
    showToast('⚠️ 保存分镜失败');
    return false;
  } catch (e) {
    showToast('⚠️ 保存失败：' + (e && e.message ? e.message : String(e)));
    return false;
  }
}

// ==================== 批量导入弹窗 ====================

const STEP2_BATCH_TEMPLATE = `[
  {
    "main_title": "第一页标题",
    "narration": "第一页要朗读的演讲稿，可多行。"
  },
  {
    "main_title": "第二页标题",
    "narration": "第二页要朗读的演讲稿。"
  }
]
`;

function openStep2BatchImportModal() {
  document.getElementById('step2-batch-import-preview').style.display = 'none';
  document.getElementById('step2-batch-import-preview').innerHTML = '';
  document.getElementById('step2-batch-import-file').value = '';
  document.getElementById('btn-step2-batch-import-append').disabled = true;
  document.getElementById('btn-step2-batch-import-overwrite').disabled = true;
  document.getElementById('modal-step2-batch-import').style.display = 'flex';
}

function closeStep2BatchImportModal() {
  document.getElementById('modal-step2-batch-import').style.display = 'none';
}

function downloadStep2BatchTemplate() {
  const blob = new Blob([STEP2_BATCH_TEMPLATE], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = '手动分镜模板.txt';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

let step2BatchImportPending = null;

function handleStep2BatchImportFile(event) {
  const file = event.target.files && event.target.files[0];
  const previewEl = document.getElementById('step2-batch-import-preview');
  const appendBtn = document.getElementById('btn-step2-batch-import-append');
  const overwriteBtn = document.getElementById('btn-step2-batch-import-overwrite');
  step2BatchImportPending = null;
  appendBtn.disabled = true;
  overwriteBtn.disabled = true;
  previewEl.style.display = 'none';
  previewEl.innerHTML = '';
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    let parsed = null;
    let parseError = '';
    try {
      parsed = JSON.parse(String(reader.result || ''));
    } catch (e) {
      parseError = String(e.message || e);
    }
    if (!Array.isArray(parsed)) {
      previewEl.style.display = 'block';
      previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件内容不是 JSON 数组${parseError ? '：' + escapeHtml(parseError) : ''}</div>`;
      return;
    }
    const slides = [];
    for (let i = 0; i < parsed.length; i++) {
      const item = parsed[i] || {};
      const title = String(item.main_title || '').trim();
      const narration = String(item.narration || '').trim();
      if (!title || !narration) {
        previewEl.style.display = 'block';
        previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 第 ${i + 1} 项缺少 main_title 或 narration 字段</div>`;
        return;
      }
      slides.push({ main_title: title, narration });
    }
    if (!slides.length) {
      previewEl.style.display = 'block';
      previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件中没有有效条目</div>`;
      return;
    }
    step2BatchImportPending = slides;
    previewEl.style.display = 'block';
    const currentCount = (state.slides || []).length;
    previewEl.innerHTML = `
      <div class="step2-batch-import-summary">
        <strong>已解析 ${slides.length} 页分镜：</strong>
        <ul>
          ${slides.slice(0, 5).map((s, i) => `<li>第 ${i + 1} 页 · ${escapeHtml(s.main_title)}</li>`).join('')}
          ${slides.length > 5 ? `<li>... 还有 ${slides.length - 5} 页</li>` : ''}
        </ul>
        <div class="step2-batch-import-hint">当前已有 ${currentCount} 页。追加导入后将变成 ${currentCount + slides.length} 页；覆盖导入将清空现有分镜后导入 ${slides.length} 页。</div>
      </div>
    `;
    appendBtn.disabled = false;
    overwriteBtn.disabled = false;
  };
  reader.onerror = () => {
    previewEl.style.display = 'block';
    previewEl.innerHTML = `<div class="step2-batch-import-error">❌ 文件读取失败</div>`;
  };
  reader.readAsText(file, 'utf-8');
}

async function submitStep2BatchImport(mode) {
  if (!state.currentProject || !step2BatchImportPending) return;
  const importedSlides = step2BatchImportPending;
  let finalSlides = [];
  if (mode === 'append') {
    finalSlides = collectManualSlidesFromState().concat(importedSlides);
  } else {
    finalSlides = importedSlides.slice();
  }
  // 重新编号 slide_id
  finalSlides = finalSlides.map((s, i) => ({
    slide_id: `slide_${String(i + 1).padStart(3, '0')}`,
    main_title: s.main_title,
    narration: s.narration,
  }));
  try {
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/manual-skeleton`, { slides: finalSlides });
    if (res && res.success) {
      showToast(`✅ 已${mode === 'append' ? '追加' : '覆盖'}导入 ${importedSlides.length} 页分镜`);
      closeStep2BatchImportModal();
      await loadStep2Data();
    } else {
      showToast('⚠️ 导入失败');
    }
  } catch (e) {
    showToast('⚠️ 导入失败：' + (e && e.message ? e.message : String(e)));
  }
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function openStep2GenerationModal() {
  const input = document.getElementById('step2-generation-requirement');
  input.value = state.step2GenerationRequirement || '';
  document.getElementById('modal-step2-generate').style.display = 'flex';
  input.focus();
}

function closeStep2GenerationModal() {
  document.getElementById('modal-step2-generate').style.display = 'none';
}

function setStep2GenerationStatus(message = '', type = '') {
  const status = document.getElementById('step2-generation-status');
  if (!status) return;
  status.textContent = message;
  status.className = `step2-generation-status${type ? ` ${type}` : ''}`;
  status.style.display = message ? 'block' : 'none';
}

async function confirmStep2Generation() {
  const userRequirement = document.getElementById('step2-generation-requirement').value.trim();
  state.step2GenerationRequirement = userRequirement;
  closeStep2GenerationModal();
  await generateStep2Contract(userRequirement);
}

async function generateStep2Contract(requirement = '') {
  const normalizedRequirement = String(requirement || '').trim();
  setStep2GenerationStatus('');
  document.getElementById('step2-loading').style.display = 'block';
  document.getElementById('step2-btn-generate').disabled = true;
  const loadingText = document.querySelector('#step2-loading p');
  const originalLoadingText = loadingText?.innerText || '';
  
  try {
    if (loadingText) loadingText.innerText = 'Step 2A：AI 正在规划每页标题、正文要点和演讲稿...';
    const scriptPayload = normalizedRequirement ? { requirement: normalizedRequirement } : {};
    const scriptRes = await API.post(
      `/api/projects/${state.currentProject.id}/steps/2/script/execute`,
      scriptPayload,
    );
    if (!scriptRes.success) {
      showToast(`❌ 错误: ${scriptRes.message || 'Step 2A 生成失败'}`);
      return;
    }
    if (loadingText) loadingText.innerText = 'Step 2B：AI 正在根据演讲稿规划画面语义块...';
    const visualRes = await API.post(`/api/projects/${state.currentProject.id}/steps/2/visual/execute`);
    if (!visualRes.success) {
      showToast(`❌ 错误: ${visualRes.message || 'Step 2B 生成失败'}`);
      return;
    }
    if (loadingText) loadingText.innerText = 'Step 2C：正在合成可用于生图、Mask 和旁白绑定的 visual_contract...';
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/2/compose`);
    if (!res.success) {
      showToast(`❌ 错误: ${res.message || 'Step 2 合成失败'}`);
      return;
    }
    showToast('🎉 Narration-first 分镜规划已生成！');
    setStep2GenerationStatus('');
    state.slides = res.contract?.slides || [];
    renderStep2Workspace();
  } catch(e) {
    const message = e?.message || '分镜生成失败，请稍后重试。';
    console.error('Step 2 generation failed:', e);
    setStep2GenerationStatus(`分镜生成失败：${message}`, 'error');
  } finally {
    if (loadingText) loadingText.innerText = originalLoadingText;
    document.getElementById('step2-loading').style.display = 'none';
    document.getElementById('step2-btn-generate').disabled = false;
  }
}

function renderStep2Workspace() {
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = Math.max(0, state.slides.length - 1);
  }
  const manual = isManualMode();
  document.getElementById('step2-editor-area').style.display = 'block';
  // 按钮显隐：自动模式显示 AI 生成分镜/文章slides/可视化；手动模式显示 添加幻灯片/批量导入
  const generateBtn = document.getElementById('step2-btn-generate');
  const scriptPromptBtn = document.getElementById('step2-btn-script-prompt');
  const visualPromptBtn = document.getElementById('step2-btn-visual-prompt');
  const addSlideBtn = document.getElementById('step2-btn-add-slide');
  const batchImportBtn = document.getElementById('step2-btn-batch-import');
  if (manual) {
    if (generateBtn) generateBtn.style.display = 'none';
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'none';
    if (visualPromptBtn) visualPromptBtn.style.display = 'none';
    if (addSlideBtn) addSlideBtn.style.display = 'inline-flex';
    if (batchImportBtn) batchImportBtn.style.display = 'inline-flex';
  } else {
    if (generateBtn) {
      generateBtn.style.display = 'inline-flex';
      generateBtn.innerHTML = `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg> AI 生成分镜`;
    }
    if (scriptPromptBtn) scriptPromptBtn.style.display = 'inline-flex';
    if (visualPromptBtn) visualPromptBtn.style.display = 'inline-flex';
    if (addSlideBtn) addSlideBtn.style.display = 'none';
    if (batchImportBtn) batchImportBtn.style.display = 'none';
  }
  document.getElementById('step2-btn-save').style.display = 'inline-flex';
  document.getElementById('step2-btn-next').style.display = 'inline-flex';
  updateStep2BatchDeleteButton();

  // 渲染精简版横向缩略图（只显示 Slide 序号）
  const thumbsContainer = document.getElementById('step2-thumbs');
  thumbsContainer.style.display = 'flex'; // 显式呈现
  thumbsContainer.classList.toggle('step2-batch-delete-mode', state.step2BatchDeleteMode);
  thumbsContainer.innerHTML = '';

  state.slides.forEach((slide, idx) => {
    const thumb = document.createElement('div');
    thumb.className = `slide-thumbnail-card step2-slide-thumb ${idx === state.activeSlideIndex ? 'active' : ''}`;
    thumb.style.cssText = 'min-width: 92px; max-width: 92px; min-height: 42px; padding: 0.55rem 0.5rem; cursor: pointer; display: flex; align-items: center; justify-content: center;';
    thumb.innerHTML = `
      ${state.step2BatchDeleteMode ? `
        <button class="step2-thumb-delete" type="button" title="删除此分镜" aria-label="删除此分镜">
          <svg class="icon" viewBox="0 0 24 24"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
        </button>
      ` : ''}
      <div style="font-size: 0.9rem; font-weight: 800; color: #111;">Slide ${idx + 1}</div>
    `;
    thumb.addEventListener('click', () => {
      if (state.step2BatchDeleteMode) {
        return;
      }
      saveCurrentSlideInputToState();
      state.activeSlideIndex = idx;
      renderStep2Workspace();
    });
    const deleteBtn = thumb.querySelector('.step2-thumb-delete');
    if (deleteBtn) {
      deleteBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        removeStep2DraftSlide(slide.slide_id);
      });
    }
    thumbsContainer.appendChild(thumb);
  });

  // 加载当前 Slide 详情
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    if (!manual) {
      syncStep2SimpleFieldsToInternalGroups(slide);
    }
    const slideIdEl = document.getElementById('step2-current-slide-id');
    const slideTitleEl = document.getElementById('step2-current-slide-title');
    if (slideIdEl) slideIdEl.innerText = slide.slide_id;
    if (slideTitleEl) slideTitleEl.innerText = slide.main_title || '未命名 Slide';
    // 同步隐藏字段
    document.getElementById('step2-main-title').value = slide.main_title || '';
    document.getElementById('step2-core-message').value = slide.core_message || '';

    const titleInput = document.getElementById('step2-slide-title-input');
    const narrationInput = document.getElementById('step2-slide-narration-input');
    if (titleInput) titleInput.value = slide.main_title || '';
    if (narrationInput) {
      // 手动模式下演讲稿可编辑，自动模式下只读
      narrationInput.readOnly = manual ? false : true;
      narrationInput.value = step2NarrationText(slide);
    }
    [titleInput, narrationInput].forEach(input => {
      if (!input || input.dataset.boundStep2SimpleEditor === '1') return;
      input.dataset.boundStep2SimpleEditor = '1';
      input.addEventListener('input', () => {
        if (input.tagName === 'TEXTAREA') autoResizeTextarea(input);
        if (manual) {
          // 手动模式下直接写回 slide.narration_beats[0].spoken_text
          saveManualNarrationInputToState(input);
        } else {
          saveCurrentSlideInputToState();
        }
        scheduleStep2AutoSave();
      });
      input.addEventListener('blur', () => {
        if (input.tagName !== 'TEXTAREA') return;
        normalizeAndResizeStep2Textarea(input);
        if (manual) {
          saveManualNarrationInputToState(input);
        } else {
          saveCurrentSlideInputToState();
        }
        scheduleStep2AutoSave();
      });
    });
    requestAnimationFrame(() => autoResizeTextarea(narrationInput));
    // 自动模式渲染可视化-旁白映射；手动模式隐藏
    const vnMap = document.getElementById('step2-visual-narration-map');
    if (manual) {
      if (vnMap) vnMap.style.display = 'none';
    } else {
      if (vnMap) vnMap.style.display = '';
      renderStep2VisualNarrationMap(slide);
    }
  }
}

// 手动模式下：把演讲稿输入写回当前 slide 的 narration_beats[0].spoken_text
function saveManualNarrationInputToState(input) {
  const slide = state.slides && state.slides[state.activeSlideIndex];
  if (!slide) return;
  if (input && input.id === 'step2-slide-narration-input') {
    if (!Array.isArray(slide.narration_beats) || !slide.narration_beats.length) {
      slide.narration_beats = [{
        id: 'beat_001',
        group_id: null,
        content_unit_id: `${slide.slide_id}_unit_001`,
        visible_anchor: '',
        spoken_intent: '',
        spoken_text: '',
      }];
    }
    slide.narration_beats[0].spoken_text = input.value;
    // 同步显示在头部
    const titleEl = document.getElementById('step2-current-slide-title');
    // 标题输入也走这个分支
  }
  if (input && input.id === 'step2-slide-title-input') {
    slide.main_title = input.value;
    const titleEl = document.getElementById('step2-current-slide-title');
    if (titleEl) titleEl.innerText = input.value || '未命名 Slide';
  }
}

// 拼接并一键复制所有 Slide 的生图提示词
async function copyStep2Prompts() {
  saveCurrentSlideInputToState();
  
  if (!state.slides || state.slides.length === 0) {
    showToast('⚠️ 暂无分镜规划数据，无法复制提示词');
    return;
  }
  
  if (!String(step3BatchPrompt || '').trim()) {
    try {
      await refreshStep3Prompts();
    } catch (error) {
      // API.fetch 已展示具体错误，这里只阻止复制空内容。
    }
  }
  const allPromptsText = String(step3BatchPrompt || '').trim();
  if (!allPromptsText) {
    showToast('批量提示词加载失败，请稍后重试');
    return;
  }
  
  navigator.clipboard.writeText(allPromptsText).then(() => {
    showToast('📋 已成功复制所有 Slide 的生图提示词到剪贴板！');
  }).catch(err => {
    console.error('复制失败:', err);
    showToast('⚠️ 复制失败，请手动选择复制');
  });
}

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function updateStep2BatchDeleteButton() {
  const btn = document.getElementById('step2-btn-save');
  const cancelBtn = document.getElementById('step2-btn-cancel-delete');
  if (!btn) return;
  if (state.step2BatchDeleteMode) {
    btn.className = 'success';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><polyline points="17 21 17 13 7 13 7 21"></polyline><polyline points="7 3 7 8 15 8"></polyline></svg>
      保存
    `;
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  } else {
    btn.className = 'secondary';
    btn.innerHTML = `
      <svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M19 6l-1 14H6L5 6"></path></svg>
      批量删除
    `;
    if (cancelBtn) cancelBtn.style.display = 'none';
  }
}

async function handleStep2BatchDeleteButton() {
  if (!state.slides || state.slides.length === 0) return;
  if (!state.step2BatchDeleteMode) {
    saveCurrentSlideInputToState();
    clearTimeout(state.step2AutoSaveTimer);
    await saveStep2Contract({ silent: true });
    state.step2BatchOriginalSlides = JSON.parse(JSON.stringify(state.slides));
    state.step2BatchOriginalActiveIndex = state.activeSlideIndex;
    state.step2BatchDeleteMode = true;
    state.step2DeleteSelection = new Set();
    renderStep2Workspace();
    showToast('已进入批量删除模式。点卡片右上角删除，此处只临时移除，点击保存后生效。');
    return;
  }
  saveStep2BatchDelete();
}

function removeStep2DraftSlide(slideId) {
  if (!state.step2BatchDeleteMode) return;
  if (state.slides.length <= 1) {
    showToast('至少需要保留 1 个分镜。');
    return;
  }
  const removedIndex = state.slides.findIndex(slide => slide.slide_id === slideId);
  if (removedIndex < 0) return;
  state.slides.splice(removedIndex, 1);
  if (state.activeSlideIndex >= state.slides.length) {
    state.activeSlideIndex = state.slides.length - 1;
  } else if (removedIndex < state.activeSlideIndex) {
    state.activeSlideIndex -= 1;
  }
  renderStep2Workspace();
}

async function saveStep2BatchDelete() {
  saveCurrentSlideInputToState();
  clearTimeout(state.step2AutoSaveTimer);
  const originalCount = state.step2BatchOriginalSlides?.length || state.slides.length;
  const removedCount = Math.max(0, originalCount - state.slides.length);
  if (removedCount === 0) {
    state.step2BatchDeleteMode = false;
    state.step2BatchOriginalSlides = null;
    renderStep2Workspace();
    showToast('已退出批量删除模式。');
    return;
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  await saveStep2Contract({ silent: true });
  renderStep2Workspace();
  showToast(`已删除 ${removedCount} 个分镜，并保存当前规划。`);
}

function cancelStep2BatchDelete() {
  if (!state.step2BatchDeleteMode) return;
  if (Array.isArray(state.step2BatchOriginalSlides)) {
    state.slides = JSON.parse(JSON.stringify(state.step2BatchOriginalSlides));
    state.activeSlideIndex = Math.min(state.step2BatchOriginalActiveIndex || 0, Math.max(0, state.slides.length - 1));
  }
  state.step2BatchDeleteMode = false;
  state.step2DeleteSelection = new Set();
  state.step2BatchOriginalSlides = null;
  renderStep2Workspace();
  showToast('已取消批量删除，分镜列表已恢复。');
}

function updateStep2AutosaveStatus(text) {
  const el = document.getElementById('step2-autosave-status');
  if (el) el.innerText = text || '';
}

function scheduleStep2AutoSave() {
  if (state.currentStep !== 2 || !state.currentProject || !state.slides?.length) return;
  if (state.step2BatchDeleteMode) return;
  updateStep2AutosaveStatus('自动保存中...');
  clearTimeout(state.step2AutoSaveTimer);
  state.step2AutoSaveTimer = setTimeout(() => {
    saveStep2Contract({ silent: true, autosave: true });
  }, 700);
}

function step2BodyContentText(slide) {
  const items = Array.isArray(slide?.body_content) ? slide.body_content : [];
  return normalizeStep2MultilineText(items.map(item => String(item || '')).filter(Boolean).join('\n'));
}

function step2NarrationText(slide) {
  const beats = Array.isArray(slide?.narration_beats) ? slide.narration_beats : [];
  const seen = new Set();
  return beats
    .map(beat => normalizeStep2NarrationText(beat?.spoken_text || ''))
    .filter(Boolean)
    .filter(text => {
      const key = narrationDedupeKey(text);
      if (key && seen.has(key)) return false;
      if (key) seen.add(key);
      return true;
    })
    .join('');
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

function normalizeStep2MultilineText(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function normalizeStep2NarrationText(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .join('\n');
}

function autoResizeTextarea(textarea) {
  if (!textarea) return;
  if (textarea.tagName === 'TEXTAREA') textarea.rows = 1;
  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight + 2}px`;
}

function normalizeAndResizeStep2Textarea(textarea) {
  if (!textarea) return;
  const normalized = textarea.id === 'step2-slide-narration-input'
    ? normalizeStep2NarrationText(textarea.value)
    : normalizeStep2MultilineText(textarea.value);
  if (textarea.value !== normalized) textarea.value = normalized;
  autoResizeTextarea(textarea);
}

function syncStep2SimpleFieldsToInternalGroups(slide) {
  if (!slide || !Array.isArray(slide.visual_groups)) return;
  const title = String(slide.main_title || '').trim();
  const titleGroup = slide.visual_groups.find(group => group?.role === 'title');
  if (titleGroup && title) {
    titleGroup.visible_text = title;
    titleGroup.display_text = title;
    titleGroup.visual_anchor = title;
    titleGroup.mask_target = title;
    titleGroup.visual_type = 'text';
  }
  const subtitleGroupIds = new Set(
    slide.visual_groups
      .filter(group => group?.role === 'subtitle')
      .map(group => group?.id)
      .filter(Boolean),
  );
  slide.subtitle = '';
  slide.visual_groups = slide.visual_groups.filter(group => group?.role !== 'subtitle');
  if (subtitleGroupIds.size && Array.isArray(slide.narration_beats)) {
    slide.narration_beats = slide.narration_beats.filter(beat => !subtitleGroupIds.has(beat?.group_id));
  }
}

function saveCurrentSlideInputToState() {
  const slide = state.slides[state.activeSlideIndex];
  if (slide) {
    slide.main_title = document.getElementById('step2-slide-title-input')?.value
      ?? document.getElementById('step2-main-title').value;
    slide.subtitle = '';
    slide.core_message = document.getElementById('step2-core-message').value;
    if (isManualMode()) {
      // 手动模式：把演讲稿直接写回 narration_beats[0].spoken_text，不走 visual_groups 同步
      const narration = document.getElementById('step2-slide-narration-input')?.value || '';
      if (!Array.isArray(slide.narration_beats) || !slide.narration_beats.length) {
        slide.narration_beats = [{
          id: 'beat_001',
          group_id: null,
          content_unit_id: `${slide.slide_id}_unit_001`,
          visible_anchor: '',
          spoken_intent: '',
          spoken_text: narration,
        }];
      } else {
        slide.narration_beats[0].spoken_text = narration;
      }
      return;
    }
    syncStep2SimpleFieldsToInternalGroups(slide);
    renderStep2VisualNarrationMap(slide);
  }
}

function renderStep2VisualNarrationMap(slide) {
  const container = document.getElementById('step2-visual-narration-map');
  if (!container) return;
  if (!slide) { container.innerHTML = ''; return; }

  const groups = Array.isArray(slide.visual_groups) ? slide.visual_groups : [];
  const beats = Array.isArray(slide.narration_beats) ? slide.narration_beats : [];
  if (groups.length === 0 && beats.length === 0) {
    container.innerHTML = '';
    return;
  }

  groups.forEach((group, index) => {
    if (!group.id) group.id = `${slide.slide_id}_group_${String(index + 1).padStart(3, '0')}`;
  });
  beats.forEach((beat, index) => {
    if (!beat.id) beat.id = `${slide.slide_id}_beat_${String(index + 1).padStart(3, '0')}`;
  });

  const roleOrder = { title: 0, subtitle: 1, body: 2, body_content: 2, content_body: 2, decoration: 3 };
  const sortedGroups = groups.filter(group => !['subtitle', 'decoration'].includes(String(group?.role || ''))).map((g, i) => ({ g, i })).sort((a, b) => {
    const ra = Number(a.g?.reveal_order ?? roleOrder[a.g?.role] ?? a.i);
    const rb = Number(b.g?.reveal_order ?? roleOrder[b.g?.role] ?? b.i);
    return ra - rb;
  }).map(item => item.g);

  const usedBeatIds = new Set();
  const groupCards = sortedGroups.map((group, idx) => {
    const gid = String(group?.id || '');
    const matched = beats.filter(beat => {
      if (beat?.group_id !== gid) return false;
      usedBeatIds.add(beat.id);
      return true;
    });
    const role = String(group?.role || 'content_body');
    const roleValue = role === 'body' || role === 'body_content' ? 'content_body' : role;
    const visualType = group?.visual_type === 'text' ? 'text' : 'picture';
    const visualContent = visualType === 'text'
      ? String(group?.display_text || group?.visible_text || group?.visual_anchor || '')
      : String(group?.visual_anchor || group?.mask_target || '');
    const typeLabel = visualType === 'text' ? '画面文字' : '画面元素';
    const mappingReady = matched.length === 1 && String(matched[0]?.spoken_text || '').trim();
    const beatsHtml = matched.length
      ? matched.map((beat, beatIndex) => renderStep2EditableBeat(beat, beatIndex, matched.length)).join('')
      : '<div class="vn-beat vn-beat-empty">缺少对应演讲片段，请重新生成 Slides → 可视化。</div>';
    const visualField = visualType === 'text'
      ? `<label class="vn-edit-field">
          <span>画面文字</span>
          <input type="text" value="${escHtml(visualContent)}" data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">
        </label>`
      : `<label class="vn-edit-field">
          <span>画面元素描述</span>
          <textarea rows="4" data-step2-group-id="${escHtml(gid)}" data-step2-group-field="visual_content">${escHtml(visualContent)}</textarea>
        </label>`;

    return `
      <div class="vn-group-card vn-role-${escHtml(roleValue)}" data-group-id="${escHtml(gid)}">
        <div class="vn-group-head">
          <span class="vn-group-num">${idx + 1}</span>
          <span class="vn-type-tag">${typeLabel}</span>
          <span class="vn-map-arrow" aria-hidden="true">→</span>
          <span class="vn-map-target">对应演讲片段</span>
          <span class="vn-beat-count${mappingReady ? '' : ' is-error'}">${mappingReady ? '已对应' : '需要检查'}</span>
        </div>
        <div class="vn-group-body">
          <div class="vn-visual">
            ${visualField}
          </div>
          <div class="vn-narration">
            ${beatsHtml}
          </div>
        </div>
      </div>`;
  }).join('');

  const orphanBeats = beats.filter(beat => !usedBeatIds.has(beat.id));
  const orphanHtml = orphanBeats.length
    ? `<div class="vn-orphan">
        <div class="vn-orphan-head">发现 ${orphanBeats.length} 段没有对应画面的演讲片段</div>
        <div class="vn-orphan-hint">当前结构不允许手动选择内部 ID，请重新生成 Slides → 可视化，让系统重新建立一对一关系。</div>
        ${orphanBeats.map((beat, index) => renderStep2EditableBeat(beat, index, orphanBeats.length)).join('')}
      </div>`
    : '';

  container.innerHTML = `
    <div class="vn-map-title">画面与演讲片段</div>
    <div class="vn-map-hint">每张卡片就是一个 Reveal 单元：左侧是实际画面内容，右侧是该画面出现时播放的演讲片段；两侧内容保持一一对应。</div>
    <div class="vn-groups">${groupCards}</div>
    ${orphanHtml}`;
}

function renderStep2EditableBeat(beat, index = 0, total = 1) {
  const beatId = String(beat?.id || '');
  return `<div class="vn-beat" data-beat-id="${escHtml(beatId)}">
    <label class="vn-edit-field">
      <span>${total > 1 ? `演讲片段 ${index + 1}（应合并为一段）` : '演讲片段'}</span>
      <textarea rows="3" data-step2-beat-id="${escHtml(beatId)}" data-step2-beat-field="spoken_text">${escHtml(beat?.spoken_text || '')}</textarea>
    </label>
  </div>`;
}

function currentStep2EditorSlide() {
  return state.slides?.[state.activeSlideIndex] || null;
}

function handleStep2MapEditorInput(event) {
  const target = event.target;
  const slide = currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  const groupId = target.dataset.step2GroupId;
  const groupField = target.dataset.step2GroupField;
  const beatId = target.dataset.step2BeatId;
  const beatField = target.dataset.step2BeatField;
  let changed = false;

  if (groupId && groupField === 'visual_content') {
    const group = slide.visual_groups?.find(item => item?.id === groupId);
    if (group) {
      const value = target.value;
      if (group.visual_type === 'text') {
        group.visible_text = value;
        group.display_text = value;
        group.visual_anchor = value;
        group.mask_target = value;
        group.narration_function = value;
        slide.narration_beats?.filter(beat => beat?.group_id === groupId).forEach(beat => { beat.visible_anchor = value; });
        if (group.role === 'title') slide.main_title = value;
      } else {
        group.mask_target = value;
        group.visual_anchor = value;
        group.narration_function = value || group.visible_text || '';
        slide.narration_beats?.filter(beat => beat?.group_id === groupId).forEach(beat => {
          beat.spoken_intent = group.narration_function;
        });
      }
      changed = true;
    }
  }

  if (beatId && beatField === 'spoken_text') {
    const beat = slide.narration_beats?.find(item => item?.id === beatId);
    if (beat) {
      beat.spoken_text = target.value;
      changed = true;
    }
  }

  if (!changed) return;
  syncStep2SummaryInputs(slide);
  scheduleStep2AutoSave();
}

function handleStep2MapEditorChange(event) {
  const target = event.target;
  const slide = currentStep2EditorSlide();
  if (!slide || !(target instanceof HTMLElement)) return;
  if (target.tagName === 'TEXTAREA') autoResizeTextarea(target);
  syncStep2SummaryInputs(slide);
  scheduleStep2AutoSave();
}

function syncStep2SummaryInputs(slide) {
  const titleInput = document.getElementById('step2-slide-title-input');
  const narrationInput = document.getElementById('step2-slide-narration-input');
  const heading = document.getElementById('step2-current-slide-title');
  if (titleInput && document.activeElement !== titleInput) titleInput.value = slide.main_title || '';
  if (heading) heading.textContent = slide.main_title || '未命名 Slide';
  if (narrationInput && document.activeElement !== narrationInput) {
    narrationInput.value = step2NarrationText(slide);
    autoResizeTextarea(narrationInput);
  }
}


async function saveStep2Contract(options = {}) {
  saveCurrentSlideInputToState();
  const payload = {
    version: "visual_contract_v1",
    topic: state.currentProject.topic || {
      topic_id: "topic_" + state.currentProject.id,
      topic_name: state.currentProject.name
    },
    slides: state.slides
  };
  
  if (state.step2AutoSaveInFlight && options.autosave) {
    scheduleStep2AutoSave();
    return { success: false };
  }
  state.step2AutoSaveInFlight = true;
  try {
    const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/result`, payload);
    if (res.success) {
      updateStep2AutosaveStatus(options.autosave ? '已自动保存' : '');
      if (!options.silent) {
        showToast('💾 分镜规划已成功保存！');
      }
    }
    return res;
  } finally {
    state.step2AutoSaveInFlight = false;
    if (options.autosave) {
      setTimeout(() => updateStep2AutosaveStatus(''), 1400);
    }
  }
}

// ==================== 步骤 3: 图片生成 ====================

let slidePrompts = [];
let step3BatchPrompt = '';
// 全局图片顺序（用于拖拽排序）
let step3ImageOrder = []; // [{slide_id, exists, url}]
let step3OrderVersion = '';
let step3OrderSaveChain = Promise.resolve();
let step3DraggedIndex = -1;
let step3CandidateReady = false;
let step3CandidateSlideId = '';
const step3GeneratingSlides = new Set();
let step3BatchGenerating = false;
let step3BatchCompleted = 0;
let step3BatchTotal = 0;
let step3VideoBackground = '#FEFDF9';

function step3GeneratingPreviewHtml(message = '生成中') {
  return `
    <div class="step3-generating-preview" role="status" aria-live="polite">
      <span class="loading-spinner" aria-hidden="true"></span>
      <strong>${escHtml(message)}</strong>
      <small>AI 正在绘制图片，请稍候...</small>
    </div>
  `;
}

function updateStep3BatchButton() {
  const button = document.getElementById('step3-btn-batch-generate');
  if (!button) return;
  const hasSlides = step3ImageOrder.length > 0;
  const generationInProgress = step3GeneratingSlides.size > 0;
  button.disabled = !hasSlides || step3BatchGenerating || generationInProgress;
  button.classList.toggle('is-loading', step3BatchGenerating);
  const uploadLabel = document.getElementById('step3-batch-upload-label');
  const uploadInput = document.getElementById('step3-batch-upload');
  uploadLabel?.classList.toggle('is-disabled', generationInProgress);
  if (uploadInput) uploadInput.disabled = generationInProgress;
  button.innerHTML = step3BatchGenerating
    ? `<span class="step3-button-spinner" aria-hidden="true"></span> 批量生成中 ${step3BatchCompleted}/${step3BatchTotal}`
    : `<svg class="icon" viewBox="0 0 24 24" style="width:14px;height:14px;">
         <rect x="3" y="4" width="18" height="16" rx="2"></rect>
         <circle cx="8.5" cy="9" r="1.5"></circle>
         <path d="m5 17 4.5-4 3.2 2.8 2.3-2.1 4 3.3"></path>
         <path d="M18 2v4M16 4h4"></path>
       </svg> 一键批量生成图片`;
}

function setStep3SlideGenerating(slideId, generating) {
  if (generating) {
    step3GeneratingSlides.add(slideId);
  } else {
    step3GeneratingSlides.delete(slideId);
  }
  renderStep3Grid();
}

async function loadStep3Data() {
  // 优先加载分镜数据，保证即使无图片也能渲染占位卡
  if (!state.slides || state.slides.length === 0) {
    const contractRes = await API.get(`/api/projects/${state.currentProject.id}/steps/2/result`);
    if (contractRes.success && contractRes.contract) {
      state.slides = contractRes.contract.slides || [];
    }
  }

  await loadStep3VisualSettings();

  // 获取每个 slide 拼接的 Prompt
  try {
    const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
    if (promptRes.success) {
      slidePrompts = promptRes.prompts || [];
      step3BatchPrompt = promptRes.batch_prompt || '';
    }
  } catch(e) {}
  
  // 获取生成的图片文件状态
  await refreshStep3Images();
}

function normalizeStep3BackgroundColor(value) {
  const color = String(value || '').trim().toUpperCase();
  return /^#[0-9A-F]{6}$/.test(color) ? color : '';
}

async function loadStep3VisualSettings() {
  const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/visual-settings`);
  step3VideoBackground = normalizeStep3BackgroundColor(res.video_background) || '#FEFDF9';
}

async function refreshStep3Images() {
  let images = [];
  try {
    const res = await API.get(`/api/projects/${state.currentProject.id}/steps/3/images`);
    if (res.success) {
      images = res.images || [];
      step3OrderVersion = String(res.order_version || '');
    }
  } catch(e) {}

  // 如果后端返回空列表但分镜数据已有，自动生成占位展示
  if (images.length === 0 && state.slides && state.slides.length > 0) {
    images = state.slides.map(s => ({ slide_id: s.slide_id, exists: false, url: '' }));
  }
  step3ImageOrder = images;
  syncStep3OrderState();
  renderStep3Grid();
  if (step3ImageOrder.length > 0 && step3ImageOrder.every(img => img.exists)) {
    refreshCurrentProjectStatus(3).catch(() => {});
  }
}

function renderStep3Grid() {
  const grid = document.getElementById('step3-images-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const hasSlides = step3ImageOrder.length > 0;
  const missingCount = step3ImageOrder.filter(img => !img.exists).length;
  const staleProvenanceCount = step3ImageOrder.filter(img => img.exists && img.provenance?.valid !== true).length;
  const allImagesReady = hasSlides && missingCount === 0 && staleProvenanceCount === 0 && step3GeneratingSlides.size === 0;
  updateStep3BatchButton();
  const confirmBtn = document.getElementById('step3-btn-confirm');
  if (confirmBtn) {
    confirmBtn.style.display = hasSlides ? 'inline-flex' : 'none';
    confirmBtn.disabled = !allImagesReady;
    confirmBtn.title = allImagesReady
      ? ''
      : (step3GeneratingSlides.size > 0
        ? '图片正在生成中'
        : staleProvenanceCount > 0
          ? `${staleProvenanceCount} 张图片来源待更新，请重新生成或上传`
          : `还缺少 ${missingCount} 张图片`);
  }

  step3ImageOrder.forEach((img, idx) => {
    const card = document.createElement('div');
    card.className = 'card soft-elevation slide-card-draggable';
    card.style.cssText = 'padding: 0.8rem; position: relative; background: var(--bg-color); margin-bottom: 0;';

    card.addEventListener('dragover', (e) => {
      if (step3DraggedIndex < 0 || step3DraggedIndex === idx) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      card.classList.add('drag-over');
    });

    card.addEventListener('dragleave', (e) => {
      if (!card.contains(e.relatedTarget)) card.classList.remove('drag-over');
    });

    card.addEventListener('drop', async (e) => {
      e.preventDefault();
      card.classList.remove('drag-over');
      const draggedIdx = Number.parseInt(e.dataTransfer.getData('text/plain'), 10);
      step3DraggedIndex = -1;
      if (!Number.isNaN(draggedIdx)) {
        await reorderStep3Images(draggedIdx, idx);
      }
    });

    const promptInfo = slidePrompts.find(item => item.slide_id === img.slide_id);
    const slideInfo = state.slides.find(item => item.slide_id === img.slide_id);
    const slideTitle = promptInfo?.title || slideInfo?.main_title || '未命名 Slide';
    const isGenerating = step3GeneratingSlides.has(img.slide_id);
    const provenanceReady = img.provenance?.valid === true;
    const previewHtml = isGenerating
      ? step3GeneratingPreviewHtml()
      : img.exists
      ? `<img src="${img.url}" style="width: 100%; height: 100%; object-fit: cover;" alt="${escHtml(slideTitle)}">`
      : `<div style="width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.3rem; color: #888; background: #fffdf5;">
           <svg class="icon" viewBox="0 0 24 24" style="width: 20px; height: 20px; color: #aaa;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"></path></svg>
           <span style="font-size: 0.75rem; font-weight: 500;">暂无图片，点击上传/生成</span>
         </div>`;

    card.innerHTML = `
      <div class="step3-card-header">
        <div class="step3-card-identity">
          <button class="slide-drag-handle" type="button" draggable="${isGenerating ? 'false' : 'true'}" ${isGenerating ? 'disabled' : ''} title="按住拖动调整页面顺序" aria-label="拖动第 ${idx + 1} 页调整顺序">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="9" cy="5" r="1.4"></circle><circle cx="15" cy="5" r="1.4"></circle>
              <circle cx="9" cy="12" r="1.4"></circle><circle cx="15" cy="12" r="1.4"></circle>
              <circle cx="9" cy="19" r="1.4"></circle><circle cx="15" cy="19" r="1.4"></circle>
            </svg>
          </button>
          <span class="step3-card-position">第 ${idx + 1} 页</span>
          <span class="step3-card-status ${isGenerating ? 'is-generating' : ''}" style="color: ${img.exists || isGenerating ? 'var(--ink-color)' : '#888'}; background: ${isGenerating ? 'var(--secondary-color)' : (img.exists && provenanceReady ? 'var(--success-color)' : '#f3f4f6')};">
            ${isGenerating ? '生成中' : (img.exists ? (provenanceReady ? '已就绪' : '来源待更新') : '待生成')}
          </span>
        </div>
        <div class="step3-card-actions">
          <button class="success step3-card-action step3-ai-action" data-slide-id="${escHtml(img.slide_id)}" ${isGenerating ? 'disabled' : ''}>
            ${isGenerating ? '生成中' : 'AI生成'}
          </button>
          <label class="btn secondary step3-card-action step3-upload-action ${isGenerating ? 'is-disabled' : ''}">
            上传
            <input class="step3-upload-input" data-slide-id="${escHtml(img.slide_id)}" type="file" accept="image/*" ${isGenerating ? 'disabled' : ''} style="display: none;">
          </label>
          ${img.exists ? `
            <button class="danger step3-card-action step3-delete-action" data-slide-id="${escHtml(img.slide_id)}" ${isGenerating ? 'disabled' : ''}>
              删除
            </button>
          ` : '<button class="step3-card-action step3-action-placeholder" type="button" disabled aria-hidden="true" tabindex="-1">删除</button>'}
        </div>
      </div>
      <div class="step3-card-title" title="${escHtml(slideTitle)}" data-slide-id="${escHtml(img.slide_id)}">${escHtml(slideTitle)}</div>

      <div class="img-preview-container" style="width: 100%; aspect-ratio: 16/9; position: relative; border: 2px solid var(--ink-color); border-radius: 6px; overflow: hidden; background: #fffdf5;">
        ${previewHtml}
      </div>
    `;
    const dragHandle = card.querySelector('.slide-drag-handle');
    card.querySelector('.step3-ai-action')?.addEventListener('click', (event) => {
      event.stopPropagation();
      openStep3AI(img.slide_id);
    });
    card.querySelector('.step3-upload-input')?.addEventListener('change', (event) => {
      uploadStep3ImageById(img.slide_id, event.currentTarget);
    });
    card.querySelector('.step3-delete-action')?.addEventListener('click', (event) => {
      event.stopPropagation();
      deleteStep3Image(img.slide_id);
    });
    dragHandle.addEventListener('click', (e) => e.stopPropagation());
    dragHandle.addEventListener('dragstart', (e) => {
      step3DraggedIndex = idx;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(idx));
      card.classList.add('is-dragging');
    });
    dragHandle.addEventListener('dragend', () => {
      step3DraggedIndex = -1;
      document.querySelectorAll('.slide-card-draggable').forEach(item => {
        item.classList.remove('is-dragging', 'drag-over');
      });
    });
    dragHandle.addEventListener('keydown', async (e) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const direction = ['ArrowLeft', 'ArrowUp'].includes(e.key) ? -1 : 1;
      await reorderStep3Images(idx, idx + direction);
    });
    grid.appendChild(card);
  });
}

function syncStep3OrderState() {
  const order = new Map(step3ImageOrder.map((item, index) => [item.slide_id, index]));
  state.slides.sort((a, b) => (order.get(a.slide_id) ?? 9999) - (order.get(b.slide_id) ?? 9999));
  slidePrompts.sort((a, b) => (order.get(a.slide_id) ?? 9999) - (order.get(b.slide_id) ?? 9999));
  const openSlideId = document.getElementById('step3-slide-id-label')?.innerText;
  if (openSlideId && openSlideId !== '--') {
    state.activeSlideIndex = state.slides.findIndex(slide => slide.slide_id === openSlideId);
  }
}

async function reorderStep3Images(draggedIdx, targetIdx) {
  if (
    draggedIdx < 0 ||
    targetIdx < 0 ||
    draggedIdx >= step3ImageOrder.length ||
    targetIdx >= step3ImageOrder.length ||
    draggedIdx === targetIdx
  ) return;

  // 乐观更新：立即重排并渲染一次，UI 即时响应
  const [moved] = step3ImageOrder.splice(draggedIdx, 1);
  step3ImageOrder.splice(targetIdx, 0, moved);
  syncStep3OrderState();
  renderStep3Grid();

  // 按操作顺序串行保存，后一个请求始终携带前一个请求返回的新版本。
  const projectId = state.currentProject.id;
  const desiredSlideIds = step3ImageOrder.map(item => item.slide_id);
  const saveOrder = async () => {
    try {
      const res = await API.put(`/api/projects/${projectId}/steps/3/order`, {
        slide_ids: desiredSlideIds,
        order_version: step3OrderVersion,
      });
      step3OrderVersion = String(res.order_version || step3OrderVersion);
      return true;
    } catch (error) {
      if (state.currentProject?.id === projectId) {
        await refreshStep3Images();
      }
      return false;
    }
  };
  const saveTask = step3OrderSaveChain.then(saveOrder, saveOrder);
  step3OrderSaveChain = saveTask.then(() => undefined);
  const saved = await saveTask;
  if (saved) {
    showToast('页面顺序已保存');
  } else {
    showToast('顺序保存冲突，已刷新为服务器最新顺序', 'error');
  }
}

async function moveStep3Image(idx, direction) {
  await reorderStep3Images(idx, idx + direction);
}

window.moveStep3Image = moveStep3Image;

function openStep3AI(slideId) {
  state.activeSlideIndex = step3ImageOrder.findIndex(img => img.slide_id === slideId);
  step3CandidateReady = false;
  step3CandidateSlideId = '';
  document.getElementById('step3-slide-id-label').innerText = slideId;
  const pInfo = slidePrompts.find(p => p.slide_id === slideId);
  document.getElementById('step3-prompt-input').value = pInfo ? pInfo.prompt : '';
  const imgInfo = step3ImageOrder.find(img => img.slide_id === slideId);
  const prevEl = document.getElementById('step3-preview-box');
  document.getElementById('step3-preview-label').innerText = '当前图片预览';
  document.getElementById('step3-candidate-status').style.display = 'none';
  document.getElementById('step3-btn-apply-candidate').style.display = 'none';
  if (imgInfo && imgInfo.exists) {
    prevEl.innerHTML = `<img src="${imgInfo.url}" alt="${slideId} 当前图片">`;
  } else {
    prevEl.innerHTML = '<span>暂无图片</span>';
  }
  document.getElementById('modal-step3-ai').style.display = 'flex';
  document.getElementById('step3-prompt-input').focus();
}

window.openStep3AI = openStep3AI;

function closeStep3AIModal() {
  document.getElementById('modal-step3-ai').style.display = 'none';
  step3CandidateReady = false;
  step3CandidateSlideId = '';
}

window.closeStep3AIModal = closeStep3AIModal;

async function uploadStep3ImageById(slideId, input) {
  const file = input.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('slide_id', slideId);
  formData.append('file', file);
  showToast('📤 正在上传并裁剪为标准格式...');
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
  if (res.success) {
    showToast('🎉 图片上传成功！');
    await refreshStep3Images();
    await refreshCurrentProjectStatus(3);
  }
  input.value = '';
}

window.uploadStep3ImageById = uploadStep3ImageById;

function deleteStep3Image(slideId) {
  showCustomConfirm(
    '删除图片',
    `确定删除 ${slideId} 的本地图片吗？该页已有的全部 Mask 和切层素材也会一起清除。`,
    async () => {
      const res = await API.delete(`/api/projects/${state.currentProject.id}/steps/3/images/${encodeURIComponent(slideId)}`);
      if (res.success) {
        await refreshStep3Images();
        await refreshCurrentProjectStatus(3);
        showToast('图片及该页 Mask 已删除。');
      }
    }
  );
}

window.deleteStep3Image = deleteStep3Image;

// 批量上传处理
async function handleStep3BatchUpload(e) {
  const files = Array.from(e.target.files);
  if (files.length === 0) return;
  
  // 按分镜顺序逐一匹配上传
  const slideIds = step3ImageOrder.map(img => img.slide_id);
  showToast(`📤 正在批量上传 ${files.length} 张图片...`);
  
  for (let i = 0; i < files.length; i++) {
    const slideId = slideIds[i];
    if (!slideId) break;
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('file', files[i]);
    try {
      await API.post(`/api/projects/${state.currentProject.id}/steps/3/upload`, formData);
    } catch(err) {
      showToast(`⚠️ 第 ${i+1} 张上传失败`);
    }
  }
  showToast('✅ 批量上传完成！');
  await refreshStep3Images();
  await refreshCurrentProjectStatus(3);
  e.target.value = '';
}

async function generateAllStep3Images() {
  if (step3BatchGenerating || step3ImageOrder.length === 0) return;

  const tasks = step3ImageOrder.map(image => {
    const promptInfo = slidePrompts.find(item => item.slide_id === image.slide_id);
    return {
      slideId: image.slide_id,
      prompt: String(promptInfo?.prompt || '').trim()
    };
  });
  const missingPrompt = tasks.find(task => !task.prompt);
  if (missingPrompt) {
    showToast(`❌ ${missingPrompt.slideId} 缺少生图提示词，请先重新进入本步骤。`);
    return;
  }

  step3BatchGenerating = true;
  step3BatchCompleted = 0;
  step3BatchTotal = tasks.length;
  tasks.forEach(task => step3GeneratingSlides.add(task.slideId));
  renderStep3Grid();
  showToast(`🎨 已开始批量生成 ${tasks.length} 张图片。`);

  let successCount = 0;
  const failedSlides = [];
  try {
    for (const task of tasks) {
      try {
        const formData = new FormData();
        formData.append('slide_id', task.slideId);
        formData.append('prompt', task.prompt);
        formData.append('preview', 'false');
        const res = await API.post(
          `/api/projects/${state.currentProject.id}/steps/3/generate`,
          formData
        );
        if (res.success) {
          successCount += 1;
          const image = step3ImageOrder.find(item => item.slide_id === task.slideId);
          if (image) {
            image.exists = true;
            image.url = res.image_url;
          }
        }
      } catch (error) {
        failedSlides.push(task.slideId);
      } finally {
        step3GeneratingSlides.delete(task.slideId);
        step3BatchCompleted += 1;
        renderStep3Grid();
      }
    }
  } finally {
    step3BatchGenerating = false;
    step3BatchCompleted = 0;
    step3BatchTotal = 0;
    step3GeneratingSlides.clear();
    await refreshStep3Images();
    await refreshCurrentProjectStatus(3);
  }

  if (failedSlides.length > 0) {
    showToast(`⚠️ 已生成 ${successCount} 张，失败：${failedSlides.join('、')}`, 5000);
  } else {
    showToast(`✅ ${successCount} 张图片已全部生成完成！`);
  }
}


// AI 生成单张候选图片，确认后才替换当前图片。
async function generateStep3Image() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  const prompt = document.getElementById('step3-prompt-input').value.trim();
  
  if (!prompt) {
    showToast('⚠️ 提示词不能为空');
    return;
  }

  step3CandidateReady = false;
  step3CandidateSlideId = '';
  setStep3SlideGenerating(slideId, true);
  document.getElementById('step3-loading').style.display = 'none';
  document.getElementById('step3-btn-generate').disabled = true;
  document.getElementById('step3-preview-label').innerText = 'AI 图片生成中';
  document.getElementById('step3-candidate-status').style.display = 'none';
  document.getElementById('step3-btn-apply-candidate').style.display = 'none';
  document.getElementById('step3-preview-box').innerHTML = step3GeneratingPreviewHtml();
  const imageModel = state.settings?.image_model || 'gpt-image-1';
  const imageSize = state.settings?.image_size || '1024x1024';
  showToast(`🎨 正在调用 ${imageModel} 合成 ${imageSize} 候选图...`);

  let generated = false;
  try {
    const formData = new FormData();
    formData.append('slide_id', slideId);
    formData.append('prompt', prompt);
    formData.append('preview', 'true');
    const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/generate`, formData);
    if (res.success) {
      const activeSlideId = document.getElementById('step3-slide-id-label').innerText;
      const modalOpen = document.getElementById('modal-step3-ai').style.display === 'flex';
      if (!modalOpen || activeSlideId !== slideId) return;
      step3CandidateReady = true;
      step3CandidateSlideId = slideId;
      generated = true;
      document.getElementById('step3-preview-label').innerText = 'AI 候选图片预览';
      document.getElementById('step3-candidate-status').style.display = 'inline-flex';
      document.getElementById('step3-preview-box').innerHTML =
        `<img src="${res.candidate_url}" alt="${slideId} AI 候选图片">`;
      document.getElementById('step3-btn-apply-candidate').style.display = 'inline-flex';
      showToast('候选图片已生成。确认画面后点击“替换原图”。');
    }
  } catch(e) {
  } finally {
    document.getElementById('step3-loading').style.display = 'none';
    document.getElementById('step3-btn-generate').disabled = false;
    setStep3SlideGenerating(slideId, false);
    const activeSlideId = document.getElementById('step3-slide-id-label').innerText;
    const modalOpen = document.getElementById('modal-step3-ai').style.display === 'flex';
    if (!generated && modalOpen && activeSlideId === slideId) {
      const image = step3ImageOrder.find(item => item.slide_id === slideId);
      document.getElementById('step3-preview-label').innerText = '当前图片预览';
      document.getElementById('step3-preview-box').innerHTML = image?.exists
        ? `<img src="${image.url}" alt="${slideId} 当前图片">`
        : '<span>暂无图片</span>';
    }
  }
}

async function applyStep3Candidate() {
  const slideId = document.getElementById('step3-slide-id-label').innerText;
  if (!step3CandidateReady || step3CandidateSlideId !== slideId) {
    showToast('请先生成一张候选图片。');
    return;
  }
  const applyButton = document.getElementById('step3-btn-apply-candidate');
  applyButton.disabled = true;
  try {
    const res = await API.post(
      `/api/projects/${state.currentProject.id}/steps/3/apply-candidate`,
      { slide_id: slideId }
    );
    if (res.success) {
      await refreshStep3Images();
      await refreshCurrentProjectStatus(3);
      closeStep3AIModal();
      showToast('候选图片已替换原图，该页旧 Mask 已清除。');
    }
  } finally {
    applyButton.disabled = false;
  }
}

window.applyStep3Candidate = applyStep3Candidate;

async function confirmStep3Images() {
  const res = await API.post(`/api/projects/${state.currentProject.id}/steps/3/confirm`);
  if (res.success) {
    await refreshCurrentProjectStatus(5);
    showToast('🔒 所有图片已确认并锁定！进入标注阶段。');
    navigateToStep(5);
  }
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

async function openStoryboardRulesModal(mode = 'script') {
  if (!state.currentProject) return;
  state.activeStep2PromptMode = mode === 'visual' ? 'visual' : 'script';
  const [promptRes, templateRes] = await Promise.all([
    API.get(`/api/projects/${state.currentProject.id}/steps/2/prompts`),
    API.get('/api/step2-prompt-templates'),
  ]);
  state.step2PromptTemplates = Array.isArray(templateRes.templates) ? templateRes.templates : [];
  state.selectedStep2PromptTemplateId = '';
  state.step2PromptCreating = false;
  renderStep2PromptEditor(promptRes);
  renderStep2PromptTemplateOptions('');
  renderStep2PromptTemplateCreation();
  document.getElementById('modal-storyboard-rules').style.display = 'flex';
}

function step2PromptModeLabel(mode = state.activeStep2PromptMode) {
  return mode === 'visual' ? 'slides➡️可视化' : '文章➡️slides';
}

function composeStep2FullPrompt(systemContent, outputExample) {
  return `${String(systemContent || '').trim()}\n\n<OutputExample>\n${String(outputExample || '').trim()}\n</OutputExample>`;
}

function updateStep2FullPromptPreviews() {
  const scriptFull = document.getElementById('step2-script-full-prompt');
  const visualFull = document.getElementById('step2-visual-full-prompt');
  if (scriptFull) {
    scriptFull.value = composeStep2FullPrompt(
      document.getElementById('step2-script-system-prompt')?.value,
      document.getElementById('step2-script-output-example')?.value,
    );
  }
  if (visualFull) {
    visualFull.value = composeStep2FullPrompt(
      document.getElementById('step2-visual-system-prompt')?.value,
      document.getElementById('step2-visual-output-example')?.value,
    );
  }
}

function renderStep2PromptEditor(promptRes = {}) {
  const prompts = promptRes.prompts || {};
  const setValue = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.value = value || '';
  };
  setValue('step2-script-system-prompt', prompts.script_system);
  setValue('step2-script-output-example', prompts.script_output_example);
  setValue('step2-visual-system-prompt', prompts.visual_system);
  setValue('step2-visual-output-example', prompts.visual_output_example);
  setValue('step2-script-full-prompt', promptRes.composed?.script_system_content);
  setValue('step2-visual-full-prompt', promptRes.composed?.visual_system_content);
  updateStep2FullPromptPreviews();
  const mode = state.activeStep2PromptMode === 'visual' ? 'visual' : 'script';
  const title = document.getElementById('storyboard-prompt-modal-title');
  const helpButton = document.getElementById('step2-prompt-help');
  const scriptSection = document.getElementById('step2-script-prompt-section');
  const visualSection = document.getElementById('step2-visual-prompt-section');
  if (title) title.textContent = step2PromptModeLabel(mode);
  if (helpButton) helpButton.dataset.promptHelp = mode === 'visual' ? 'step2-visual' : 'step2-script';
  if (scriptSection) scriptSection.style.display = mode === 'script' ? 'block' : 'none';
  if (visualSection) visualSection.style.display = mode === 'visual' ? 'block' : 'none';
  renderStep2PromptTemplateOptions();
}

function step2PromptFormPayloadForMode(mode = state.activeStep2PromptMode) {
  if (mode === 'visual') {
    return {
      prompt_type: 'visual',
      visual_system: document.getElementById('step2-visual-system-prompt')?.value || '',
      visual_output_example: document.getElementById('step2-visual-output-example')?.value || '',
    };
  }
  return {
    prompt_type: 'script',
    script_system: document.getElementById('step2-script-system-prompt')?.value || '',
    script_output_example: document.getElementById('step2-script-output-example')?.value || '',
  };
}

function applyStep2PromptTemplate(template) {
  if (!template?.prompts) return;
  const prompts = template.prompts;
  if (template.prompt_type === 'visual') {
    const system = document.getElementById('step2-visual-system-prompt');
    const example = document.getElementById('step2-visual-output-example');
    if (system) system.value = prompts.visual_system || '';
    if (example) example.value = prompts.visual_output_example || '';
  } else {
    const system = document.getElementById('step2-script-system-prompt');
    const example = document.getElementById('step2-script-output-example');
    if (system) system.value = prompts.script_system || '';
    if (example) example.value = prompts.script_output_example || '';
  }
  updateStep2FullPromptPreviews();
}

function renderStep2PromptTemplateOptions(selectedId = state.selectedStep2PromptTemplateId || '') {
  const mode = state.activeStep2PromptMode === 'visual' ? 'visual' : 'script';
  const select = document.getElementById('step2-prompt-template-select');
  if (!select) return;
  const templates = (state.step2PromptTemplates || []).filter(template => template.prompt_type === mode);
  select.innerHTML = [
    `<option value="">当前 ${escHtml(step2PromptModeLabel(mode))} Prompt</option>`,
    ...templates.map(template =>
      `<option value="${escHtml(template.id)}">${escHtml(template.name)}${template.built_in ? ' · 内置' : ''}</option>`
    ),
  ].join('');
  select.value = templates.some(template => template.id === selectedId) ? selectedId : '';
  state.selectedStep2PromptTemplateId = select.value || '';
  updateStep2PromptTemplateDeleteButton();
}

function renderStep2PromptTemplateCreation() {
  const panel = document.getElementById('step2-prompt-template-create-panel');
  const modeLabel = document.getElementById('step2-prompt-create-mode-label');
  if (panel) panel.style.display = state.step2PromptCreating ? 'grid' : 'none';
  if (modeLabel) modeLabel.textContent = step2PromptModeLabel();
}

function beginStep2PromptTemplateCreation() {
  state.step2PromptCreating = true;
  state.selectedStep2PromptTemplateId = '';
  const select = document.getElementById('step2-prompt-template-select');
  const nameInput = document.getElementById('step2-prompt-template-name');
  if (select) select.value = '';
  if (nameInput) nameInput.value = '';
  updateStep2PromptTemplateDeleteButton();
  renderStep2PromptTemplateCreation();
  nameInput?.focus();
}

function cancelStep2PromptTemplateCreation() {
  state.step2PromptCreating = false;
  const nameInput = document.getElementById('step2-prompt-template-name');
  if (nameInput) nameInput.value = '';
  renderStep2PromptTemplateCreation();
}

function selectedStep2PromptTemplate() {
  const templateId = document.getElementById('step2-prompt-template-select')?.value || state.selectedStep2PromptTemplateId || '';
  return (state.step2PromptTemplates || []).find(template => template.id === templateId) || null;
}

function updateStep2PromptTemplateDeleteButton() {
  const button = document.getElementById('btn-step2-prompt-template-delete');
  if (!button) return;
  const template = selectedStep2PromptTemplate();
  button.disabled = !template || !!template.built_in;
  button.title = template?.built_in ? '内置模板不能删除' : '';
}

async function refreshStep2PromptTemplates(selectedId = '') {
  const res = await API.get('/api/step2-prompt-templates');
  state.step2PromptTemplates = Array.isArray(res.templates) ? res.templates : [];
  renderStep2PromptTemplateOptions(selectedId);
  return state.step2PromptTemplates;
}

async function loadSelectedStep2PromptTemplate() {
  const template = selectedStep2PromptTemplate();
  if (!template) {
    showToast('请选择一个 Prompt 模板。');
    return;
  }
  const res = await API.get(`/api/step2-prompt-templates/${encodeURIComponent(template.id)}`);
  if (res.success && res.template) {
    cancelStep2PromptTemplateCreation();
    applyStep2PromptTemplate(res.template);
    state.selectedStep2PromptTemplateId = res.template.id;
    renderStep2PromptTemplateOptions(res.template.id);
    showToast(`已载入 ${step2PromptModeLabel()} 模板“${res.template.name}”。`);
  }
}

async function saveStep2PromptTemplate() {
  if (!state.step2PromptCreating) {
    beginStep2PromptTemplateCreation();
    return;
  }
  const name = document.getElementById('step2-prompt-template-name')?.value.trim();
  if (!name) {
    showToast('请填写模板名称。');
    return;
  }
  const payload = {
    name,
    ...step2PromptFormPayloadForMode(),
  };
  const res = await API.post('/api/step2-prompt-templates', payload);
  if (res.success) {
    state.step2PromptTemplates = res.templates || [];
    state.step2PromptCreating = false;
    renderStep2PromptTemplateOptions(res.template?.id || '');
    renderStep2PromptTemplateCreation();
    showToast(`模板“${res.template?.name || name}”已保存。`);
  }
}

async function deleteSelectedStep2PromptTemplate() {
  const template = selectedStep2PromptTemplate();
  if (!template) {
    showToast('请选择要删除的 Prompt 模板。');
    return;
  }
  if (template.built_in) {
    showToast('内置模板不能删除。');
    return;
  }
  const confirmed = window.confirm(`确定删除模板“${template.name}”吗？`);
  if (!confirmed) return;
  const res = await API.delete(`/api/step2-prompt-templates/${encodeURIComponent(template.id)}`);
  if (res.success) {
    state.step2PromptTemplates = res.templates || [];
    state.selectedStep2PromptTemplateId = '';
    const nameInput = document.getElementById('step2-prompt-template-name');
    if (nameInput) nameInput.value = '';
    renderStep2PromptTemplateOptions();
    showToast(`模板“${template.name}”已删除。`);
  }
}

async function saveStep2Prompts() {
  if (!state.currentProject?.id) return;
  const payload = {
    script_system: document.getElementById('step2-script-system-prompt')?.value || '',
    script_output_example: document.getElementById('step2-script-output-example')?.value || '',
    visual_system: document.getElementById('step2-visual-system-prompt')?.value || '',
    visual_output_example: document.getElementById('step2-visual-output-example')?.value || '',
  };
  const res = await API.put(`/api/projects/${state.currentProject.id}/steps/2/prompts`, payload);
  if (res.success) {
    renderStep2PromptEditor(res);
    closeStoryboardRulesModal();
    showToast('Step 2 Prompt 已保存。');
  }
}

function closeStoryboardRulesModal() {
  cancelStep2PromptTemplateCreation();
  document.getElementById('modal-storyboard-rules').style.display = 'none';
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
    color: '#111111',
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
  text.textContent = sample || '这是一段视频字幕效果预览';
  text.style.fontFamily = `${font.family}, "Microsoft YaHei", sans-serif`;
  text.style.fontSize = `${settings.font_size * scale}px`;
  text.style.fontWeight = String(settings.font_weight);
  text.style.bottom = `${settings.bottom * scale}px`;
  text.style.left = `${settings.horizontal_margin * scale}px`;
  text.style.right = `${settings.horizontal_margin * scale}px`;
  text.style.color = settings.color;
  // 预览中加入逐字高亮示意：把前 1/3 的字着色为 highlight_color
  const enableHighlight = settings.token_highlight !== false;
  if (enableHighlight) {
    text.style.color = settings.highlight_color;
  } else {
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

async function refreshStep3Prompts(options = {}) {
  if (!state.currentProject?.id) return [];
  const promptRes = await API.get(`/api/projects/${state.currentProject.id}/steps/3/prompts`);
  if (promptRes.success) {
    slidePrompts = promptRes.prompts || [];
    step3BatchPrompt = promptRes.batch_prompt || '';
  }
  if (options.updateOpenEditor) {
    const currentSlideId = document.getElementById('step3-slide-id-label')?.innerText;
    const promptInput = document.getElementById('step3-prompt-input');
    const promptInfo = slidePrompts.find(item => item.slide_id === currentSlideId);
    if (promptInput && promptInfo && currentSlideId && currentSlideId !== '--') {
      promptInput.value = promptInfo.prompt || '';
    }
  }
  return slidePrompts;
}

function currentStep3PromptInfo() {
  const openSlideId = document.getElementById('step3-slide-id-label')?.innerText;
  const fallbackSlideId = state.slides?.[state.activeSlideIndex]?.slide_id || step3ImageOrder?.[0]?.slide_id;
  const slideId = openSlideId && openSlideId !== '--' ? openSlideId : fallbackSlideId;
  return slidePrompts.find(item => item.slide_id === slideId) || slidePrompts[0] || null;
}

function updateStep3PromptFullPreview() {
  const settings = state.step3PromptSettings || {};
  const systemContent = document.getElementById('step3-image-system-prompt')?.value || '';
  const promptInfo = currentStep3PromptInfo();
  const inputPreview = document.getElementById('step3-image-input-preview');
  const fullPreview = document.getElementById('step3-image-full-prompt');
  const slidePrompt = String(promptInfo?.slide_prompt || '').trim();
  if (inputPreview) {
    const jsonStart = slidePrompt.indexOf('{');
    inputPreview.value = jsonStart >= 0
      ? slidePrompt.slice(jsonStart)
      : JSON.stringify(settings.current_input || settings.input_example || {}, null, 2);
  }
  if (fullPreview) {
    fullPreview.value = [
      '=== 图片生成 System Content ===',
      systemContent.trim(),
      '=== 当前生效的图片风格 ===',
      String(settings.style_content || '').trim(),
      '=== 当前 Slide 输入 ===',
      slidePrompt || `最小单页输入：\n${JSON.stringify(settings.current_input || settings.input_example || {}, null, 2)}`,
      String(settings.protected_rules || '').trim(),
    ].filter(Boolean).join('\n\n');
  }
}

async function openStep3PromptSettingsModal() {
  if (!state.currentProject?.id) return;
  const modal = document.getElementById('modal-step3-prompt-settings');
  const systemInput = document.getElementById('step3-image-system-prompt');
  const inputPreview = document.getElementById('step3-image-input-preview');
  const fullPreview = document.getElementById('step3-image-full-prompt');
  modal.style.display = 'flex';
  systemInput.value = '加载中...';
  inputPreview.value = '';
  fullPreview.value = '';
  try {
    const [result] = await Promise.all([
      API.get(`/api/projects/${state.currentProject.id}/steps/3/prompt-settings`),
      refreshStep3Prompts(),
    ]);
    state.step3PromptSettings = result.prompts || {};
    systemInput.value = state.step3PromptSettings.system_content || '';
    updateStep3PromptFullPreview();
  } catch (error) {
    modal.style.display = 'none';
  }
}

function closeStep3PromptSettingsModal() {
  const modal = document.getElementById('modal-step3-prompt-settings');
  if (modal) modal.style.display = 'none';
}

function resetStep3PromptSettings() {
  const input = document.getElementById('step3-image-system-prompt');
  if (!input) return;
  input.value = state.step3PromptSettings?.default_system_content || '';
  updateStep3PromptFullPreview();
  showToast('已恢复默认内容，保存后生效');
}

async function saveStep3PromptSettings() {
  const systemContent = document.getElementById('step3-image-system-prompt')?.value.trim() || '';
  if (!systemContent) return showToast('图片生成 System Content 不能为空');
  const button = document.getElementById('btn-step3-prompt-save');
  button.disabled = true;
  try {
    const result = await API.put(
      `/api/projects/${state.currentProject.id}/steps/3/prompt-settings`,
      { prompts: { system_content: systemContent } },
    );
    state.step3PromptSettings = result.prompts || {};
    await refreshStep3Prompts({ updateOpenEditor: true });
    closeStep3PromptSettingsModal();
    showToast('图片生成 Prompt 已保存');
  } finally {
    button.disabled = false;
  }
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
        当前页暂未生成 AI 语块关联，请重新运行 AI 标注。
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
  return {
    x: Math.max(0, Math.min(1920, (event.clientX - rect.left) * 1920 / rect.width)),
    y: Math.max(0, Math.min(1080, (event.clientY - rect.top) * 1080 / rect.height)),
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
  const displaySize = Math.max(8, toolSize * canvasRect.width / 1920);
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
  redrawCanvas();
}

function continueMaskStroke(event, canvas) {
  updateMaskToolCursor(event);
  if (!state.canvasState.isPainting || !state.canvasState.currentStroke) return;
  event.preventDefault();
  const point = getCanvasCoords(event, canvas);
  const points = state.canvasState.currentStroke.points;
  const last = points[points.length - 1];
  if (!last || Math.hypot(point.x - last.x, point.y - last.y) >= 3) {
    points.push({ x: Math.round(point.x), y: Math.round(point.y) });
    redrawCanvas();
  }
}

function finishMaskStroke(event, canvas) {
  if (!state.canvasState.isPainting) return;
  state.canvasState.isPainting = false;
  state.canvasState.currentStroke = null;
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

function buildMaskDisplayLayer(item, idx) {
  const isSelected = idx === state.canvasState.selectedBoxIndex;
  const color = getBoxColor(item, idx);
  const signature = `${maskDisplaySignature(item)}:${color}:${isSelected ? 1 : 0}`;
  const cached = maskDisplayLayerCache.get(item);
  if (cached?.signature === signature) return cached.layer;

  const maskLayer = rasterizeManualMask(item);
  const outlineMask = createStep5OffscreenCanvas();
  const outlineMaskCtx = outlineMask.getContext('2d');
  for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 8) {
    const offsetX = Math.round(Math.cos(angle) * MASK_PREVIEW_OUTLINE_PX);
    const offsetY = Math.round(Math.sin(angle) * MASK_PREVIEW_OUTLINE_PX);
    outlineMaskCtx.drawImage(maskLayer, offsetX, offsetY);
  }
  outlineMaskCtx.globalCompositeOperation = 'destination-out';
  outlineMaskCtx.drawImage(maskLayer, 0, 0);

  const displayLayer = createStep5OffscreenCanvas();
  const displayCtx = displayLayer.getContext('2d');
  displayCtx.fillStyle = hexToRgba(color, isSelected ? 0.68 : 0.55);
  displayCtx.fillRect(0, 0, 1920, 1080);
  displayCtx.globalCompositeOperation = 'destination-in';
  displayCtx.drawImage(maskLayer, 0, 0);
  displayCtx.globalCompositeOperation = 'source-over';

  const outlineColorLayer = createStep5OffscreenCanvas();
  const outlineColorCtx = outlineColorLayer.getContext('2d');
  outlineColorCtx.fillStyle = hexToRgba(color, isSelected ? 1 : 0.9);
  outlineColorCtx.fillRect(0, 0, 1920, 1080);
  outlineColorCtx.globalCompositeOperation = 'destination-in';
  outlineColorCtx.drawImage(outlineMask, 0, 0);
  displayCtx.drawImage(outlineColorLayer, 0, 0);

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

function drawManualMaskStrokes(ctx, item, idx) {
  const strokes = item.manual_mask?.strokes || [];
  const exactRuns = item.manual_mask?.rle?.runs || [];
  if (!strokes.length && !exactRuns.length) return;
  ctx.drawImage(buildMaskDisplayLayer(item, idx), 0, 0);
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
      drawManualMaskStrokes(ctx, item, idx);
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
        ? '进入视频合成'
        : '确认并进入视频合成';
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
      showToast('✅ 音频已确认，准备进入视频合成。');
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
        document.getElementById('step8-error-message').innerText = message;
        document.getElementById('step8-error-box').style.display = 'block';
        showToast(`❌ 渲染失败: ${message}`, 7000);
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
    document.getElementById('step8-error-message').innerText = message;
    document.getElementById('step8-error-box').style.display = 'block';
    document.getElementById('step8-loading').style.display = 'none';
    if (renderBtn) renderBtn.disabled = false;
    showToast(`❌ 渲染失败: ${message}`, 7000);
  }
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
window.loadStep5Data = loadStep5Data;
window.renderStep5Workspace = renderStep5Workspace;
window.saveStep5Draft = saveStep5Draft;
window.saveStep5CurrentState = saveStep5CurrentState;
window.refreshStep3Prompts = refreshStep3Prompts;
window.focusFirstAiMaskResult = focusFirstAiMaskResult;
window.focusAiMaskIssue = focusAiMaskIssue;
window.setStep5MaskPreviewMode = setStep5MaskPreviewMode;
window.getCurrentStep5SlideId = () => String(getCurrentManifestSlide()?.slide_id || '');
window.PPTStudio = Object.assign(window.PPTStudio || {}, {
  getCurrentProject: () => state.currentProject,
  flushStep5Draft,
});
