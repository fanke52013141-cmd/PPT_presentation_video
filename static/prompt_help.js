// Shared Prompt input/output help catalog and modal.
// Escaping is provided by app.js; the document-level trigger lives in event_bindings.js.

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

