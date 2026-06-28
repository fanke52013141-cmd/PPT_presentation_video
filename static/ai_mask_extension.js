(function () {
  'use strict';

  const MODAL_ID = 'modal-ai-mask-settings';
  const USER_SETTING_KEYS = new Set([
    'white_threshold',
    'color_tolerance',
    'min_element_area',
    'component_padding_px',
    'merge_gap_px',
    'subtitle_safe_y',
    'stroke_brush_size'
  ]);

  const PARAMS = [
    {
      key: 'white_threshold', label: '白底识别阈值', type: 'number', default: 245, min: 220, max: 255, step: 1,
      usual: '235 - 252',
      help: '判断哪些像素算白色背景。背景灰、白边残留多就调低；浅色元素被误删就调高。'
    },
    {
      key: 'color_tolerance', label: '白色色差容忍', type: 'number', default: 12, min: 0, max: 40, step: 1,
      usual: '5 - 24',
      help: '允许白色像素有轻微偏黄、偏蓝。白底有色偏就调高；浅色彩色元素被当背景删掉就调低。'
    },
    {
      key: 'min_element_area', label: '最小元素面积', type: 'number', default: 120, min: 10, max: 10000, step: 10,
      usual: '20 - 800',
      help: '小于这个面积的连通块会当噪点过滤。噪点太多调高；小图标、标点、小字被漏掉调低。'
    },
    {
      key: 'component_padding_px', label: '元素外扩边距', type: 'number', default: 12, min: 0, max: 80, step: 1,
      usual: '4 - 32 px',
      help: '检测到元素后向外多包一点，避免边缘被切。元素边缘缺失调高；相邻元素被带进去调低。'
    },
    {
      key: 'merge_gap_px', label: '语块合并距离', type: 'number', default: 40, min: 0, max: 160, step: 4,
      usual: '12 - 100 px',
      help: '同一个语块绑定多个元素时，决定合并范围。图标+标题被拆太碎调高；多个语块粘在一起调低。'
    },
    {
      key: 'subtitle_safe_y', label: '字幕安全线', type: 'number', default: 930, min: 760, max: 1080, step: 10,
      usual: '880 - 1040 px',
      help: '自动 Mask 尽量不进入这条线以下，避免挡字幕。底部内容必须标注就调高；字幕容易冲突就调低。'
    },
    {
      key: 'stroke_brush_size', label: '自动画笔宽度', type: 'number', default: 96, min: 24, max: 240, step: 4,
      usual: '48 - 180 px',
      help: 'AI 结果会写成手动 Mask 笔画，这里控制笔画粗细。Mask 有空洞调大；盖到旁边元素调小。'
    }
  ];

  function apiGet(url) {
    return window.API?.get ? window.API.get(url) : fetch(url).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function apiPut(url, body) {
    return window.API?.put ? window.API.put(url, body) : fetch(url, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function apiPost(url, body) {
    return window.API?.post ? window.API.post(url, body) : fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
    }).then(async r => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || d.message || r.statusText);
      return d;
    });
  }

  function toast(msg, duration) {
    if (window.showToast) window.showToast(msg, duration || 3000);
    else console.log(msg);
  }

  function projectId() {
    const fromWindow = window.state?.currentProject?.id || window.PPTStudio?.getCurrentProject?.()?.id;
    if (fromWindow) return fromWindow;
    const bgSrc = document.getElementById('step5-bg-img')?.getAttribute('src') || '';
    const match = bgSrc.match(/\/api\/projects\/([^/]+)\/slides\//);
    if (match) return decodeURIComponent(match[1]);
    const currentLinks = Array.from(document.querySelectorAll('[src], [href]'))
      .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
      .join('\n');
    const anyMatch = currentLinks.match(/\/api\/projects\/([^/]+)\//);
    return anyMatch ? decodeURIComponent(anyMatch[1]) : null;
  }

  function escapeAttr(value) {
    return String(value ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function ensureStyles() {
    if (document.getElementById('ai-mask-extension-style')) return;
    const style = document.createElement('style');
    style.id = 'ai-mask-extension-style';
    style.textContent = `
      .ai-mask-compact-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:.65rem;margin-top:.75rem}
      .ai-mask-param-row{display:grid;grid-template-columns:minmax(112px,1fr) minmax(88px,120px) 28px;align-items:center;gap:.5rem;border:1.5px solid var(--ink-color,#111);border-radius:9px;padding:.55rem .65rem;background:#fffef9}
      .ai-mask-param-row label{font-weight:800;font-size:.86rem;color:#222;min-width:0}
      .ai-mask-param-row input[type="number"],.ai-mask-param-row select{width:100%;min-height:32px;padding:.28rem .4rem;border:1.5px solid #111;border-radius:6px;background:#fff;font:inherit;box-sizing:border-box}
      .ai-mask-switch{display:flex;align-items:center;justify-content:flex-start;gap:.35rem;font-size:.82rem;font-weight:700;white-space:nowrap}
      .ai-mask-help{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border:1.5px solid #111;border-radius:999px;background:#f4f2eb;font-weight:900;cursor:help;position:relative;line-height:1}
      .ai-mask-help:hover::after{content:attr(data-help);position:absolute;right:0;top:30px;width:280px;z-index:9000;padding:.65rem .75rem;border:1.5px solid #111;border-radius:8px;background:#fffef9;box-shadow:3px 3px 0 rgba(0,0,0,.15);white-space:pre-wrap;text-align:left;font-weight:600;font-size:.78rem;line-height:1.45;color:#222}
      .ai-mask-section-title{display:flex;align-items:center;justify-content:space-between;gap:.8rem;margin-top:1rem}
      .ai-mask-prompt-block{margin-top:1rem;border-top:1.5px dashed #111;padding-top:.8rem}
      .ai-mask-prompt-block textarea{width:100%;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.84rem;line-height:1.45;box-sizing:border-box}
      .ai-mask-modal-scroll{max-height:72vh;overflow:auto;padding-right:.3rem}
      #step5-canvas{pointer-events:none!important;cursor:default!important}
      #step5-boxes-list input,#step5-boxes-list textarea,#step5-boxes-list select,#step5-boxes-list button{pointer-events:none;opacity:.72}
      body.step5-fullscreen-mode #canvas-container{aspect-ratio:16/9;height:auto!important;max-height:none!important;}
      body.step5-fullscreen-mode #canvas-container canvas,body.step5-fullscreen-mode #canvas-container img{width:100%!important;height:100%!important;object-fit:contain!important;}
      body.step5-fullscreen-mode #step-panel-5 .workspace-left{align-items:center;justify-content:center;overflow:hidden;}
    `;
    document.head.appendChild(style);
  }

  function fitFullscreenCanvas() {
    const container = document.getElementById('canvas-container');
    if (!container) return;
    if (!document.body.classList.contains('step5-fullscreen-mode')) {
      container.style.width = '';
      container.style.height = '';
      return;
    }
    const left = container.closest('.workspace-left') || container.parentElement;
    const rect = left?.getBoundingClientRect?.();
    const maxW = Math.max(240, (rect?.width || window.innerWidth) - 12);
    const maxH = Math.max(135, (rect?.height || window.innerHeight) - 12);
    let width = maxW;
    let height = width * 9 / 16;
    if (height > maxH) {
      height = maxH;
      width = height * 16 / 9;
    }
    container.style.width = `${Math.floor(width)}px`;
    container.style.height = `${Math.floor(height)}px`;
  }

  function installFullscreenFitWatch() {
    if (window.__aiMaskFullscreenFitWatch) return;
    window.__aiMaskFullscreenFitWatch = true;
    window.addEventListener('resize', fitFullscreenCanvas);
    const observer = new MutationObserver(fitFullscreenCanvas);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    setInterval(fitFullscreenCanvas, 800);
  }

  function button(id, text, cls) {
    const b = document.createElement('button');
    b.id = id;
    b.type = 'button';
    b.className = cls || 'secondary';
    b.textContent = text;
    return b;
  }

  function injectButtons() {
    const toolbar = document.querySelector('#step-panel-5 .step5-toolbar');
    if (!toolbar) return;
    ensureInlineStatus();
    if (document.getElementById('step5-btn-ai-mask')) return;
    const settings = button('step5-btn-ai-mask-settings', 'AI 标注设置', 'secondary');
    const run = button('step5-btn-ai-mask', '重新运行 AI 标注', 'success');
    const anchor = document.getElementById('step5-btn-fullscreen');
    toolbar.insertBefore(settings, anchor || null);
    toolbar.insertBefore(run, anchor || null);
    settings.addEventListener('click', openSettings);
    run.addEventListener('click', runAnnotation);
  }

  function ensureInlineStatus() {
    return document.getElementById('project-activity-status');
  }

  function setInlineStatus(message, active = true, spinning = false) {
    const status = ensureInlineStatus();
    if (!status) return;
    status.innerHTML = message
      ? `${spinning ? '<span class="button-spinner"></span>' : ''}<span>${escapeAttr(message)}</span>`
      : '';
    status.classList.toggle('active', !!active && !!message);
    status.classList.toggle('running', !!spinning);
  }

  function inputHtml(def, value) {
    if (def.type === 'boolean') {
      return `<label class="ai-mask-switch"><input class="ai-mask-setting-input" data-key="${def.key}" type="checkbox" ${value ? 'checked' : ''}> 开启</label>`;
    }
    return `<input class="ai-mask-setting-input" data-key="${def.key}" type="number" min="${def.min}" max="${def.max}" step="${def.step}" value="${escapeAttr(value)}">`;
  }

  function paramRow(def, settings) {
    const value = settings[def.key] !== undefined ? settings[def.key] : def.default;
    const rangeLine = `默认：${def.default}\n常用：${def.usual}\n作用：${def.help}`;
    return `
      <div class="ai-mask-param-row">
        <label for="ai-mask-param-${def.key}">${def.label}</label>
        ${inputHtml(def, value).replace('class="ai-mask-setting-input"', `id="ai-mask-param-${def.key}" class="ai-mask-setting-input"`)}
        <span class="ai-mask-help" data-help="${escapeAttr(rangeLine)}">?</span>
      </div>
    `;
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = MODAL_ID;
    modal.className = 'modal-overlay';
    modal.style.display = 'none';
    modal.innerHTML = `
      <div class="modal-content config-editor-modal" style="max-width:900px;width:min(900px,94vw)">
        <div class="ai-mask-modal-scroll">
          <h3 class="highlight-title">AI Mask 自动标注设置</h3>
          <p class="config-editor-note">只保留常用 Mask 参数。大模型匹配参数使用系统默认值；日常只需要调整识别、合并和覆盖策略。</p>
          <div class="ai-mask-section-title"><h4 style="margin:0">Mask 参数</h4><span class="config-editor-note" style="margin:0">悬停问号查看说明</span></div>
          <div id="ai-mask-settings-grid" class="ai-mask-compact-grid"></div>
          <div class="ai-mask-prompt-block">
            <h4>匹配规则提示词</h4>
            <p class="config-editor-note">这里控制“画面元素如何匹配到语块和演讲稿”。可以改方法论；不需要调大模型参数。</p>
            <textarea id="ai-mask-methodology" rows="10" spellcheck="false"></textarea>
          </div>
          <details class="ai-mask-prompt-block">
            <summary style="font-weight:800;cursor:pointer">高级：输出 JSON 结构</summary>
            <p class="config-editor-note">默认不要修改。只有后端解析结构同步调整时才需要改。</p>
            <textarea id="ai-mask-output-structure" rows="8" spellcheck="false"></textarea>
          </details>
        </div>
        <div class="config-editor-actions">
          <button id="btn-ai-mask-settings-cancel" class="secondary" type="button">取消</button>
          <button id="btn-ai-mask-settings-save" class="success" type="button">保存设置</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#btn-ai-mask-settings-cancel').addEventListener('click', () => modal.style.display = 'none');
    modal.querySelector('#btn-ai-mask-settings-save').addEventListener('click', saveSettings);
    return modal;
  }

  async function openSettings() {
    ensureStyles();
    const modal = ensureModal();
    modal.style.display = 'flex';
    const grid = modal.querySelector('#ai-mask-settings-grid');
    grid.innerHTML = '<div class="card">加载设置中...</div>';
    try {
      const data = await apiGet('/api/settings/ai-mask');
      const settings = data.settings || {};
      grid.innerHTML = PARAMS.map(def => paramRow(def, settings)).join('');
      modal.querySelector('#ai-mask-methodology').value = data.prompts?.methodology || '';
      modal.querySelector('#ai-mask-output-structure').value = data.prompts?.output_structure || '';
    } catch (e) {
      grid.innerHTML = `<div class="card sketch-dashed">加载失败：${escapeAttr(e.message)}</div>`;
    }
  }

  function collect() {
    const modal = ensureModal();
    const settings = {};
    modal.querySelectorAll('.ai-mask-setting-input').forEach(input => {
      const key = input.dataset.key;
      if (!key || !USER_SETTING_KEYS.has(key)) return;
      if (input.type === 'checkbox') settings[key] = input.checked;
      else if (input.type === 'number') settings[key] = Number(input.value);
      else settings[key] = input.value;
    });
    return {
      settings,
      prompts: {
        methodology: modal.querySelector('#ai-mask-methodology').value,
        output_structure: modal.querySelector('#ai-mask-output-structure').value
      }
    };
  }

  async function saveSettings() {
    const btn = document.getElementById('btn-ai-mask-settings-save');
    btn.disabled = true;
    try {
      await apiPut('/api/settings/ai-mask', collect());
      toast('✅ AI Mask 设置已保存');
      document.getElementById(MODAL_ID).style.display = 'none';
    } catch (e) {
      toast(`❌ 保存失败：${e.message}`, 6000);
    } finally {
      btn.disabled = false;
    }
  }

  async function flushStep5DraftBeforeAiMask() {
    if (window.PPTStudio && typeof window.PPTStudio.flushStep5Draft === 'function') {
      await window.PPTStudio.flushStep5Draft();
      return;
    }
    if (typeof window.saveStep5CurrentState === 'function') {
      window.saveStep5CurrentState();
    }
    if (typeof window.saveStep5Draft === 'function') {
      await window.saveStep5Draft();
    }
  }

  async function runAnnotation(options = {}) {
    const id = projectId();
    if (!id) {
      toast('请先打开项目并进入 Mask 标注页。未能识别当前 project_id。', 6000);
      return;
    }
    const btn = document.getElementById('step5-btn-ai-mask');
    const settingsBtn = document.getElementById('step5-btn-ai-mask-settings');
    const status = ensureInlineStatus();
    btn.disabled = true;
    if (settingsBtn) settingsBtn.disabled = true;
    setInlineStatus('正在准备 AI 标注...', true, true);
    try {
      await flushStep5DraftBeforeAiMask();
      setInlineStatus('AI 正在关联画面元素与演讲稿...', true, true);
      const result = await apiPost(`/api/projects/${encodeURIComponent(id)}/steps/5/ai-mask/annotate`, {
        scope: 'all_slides',
        settings: {
          overwrite_existing_manual_mask: true,
          skip_locked_groups: false,
        },
      });
      if (result.complete !== true) {
        throw new Error('仍有画面语块未能完成关联，请重新运行 AI 标注');
      }
      setInlineStatus('AI 标注已完成', true, false);
      toast(options.automatic ? 'AI 标注已自动完成。' : 'AI 标注已重新完成。', 4500);
      if (typeof window.loadStep5Data === 'function') await window.loadStep5Data();
      else if (typeof loadStep5Data === 'function') await loadStep5Data();
      if (typeof window.renderStep5Workspace === 'function') window.renderStep5Workspace();
      if (typeof window.focusFirstAiMaskResult === 'function') {
        window.focusFirstAiMaskResult();
      }
    } catch (e) {
      setInlineStatus('AI 标注失败', true, false);
      toast(`❌ AI 标注失败：${e.message}`, 8000);
    } finally {
      if (settingsBtn) settingsBtn.disabled = false;
      btn.disabled = false;
      fitFullscreenCanvas();
    }
  }

  const AUTO_ATTEMPTED = new Set();

  async function maybeAutoAnnotate() {
    const panel = document.getElementById('step-panel-5');
    if (!panel || window.getComputedStyle(panel).display === 'none') return;
    const id = projectId();
    if (!id || AUTO_ATTEMPTED.has(id)) return;
    AUTO_ATTEMPTED.add(id);
    try {
      const result = await apiGet(`/api/projects/${encodeURIComponent(id)}/steps/5/result`);
      if (result.manifest?.ai_mask_annotation?.status === 'completed') {
        setInlineStatus('AI 标注已完成', true, false);
        return;
      }
      await runAnnotation({ automatic: true });
    } catch (error) {
      setInlineStatus('AI 标注等待重试', true, false);
    }
  }

  function installAutoAnnotationWatch() {
    if (window.__aiMaskAutoAnnotationWatch) return;
    window.__aiMaskAutoAnnotationWatch = true;
    const panel = document.getElementById('step-panel-5');
    if (!panel) return;
    const observer = new MutationObserver(() => {
      if (window.getComputedStyle(panel).display !== 'none') maybeAutoAnnotate();
    });
    observer.observe(panel, { attributes: true, attributeFilter: ['style', 'class'] });
    maybeAutoAnnotate();
  }

  function boot() {
    ensureStyles();
    installFullscreenFitWatch();
    fitFullscreenCanvas();
    injectButtons();
    installAutoAnnotationWatch();
  }

  const timer = setInterval(() => {
    boot();
    if (document.getElementById('step5-btn-ai-mask')) clearInterval(timer);
  }, 500);
  document.addEventListener('DOMContentLoaded', boot);
})();
